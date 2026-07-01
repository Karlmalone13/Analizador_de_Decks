#!/usr/bin/env python3
"""
compare_vs_human.py -- Compara as decisoes da IA com as do humano,
turno a turno, a partir de um log de partida real parseado.

Uso:
    python compare_vs_human.py logs/parsed/<arquivo>.json
    python compare_vs_human.py logs/parsed/<arquivo>.json --player Karlmalone#2854
    python compare_vs_human.py logs/parsed/<arquivo>.json --turn 7
    python compare_vs_human.py logs/parsed/<arquivo>.json --no-state

Para cada turno mostra:
  - Estado reconstruido (mao, campo, DON, vida)
  - O que o humano fez (jogadas do log)
  - O que a IA teria feito (top acoes por score do Turn Planner)
  - DIVERGENCIA quando IA e humano escolheram diferente
"""

import sys
import json
import argparse
from pathlib import Path

ENGINE_DIR = Path(__file__).parent / 'optcg_engine'
sys.path.insert(0, str(ENGINE_DIR))
sys.path.insert(0, str(Path(__file__).parent))

from decision_engine import (
    load_cards_db, _make_card, _CARD_DATA_CACHE,
    Card, CardData, GameState, OPTCGMatch, DecisionEngine,
    get_card_effects,
)
from optcg_engine.opponent_model import OpponentModel

import dataclasses

CARDS_DB: dict = {}

# ---------------------------------------------------------------------------
# Construcao de Card a partir de codigo
# ---------------------------------------------------------------------------

def make_card_from_code(code: str) -> Card:
    data = CARDS_DB.get(code)
    if data is None:
        cd = _CARD_DATA_CACHE.get(code)
        if cd is None:
            cd = CardData(code=code, name=code, card_type='CHARACTER',
                          color='', cost=0, power=0)
            _CARD_DATA_CACHE[code] = cd
        return Card(data=cd)
    return _make_card(code, data)


def make_leader_card(code: str) -> Card:
    card = make_card_from_code(code)
    if card.data.card_type != 'LEADER':
        leader_key = code + '__leader'
        cd = _CARD_DATA_CACHE.get(leader_key)
        if cd is None:
            cd = dataclasses.replace(card.data, card_type='LEADER')
            _CARD_DATA_CACHE[leader_key] = cd
        card = Card(data=cd,
                    has_rush=card.has_rush,
                    has_blocker=card.has_blocker,
                    has_double_attack=card.has_double_attack,
                    has_banish=card.has_banish,
                    has_unblockable=card.has_unblockable)
    return card


def make_life_cards(count: int) -> list:
    """Cria N cartas de placeholder representando Life (face-down)."""
    cd = _CARD_DATA_CACHE.get('__life__')
    if cd is None:
        cd = CardData(code='__life__', name='Life', card_type='CHARACTER',
                      color='', cost=0, power=0)
        _CARD_DATA_CACHE['__life__'] = cd
    return [Card(data=cd) for _ in range(count)]


# ---------------------------------------------------------------------------
# Construcao de GameState a partir de snapshot
# ---------------------------------------------------------------------------

def build_game_states(turn_data: dict, meta: dict, active_player_name: str):
    """
    Retorna (state_active, state_opp) como GameState.
    Usa o snapshot do turno (estado apos o turno, que e o estado no inicio
    do turno seguinte do ativo).
    """
    snap    = turn_data.get('snapshot', {})
    players = meta['players']
    p1_name = players['p1']['name']
    p2_name = players['p2']['name']
    opp_name = p2_name if active_player_name == p1_name else p1_name

    active_meta = players['p1'] if active_player_name == p1_name else players['p2']
    opp_meta    = players['p2'] if active_player_name == p1_name else players['p1']

    active_snap = snap.get(active_player_name, {})
    opp_snap    = snap.get(opp_name, {})

    # Jogador ativo
    leader_active = make_leader_card(active_meta['leader'].get('code', ''))
    hand_a   = [make_card_from_code(c) for c in active_snap.get('hand', [])]
    board_a  = [make_card_from_code(c) for c in active_snap.get('board', [])]
    trash_a  = [make_card_from_code(c) for c in active_snap.get('trash', [])]
    life_cnt_a = active_snap.get('life', 4)
    don_drawn  = turn_data.get('don_drawn', 2)

    state_a = GameState(
        leader=leader_active,
        hand=hand_a,
        field_chars=board_a,
        trash=trash_a,
        life=make_life_cards(life_cnt_a),
        don_available=don_drawn,
        don_rested=max(0, 10 - don_drawn),
        don_deck=0,
        turn=turn_data.get('turn', 1),
        is_first=True,
    )

    # Oponente
    leader_opp = make_leader_card(opp_meta['leader'].get('code', ''))
    board_o  = [make_card_from_code(c) for c in opp_snap.get('board', [])]
    trash_o  = [make_card_from_code(c) for c in opp_snap.get('trash', [])]
    life_cnt_o = opp_snap.get('life', 4)

    state_o = GameState(
        leader=leader_opp,
        hand=[],
        field_chars=board_o,
        trash=trash_o,
        life=make_life_cards(life_cnt_o),
        don_available=0,
        don_rested=10,
        don_deck=0,
        turn=turn_data.get('turn', 1),
        is_first=False,
    )

    return state_a, state_o


