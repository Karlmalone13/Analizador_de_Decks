"""
importar_logs_autosaved.py
==========================
Converte os .log do AutoSaved do simulador OPTCG para o formato
logs/parsed/*.json + atualiza logs/index.json.

Uso:
    python importar_logs_autosaved.py <pasta_autosaved> [--dry-run]

Exemplo:
    python importar_logs_autosaved.py "E:/Games/OnePieceSimulador/Builds_Windows/CombatLogs/AutoSaved"

Formato de saída (logs/parsed/<timestamp>.json):
{
  "meta": {
    "source": "autosaved_log",
    "original_file": "2026-07-02T00.33.08.log",
    "p1": {"name": "...", "leader_name": "...", "leader_code": "...", "goes_first": true/false},
    "p2": {"name": "...", "leader_name": "...", "leader_code": "...", "goes_first": true/false},
    "winner": "p1" | "p2" | null,
    "winner_name": "...",
    "total_turns": N,
    "mulligan_p1": {"before": [...codes], "after": [...codes], "took_mulligan": bool},
    "mulligan_p2": {"before": [...codes], "after": [...codes], "took_mulligan": bool}
  },
  "turns": [
    {
      "turn": 1,
      "player": "...",
      "player_role": "p1" | "p2",
      "card_drawn": {"name": "...", "code": "..."},
      "don_drawn": N,
      "actions": [
        {"type": "play",     "card": "CODE", "card_name": "...", "effects": [...]},
        {"type": "activate", "card": "CODE", "card_name": "...", "effects": [...]},
        {"type": "attack",   "attacker": "...", "attacker_code": "CODE",
                             "target": "...", "result": "hit"|"blocked"|"failed",
                             "damage": N|null, "countered_by": []},
        {"type": "attach_don", "amount": N, "to": "CODE", "to_name": "..."},
      ],
      "snapshot": {
        "p1": {"hand": [...codes], "board": [...codes], "trash": [...codes], "life": N},
        "p2": {"hand": [...codes], "board": [...codes], "trash": [...codes], "life": N}
      }
    }
  ]
}
"""
from __future__ import annotations
import re
import json
import os
import sys
import csv
import hashlib
from pathlib import Path
from datetime import datetime


# ── Cores dos líderes ─────────────────────────────────────────────────────────

_COLOR_ABBR: dict[str, str] = {
    'red': 'R',
    'blue': 'Bl',
    'green': 'G',
    'yellow': 'Y',
    'black': 'B',
    'purple': 'P',
}


def _load_card_db() -> dict[str, dict]:
    """Carrega cards_rows.csv e retorna {code: {color, name}}."""
    db: dict[str, dict] = {}
    csv_path = Path(__file__).parent / 'cards_rows.csv'
    if not csv_path.exists():
        return db
    with csv_path.open(encoding='utf-8') as f:
        for row in csv.DictReader(f):
            code = row.get('id', '').strip()
            if code:
                db[code] = {
                    'color': row.get('card_color', '').strip(),
                    'name':  row.get('card_name', '').strip(),
                }
    return db


def _color_abbr(color_str: str) -> str:
    """'Green Red' → 'GR', 'Black Yellow' → 'BY', etc."""
    if not color_str:
        return ''
    # Trata variantes com '/' (ex: 'Blue/Black') como espaço
    parts = color_str.replace('/', ' ').split()
    abbrs = [_COLOR_ABBR.get(p.lower(), p[0].upper()) for p in parts if p]
    abbrs.sort()
    return ''.join(abbrs)


def _leader_with_color(leader_name: str, leader_code: str, card_db: dict) -> str:
    """'Krieg', 'OP15-001' → 'Krieg GR'  (sem cor se não encontrado)."""
    abbr = _color_abbr(card_db.get(leader_code, {}).get('color', ''))
    return f'{leader_name} {abbr}' if abbr else leader_name


# ── Regex helpers ─────────────────────────────────────────────────────────────

