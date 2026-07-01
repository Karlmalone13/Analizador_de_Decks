#!/usr/bin/env python3
"""
parse_combat_log.py — Converte um combat log do simulador oficial OPTCG
em JSON estruturado com decisões turno a turno.

Uso:
    python parse_combat_log.py partida.log
    python parse_combat_log.py partida.log --output partida.json
    python parse_combat_log.py partida.log --summary   (imprime resumo no terminal)
"""

import re
import json
import argparse
from pathlib import Path

# ─── Regex patterns ──────────────────────────────────────────────────────────

RE_LEADER   = re.compile(r'^\[(.+?)\] Leader is (.+?) \["([A-Z0-9]+-\d+)">')
RE_DRAW_DON = re.compile(r'^\[(.+?)\] Draw (\d+) Don')
RE_DREW     = re.compile(r'^\[(.+?)\] Drew card from deck: (.+?) \["([A-Z0-9]+-\d+)">')
RE_DEPLOY   = re.compile(r'^\[(.+?)\] Deploy (.+?) \["([A-Z0-9]+-\d+)">')
RE_ATTACH   = re.compile(r'^\[(.+?)\] Attach (\d+) Don to (.+?) \["([A-Z0-9]+-\d+)"\] \((\d+) Total\)')
RE_ATTACK   = re.compile(r'^\[(.+?)\] (.+?) \["[A-Z0-9]+-\d+"\] attacking (.+)')
RE_BLOCKS   = re.compile(r'^\[(.+?)\] (.+?) \["([A-Z0-9]+-\d+)"\] Blocks')
RE_DESTROY  = re.compile(r'^\[(.+?)\] (.+?) \["([A-Z0-9]+-\d+)"\] Destroyed')
RE_HIT      = re.compile(r'^(.+?) hit for (\d+) damage')
RE_FAILS    = re.compile(r'^Attack Fails')
RE_DISCARD  = re.compile(r'^\[(.+?)\] Discard (.+?) \["([A-Z0-9]+-\d+)"\] for Counter')
RE_EFFECT   = re.compile(r'^\[(.+?)\] (.+?) \["([A-Z0-9]+-\d+)"\]: (.+)')
RE_END      = re.compile(r'^\[(.+?)\] End Turn')
RE_HAND     = re.compile(r'^\[(.+?)\] Hand: \[(.*?)\]')
RE_BOARD    = re.compile(r'^\[(.+?)\] Board: \[(.*?)\]')
RE_TRASH    = re.compile(r'^\[(.+?)\] Trash: \[(.*?)\]')
RE_LIFE     = re.compile(r'^\[(.+?)\] Life: (\d+)')
RE_MULLIGAN = re.compile(r'^\[(.+?)\] Mulligan')
RE_CHOSE    = re.compile(r'^\[(.+?)\] Chose to go (First|Second)')


def _codes(s: str) -> list[str]:
    return [c.strip() for c in s.split(',') if c.strip()] if s.strip() else []


def _clean(line: str) -> str:
    """Remove zero-width spaces and strip."""
    return line.replace('​', '').strip()


# ─── Parser principal ─────────────────────────────────────────────────────────