# ---------------------------------------------------------------------------
# Execucao do Turn Planner
# ---------------------------------------------------------------------------

def get_ai_actions(turn_data: dict, meta: dict, active_player: str) -> list:
    """
    Reconstroi o estado e roda _generate_and_score_actions.
    Retorna lista de dicts com score, tipo, carta.
    """
    snap = turn_data.get('snapshot', {})
    if not snap.get(active_player):
        return [{'error': 'sem snapshot para este jogador'}]

    try:
        state_a, state_o = build_game_states(turn_data, meta, active_player)

        # Instancia OPTCGMatch minimo (sem __init__ completo)
        match = OPTCGMatch.__new__(OPTCGMatch)
        match.state_a = state_a
        match.state_b = state_o
        match.global_turn = turn_data.get('turn', 1)
        match.replay_log = None
        match._suppress_replay_log = False
        match._name_a = active_player
        match._name_b = 'opp'
        match.decision_log = None
        match.model_for_a = OpponentModel(full_decklist=[])
        match.model_for_b = OpponentModel(full_decklist=[])

        engine = DecisionEngine(state_a, state_o)
        actions = match._generate_and_score_actions(state_a, state_o, engine)

    except Exception as e:
        import traceback
        return [{'error': f'{e}\n{traceback.format_exc()[-400:]}'}]

    result = []
    for item in sorted(actions, key=lambda x: -x[0])[:8]:
        score   = item[0]
        kind    = item[1]
        card    = item[2] if len(item) > 2 else None
        ccode   = card.code if card and hasattr(card, 'code') else ''
        cname   = card.name[:28] if card and hasattr(card, 'name') else ''
        result.append({'score': round(score, 1), 'type': kind,
                       'card': ccode, 'card_name': cname})
    return result


# ---------------------------------------------------------------------------
# Formatacao da saida
# ---------------------------------------------------------------------------

DIVIDER = '=' * 70

def _card_label(code: str) -> str:
    d = CARDS_DB.get(code, {})
    return f'{code}  {d.get("name", "")[:25]}' if d else code


