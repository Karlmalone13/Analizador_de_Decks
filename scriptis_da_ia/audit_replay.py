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

Uso: python audit_replay.py [--n N] [--seed S]
"""
import argparse
import contextlib
import io
import os
import random
import sys
import traceback

import pandas as pd

from replay_optcg import ReplayMatch
from optcg_engine.decision_engine import build_real_deck, load_cards_db, validar_deck

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--n', type=int, default=25, help='numero de partidas a rodar')
parser.add_argument('--seed', type=int, default=42, help='seed do random (reprodutibilidade)')
args = parser.parse_args()

random.seed(args.seed)

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

print(f'{len(deck_list)} decks reais carregados do decklists_raw.csv')


anomalias = []
exceptions = 0
don_dump_feito = set()

for i in range(args.n):
    idx_a, idx_b = random.sample(range(len(deck_list)), 2)
    name_a, deck_a = deck_list[idx_a]
    name_b, deck_b = deck_list[idx_b]

    buf = io.StringIO()
    vencedor = None
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

        texto = buf.getvalue()
        vistos_antes = len(anomalias)
        for entry in match.decision_log or []:
            if entry.get('kind') != 'invariant_violation':
                continue
            label = name_a[:20] if entry.get('player') == 'A' else name_b[:20]
            anomalias.append(f"Match {i} ({name_a[:15]} vs {name_b[:15]}): "
                             f"[T{entry.get('turn')}] {label}: {entry.get('check')} "
                             f"-- {entry.get('detail')}")
            if entry.get('check') == 'don_conservation' and i not in don_dump_feito:
                don_dump_feito.add(i)
                dump_path = f"{os.environ.get('TEMP', '.')}/don_dump_match_{i}.txt"
                with open(dump_path, 'w', encoding='utf-8') as fdump:
                    fdump.write(texto)
                anomalias.append(f'  (log completo do Match {i} salvo em {dump_path})')

        if 'nao implementado' in texto.lower():
            for linha in texto.splitlines():
                if 'nao implementado' in linha.lower():
                    anomalias.append(f'Match {i}: log com "nao implementado" -> {linha.strip()}')
    except Exception as e:
        exceptions += 1
        anomalias.append(f'Match {i} ({name_a[:15]} vs {name_b[:15]}): EXCECAO {type(e).__name__}: {e}')
        anomalias.append(traceback.format_exc()[-800:])

    print(f'  Match {i+1}/{args.n}: {name_a[:20]} vs {name_b[:20]} -> vencedor={vencedor}, '
          f'turnos={match.global_turn if hasattr(match, "global_turn") else "?"}')

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
