#!/usr/bin/env python3
"""Reconstrucao offline (20/09/2026, pedido do usuario) dos ultimos N logs
com bot -- roda `decision_quality_full._defense_verdict` (que ja reconstroi
o board turno a turno e chama `should_use_blocker`/`should_use_counter` DE
VERDADE) pra capturar `blocker_trace`/`counter_trace` -- os scores que
passaram a ser gravados no motor nesta sessao (`_ultimo_blocker_trace`/
`_ultimo_counter_trace`).

So cobre blocker/counter: e o unico par reconstruivel a partir do COMBAT
LOG sozinho (reaction/optional/trigger/target_order/mulligan/effect_option
dependem da sequencia exata de prompts, que so existe numa partida ao vivo
via decision log JSONL -- nao ha como reconstruir isso de um combat log
morto). REGRA_SEM_DUPLICACAO: nao reimplementa a reconstrucao, so drena o
que `_defense_verdict` (decision_quality_full.py) ja calcula com `eng`.

ARMADILHA DE METODO evitada aqui (registrada pra nao repetir): a primeira
versao deste script comparava a decisao RECONSTRUIDA contra o MELHOR score
da propria reconstrucao -- sempre 0,0 de "gap", porque `should_use_blocker`/
`should_use_counter` SEMPRE devolvem o proprio argmax (sem exploracao
aleatoria ligada por padrao). Nao e regret, e uma tautologia. O que da pra
medir de verdade com dado morto (combat log, sem replay ao vivo) e:
  1. CONCORDANCIA com o que aconteceu na partida real (ja e o que
     `_defense_verdict` mede -- hist_blocked/engine_blocked etc.);
  2. a MARGEM da decisao reconstruida (golpe vs custo) -- ajuda a
     interpretar POR QUE um caso discordou: foi um call apertado (margem
     pequena) ou uma diferenca grande de leitura (margem grande)?

Uso: python reconstroi_blocker_counter_ultimos10.py [--n 10]
"""
import argparse
import json
import os

import pandas as pd

from decision_quality_full import _defense_verdict, LOGS_DIR
from optcg_engine.decision_engine import load_cards_db


def _bot_logs(n: int) -> list[dict]:
    idx = json.load(open(os.path.join(LOGS_DIR, 'index.json'), encoding='utf-8'))
    bot = [e for e in idx if e.get('tipo') in ('com_bot', 'cpu_vs_cpu') and e.get('date')
           and e.get('parsed_file')]
    bot.sort(key=lambda e: (e['date'], e.get('id') or ''))
    return bot[-n:]


def _sides_to_audit(entry: dict) -> list[str]:
    """cpu_vs_cpu: os DOIS lados sao o bot (self-play) -- audita os dois.
    com_bot: SO o bot_side -- auditar o lado humano seria perguntar 'o que
    o NOSSO motor faria no lugar do humano', que nao mede o bot."""
    if entry.get('tipo') == 'cpu_vs_cpu':
        return [entry['p1']['name'], entry['p2']['name']]
    bs = entry.get('bot_side')
    if bs == 'p1':
        return [entry['p1']['name']]
    if bs == 'p2':
        return [entry['p2']['name']]
    return []


