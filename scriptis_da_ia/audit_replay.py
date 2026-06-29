"""
Auditoria via partida real instrumentada: roda N matchups reais (decklists de
torneio, decklists_raw.csv) via ReplayMatch (mesmo motor do replay_optcg.py,
sem a parte interativa/visual) e, a cada turno, verifica invariantes que NÃO
são cobertas pelo smoke_test_broad.py (que só checa "não lançou excecao"):

1. Conservação de DON: don_available + don_rested + don_attached em campo
   (chars + leader) deve ser exatamente (10 - don_deck) para cada jogador.
   Detecta também carta duplicada por REFERÊNCIA (mesmo objeto Python 2x)
   em field_chars -- foi assim que se achou o bug de identidade do Card
   corrigido em 29/06/2026 (ver TODO.md).
2. Power nunca negativo (debuffs empilhados podem zerar na regra real, não
   ficar negativo).
3. Conservação de contagem de cartas (hand+field_chars+deck+trash+life+stage
   nunca muda durante a partida -- nenhuma carta sai do pool de 50/51).
4. Captura qualquer string de log contendo "nao implementado".

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


def check_don_conservation(p, label, turno):
    field_don = sum(c.don_attached for c in p.field_chars) + p.leader.don_attached
    total = p.don_available + p.don_rested + field_don
    esperado = 10 - p.don_deck
    if total != esperado:
        detalhe = ', '.join(f'{c.name[:18]}(id={id(c)})={c.don_attached}' for c in p.field_chars if c.don_attached) or '(nenhum)'
        detalhe += f' | leader={p.leader.name[:18]}={p.leader.don_attached}'
        ids = [id(c) for c in p.field_chars]
        dups = [i for i in set(ids) if ids.count(i) > 1]
        if dups:
            detalhe += f' | DUPLICADO NA LISTA field_chars: {len(dups)} objeto(s) repetido(s), ids={dups}'
        return (f'[T{turno}] {label}: DON nao bate -- available={p.don_available} '
                f'rested={p.don_rested} field={field_don} soma={total} '
                f'esperado(10-don_deck)={esperado} | detalhe: {detalhe}')
    return None


def check_negative_power(p, label, turno):
    issues = []
    for c in p.field_chars + [p.leader]:
        if c.effective_power() < 0:
            issues.append(f'[T{turno}] {label}: {c.name} com power negativo ({c.effective_power()})')
    return issues


def total_cards(p):
    """Conservacao de cartas: hand+field_chars+deck+trash+life nunca muda
    durante a partida (nenhuma carta sai do pool de 50 -- [Banish] aqui e so
    a keyword de combate, nao remove carta do jogo). Conta por tamanho de
    lista, nao por id() de objeto -- id() pode ser reciclado pelo GC entre
    cartas efemeras (deepcopy de curta duracao do Turn Planner), o que daria
    falso positivo de "carta duplicada" sem nenhuma acao real por tras."""
    return (len(p.hand) + len(p.field_chars) + len(p.deck) + len(p.trash) + len(p.life)
            + (1 if p.field_stage else 0))


anomalias = []
exceptions = 0
don_dump_feito = set()

for i in range(args.n):
    idx_a, idx_b = random.sample(range(len(deck_list)), 2)
    name_a, deck_a = deck_list[idx_a]
    name_b, deck_b = deck_list[idx_b]

    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            match = ReplayMatch(deck_a, deck_b, name_a[:25], name_b[:25])
            match.setup()
            total_inicial_a = total_cards(match.state_a)
            total_inicial_b = total_cards(match.state_b)
            vencedor = None
            # Mesma logica canonica de OPTCGMatch.simulate()
            for turn_num in range(match.MAX_TURNS * 2):
                p = (match.state_a if match.state_a.is_first else match.state_b) \
                    if turn_num % 2 == 0 \
                    else (match.state_b if match.state_a.is_first else match.state_a)
                opp = match.state_b if p is match.state_a else match.state_a
                vencedor = match.play_turn(p, opp)

                for p_check, label, total_ini in [(match.state_a, name_a[:20], total_inicial_a),
                                                    (match.state_b, name_b[:20], total_inicial_b)]:
                    err = check_don_conservation(p_check, label, match.global_turn)
                    if err:
                        anomalias.append(f'Match {i} ({name_a[:15]} vs {name_b[:15]}): {err}')
                        if i not in don_dump_feito:
                            don_dump_feito.add(i)
                            dump_path = f"{os.environ.get('TEMP', '.')}/don_dump_match_{i}.txt"
                            with open(dump_path, 'w', encoding='utf-8') as fdump:
                                fdump.write(buf.getvalue())
                            anomalias.append(f'  (log completo do Match {i} salvo em {dump_path})')
                    anomalias.extend(f'Match {i}: {x}' for x in check_negative_power(p_check, label, match.global_turn))
                    atual = total_cards(p_check)
                    if atual != total_ini:
                        anomalias.append(f'Match {i} [T{match.global_turn}] {label}: total de cartas mudou '
                                          f'de {total_ini} para {atual} (hand={len(p_check.hand)} '
                                          f'field={len(p_check.field_chars)} deck={len(p_check.deck)} '
                                          f'trash={len(p_check.trash)} life={len(p_check.life)})')

                if vencedor:
                    break
        texto = buf.getvalue()
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