_RE_PLAYER_LINE  = re.compile(r'^\[(.+?)\] (.+)$')
_RE_LINK_CODE    = re.compile(r'link="([A-Z0-9\-]+)"')
_RE_CODES_LIST   = re.compile(r'\[([A-Z0-9\-, ]+)\]')  # [CODE1,CODE2,...]
_RE_LEADER       = re.compile(r'^(.+) Has Connected$')
_RE_LEADER_IS    = re.compile(r'^Leader is (.+?) \[.*?link="([^"]+)"')
_RE_HAND_BEFORE  = re.compile(r'^Hand before Mulligan: \[([^\]]*)\]$')
_RE_HAND_AFTER   = re.compile(r'^Hand after Mulligan: \[([^\]]*)\]$')
_RE_HAND_SNAP    = re.compile(r'^Hand: \[([^\]]*)\]$')
_RE_BOARD_SNAP   = re.compile(r'^Board: \[([^\]]*)\]$')
_RE_TRASH_SNAP   = re.compile(r'^Trash: \[([^\]]*)\]$')
_RE_LIFE_SNAP    = re.compile(r'^Life: (\d+)$')
_RE_DREW         = re.compile(r'^Drew card from deck: (.+?) \[.*?link="([^"]+)"')
_RE_DRAW_DON     = re.compile(r'^Draw (\d+) Don$')
_RE_DRAW_CARD    = re.compile(r'^Draw (\d+) Card')
_RE_DEPLOY       = re.compile(r'^Deploy (.+?) \[.*?link="([^"]+)"')
_RE_EFFECT_LINE  = re.compile(r'^(.+?) \[.*?link="([^"]+)"\]: (.+)$')
_RE_ATTACK       = re.compile(r'^(.+?) \[.*?link="([^"]+)"\] attacking (.+?)( \[.*\])?$')
_RE_HIT          = re.compile(r'^(.+?) hit for (\d+) damage$')
_RE_ATTACH_DON   = re.compile(r'^Attach (\d+) Don to (.+?) \[.*?link="([^"]+)"\] \((\d+) Total\)$')
_RE_CHOSE_FIRST  = re.compile(r'^Chose to go (First|Second)$')
_RE_CONCEDES     = re.compile(r'^Concedes!$')
_RE_VERSION      = re.compile(r'^Version is ')
_RE_CONNECTED    = re.compile(r'^.+ Has Connected$')
_RE_WAITING      = re.compile(r'^Waiting for a Connection')
_RE_TURN_ATTACK_FAIL = re.compile(r'^Attack Fails$')
_RE_BLOCKED_BY   = re.compile(r'^Blocked by (.+?) \[.*?link="([^"]+)"')


def _codes_from_str(s: str) -> list[str]:
    """Extrai lista de códigos de carta de uma string '[CODE1,CODE2,...]'."""
    s = s.strip()
    if not s:
        return []
    return [c.strip() for c in s.split(',') if c.strip()]


def _first_link(line: str) -> str | None:
    m = _RE_LINK_CODE.search(line)
    return m.group(1) if m else None


