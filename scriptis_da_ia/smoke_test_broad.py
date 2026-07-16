"""
Smoke test amplo: monta decks aleatorios validos (1 leader + 50 nao-lideres,
mesma cor do leader) a partir do cards_rows.csv real, e roda N partidas
completas via OPTCGMatch.simulate(), capturando QUALQUER exceção.
Objetivo: garantir que as mudancas em execute()/apply_your_turn_buffs()
(que rodam para TODAS as cartas, nao so as 25 afetadas) nao quebraram nada
no resto do pool.
"""
import os, sys, random, traceback
sys.path.insert(0, '.')
from optcg_engine.decision_engine import (
    load_cards_db, _make_card, Card, CardData, OPTCGMatch
)

random.seed(42)

db = load_cards_db('cards_rows.csv')
leaders = {c: d for c, d in db.items() if d['type'] == 'LEADER'}
non_leaders_by_color = {}
for code, data in db.items():
    if data['type'] == 'LEADER':
        continue
    non_leaders_by_color.setdefault(data['color'], []).append(code)

def random_deck():
    leader_code = random.choice(list(leaders.keys()))
    leader_data = leaders[leader_code]
    leader = _make_card(leader_code, leader_data)
    color = leader_data['color']
    pool = non_leaders_by_color.get(color, [])
    if len(pool) < 10:
        pool = pool + sum((v for v in non_leaders_by_color.values()), [])
    cards = []
    chosen = random.sample(pool, min(13, len(pool)))
    for code in chosen:
        for _ in range(4):
            cards.append(_make_card(code, db[code]))
    cards = cards[:50]
    while len(cards) < 50 and pool:
        extra = random.choice(pool)
        cards.append(_make_card(extra, db[extra]))
    return leader, cards, None

# Lotes diarios usam 7 para feedback rapido. Checkpoints maiores podem rodar
# `SMOKE_BROAD_N=40 python smoke_test_broad.py` sem editar o arquivo.
N = int(os.environ.get('SMOKE_BROAD_N', '7'))
falhas = []
for i in range(N):
    try:
        deck_a = random_deck()
        deck_b = random_deck()
        match = OPTCGMatch(deck_a, deck_b)
        result = match.simulate()
        assert result['winner'] in ('A', 'B', 'DRAW')
    except Exception as e:
        falhas.append((i, str(e), traceback.format_exc()))

print(f'{N - len(falhas)}/{N} partidas completaram sem exceção')
if falhas:
    print()
    print('=== FALHAS ===')
    for i, msg, tb in falhas[:5]:
        print(f'--- partida {i} ---')
        print(tb[-1500:])
        print()
sys.exit(1 if falhas else 0)
