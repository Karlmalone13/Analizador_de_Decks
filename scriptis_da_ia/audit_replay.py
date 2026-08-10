"""
Auditoria via partida real instrumentada: roda N matchups reais (decklists de
torneio, decklists_raw.csv) via ReplayMatch (mesmo motor do replay_optcg.py,
sem a parte interativa/visual) e reporta o que a instrumentacao unificada do
motor encontrar.

As checagens de invariante (conservacao de DON, poder nunca negativo,
conservacao de contagem de cartas) NAO vivem mais neste script -- foram
migradas pra `OPTCGMatch._check_invariants()` (decision_engine.py, pedido do
usuario 25/07: uma lista de auditoria so, `decision_log`, em vez de um script
externo com sua propria checagem). Este script so liga
`enable_decision_audit()`, roda as partidas, e filtra `decision_log` por
`kind == 'invariant_violation'` -- qualquer outro consumidor de self-play
(baseline_metrics.py, tune_weights.py, o futuro simulador self x self) ganha
a MESMA checagem de graca so ligando a auditoria.

Unica checagem que NAO foi migrada (natureza diferente -- varredura do texto
IMPRESSO da partida inteira, nao um invariante de GameState): captura
qualquer linha de log contendo "nao implementado".

Uso: python audit_replay.py [--n N] [--seed S] [--workers W]

Paralelismo (achado 10/08, pedido do usuario "acelerar as simulacoes"):
partidas sao 100% independentes entre si (nenhum estado compartilhado) --
`--workers N` roda N partidas em processos separados via ProcessPoolExecutor,
mesmo padrao ja usado e validado nos scripts de calibracao self-play (blocos
449/459/468/480). `--workers 1` (default) preserva o comportamento sequencial
de sempre. Nota de reprodutibilidade: a versao sequencial antiga avançava um
UNICO `random` global entre as partidas (seed do match N dependia de quantas
chamadas de random.* as partidas 0..N-1 ja tinham feito) -- com paralelismo
isso não é reproduzível entre processos, então cada partida agora usa sua
PRÓPRIA seed derivada de `--seed`+índice (`args.seed * 1_000_003 + i`),
independente de execução sequencial ou paralela ou da ordem em que os
processos terminam. Resultado: `--seed` continua determinístico (mesmo seed
= mesmos matchups/mesmas partidas), só a combinação exata de matchups por
índice muda em relação ao comportamento pré-paralelismo.
"""
import argparse
import concurrent.futures
import contextlib
import io
import os
import random
import sys
import traceback

import pandas as pd

from replay_optcg import ReplayMatch
from optcg_engine.decision_engine import build_real_deck, load_cards_db, validar_deck


def _load_deck_list():
    cards_db = load_cards_db('cards_rows.csv')
    df_raw = pd.read_csv('decklists_raw.csv')
    urls = df_raw.groupby('deck_url')['deck_name'].first()

    deck_list = []
    for url, name in urls.items():
        result = build_real_deck(name, url, df_raw, cards_db)
        if not result:
            continue
        leader, cards, start_stage = result
        valido, erros = validar_deck(leader, cards, cards_db)
        if not valido:
            continue
        if len(cards) >= 40:
            deck_list.append((name, (leader, cards, start_stage)))
        if len(deck_list) >= 16:
            break
    return deck_list