def _pct(n: int, d: int) -> str:
    return f'{n}/{d} ({100*n/d:.1f}%)' if d else 'n/d'


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=10)
    args = ap.parse_args()

    cards_db = load_cards_db('cards_rows.csv')
    df_raw = pd.read_csv('decklists_raw.csv')
    urls = df_raw.groupby('deck_url')['deck_name'].first()

    logs = _bot_logs(args.n)
    print(f'{len(logs)} log(s) selecionado(s):')
    for e in logs:
        print(f"  {e['id']} ({e['date']}, {e['tipo']}) "
              f"{e['p1']['leader_name']} x {e['p2']['leader_name']}")

    rows_all: list[dict] = []
    erros: list[str] = []

    for e in logs:
        full_path = os.path.join(LOGS_DIR, e['parsed_file'])
        for side in _sides_to_audit(e):
            result = _defense_verdict(full_path, side, cards_db, df_raw, urls)
            if 'error' in result:
                erros.append(f"{e['id']} ({side}): {result['error']}")
                continue
            for row in result['rows']:
                if 'error' in row:
                    erros.append(f"{e['id']} ({side}) turno {row.get('turn')}: {row['error']}")
                    continue
                row['_game'] = e['id']
                row['_side'] = side
                rows_all.append(row)

    print(f'\n{"="*72}')
    print(f'RECONSTRUCAO OFFLINE -- {len(rows_all)} janela(s) de defesa reconstruida(s)')
    print(f'{"="*72}')

    # ── 1. CONCORDANCIA com o que a partida real fez ─────────────────────
    print('\n--- concordancia com o historico (guard-rail de semelhanca, sem numero-alvo) ---')
    n_blocked_ok = sum(1 for r in rows_all if r['hist_blocked'] == r['engine_blocked'])
    print(f'  bloquear ou nao:          {_pct(n_blocked_ok, len(rows_all))}')
    ambos_blocked = [r for r in rows_all if r['hist_blocked'] and r['engine_blocked']]
    n_carta_ok = sum(1 for r in ambos_blocked
                     if r['engine_blocker_card']
                     and r['engine_blocker_card'] in (r.get('hist_blocker_card') or ''))
    print(f'  qual carta bloqueou:      {_pct(n_carta_ok, len(ambos_blocked))}'
          f'  (so quando os dois bloquearam)')
    n_counter_ok = sum(1 for r in rows_all if r['hist_countered'] == r['engine_countered'])
    print(f'  counterar ou nao:         {_pct(n_counter_ok, len(rows_all))}')

    # ── 2. MARGEM das decisoes reconstruidas (o que o trace novo da) ─────
    print('\n--- margem da decisao reconstruida (bt/ct -- quao apertado foi o call) ---')
    margens_blocker: list[float] = []
    margens_blocker_discordou: list[float] = []
    for r in rows_all:
        bt = r.get('blocker_trace')
        if not bt:
            continue
        melhor_custo = max((c['custo'] for c in bt['candidatos']), default=bt['golpe_sem_bloquear'])
        margem = abs(melhor_custo - bt['golpe_sem_bloquear'])
        margens_blocker.append(margem)
        if r['hist_blocked'] != r['engine_blocked']:
            margens_blocker_discordou.append(margem)
    if margens_blocker:
        print(f'  blocker: margem media geral = {sum(margens_blocker)/len(margens_blocker):.3f}  '
              f'(n={len(margens_blocker)}, de {len(rows_all)} janelas -- so quando o value_net decidiu)')
        if margens_blocker_discordou:
            m = sum(margens_blocker_discordou) / len(margens_blocker_discordou)
            print(f'           margem media NOS CASOS QUE DISCORDARAM do historico = {m:.3f}  '
                  f'(n={len(margens_blocker_discordou)})')
            print('           (margem pequena aqui = call apertado, nao erro grosseiro; '
                  'margem grande = leitura bem diferente da partida real)')
    else:
        print('  blocker: nenhuma janela com trace (value_net nao decidiu em nenhuma, ou 0 blockers no board)')

    margens_counter: list[float] = []
    margens_counter_discordou: list[float] = []
    for r in rows_all:
        ct = r.get('counter_trace')
        if not ct:
            continue
        margem = abs(ct['custo_counterar'] - ct['perda_sem_counter'])
        margens_counter.append(margem)
        if r['hist_countered'] != r['engine_countered']:
            margens_counter_discordou.append(margem)
    if margens_counter:
        print(f'  counter: margem media geral = {sum(margens_counter)/len(margens_counter):.3f}  '
              f'(n={len(margens_counter)}, de {len(rows_all)} janelas)')
        if margens_counter_discordou:
            m = sum(margens_counter_discordou) / len(margens_counter_discordou)
            print(f'           margem media NOS CASOS QUE DISCORDARAM do historico = {m:.3f}  '
                  f'(n={len(margens_counter_discordou)})')
    else:
        print('  counter: nenhuma janela com trace')

    if erros:
        print(f'\n{len(erros)} erro(s)/exclusao(oes):')
        for msg in erros[:15]:
            print(f'  {msg}')
        if len(erros) > 15:
            print(f'  ... e mais {len(erros) - 15}')


if __name__ == '__main__':
    main()