def parse_log(log_path: str) -> dict:
    raw = Path(log_path).read_text(encoding='utf-8', errors='replace').splitlines()
    lines = [_clean(l) for l in raw]

    # ── 1. Cabeçalho: jogadores, líderes, ordem ───────────────────────────────
    players: list[str] = []
    leaders: dict = {}
    goes_first: str | None = None
    goes_second: str | None = None

    for line in lines:
        m = RE_LEADER.match(line)
        if m:
            p, lname, lcode = m.group(1), m.group(2), m.group(3)
            if p not in leaders:
                players.append(p)
                leaders[p] = {'name': lname, 'code': lcode}
        m = RE_CHOSE.match(line)
        if m:
            if m.group(2) == 'First':
                goes_first = m.group(1)
            else:
                goes_second = m.group(1)

    if len(players) < 2:
        raise ValueError('Não encontrei 2 jogadores no log.')

    p1, p2 = players[0], players[1]
    # quem escolheu ir primeiro/segundo
    if goes_first:
        turn_order = [goes_first, p1 if goes_first == p2 else p2]
    else:
        turn_order = players[:]

    # ── 2. Separar blocos de turno ────────────────────────────────────────────
    # Um turno começa quando um jogador roba DON e termina no End Turn + snapshot.
    # Turnos iniciais (sem roubar DON): turno 0 do jogador que vai segundo.

    turn_blocks: list[dict] = []
    current_player: str | None = None
    current_lines: list[str] = []
    game_started = False
    last_player_idx = -1   # para alternância quando Draw Don não aparece no log

    i = 0
    while i < len(lines):
        line = lines[i]

        if not game_started:
            m = RE_DRAW_DON.match(line)
            if m:
                game_started = True
                current_player = m.group(1)
                if current_player in players:
                    last_player_idx = players.index(current_player)
                current_lines = [line]
            else:
                m2 = RE_END.match(line)
                if m2 and not game_started:
                    p0 = m2.group(1)
                    turn_blocks.append({
                        'player': p0,
                        'lines': current_lines + [line],
                        'snap_lines': _collect_snap(lines, i + 1),
                    })
                    if p0 in players:
                        last_player_idx = players.index(p0)
                    i = _skip_snap(lines, i + 1)
                    current_lines = []
                    continue
            i += 1
            continue

        m_end = RE_END.match(line)
        if m_end:
            current_lines.append(line)
            snap_lines = _collect_snap(lines, i + 1)
            turn_blocks.append({
                'player': current_player,
                'lines': current_lines,
                'snap_lines': snap_lines,
            })
            if current_player in players:
                last_player_idx = players.index(current_player)
            i = _skip_snap(lines, i + 1)
            current_player = None
            current_lines = []
            continue

        # Detecta jogador atual por Draw Don, Draw Card ou alternância
        if current_player is None:
            detected = None
            m_don = RE_DRAW_DON.match(line)
            m_draw = re.match(r'^\[(.+?)\] Draw \d+ Card', line)
            m_drew = RE_DREW.match(line)
            if m_don:
                detected = m_don.group(1)
            elif m_draw:
                detected = m_draw.group(1)
            elif m_drew:
                detected = m_drew.group(1)

            if detected and detected in players:
                current_player = detected
            elif last_player_idx >= 0 and len(players) == 2:
                # Inferir por alternância se não encontrou pelo log
                current_player = players[1 - last_player_idx]

        current_lines.append(line)
        i += 1

    # ── 3. Parsear cada bloco ─────────────────────────────────────────────────
    parsed_turns = []

    for t_idx, block in enumerate(turn_blocks):
        player = block['player']
        blines = block['lines']

        actions: list[dict] = []
        don_drawn = 0
        card_drawn = None
        current_attack: dict | None = None

        for line in blines:
            if line.startswith('RZ1') or not line:
                continue

            # DON do turno
            m = RE_DRAW_DON.match(line)
            if m and m.group(1) == player:
                don_drawn = int(m.group(2))
                continue

            # Carta comprada no início do turno
            m = RE_DREW.match(line)
            if m and m.group(1) == player:
                card_drawn = {'name': m.group(2), 'code': m.group(3)}
                continue

            # Jogar carta
            m = RE_DEPLOY.match(line)
            if m and m.group(1) == player:
                current_attack = None
                actions.append({
                    'type': 'play',
                    'card': m.group(3),
                    'card_name': m.group(2),
                    'effects': []
                })
                continue

            # Anexar DON
            m = RE_ATTACH.match(line)
            if m and m.group(1) == player:
                current_attack = None
                actions.append({
                    'type': 'attach_don',
                    'amount': int(m.group(2)),
                    'to': m.group(4),
                    'to_name': m.group(3),
                    'total': int(m.group(5))
                })
                continue

            # Declarar ataque
            m = RE_ATTACK.match(line)
            if m and m.group(1) == player:
                current_attack = {
                    'type': 'attack',
                    'attacker': m.group(2),
                    'target': m.group(3),
                    'result': None,
                    'damage': None,
                    'blocked_by': None,
                    'countered_by': []
                }
                actions.append(current_attack)
                continue

            # Bloqueio (pelo oponente — anota no ataque atual)
            m = RE_BLOCKS.match(line)
            if m and m.group(1) != player and current_attack:
                current_attack['blocked_by'] = m.group(3)
                continue

            # Counter (oponente descarta para counter)
            m = RE_DISCARD.match(line)
            if m and m.group(1) != player and current_attack:
                current_attack['countered_by'].append(m.group(3))
                continue

            # Resultado do ataque
            m = RE_HIT.match(line)
            if m and current_attack:
                current_attack['result'] = 'hit'
                current_attack['damage'] = int(m.group(2))
                current_attack = None
                continue

            if RE_FAILS.match(line) and current_attack:
                current_attack['result'] = 'blocked'
                current_attack = None
                continue

            # Efeitos de cartas
            m = RE_EFFECT.match(line)
            if m and m.group(1) == player:
                src_name = m.group(2)
                src_code = m.group(3)
                effect_desc = m.group(4)
                # Pertence ao último play desta carta?
                last_play = next(
                    (a for a in reversed(actions)
                     if a['type'] == 'play' and a['card'] == src_code),
                    None
                )
                last_activate = next(
                    (a for a in reversed(actions)
                     if a['type'] == 'activate' and a.get('card') == src_code),
                    None
                )
                if last_play and not last_activate:
                    last_play['effects'].append(effect_desc)
                elif last_activate:
                    last_activate.setdefault('effects', []).append(effect_desc)
                else:
                    actions.append({
                        'type': 'activate',
                        'card': src_code,
                        'card_name': src_name,
                        'effects': [effect_desc]
                    })
                continue

        # Snapshot do fim do turno — pode aparecer dentro do bloco (antes do
        # End Turn) ou logo após. Coleta de ambos e mescla (último vence).
        all_snap_lines = (
            [l for l in blines if RE_HAND.match(l) or RE_BOARD.match(l)
             or RE_TRASH.match(l) or RE_LIFE.match(l)]
            + block['snap_lines']
        )
        snap = _parse_snap(all_snap_lines)

        parsed_turns.append({
            'turn': t_idx + 1,
            'player': player,
            'card_drawn': card_drawn,
            'don_drawn': don_drawn,
            'actions': [a for a in actions if a['type'] != 'attach_don' or a['amount'] > 0],
            'snapshot': snap,
        })

    opp = {p1: p2, p2: p1}

    return {
        'meta': {
            'players': {
                'p1': {'name': p1, 'leader': leaders.get(p1, {})},
                'p2': {'name': p2, 'leader': leaders.get(p2, {})},
            },
            'goes_first': goes_first,
        },
        'total_turns': len(parsed_turns),
        'turns': parsed_turns,
    }


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _collect_snap(lines: list[str], start: int) -> list[str]:
    result = []
    j = start
    while j < len(lines) and j < start + 30:
        l = _clean(lines[j])
        if RE_HAND.match(l) or RE_BOARD.match(l) or RE_TRASH.match(l) or RE_LIFE.match(l):
            result.append(l)
            j += 1
        elif l.startswith('RZ1') or not l:
            j += 1
        else:
            break
    return result


