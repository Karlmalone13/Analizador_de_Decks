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
import copy
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


def _total_don_for_turn(personal_turn: int, is_first: bool) -> int:
    if personal_turn <= 0:
        return 0
    if is_first:
        return min(10, 1 + (personal_turn - 1) * 2)
    return min(10, personal_turn * 2)


# ---------------------------------------------------------------------------
# Construcao de GameState a partir de snapshot
# ---------------------------------------------------------------------------

def _names(meta: dict, active_player_name: str):
    players = meta['players']
    p1_name = players['p1']['name']
    p2_name = players['p2']['name']
    opp_name = p2_name if active_player_name == p1_name else p1_name
    active_meta = players['p1'] if active_player_name == p1_name else players['p2']
    opp_meta = players['p2'] if active_player_name == p1_name else players['p1']
    return p1_name, p2_name, opp_name, active_meta, opp_meta


def _remove_one(seq: list, code: str) -> bool:
    for i, item in enumerate(seq):
        if item == code:
            seq.pop(i)
            return True
    return False


def _is_stage_code(code: str) -> bool:
    data = CARDS_DB.get(code) or {}
    return (data.get('card_type') or data.get('type') or '').upper() == 'STAGE'


def _infer_stages_until(turns: list, idx: int) -> dict[str, str]:
    stages = {}
    for turn in turns[:idx + 1]:
        player = turn.get('player')
        if not player:
            continue
        for action in turn.get('actions', []):
            code = action.get('card')
            if action.get('type') == 'activate' and code and _is_stage_code(code):
                stages[player] = code
    return stages


def _pre_turn_snapshot(turns: list, idx: int, meta: dict) -> dict:
    """
    Monta um snapshot aproximado de INICIO do turno.

    O JSON do parser guarda snapshots pos-turno. Para comparar a IA com a
    escolha humana, o estado correto e o fim do turno anterior + carta
    comprada no turno atual. Para T1 nao existe turno anterior; usamos o
    snapshot do proprio T1 e desfazemos apenas plays/activates simples que
    aparecem no log (fallback imperfeito, mas menos enganoso que pos-turno).
    """
    turn = turns[idx]
    player = turn.get('player')
    current = copy.deepcopy(turn.get('snapshot', {}))

    if idx > 0:
        current = copy.deepcopy(turns[idx - 1].get('snapshot', {}))

    if player and player in current:
        drawn = (turn.get('card_drawn') or {}).get('code')
        if drawn:
            current[player].setdefault('hand', []).append(drawn)

    for stage_player, stage_code in _infer_stages_until(turns, idx).items():
        current.setdefault(stage_player, {})['stage'] = stage_code

    if idx == 0 and player and player in current:
        st = current[player]
        hand = st.setdefault('hand', [])
        board = st.setdefault('board', [])
        trash = st.setdefault('trash', [])
        for action in reversed(turn.get('actions', [])):
            code = action.get('card')
            if not code:
                continue
            if action.get('type') == 'play':
                if _remove_one(board, code) or _remove_one(trash, code):
                    hand.append(code)

    return current


