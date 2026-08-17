"""
audit_candidate_generation.py -- audita a GERACAO de candidatos por arquetipo.

Item 1 do roadmap do bloco 569. Nasceu da constatacao de que 3 dos 4 achados
de 16/08 nao eram erro de PONTUACAO, e sim **opcao que nunca chegou a ser
gerada**: "guardar o [Blocker]" (b.563), a janela de custo de DON (b.565/566)
e "anexar DON no LIDER" (b.567). Calibragem de peso nao alcanca esse tipo de
bug -- jogada nao gerada tem probabilidade ZERO, nao baixa -- e ela ainda some
das metricas de arrependimento (`mean_counterfactual_regret: 0.0` enquanto o
bot ignora a jogada certa).

Enquanto o `decision_quality_report.py` pergunta "das opcoes oferecidas, o bot
escolheu bem?", este script pergunta o passo ANTERIOR: **"o que sequer virou
opcao?"**

Mede, por lider/deck, sobre N partidas de self-play:

  1. TIPOS DE ACAO gerados (play/attack/attach_don/activate/...): quais o
     Turn Planner produz e quais NUNCA aparecem.
  2. ALVO do `attach_don`: separa LIDER de personagem. Era exatamente o bug do
     bloco 567 -- o loop so percorria `field_chars`, entao "anexar DON no
     lider" nunca existia. Serve de teste de nao-regressao permanente.
  3. CARTAS DO DECK QUE NUNCA VIRARAM CANDIDATA: o sinal mais forte. Uma carta
     que o deck inteiro tem 4 copias e que jamais aparece em `candidates` e
     candidata a buraco de geracao -- nao a "carta ruim".

LIMITACAO (mesma do decision_quality_report, herdada do decision_log): so os
top-8 candidatos por decisao sao gravados. Uma carta que aparece mas nunca
chega perto do topo pode ser contada como "nunca ofertada". Por isso a saida
separa "nunca vista em NENHUM candidato" (sinal forte) de "vista poucas
vezes" (ruido possivel). Confirmar na mao antes de tratar como bug.

Uso:
    python audit_candidate_generation.py --leader OP13-001 --n 10 --workers 4 --decks-do-jogo
"""
from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import io
import random
from collections import Counter, defaultdict

from replay_optcg import ReplayMatch
from decision_quality_report import _load_deck_list


def _run_one(task):
    i, seed, leader_code, pool_size, decks_do_jogo = task
    deck_list = _load_deck_list(pool_size, decks_do_jogo)
    alvos = [idx for idx, (_, d) in enumerate(deck_list) if d[0].code == leader_code]
    if not alvos:
        return None
    rng = random.Random(seed)
    ia = rng.choice(alvos)
    ib = rng.choice([x for x in range(len(deck_list)) if x != ia])
    (na, da), (nb, db) = deck_list[ia], deck_list[ib]
    random.seed(seed)

    # Composicao real do deck do lado auditado (pra saber o que DEVERIA
    # poder aparecer algum dia)
    codes_no_deck = Counter(c.code for c in da[1])

    kinds = Counter()
    attach_alvo = Counter()
    vistos = Counter()

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        match = ReplayMatch(da, db, na[:25], nb[:25])
        match.enable_decision_audit()
        match.setup()
        for t in range(match.MAX_TURNS * 2):
            p = match.state_a if t % 2 == 0 else match.state_b
            o = match.state_b if p is match.state_a else match.state_a
            if match.play_turn(p, o):
                break

    for e in (match.decision_log or []):
        if not e or e.get('kind') != 'turn_planner' or e.get('player') != 'A':
            continue
        for c in (e.get('candidates') or []):
            k = c.get('kind')
            if not k:
                continue
            kinds[k] += 1
            card = c.get('card') or {}
            code = card.get('code')
            if code:
                vistos[code] += 1
            if k == 'attach_don':
                # alvo do attach: o proprio lider ou um personagem?
                alvo = c.get('target') or card
                acode = (alvo or {}).get('code') if isinstance(alvo, dict) else None
                if acode and acode == match.state_a.leader.code:
                    attach_alvo['LIDER'] += 1
                else:
                    attach_alvo['personagem'] += 1

    return {'kinds': kinds, 'attach_alvo': attach_alvo,
            'vistos': vistos, 'deck': codes_no_deck, 'nome': na}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--leader', required=True)
    ap.add_argument('--n', type=int, default=10)
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--pool-size', type=int, default=30)
    ap.add_argument('--decks-do-jogo', action='store_true')
    args = ap.parse_args()

    tasks = [(i, args.seed * 1_000_003 + i, args.leader, args.pool_size,
              args.decks_do_jogo) for i in range(args.n)]
    if args.workers <= 1:
        res = [_run_one(t) for t in tasks]
    else:
        with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as ex:
            res = list(ex.map(_run_one, tasks))
    res = [r for r in res if r]
    if not res:
        raise SystemExit(f'lider {args.leader} sem deck valido no pool '
                         f'(use --decks-do-jogo se for deck seu do simulador)')

    kinds = Counter()
    attach = Counter()
    vistos = Counter()
    deck = Counter()
    for r in res:
        kinds.update(r['kinds'])
        attach.update(r['attach_alvo'])
        vistos.update(r['vistos'])
        deck.update(r['deck'])

    print('=' * 72)
    print(f'GERACAO DE CANDIDATOS -- lider {args.leader} ({len(res)} partidas)')
    print(f'deck: {res[0]["nome"]}')
    print('=' * 72)

    print('\n1) TIPOS DE ACAO gerados pelo Turn Planner')
    for k, v in kinds.most_common():
        print(f'   {k:22} {v:6}')
    esperados = {'play', 'attack', 'attach_don', 'activate', 'play_from_trash'}
    faltando = esperados - set(kinds)
    if faltando:
        print(f'   >> NUNCA gerados: {sorted(faltando)}')

    print('\n2) Alvo do attach_don (bug do bloco 567: LIDER nunca aparecia)')
    if not attach:
        print('   nenhum attach_don gerado nesta amostra')
    else:
        for k, v in attach.most_common():
            print(f'   {k:22} {v:6}')
        if 'LIDER' not in attach:
            print('   >> ALERTA: attach_don no LIDER nunca gerado '
                  '(regressao do bloco 567?)')

    print('\n3) Cartas do deck que NUNCA viraram candidata')
    nunca = sorted((c for c in deck if c not in vistos),
                   key=lambda c: -deck[c])
    if not nunca:
        print('   nenhuma -- toda carta do deck apareceu como candidata alguma vez')
    else:
        print(f'   {len(nunca)} de {len(deck)} codigos distintos do deck:')
        for c in nunca:
            print(f'     {c:12} x{deck[c]} no deck')
    raras = sorted(((c, vistos[c]) for c in deck if 0 < vistos[c] <= 2),
                   key=lambda x: x[1])
    if raras:
        print('   -- vistas 1-2x (pode ser ruido do top-8, nao alarme):')
        print('     ' + ', '.join(f'{c}({n})' for c, n in raras))

    print('\nLEITURA: "nunca virou candidata" e o sinal FORTE (buraco de geracao,')
    print('nao carta ruim). O decision_log so grava os top-8 por decisao, entao')
    print('confirme na mao antes de tratar como bug -- ver docstring.')


if __name__ == '__main__':
    main()