def _skip_snap(lines: list[str], start: int) -> int:
    j = start
    while j < len(lines) and j < start + 30:
        l = _clean(lines[j])
        if RE_HAND.match(l) or RE_BOARD.match(l) or RE_TRASH.match(l) or RE_LIFE.match(l):
            j += 1
        elif l.startswith('RZ1') or not l:
            j += 1
        else:
            break
    return j


def _parse_snap(snap_lines: list[str]) -> dict:
    snap: dict = {}
    for line in snap_lines:
        m = RE_HAND.match(line)
        if m:
            snap.setdefault(m.group(1), {})['hand'] = _codes(m.group(2))
            continue
        m = RE_BOARD.match(line)
        if m:
            snap.setdefault(m.group(1), {})['board'] = _codes(m.group(2))
            continue
        m = RE_TRASH.match(line)
        if m:
            snap.setdefault(m.group(1), {})['trash'] = _codes(m.group(2))
            continue
        m = RE_LIFE.match(line)
        if m:
            snap.setdefault(m.group(1), {})['life'] = int(m.group(2))
    return snap


# ─── Summary printer ─────────────────────────────────────────────────────────

def print_summary(data: dict):
    meta = data['meta']
    p1 = meta['players']['p1']
    p2 = meta['players']['p2']
    print(f"\n{'='*60}")
    print(f"  {p1['name']} ({p1['leader']['name']}) vs {p2['name']} ({p2['leader']['name']})")
    print(f"  Primeiro: {meta.get('goes_first', '?')} | {data['total_turns']} turnos")
    print(f"{'='*60}")

    for t in data['turns']:
        if not t.get('player'):
            continue
        snap = t['snapshot']
        p = t['player']
        others = [k for k in snap if k != p]
        opp = others[0] if others else None

        life_p = snap.get(p, {}).get('life', '?')
        life_o = snap.get(opp, {}).get('life', '?') if opp else '?'
        board_p = snap.get(p, {}).get('board', [])
        drawn = t['card_drawn']['code'] if t['card_drawn'] else '-'
        don = t['don_drawn']

        play_acts = [a for a in t['actions'] if a['type'] == 'play']
        atk_acts  = [a for a in t['actions'] if a['type'] == 'attack']
        act_acts  = [a for a in t['actions'] if a['type'] == 'activate']

        hits   = sum(1 for a in atk_acts if a['result'] == 'hit')
        blocks = sum(1 for a in atk_acts if a['result'] == 'blocked')

        print(f"\n  T{t['turn']:02d} {p[:18]:18s} | +{don}DON drew={drawn}")
        print(f"       vida: eu={life_p}  opp={life_o}  board={len(board_p)} chars")
        for a in play_acts:
            fx = '  -> ' + ' | '.join(a['effects'][:2]) if a['effects'] else ''
            print(f"       > play  {a['card']:12s} {a['card_name'][:22]}{fx}")
        for a in act_acts:
            fx = '  -> ' + ' | '.join(a.get('effects', [])[:2])
            print(f"       * activ {a['card']:12s} {a['card_name'][:22]}{fx}")
        for a in atk_acts:
            res = f"HIT({a['damage']})" if a['result'] == 'hit' else 'BLOCKED'
            blk = f"  [bloq: {a['blocked_by'][:10]}]" if a['blocked_by'] else ''
            ctr = f"  [ctr: {','.join(a['countered_by'][:2])}]" if a['countered_by'] else ''
            print(f"       ! atk   {a['attacker'][:18]} -> {res}{blk}{ctr}")


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description='Parse OPTCG combat log → JSON')
    ap.add_argument('log_file')
    ap.add_argument('--output', '-o', help='Arquivo de saída .json')
    ap.add_argument('--summary', '-s', action='store_true', help='Imprimir resumo no terminal')
    args = ap.parse_args()

    out = args.output or str(Path(args.log_file).with_suffix('.json'))

    print(f'Parseando {args.log_file} ...')
    data = parse_log(args.log_file)

    with open(out, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f'OK {data["total_turns"]} turnos -> {out}')

    if args.summary:
        print_summary(data)


if __name__ == '__main__':
    main()
