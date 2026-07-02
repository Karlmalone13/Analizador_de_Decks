#!/usr/bin/env python3
"""
Extrai padroes de pilotagem humana a partir de logs parseados.

Objetivo: gerar sinais para ensinar a IA sobre ordem de jogadas, combos,
ataques e defesa/counter sem tratar poucos logs como regra absoluta.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


def turn_band(turn: int) -> str:
    if turn <= 3:
        return 'early'
    if turn <= 8:
        return 'mid'
    return 'late'


def player_meta(meta: dict, player: str) -> dict:
    players = meta.get('players', {})
    for side in ('p1', 'p2'):
        data = players.get(side, {})
        if data.get('name') == player:
            return data
    return {}


def opponent_name(meta: dict, player: str) -> str:
    players = meta.get('players', {})
    names = [players.get(side, {}).get('name') for side in ('p1', 'p2')]
    for name in names:
        if name and name != player:
            return name
    return ''


def leader_key(meta: dict, player: str) -> str:
    data = player_meta(meta, player)
    leader = data.get('leader', {})
    code = leader.get('code') or 'UNKNOWN'
    name = leader.get('name') or code
    return f'{code}|{name}'


def action_code(action: dict) -> str:
    kind = action.get('type', '')
    if kind in ('play', 'activate'):
        return action.get('card') or ''
    if kind == 'attack':
        return action.get('attacker_code') or action.get('attacker') or ''
    if kind == 'attach_don':
        return action.get('to') or action.get('target_code') or action.get('target') or ''
    return action.get('card') or ''


def action_token(action: dict) -> str:
    kind = action.get('type', '')
    code = action_code(action)
    if not kind:
        return ''
    return f'{kind}:{code}' if code else kind


def action_family(action: dict) -> str:
    kind = action.get('type', '')
    if kind == 'attack':
        if action.get('result') == 'hit':
            return 'attack_hit'
        if action.get('blocked_by'):
            return 'attack_blocked_by_blocker'
        if action.get('countered_by'):
            return 'attack_countered'
        return 'attack_blocked'
    return kind or 'unknown'


def pre_turn_snapshot(turns: list[dict], idx: int) -> dict:
    if idx > 0:
        return turns[idx - 1].get('snapshot', {}) or {}
    return turns[idx].get('snapshot', {}) or {}


def snapshot_context(snapshot: dict, player: str, opp: str) -> dict:
    me = snapshot.get(player, {}) or {}
    other = snapshot.get(opp, {}) or {}
    return {
        'my_life': me.get('life'),
        'opp_life': other.get('life'),
        'my_hand': len(me.get('hand', []) or []),
        'opp_hand': len(other.get('hand', []) or []),
        'my_board': len(me.get('board', []) or []),
        'opp_board': len(other.get('board', []) or []),
        'my_trash': len(me.get('trash', []) or []),
        'opp_trash': len(other.get('trash', []) or []),
    }


def counter_to_dict(counter: Counter, limit: int = 20) -> list[dict]:
    return [{'pattern': key, 'count': value}
            for key, value in counter.most_common(limit)]


def nested_counter_to_dict(data: dict[str, Counter], limit: int = 12) -> dict:
    return {key: counter_to_dict(counter, limit)
            for key, counter in sorted(data.items())}


def card_name(cards_db: dict, code: str) -> str:
    return (cards_db.get(code) or {}).get('name', '')


def load_cards_db(path: Path) -> dict:
    if not path.exists():
        return {}
    import csv
    cards = {}
    with path.open('r', encoding='utf-8-sig', newline='') as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            code = row.get('code') or row.get('id') or row.get('Code')
            if code:
                cards[code] = row
    return cards


def extract_patterns(paths: list[Path], cards_db: dict, min_support: int) -> dict:
    by_leader_band: dict[str, Counter] = defaultdict(Counter)
    by_leader_order: dict[str, Counter] = defaultdict(Counter)
    by_leader_ngram2: dict[str, Counter] = defaultdict(Counter)
    by_leader_ngram3: dict[str, Counter] = defaultdict(Counter)
    by_leader_attack: dict[str, Counter] = defaultdict(Counter)
    by_defender: dict[str, Counter] = defaultdict(Counter)
    context_examples: dict[str, list[dict]] = defaultdict(list)
    global_action_orders = Counter()

    total_turns = 0
    total_actions = 0
    total_defenses = 0

    for path in paths:
        data = json.loads(path.read_text(encoding='utf-8'))
        meta = data.get('meta', {})
        turns = data.get('turns', [])

        for idx, turn in enumerate(turns):
            player = turn.get('player')
            actions = turn.get('actions', []) or []
            if not player:
                continue

            total_turns += 1
            total_actions += len(actions)
            opp = opponent_name(meta, player)
            leader = leader_key(meta, player)
            band = turn_band(turn.get('turn', 0))
            scope = f'{leader}|{band}'
            snapshot = pre_turn_snapshot(turns, idx)
            ctx = snapshot_context(snapshot, player, opp)

            tokens = [action_token(action) for action in actions if action_token(action)]
            families = [action_family(action) for action in actions]
            if not tokens:
                tokens = ['pass']
                families = ['pass']

            order = ' > '.join(families)
            exact_order = ' > '.join(tokens)
            global_action_orders[order] += 1
            by_leader_band[scope][order] += 1
            by_leader_order[leader][exact_order] += 1

            for a, b in zip(tokens, tokens[1:]):
                by_leader_ngram2[leader][f'{a} > {b}'] += 1
            for a, b, c in zip(tokens, tokens[1:], tokens[2:]):
                by_leader_ngram3[leader][f'{a} > {b} > {c}'] += 1

            first_attack_idx = next((i for i, action in enumerate(actions)
                                     if action.get('type') == 'attack'), None)
            if first_attack_idx is not None:
                before = [action_token(a) for a in actions[:first_attack_idx]
                          if action_token(a)]
                first_attack = action_token(actions[first_attack_idx])
                key = ' > '.join(before + [first_attack]) if before else first_attack
                by_leader_attack[leader][key] += 1

            for action in actions:
                if action.get('type') != 'attack':
                    continue
                defender = leader_key(meta, opp)
                blocked_by = action.get('blocked_by')
                countered_by = action.get('countered_by') or []
                if blocked_by:
                    total_defenses += 1
                    by_defender[defender][f'blocker:{blocked_by}'] += 1
                for counter_card in countered_by:
                    total_defenses += 1
                    by_defender[defender][f'counter:{counter_card}'] += 1

            if len(context_examples[scope]) < 5:
                context_examples[scope].append({
                    'log': path.name,
                    'turn': turn.get('turn'),
                    'context': ctx,
                    'sequence': tokens,
                })

    candidates = []
    for leader, counter in by_leader_ngram2.items():
        for pattern, count in counter.items():
            if count >= min_support:
                candidates.append({
                    'type': 'sequence_2',
                    'leader': leader,
                    'pattern': pattern,
                    'count': count,
                })
    for leader, counter in by_leader_ngram3.items():
        for pattern, count in counter.items():
            if count >= min_support:
                candidates.append({
                    'type': 'sequence_3',
                    'leader': leader,
                    'pattern': pattern,
                    'count': count,
                })
    for leader, counter in by_leader_attack.items():
        for pattern, count in counter.items():
            if count >= min_support:
                candidates.append({
                    'type': 'before_attack',
                    'leader': leader,
                    'pattern': pattern,
                    'count': count,
                })
    candidates.sort(key=lambda row: (-row['count'], row['leader'], row['pattern']))

    return {
        'meta': {
            'logs': len(paths),
            'turns': total_turns,
            'actions': total_actions,
            'defense_events': total_defenses,
            'min_support': min_support,
            'note': 'Padroes observados em logs humanos; usar como sinal, nao como regra absoluta.',
        },
        'global_action_orders': counter_to_dict(global_action_orders, 30),
        'by_leader_band': nested_counter_to_dict(by_leader_band, 10),
        'by_leader_exact_orders': nested_counter_to_dict(by_leader_order, 10),
        'by_leader_ngrams_2': nested_counter_to_dict(by_leader_ngram2, 12),
        'by_leader_ngrams_3': nested_counter_to_dict(by_leader_ngram3, 12),
        'by_leader_before_attack': nested_counter_to_dict(by_leader_attack, 12),
        'by_defender_response': nested_counter_to_dict(by_defender, 12),
        'context_examples': dict(sorted(context_examples.items())),
        'heuristic_candidates': candidates[:80],
        'card_names': {code: card_name(cards_db, code)
                       for code in sorted({token.split(':', 1)[1].split(' > ')[0]
                                           for row in candidates
                                           for token in row['pattern'].split(' > ')
                                           if ':' in token})},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--logs-dir', default='logs/parsed',
                        help='Pasta com logs parseados, relativa a scriptis_da_ia ou absoluta')
    parser.add_argument('--output', default='human_patterns.json',
                        help='Arquivo JSON de saida, relativo a scriptis_da_ia ou absoluto')
    parser.add_argument('--min-support', type=int, default=2,
                        help='Contagem minima para virar candidato de heuristica')
    parser.add_argument('--top', type=int, default=12,
                        help='Quantidade de candidatos impressos no terminal')
    args = parser.parse_args()

    base = Path(__file__).resolve().parent
    logs_dir = Path(args.logs_dir)
    if not logs_dir.is_absolute():
        logs_dir = base / logs_dir
    output = Path(args.output)
    if not output.is_absolute():
        output = base / output

    paths = sorted(logs_dir.glob('*.json'))
    if not paths:
        raise SystemExit(f'Nenhum log parseado encontrado em {logs_dir}')

    cards_db = load_cards_db(base / 'cards_rows.csv')
    result = extract_patterns(paths, cards_db, min_support=args.min_support)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')

    print(f'Logs: {result["meta"]["logs"]} | turnos: {result["meta"]["turns"]} | acoes: {result["meta"]["actions"]}')
    print(f'Defesas/counters observados: {result["meta"]["defense_events"]}')
    print(f'Saida: {output}')
    print('\nTop padroes globais de ordem:')
    for row in result['global_action_orders'][:args.top]:
        print(f'  {row["count"]:>3}  {row["pattern"]}')
    print('\nCandidatos para heuristica:')
    for row in result['heuristic_candidates'][:args.top]:
        print(f'  {row["count"]:>3}  {row["leader"]}  {row["type"]}: {row["pattern"]}')


if __name__ == '__main__':
    main()