def parse_log(path: Path) -> dict | None:
    """
    Lê um arquivo .log do AutoSaved e retorna o dict no formato logs/parsed/*.json.
    Retorna None se o arquivo não tiver dados suficientes para um registro válido.
    """
    try:
        raw = path.read_text(encoding='utf-8', errors='replace')
    except Exception as e:
        print(f'  ERRO lendo {path.name}: {e}')
        return None

    lines = raw.splitlines()

    # ── Fase 1: Setup (líderes, turn order, mulligans) ────────────────────────
    players: dict[str, dict] = {}   # name → {name, leader_name, leader_code, role}
    p_order: list[str] = []         # ordem de conexão (p1=primeiro a conectar)
    goes_first_name: str | None = None
    mulligan: dict[str, dict] = {}  # name → {before, after, took_mulligan}
    pending_hand_before: dict[str, list] = {}
    pending_hand_after: dict[str, list] = {}
    pending_mulligan_took: set[str] = set()

    # ── Fase 2: Turnos ────────────────────────────────────────────────────────
    turns: list[dict] = []
    cur_turn_player: str | None = None
    cur_turn_num = 0
    cur_player_turn_num: dict[str, int] = {}  # por jogador
    cur_actions: list[dict] = []
    cur_card_drawn: dict | None = None
    cur_don_drawn = 0
    pending_attack: dict | None = None
    in_game = False   # True após o setup acabar
    winner_name: str | None = None

    # Rastreamento de vida em tempo real (atualizado por snapshot E por hits)
    tracked_life: dict[str, int] = {}   # name → vida atual

    # Estado de snapshot (atualizado após cada End Turn)
    snap_state: dict[str, dict] = {}  # name → {hand, board, trash, life}

    def flush_turn():
        nonlocal cur_actions, cur_card_drawn, cur_don_drawn, pending_attack
        if cur_turn_player is None:
            return
        role = players.get(cur_turn_player, {}).get('role', 'p1')
        opp_role = 'p2' if role == 'p1' else 'p1'
        opp_name = next((n for n, d in players.items() if d.get('role') == opp_role), None)

        snap = {}
        for pname, pdata in snap_state.items():
            prole = players.get(pname, {}).get('role', 'p1')
            snap[prole] = {
                'hand':  list(pdata.get('hand', [])),
                'board': list(pdata.get('board', [])),
                'trash': list(pdata.get('trash', [])),
                'life':  pdata.get('life', -1),
            }

        turns.append({
            'turn':        cur_turn_num,
            'player':      cur_turn_player,
            'player_role': role,
            'card_drawn':  cur_card_drawn,
            'don_drawn':   cur_don_drawn,
            'actions':     list(cur_actions),
            'snapshot':    snap,
        })
        cur_actions = []
        cur_card_drawn = None
        cur_don_drawn = 0
        pending_attack = None

    for raw_line in lines:
        line = raw_line.strip()
        # Remove zero-width spaces comuns em nomes do simulador
        line = line.replace('​', '').replace('‌', '')

        # ── Linhas de setup ────────────────────────────────────────────────────
        if _RE_WAITING.match(line) or _RE_VERSION.match(line):
            continue

        if _RE_CONNECTED.match(line):
            name = line.replace(' Has Connected', '').strip()
            if name not in players:
                players[name] = {'name': name, 'leader_name': '', 'leader_code': '', 'role': ''}
                p_order.append(name)
            continue

        # Linha de jogador
        pm = _RE_PLAYER_LINE.match(line)
        if pm:
            pname = pm.group(1).strip()
            action = pm.group(2).strip()

            # Registra jogador se ainda não conhecido
            if pname not in players:
                players[pname] = {'name': pname, 'leader_name': '', 'leader_code': '', 'role': ''}
                p_order.append(pname)

            # Líder
            lm = _RE_LEADER_IS.match(action)
            if lm:
                players[pname]['leader_name'] = lm.group(1)
                players[pname]['leader_code'] = lm.group(2)
                continue

            # Turno escolhido
            cm = _RE_CHOSE_FIRST.match(action)
            if cm:
                choice = cm.group(1)
                goes_first_name = pname if choice == 'First' else next(
                    (n for n in p_order if n != pname), pname
                )
                continue

            # Mão antes do mulligan
            hbm = _RE_HAND_BEFORE.match(action)
            if hbm:
                pending_hand_before[pname] = _codes_from_str(hbm.group(1))
                continue

            # Mão depois do mulligan
            ham = _RE_HAND_AFTER.match(action)
            if ham:
                pending_hand_after[pname] = _codes_from_str(ham.group(1))
                continue

            # Tomou mulligan
            if action == 'Mulligan':
                pending_mulligan_took.add(pname)
                continue

            # ── Fim de turno ─────────────────────────────────────────────────
            if action == 'End Turn':
                in_game = True
                # Não faz flush ainda — esperamos o snapshot que vem logo depois
                continue

            # Snapshot de mão
            hsm = _RE_HAND_SNAP.match(action)
            if hsm:
                if pname not in snap_state:
                    snap_state[pname] = {'hand': [], 'board': [], 'trash': [], 'life': -1}
                snap_state[pname]['hand'] = _codes_from_str(hsm.group(1))
                continue

            # Snapshot de board
            bsm = _RE_BOARD_SNAP.match(action)
            if bsm:
                if pname not in snap_state:
                    snap_state[pname] = {'hand': [], 'board': [], 'trash': [], 'life': -1}
                snap_state[pname]['board'] = _codes_from_str(bsm.group(1))
                continue

            # Snapshot de trash
            tsm = _RE_TRASH_SNAP.match(action)
            if tsm:
                if pname not in snap_state:
                    snap_state[pname] = {'hand': [], 'board': [], 'trash': [], 'life': -1}
                snap_state[pname]['trash'] = _codes_from_str(tsm.group(1))
                continue

            # Snapshot de vida
            lsm = _RE_LIFE_SNAP.match(action)
            if lsm:
                life_val = int(lsm.group(1))
                if pname not in snap_state:
                    snap_state[pname] = {'hand': [], 'board': [], 'trash': [], 'life': -1}
                snap_state[pname]['life'] = life_val
                tracked_life[pname] = life_val  # sincroniza rastreamento real-time
                # Se chegamos ao snapshot do 2º jogador (ambos registrados),
                # é hora de fazer o flush do turno que acabou
                if len(snap_state) == 2 and cur_turn_player is not None:
                    flush_turn()
                continue

            # ── Ações de jogo ─────────────────────────────────────────────────
            # Carta comprada
            dm = _RE_DREW.match(action)
            if dm:
                cur_card_drawn = {'name': dm.group(1), 'code': dm.group(2)}
                continue

            # Compra de DON
            ddonm = _RE_DRAW_DON.match(action)
            if ddonm:
                cur_don_drawn += int(ddonm.group(1))
                continue

            # Início de turno: se o jogador mudou, iniciamos novo turno
            if pname != cur_turn_player:
                cur_turn_player = pname
                cur_player_turn_num[pname] = cur_player_turn_num.get(pname, 0) + 1
                cur_turn_num += 1
                # cur_actions etc. já foram resetados pelo flush_turn() anterior

            # Deploy / Play
            depm = _RE_DEPLOY.match(action)
            if depm:
                cur_actions.append({
                    'type': 'play',
                    'card': depm.group(2),
                    'card_name': depm.group(1),
                    'effects': [],
                })
                continue

            # Attach DON
            adonm = _RE_ATTACH_DON.match(action)
            if adonm:
                cur_actions.append({
                    'type': 'attach_don',
                    'amount': int(adonm.group(1)),
                    'to': adonm.group(3),
                    'to_name': adonm.group(2),
                    'total': int(adonm.group(4)),
                })
                continue

            # Attack
            atm = _RE_ATTACK.match(action)
            if atm:
                pending_attack = {
                    'type': 'attack',
                    'attacker': atm.group(1),
                    'attacker_code': atm.group(2),
                    'target': atm.group(3).strip(),
                    'result': 'unknown',
                    'damage': None,
                    'countered_by': [],
                }
                cur_actions.append(pending_attack)
                continue

            # Concede → registra vencedor
            if _RE_CONCEDES.match(action):
                winner_name = next((n for n in players if n != pname), None)
                continue

            # Efeito de carta ativada
            efm = _RE_EFFECT_LINE.match(action)
            if efm:
                card_name = efm.group(1)
                card_code = efm.group(2)
                effect    = efm.group(3)
                # Se tem uma ação de play aberta para essa carta, adiciona efeito
                matched = False
                for a in reversed(cur_actions):
                    if a.get('card') == card_code:
                        a.setdefault('effects', []).append(effect)
                        matched = True
                        break
                if not matched:
                    cur_actions.append({
                        'type': 'activate',
                        'card': card_code,
                        'card_name': card_name,
                        'effects': [effect],
                    })
                continue

        else:
            # Linhas sem prefixo de jogador
            if not line or line.startswith('RZ1|'):
                continue

            # Resultado de combate: "X [code] hit for N damage"
            # "X" aqui é SEMPRE um líder (personagens que perdem batalha são KO, não "hit")
            hitm = _RE_HIT.match(line)
            if hitm:
                victim_name_raw = hitm.group(1).strip()
                damage = int(hitm.group(2))
                if pending_attack:
                    pending_attack['result'] = 'hit'
                    pending_attack['damage'] = damage

                # Identificar a quem pertence o líder que levou o hit
                # Tenta pelo nome do alvo no pending_attack ou pelo texto da linha
                victim_player = None
                for pn, pd in players.items():
                    leader_name = pd.get('leader_name', '')
                    leader_code = pd.get('leader_code', '')
                    # Verifica se o nome da linha bate com o nome do líder
                    if leader_name and leader_name in victim_name_raw:
                        victim_player = pn
                        break
                    # Fallback: tenta pelo target do pending_attack
                    if pending_attack and leader_name and leader_name in pending_attack.get('target', ''):
                        victim_player = pn
                        break

                if victim_player and not winner_name:
                    current = tracked_life.get(victim_player, 5)
                    if current <= 0:
                        # Já tinha 0 vida → hit fatal = esse jogador perde
                        winner_name = next((n for n in players if n != victim_player), None)
                    else:
                        tracked_life[victim_player] = current - damage
                continue

            # "Attack Fails"
            if _RE_TURN_ATTACK_FAIL.match(line):
                if pending_attack:
                    pending_attack['result'] = 'failed'
                continue

            # "X[power] vs Y[power]" — linha de combate, skip
            if ' vs ' in line and '[' in line:
                continue

    # Flush do último turno se não foi feito
    if cur_turn_player is not None and cur_actions:
        flush_turn()

    # ── Determinar roles (p1 = goes_first) ───────────────────────────────────
    if len(p_order) < 2:
        return None  # log incompleto

    if goes_first_name and goes_first_name in players:
        players[goes_first_name]['role'] = 'p1'
        for n in players:
            if n != goes_first_name:
                players[n]['role'] = 'p2'
    else:
        # Fallback: primeiro a conectar = p1
        for i, n in enumerate(p_order[:2]):
            players[n]['role'] = f'p{i+1}'

    p1_name = next((n for n, d in players.items() if d.get('role') == 'p1'), p_order[0])
    p2_name = next((n for n, d in players.items() if d.get('role') == 'p2'), p_order[-1])

    # ── Vencedor (fallback: vida=0 no último snapshot) ────────────────────────
    if not winner_name and turns:
        last_snap = turns[-1].get('snapshot', {})
        for role in ('p1', 'p2'):
            if last_snap.get(role, {}).get('life', 99) == 0:
                loser_role = role
                winner_name = p1_name if loser_role == 'p2' else p2_name
                break

    winner_role = None
    winner_leader = None
    if winner_name:
        winner_role = players.get(winner_name, {}).get('role')
        winner_leader = players.get(winner_name, {}).get('leader_name')

    # ── Mulligans ─────────────────────────────────────────────────────────────
    def build_mulligan(name: str) -> dict:
        before = pending_hand_before.get(name, [])
        after  = pending_hand_after.get(name, [])
        took   = name in pending_mulligan_took
        return {'before': before, 'after': after if after else before, 'took_mulligan': took}

    result = {
        'meta': {
            'source':        'autosaved_log',
            'original_file': path.name,
            'p1': {
                'name':        p1_name,
                'leader_name': players.get(p1_name, {}).get('leader_name', ''),
                'leader_code': players.get(p1_name, {}).get('leader_code', ''),
                'goes_first':  True,
            },
            'p2': {
                'name':        p2_name,
                'leader_name': players.get(p2_name, {}).get('leader_name', ''),
                'leader_code': players.get(p2_name, {}).get('leader_code', ''),
                'goes_first':  False,
            },
            'winner':        winner_role,
            'winner_name':   winner_name,
            'winner_leader': winner_leader,
            'total_turns': len(turns),
            'mulligan_p1': build_mulligan(p1_name),
            'mulligan_p2': build_mulligan(p2_name),
        },
        'turns': turns,
    }

    return result