def print_turn(turn: dict, meta: dict, active_player: str, show_state: bool):
    snap    = turn['snapshot']
    actions = turn['actions']
    t_num   = turn['turn']
    don     = turn.get('don_drawn', '?')
    drawn   = turn.get('card_drawn') or {}
    drawn_s = f'{drawn.get("code","")} {drawn.get("name","")[:20]}' if drawn else '-'

    players  = meta['players']
    p1_name  = players['p1']['name']
    opp_name = players['p2']['name'] if active_player == p1_name else players['p1']['name']

    as_ = snap.get(active_player, {})
    os_ = snap.get(opp_name, {})

    print(f'\n{DIVIDER}')
    print(f'  T{t_num:02d}  {active_player}  |  +{don} DON  comprou: {drawn_s}')
    print(DIVIDER)

    if show_state:
        vida_eu  = as_.get('life', '?')
        vida_opp = os_.get('life', '?')
        hand     = as_.get('hand', [])
        board    = as_.get('board', [])
        trash    = as_.get('trash', [])
        ob       = os_.get('board', [])

        print(f'  Vida eu={vida_eu}  opp={vida_opp}  DON={don}  Mao={len(hand)}')
        if hand:
            print('  MAO:')
            for c in hand:
                print(f'    {_card_label(c)}')
        if board:
            print('  CAMPO (eu):')
            for c in board:
                print(f'    {_card_label(c)}')
        if ob:
            print('  CAMPO (opp):')
            for c in ob:
                print(f'    {_card_label(c)}')
        if trash:
            print(f'  TRASH ({len(trash)}): ' + ', '.join(trash[:5]) +
                  ('...' if len(trash) > 5 else ''))

    # Humano
    plays   = [a for a in actions if a['type'] == 'play']
    attacks = [a for a in actions if a['type'] == 'attack']
    activs  = [a for a in actions if a['type'] == 'activate']

    print('\n  [HUMANO]')
    for a in plays:
        print(f'    PLAY   {a["card"]:12s} {a.get("card_name","")[:28]}')
    for a in activs:
        print(f'    ACTIV  {a["card"]:12s} {a.get("card_name","")[:28]}')
    for a in attacks:
        res = f'HIT({a["damage"]})' if a['result'] == 'hit' else 'BLOCKED'
        blk = f'  [bloq: {a["blocked_by"][:15]}]' if a['blocked_by'] else ''
        print(f'    ATK    {a["attacker"][:20]}  -> {res}{blk}')
    if not plays and not attacks and not activs:
        print('    (sem acoes registradas)')

    # IA
    print('\n  [IA — top acoes por score]')
    ai = get_ai_actions(turn, meta, active_player)
    for i, a in enumerate(ai):
        if 'error' in a:
            print(f'    ERRO: {a["error"][:200]}')
            return
        marker = '>>>' if i == 0 else '   '
        cinfo  = f'{a["card"]:12s} {a["card_name"]}' if a['card'] else ''
        print(f'    {marker} [{a["score"]:7.1f}]  {a["type"]:14s} {cinfo}')

    # Divergencia
    human_cards = {a['card'] for a in plays}
    ai_top = ai[0] if ai and 'error' not in ai[0] else None

    if ai_top:
        ai_card = ai_top['card']
        if human_cards and ai_card and ai_card not in human_cards:
            print(f'\n  *** DIVERGENCIA: humano jogou {human_cards} | '
                  f'IA preferia {ai_card} ({ai_top["card_name"]}) '
                  f'[score {ai_top["score"]}]')
        elif not plays and not attacks and ai_top['score'] > 30:
            print(f'\n  *** DIVERGENCIA: humano passou | '
                  f'IA teria feito {ai_top["type"]} {ai_card} '
                  f'[score {ai_top["score"]}]')


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('log_json', help='JSON parseado em logs/parsed/')
    ap.add_argument('--player', default=None, help='Filtrar por jogador')
    ap.add_argument('--turn',   type=int, default=None, help='So este turno')
    ap.add_argument('--no-state', action='store_true',
                    help='Omitir mao/campo (saida mais curta)')
    args = ap.parse_args()

    csv_path = Path(__file__).parent / 'cards_rows.csv'
    print('Carregando banco de cartas...')
    global CARDS_DB
    CARDS_DB = load_cards_db(str(csv_path))

    log_path = Path(args.log_json)
    if not log_path.exists():
        print(f'Nao encontrado: {log_path}')
        sys.exit(1)

    data  = json.loads(log_path.read_text(encoding='utf-8'))
    meta  = data['meta']
    turns = data['turns']
    p1    = meta['players']['p1']
    p2    = meta['players']['p2']

    print(f'\n{DIVIDER}')
    print(f'  {p1["name"]} ({p1["leader"]["name"]}) vs '
          f'{p2["name"]} ({p2["leader"]["name"]})')
    print(f'  {data["total_turns"]} turnos')
    print(DIVIDER)

    for turn in turns:
        player = turn.get('player')
        if not player:
            continue
        if args.player and player != args.player:
            continue
        if args.turn and turn['turn'] != args.turn:
            continue
        print_turn(turn, meta, player, show_state=not args.no_state)

    print(f'\n{DIVIDER}  Fim  {DIVIDER}\n')


if __name__ == '__main__':
    main()