def build_game_states(turn_data: dict, meta: dict, active_player_name: str,
                      snapshot: dict | None = None):
    """
    Retorna (state_active, state_opp) como GameState.
    Usa snapshot de inicio de turno quando fornecido. O snapshot armazenado
    no log parseado e pos-turno, entao chamar sem `snapshot` deve ser evitado
    para analise IA vs humano.
    """
    snap = snapshot if snapshot is not None else turn_data.get('snapshot', {})
    _p1_name, _p2_name, opp_name, active_meta, opp_meta = _names(meta, active_player_name)

    active_snap = snap.get(active_player_name, {})
    opp_snap    = snap.get(opp_name, {})
    global_turn = turn_data.get('turn', 1)
    active_is_first = (global_turn % 2) == 1
    active_personal_turn = (global_turn + 1) // 2
    opp_personal_turn = max(1, global_turn // 2)
    active_total_don = _total_don_for_turn(active_personal_turn, active_is_first)
    opp_total_don = _total_don_for_turn(opp_personal_turn, not active_is_first)

    # Jogador ativo
    leader_active = make_leader_card(active_meta['leader'].get('code', ''))
    hand_a   = [make_card_from_code(c) for c in active_snap.get('hand', [])]
    board_a  = [make_card_from_code(c) for c in active_snap.get('board', [])]
    trash_a  = [make_card_from_code(c) for c in active_snap.get('trash', [])]
    stage_a  = make_card_from_code(active_snap.get('stage')) if active_snap.get('stage') else None
    life_cnt_a = active_snap.get('life', 4)

    state_a = GameState(
        leader=leader_active,
        hand=hand_a,
        field_chars=board_a,
        field_stage=stage_a,
        trash=trash_a,
        life=make_life_cards(life_cnt_a),
        don_available=active_total_don,
        don_rested=0,
        don_deck=max(0, 10 - active_total_don),
        turn=active_personal_turn,
        is_first=active_is_first,
    )

    # Oponente
    leader_opp = make_leader_card(opp_meta['leader'].get('code', ''))
    board_o  = [make_card_from_code(c) for c in opp_snap.get('board', [])]
    trash_o  = [make_card_from_code(c) for c in opp_snap.get('trash', [])]
    stage_o  = make_card_from_code(opp_snap.get('stage')) if opp_snap.get('stage') else None
    life_cnt_o = opp_snap.get('life', 4)

    state_o = GameState(
        leader=leader_opp,
        hand=[],
        field_chars=board_o,
        field_stage=stage_o,
        trash=trash_o,
        life=make_life_cards(life_cnt_o),
        don_available=0,
        don_rested=opp_total_don,
        don_deck=max(0, 10 - opp_total_don),
        turn=opp_personal_turn,
        is_first=not active_is_first,
    )

    return state_a, state_o


# ---------------------------------------------------------------------------
# Execucao do Turn Planner
# ---------------------------------------------------------------------------

def get_ai_actions(turn_data: dict, meta: dict, active_player: str,
                   snapshot: dict | None = None) -> list:
    """
    Reconstroi o estado e roda _generate_and_score_actions.
    Retorna lista de dicts com score, tipo, carta.
    """
    snap = snapshot if snapshot is not None else turn_data.get('snapshot', {})
    if not snap.get(active_player):
        return [{'error': 'sem snapshot para este jogador'}]

    try:
        state_a, state_o = build_game_states(turn_data, meta, active_player, snapshot=snap)

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

    actionable = [item for item in actions if item[0] > 0]
    if not actionable:
        return [{'score': 0, 'type': 'pass', 'card': '', 'card_name': ''}]

    result = []
    for item in sorted(actionable, key=lambda x: -x[0])[:8]:
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


def _human_action_key(action: dict) -> tuple[str, str]:
    kind = action.get('type', '')
    if kind in ('play', 'activate'):
        return kind, action.get('card') or ''
    if kind == 'attack':
        return kind, action.get('attacker_code') or action.get('attacker') or ''
    if kind == 'attach_don':
        return kind, action.get('target_code') or action.get('target') or ''
    return kind, action.get('card') or ''


def _ai_action_key(action: dict) -> tuple[str, str]:
    return action.get('type', ''), action.get('card') or ''


def _human_turn_keys(actions: list[dict]) -> tuple[set[tuple[str, str]], set[str]]:
    keys = {_human_action_key(a) for a in actions
            if a.get('type') in ('play', 'activate', 'attack', 'attach_don')}
    if not keys:
        keys.add(('pass', ''))
    return keys, {kind for kind, _code in keys}


def _ai_match_label(ai_action: dict, human_keys: set[tuple[str, str]],
                    human_kinds: set[str]) -> str:
    key = _ai_action_key(ai_action)
    if key in human_keys:
        return 'exact'
    if key[0] in human_kinds:
        return 'kind'
    return 'miss'


def summarize_human_vs_ai(data: dict, top_k: int = 5) -> dict:
    meta = data['meta']
    stats = {
        'turns': 0,
        'errors': 0,
        'top1_exact': 0,
        'top1_kind': 0,
        'topk_exact': 0,
        'topk_kind': 0,
        'misses': [],
    }
    for idx, turn in enumerate(data.get('turns', [])):
        player = turn.get('player')
        if not player:
            continue
        stats['turns'] += 1
        human_keys, human_kinds = _human_turn_keys(turn.get('actions', []))
        snap = _pre_turn_snapshot(data['turns'], idx, meta)
        ai_actions = get_ai_actions(turn, meta, player, snapshot=snap)
        if not ai_actions or 'error' in ai_actions[0]:
            stats['errors'] += 1
            continue

        labels = [_ai_match_label(a, human_keys, human_kinds)
                  for a in ai_actions[:top_k]]
        if labels and labels[0] == 'exact':
            stats['top1_exact'] += 1
        if labels and labels[0] in ('exact', 'kind'):
            stats['top1_kind'] += 1
        if 'exact' in labels:
            stats['topk_exact'] += 1
        if any(label in ('exact', 'kind') for label in labels):
            stats['topk_kind'] += 1
        elif len(stats['misses']) < 12:
            stats['misses'].append({
                'turn': turn.get('turn'),
                'player': player,
                'human': sorted(human_keys),
                'ai_top': [_ai_action_key(a) + (a.get('score'),)
                           for a in ai_actions[:top_k]],
            })
    return stats


def print_turn(turn: dict, meta: dict, active_player: str, show_state: bool,
               ai_snapshot: dict | None = None, top_k: int = 5):
    snap    = ai_snapshot if ai_snapshot is not None else turn['snapshot']
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
    ai = get_ai_actions(turn, meta, active_player, snapshot=snap)
    human_keys, human_kinds = _human_turn_keys(actions)
    for i, a in enumerate(ai[:top_k]):
        if 'error' in a:
            print(f'    ERRO: {a["error"][:200]}')
            return
        marker = '>>>' if i == 0 else '   '
        cinfo  = f'{a["card"]:12s} {a["card_name"]}' if a['card'] else ''
        match = _ai_match_label(a, human_keys, human_kinds)
        print(f'    {marker} [{a["score"]:7.1f}]  {a["type"]:14s} {cinfo}  [{match}]')

    # Divergencia
    ai_top = ai[0] if ai and 'error' not in ai[0] else None

    if ai_top:
        top_labels = [_ai_match_label(a, human_keys, human_kinds) for a in ai[:top_k]]
        if top_labels and top_labels[0] == 'miss' and 'exact' not in top_labels:
            print(f'\n  *** DIVERGENCIA: nenhuma acao exata do humano apareceu no top {top_k} da IA')
            print(f'      humano: {sorted(human_keys)}')


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
    ap.add_argument('--top-k', type=int, default=5,
                    help='Quantas acoes da IA comparar contra o turno humano')
    ap.add_argument('--summary', action='store_true',
                    help='Resumo agregado; aceita arquivo ou pasta de logs parseados')
    args = ap.parse_args()

    csv_path = Path(__file__).parent / 'cards_rows.csv'
    print('Carregando banco de cartas...')
    global CARDS_DB
    CARDS_DB = load_cards_db(str(csv_path))

    log_path = Path(args.log_json)
    if not log_path.exists():
        print(f'Nao encontrado: {log_path}')
        sys.exit(1)

    if args.summary:
        paths = sorted(log_path.glob('*.json')) if log_path.is_dir() else [log_path]
        total = {
            'turns': 0,
            'errors': 0,
            'top1_exact': 0,
            'top1_kind': 0,
            'topk_exact': 0,
            'topk_kind': 0,
        }
        misses = []
        for path in paths:
            data = json.loads(path.read_text(encoding='utf-8'))
            stats = summarize_human_vs_ai(data, top_k=args.top_k)
            for key in total:
                total[key] += stats[key]
            for miss in stats['misses']:
                if len(misses) < 12:
                    miss = dict(miss)
                    miss['log'] = path.name
                    misses.append(miss)

        turns = max(1, total['turns'])
        print(f'\n{DIVIDER}')
        print(f'  Logs: {len(paths)} | turnos: {total["turns"]} | erros: {total["errors"]}')
        print(f'  top1 exact: {total["top1_exact"]}/{turns}')
        print(f'  top1 kind : {total["top1_kind"]}/{turns}')
        print(f'  top{args.top_k} exact: {total["topk_exact"]}/{turns}')
        print(f'  top{args.top_k} kind : {total["topk_kind"]}/{turns}')
        if misses:
            print('\n  Amostras sem match no top K:')
            for miss in misses:
                print(f'    {miss["log"]} T{miss["turn"]}: humano={miss["human"]} ia={miss["ai_top"]}')
        print(f'{DIVIDER}\n')
        return

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

    for idx, turn in enumerate(turns):
        player = turn.get('player')
        if not player:
            continue
        if args.player and player != args.player:
            continue
        if args.turn and turn['turn'] != args.turn:
            continue
        ai_snapshot = _pre_turn_snapshot(turns, idx, meta)
        print_turn(turn, meta, player, show_state=not args.no_state,
                   ai_snapshot=ai_snapshot, top_k=args.top_k)

    print(f'\n{DIVIDER}  Fim  {DIVIDER}\n')


if __name__ == '__main__':
    main()