def _run_one_match(task):
    """Roda 1 partida completa e devolve tudo que o processo principal
    precisa pra reportar/agregar -- SEM depender de estado global
    compartilhado (cada chamada roda potencialmente num processo separado)."""
    i, match_seed = task
    deck_list = _load_deck_list()  # cada processo carrega o proprio banco
    rng = random.Random(match_seed)
    idx_a, idx_b = rng.sample(range(len(deck_list)), 2)
    name_a, deck_a = deck_list[idx_a]
    name_b, deck_b = deck_list[idx_b]

    # O motor usa `random.*` global (nao um Random() proprio) pra amostragem
    # Monte Carlo/decisoes internas -- precisa da MESMA seed determinada por
    # match, nao so o rng.sample() acima (que so escolhe o matchup).
    random.seed(match_seed)

    anomalias_locais = []
    exception_local = False
    vencedor = None
    turnos = '?'
    dump_info = None  # (path, texto) se achar don_conservation

    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            match = ReplayMatch(deck_a, deck_b, name_a[:25], name_b[:25])
            match.enable_decision_audit()
            match.setup()
            # Mesma logica canonica de OPTCGMatch.simulate()
            for turn_num in range(match.MAX_TURNS * 2):
                p = (match.state_a if match.state_a.is_first else match.state_b) \
                    if turn_num % 2 == 0 \
                    else (match.state_b if match.state_a.is_first else match.state_a)
                opp = match.state_b if p is match.state_a else match.state_a
                vencedor = match.play_turn(p, opp)
                if vencedor:
                    break

        turnos = match.global_turn if hasattr(match, "global_turn") else "?"
        texto = buf.getvalue()
        for entry in match.decision_log or []:
            if entry.get('kind') != 'invariant_violation':
                continue
            label = name_a[:20] if entry.get('player') == 'A' else name_b[:20]
            anomalias_locais.append(f"Match {i} ({name_a[:15]} vs {name_b[:15]}): "
                             f"[T{entry.get('turn')}] {label}: {entry.get('check')} "
                             f"-- {entry.get('detail')}")
            if entry.get('check') == 'don_conservation' and dump_info is None:
                dump_path = f"{os.environ.get('TEMP', '.')}/don_dump_match_{i}.txt"
                dump_info = (dump_path, texto)

        if 'nao implementado' in texto.lower():
            for linha in texto.splitlines():
                if 'nao implementado' in linha.lower():
                    anomalias_locais.append(f'Match {i}: log com "nao implementado" -> {linha.strip()}')
    except Exception as e:
        exception_local = True
        anomalias_locais.append(f'Match {i} ({name_a[:15]} vs {name_b[:15]}): EXCECAO {type(e).__name__}: {e}')
        anomalias_locais.append(traceback.format_exc()[-800:])

    if dump_info:
        dump_path, dump_texto = dump_info
        with open(dump_path, 'w', encoding='utf-8') as fdump:
            fdump.write(dump_texto)
        anomalias_locais.append(f'  (log completo do Match {i} salvo em {dump_path})')

    return i, name_a, name_b, vencedor, turnos, anomalias_locais, exception_local


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--n', type=int, default=25, help='numero de partidas a rodar')
    parser.add_argument('--seed', type=int, default=42, help='seed do random (reprodutibilidade)')
    parser.add_argument('--workers', type=int, default=1,
                        help='processos paralelos (1=sequencial, comportamento de sempre). '
                             'Partidas sao independentes -- paraleliza sem risco de correcao.')
    args = parser.parse_args()

    deck_list = _load_deck_list()
    print(f'{len(deck_list)} decks reais carregados do decklists_raw.csv')

    tasks = [(i, args.seed * 1_000_003 + i) for i in range(args.n)]

    if args.workers <= 1:
        resultados = [_run_one_match(t) for t in tasks]
    else:
        with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as ex:
            resultados = list(ex.map(_run_one_match, tasks))
        resultados.sort(key=lambda r: r[0])

    anomalias = []
    exceptions = 0
    for i, name_a, name_b, vencedor, turnos, anomalias_locais, exception_local in resultados:
        anomalias.extend(anomalias_locais)
        if exception_local:
            exceptions += 1
        print(f'  Match {i+1}/{args.n}: {name_a[:20]} vs {name_b[:20]} -> vencedor={vencedor}, '
              f'turnos={turnos}')

    print()
    print(f'{"="*70}')
    print(f'{args.n} partidas reais rodadas (seed={args.seed}), {exceptions} excecoes')
    print(f'{len(anomalias)} anomalias encontradas:')
    print(f'{"="*70}')
    for a in anomalias[:60]:
        print(' -', a)
    if len(anomalias) > 60:
        print(f'  ... e mais {len(anomalias)-60}')

    sys.exit(1 if (exceptions or anomalias) else 0)


if __name__ == '__main__':
    main()