def importar(autosaved_dir: str, dry_run: bool = False) -> None:
    base_dir  = Path(__file__).parent
    logs_dir  = base_dir / 'logs'
    parsed_dir = logs_dir / 'parsed'
    index_path = logs_dir / 'index.json'

    if not dry_run:
        parsed_dir.mkdir(parents=True, exist_ok=True)

    card_db = _load_card_db()

    # Carrega index existente
    existing: list[dict] = []
    if index_path.exists():
        try:
            existing = json.loads(index_path.read_text(encoding='utf-8'))
        except Exception:
            existing = []

    existing_files = {e.get('original_file', '') for e in existing}

    autosaved = Path(autosaved_dir)
    log_files = sorted(autosaved.glob('*.log'))
    print(f'Encontrados {len(log_files)} arquivos .log em {autosaved}')

    novos = 0
    skipped = 0
    erros = 0

    for lf in log_files:
        if lf.name in existing_files:
            print(f'  SKIP (já importado): {lf.name}')
            skipped += 1
            continue

        print(f'  Processando: {lf.name}')
        result = parse_log(lf)

        if result is None:
            print(f'    -> IGNORADO (dados insuficientes)')
            erros += 1
            continue

        meta = result['meta']
        p1 = meta['p1']
        p2 = meta['p2']

        # Enriquece leader_name com cor (ex: "Krieg" → "Krieg GR")
        for player in (p1, p2):
            player['leader_name'] = _leader_with_color(
                player['leader_name'], player['leader_code'], card_db
            )
        if meta.get('winner'):
            winner_p = p1 if meta['winner'] == 'p1' else p2
            meta['winner_leader'] = winner_p['leader_name']

        if not p1['leader_code'] or not p2['leader_code']:
            print(f'    -> IGNORADO (líderes não identificados)')
            erros += 1
            continue

        print(f'    {p1["name"]} ({p1["leader_name"]}) vs {p2["name"]} ({p2["leader_name"]})')
        wl = meta.get('winner_leader') or meta.get('winner_name') or '?'
        print(f'    Turnos: {meta["total_turns"]} | Vencedor: {wl}')
        print(f'    Mulligan P1: {meta["mulligan_p1"]["took_mulligan"]} | P2: {meta["mulligan_p2"]["took_mulligan"]}')

        # Nome do arquivo parsed: mesmo timestamp do .log
        ts = lf.stem  # ex: "2026-07-02T00.33.08"
        parsed_name = f'{ts}_autosaved.json'

        if not dry_run:
            out_path = parsed_dir / parsed_name
            out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')

            # Adiciona ao index
            existing.append({
                'original_file': lf.name,
                'parsed_file':   f'parsed/{parsed_name}',
                'source':        'autosaved_log',
                'p1': {
                    'name':        p1['name'],
                    'leader_name': p1['leader_name'],
                    'leader_code': p1['leader_code'],
                },
                'p2': {
                    'name':        p2['name'],
                    'leader_name': p2['leader_name'],
                    'leader_code': p2['leader_code'],
                },
                'winner':      meta.get('winner'),
                'winner_name':   meta.get('winner_name'),
                'winner_leader': meta.get('winner_leader'),
                'total_turns': meta['total_turns'],
            })

        novos += 1

    if not dry_run and novos > 0:
        index_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'\nIndex atualizado: {index_path}')

    print(f'\nResumo: {novos} importados | {skipped} já existiam | {erros} ignorados')


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='Importa logs AutoSaved do simulador OPTCG')
    ap.add_argument('autosaved_dir', help='Caminho para a pasta AutoSaved')
    ap.add_argument('--dry-run', action='store_true', help='Mostra o que seria importado sem salvar')
    args = ap.parse_args()
    importar(args.autosaved_dir, dry_run=args.dry_run)
