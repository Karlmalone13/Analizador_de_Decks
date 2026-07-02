"""
bot_optcgsim.py — Bot para jogar partidas automáticas no OPTCGSim
=================================================================
O bot joga como P2 (jogador de baixo). Decisões são tomadas pelo
engine de decisão real (decision_engine.py) via sim_bridge.py.

Fluxo por turno:
  1. Detecta fase via pixels (botões no canto inferior direito)
  2. Scan completo UMA VEZ no início da Main Phase (hover+OCR)
  3. Após cada ação: OCR do painel de log (esquerda) → aplica delta
     ao GameState sem rescanear o tabuleiro inteiro
  4. engine.choose_action() decide a melhor ação
  5. Executa a ação no simulador (clique/drag)

Uso:
    python bot_optcgsim.py [--deck NOME] [--partidas N] [--delay-inicio N]

Coordenadas: resolução 1366×768, janela maximizada.
"""
from __future__ import annotations
import time, sys, re, json, argparse, subprocess
from pathlib import Path
from typing import Optional
from PIL import ImageOps

try:
    import pyautogui as pag
    from PIL import ImageGrab, Image, ImageEnhance, ImageFilter
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
except ImportError:
    print("Instale: pip install pyautogui pillow pytesseract")
    sys.exit(1)

pag.PAUSE = 0.05

# ── Path do engine ─────────────────────────────────────────────────────────────
_SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(_SCRIPTS_DIR))

_bridge = None
def _get_bridge():
    global _bridge
    if _bridge is None:
        try:
            from optcg_engine import sim_bridge
            _bridge = sim_bridge
        except Exception as e:
            print(f"[AVISO] sim_bridge não disponível: {e}")
    return _bridge

# ── Banco de cartas (nome → código) ───────────────────────────────────────────
_DB_PATH = _SCRIPTS_DIR / "card_analysis_db.json"
_CARD_DB: dict[str, list[dict]] = {}

def _load_card_db() -> None:
    if not _DB_PATH.exists():
        return
    try:
        raw = json.loads(_DB_PATH.read_text(encoding="utf-8"))
        for code, info in raw.items():
            name = info.get("name", "").strip().lower()
            if name:
                _CARD_DB.setdefault(name, []).append({**info, "code": code})
    except Exception:
        pass

_load_card_db()

def _lookup_by_name(name: str, cost: int | None = None) -> dict | None:
    key = name.strip().lower()
    candidates = _CARD_DB.get(key)
    if not candidates:
        for k, v in _CARD_DB.items():
            if key in k or k in key:
                candidates = v
                break
    if not candidates:
        return None
    if len(candidates) == 1 or cost is None:
        return candidates[0]
    for c in candidates:
        if c.get("cost") == cost:
            return c
    return candidates[0]

# ── Coordenadas fixas (1366×768) ───────────────────────────────────────────────
C_SOLO_V_SELF  = (684, 438)
C_DECK_P1_DD   = (297, 178)   # dropdown P1 na tela de seleção
C_DECK_P2_DD   = (297, 275)   # dropdown P2 na tela de seleção
C_START        = (297, 407)   # botão Start na tela de seleção
C_BTN_TOP      = (1101, 578)
C_BTN_MAIN     = (1101, 643)
C_BACK_MAIN    = (1165, 82)
C_DOWNLOAD_LOG = (1165, 172)
C_P2_LEADER    = (700, 527)
C_P1_LEADER    = (632, 223)
C_P1_CHAR_AREA = (680, 310)

# Mão P2
HAND_Y       = 648
HAND_X_START = 107
HAND_X_END   = 410
HAND_STEP    = 35
HOVER_WAIT   = 0.30   # reduzido de 0.65 → 0.30s

# Preview de carta (lado direito)
PREVIEW_NAME_BBOX  = (945, 415, 1185, 445)
PREVIEW_COST_BBOX  = (930,  58,  975,  98)
PREVIEW_POWER_BBOX = (1130,  58, 1230,  95)

# DON e outros counters
DON_P2_HOVER = (495, 634)
DON_P1_HOVER = (865, 100)
OPP_HAND_HOVER = (250, 90)

def _badge_bbox(hover_x: int, hover_y: int) -> tuple:
    x, y = hover_x, hover_y - 45
    return (x - 25, y - 20, x + 25, y + 20)

# ── Painel de log (esquerda) ───────────────────────────────────────────────────
LOG_BBOX = (135, 210, 390, 475)

# Regex para parsear linhas do log
_RE_CODE    = re.compile(r'\[([A-Z]{1,4}\d{2}-\d{3}[a-z]?)\]')
_RE_DRAW_N  = re.compile(r'Draw (\d+) Card')
_RE_REST_N  = re.compile(r'Rest (\d+) Don')
_RE_SEND_LIFE = re.compile(r'Send (\d+) Life to Hand')
_RE_HIT     = re.compile(r'hit for (\d+) damage')

# Estado acumulado do log (reset a cada partida)
_log_lines_seen: list[str] = []

def _reset_log():
    global _log_lines_seen
    _log_lines_seen = []

def _read_log_lines() -> list[str]:
    """OCR do painel de log. Retorna lista de linhas visíveis."""
    img = ImageGrab.grab(bbox=LOG_BBOX)
    img = img.convert('L')
    img = ImageOps.invert(img)   # texto claro em fundo escuro → inverte
    img = img.resize((img.width * 3, img.height * 3), Image.LANCZOS)
    img = ImageEnhance.Contrast(img).enhance(2.0)
    raw = pytesseract.image_to_string(img, config='--psm 6').strip()
    return [l.strip() for l in raw.splitlines() if l.strip()]

def read_log_delta() -> list[str]:
    """
    Lê o painel de log e retorna apenas as linhas novas
    desde a última chamada.
    """
    global _log_lines_seen
    current = _read_log_lines()
    if not current:
        return []
    if not _log_lines_seen:
        _log_lines_seen = current
        return current

    # Procura a última linha conhecida dentro do current para encontrar o delta
    last = _log_lines_seen[-1]
    try:
        idx = len(current) - 1 - list(reversed(current)).index(last)
        new_lines = current[idx + 1:]
    except ValueError:
        # OCR leu diferente — tudo é novo
        new_lines = current

    _log_lines_seen = current
    return new_lines

def apply_log_delta(gs, opp_gs, lines: list[str]) -> bool:
    """
    Aplica novas linhas do log ao GameState do bot e do oponente.

    Retorna True se a mão do bot mudou (carta sacada/recebida)
    e portanto precisa de rescan parcial da mão.
    """
    needs_hand_rescan = False

    try:
        from optcg_engine.decision_engine import _make_card, load_cards_db
        cards_db = getattr(_get_bridge(), '_cards_db', {})
    except Exception:
        cards_db = {}

    def _get_card(code: str):
        data = cards_db.get(code)
        if not data:
            return None
        try:
            return _make_card(code, data)
        except Exception:
            return None

    for line in lines:
        codes = _RE_CODE.findall(line)
        is_you = '[You]' in line or line.startswith('You')
        is_opp = '[Opponent]' in line or line.startswith('Opponent')

        # ── Deploy ────────────────────────────────────────────────────────────
        if 'Deploy' in line and codes:
            code = codes[-1]
            if is_you:
                # Remove da mão
                gs.hand = [c for c in gs.hand if c.code != code]
                # Adiciona ao campo se ainda não estiver
                if not any(c.code == code for c in gs.field_chars):
                    card = _get_card(code)
                    if card:
                        gs.field_chars.append(card)
            elif is_opp:
                if not any(c.code == code for c in opp_gs.field_chars):
                    card = _get_card(code)
                    if card:
                        opp_gs.field_chars.append(card)

        # ── Saque de cartas ───────────────────────────────────────────────────
        elif 'Draw' in line and 'Card' in line:
            if is_you:
                needs_hand_rescan = True
            elif is_opp:
                m = _RE_DRAW_N.search(line)
                opp_gs.hand.extend([None] * int(m.group(1))) if m else None

        # ── Vida para mão (ON PLAY de certas cartas) ──────────────────────────
        elif 'Life to Hand' in line and is_you:
            m = _RE_SEND_LIFE.search(line)
            if m:
                n = int(m.group(1))
                gs.life = gs.life[n:] if len(gs.life) >= n else []
                needs_hand_rescan = True  # carta nova na mão

        # ── DON restado por efeito ────────────────────────────────────────────
        elif 'Rest' in line and 'Don' in line and is_you:
            m = _RE_REST_N.search(line)
            if m:
                gs.don_available = max(0, gs.don_available - int(m.group(1)))

        # ── K.O. ─────────────────────────────────────────────────────────────
        elif 'K.O.' in line and codes:
            code = codes[-1]
            if is_you:
                gs.field_chars = [c for c in gs.field_chars if c.code != code]
            elif is_opp:
                opp_gs.field_chars = [c for c in opp_gs.field_chars
                                       if c.code != code]

        # ── Dano na vida ──────────────────────────────────────────────────────
        elif 'hit for' in line:
            m = _RE_HIT.search(line)
            if m:
                dmg = int(m.group(1))
                # Heurística: se "You" foi atingido → nossa vida diminui
                if is_you or 'Player 2' in line:
                    gs.life = gs.life[dmg:] if len(gs.life) >= dmg else []
                else:
                    opp_gs.life = (opp_gs.life[dmg:]
                                   if len(opp_gs.life) >= dmg else [])

    return needs_hand_rescan

# ── OCR do preview de carta ────────────────────────────────────────────────────
_NAME_NOISE = re.compile(r'^[^A-Za-z]+')

def _ocr_crop(bbox: tuple, whitelist: str | None = None,
              psm: int = 7, scale: int = 4) -> str:
    img = ImageGrab.grab(bbox=bbox)
    img = img.resize((img.width * scale, img.height * scale), Image.LANCZOS)
    img = img.convert('L')
    img = ImageEnhance.Contrast(img).enhance(2.5)
    img = img.filter(ImageFilter.SHARPEN)
    cfg = f'--psm {psm}'
    if whitelist:
        cfg += f' -c tessedit_char_whitelist={whitelist}'
    return pytesseract.image_to_string(img, config=cfg).strip()

def _read_preview_name() -> str:
    raw = _ocr_crop(PREVIEW_NAME_BBOX, psm=7)
    clean = _NAME_NOISE.sub('', raw).strip()
    return re.sub(r'^[^A-Z]+', '', clean)

def _read_preview_cost() -> int | None:
    raw = _ocr_crop(PREVIEW_COST_BBOX, whitelist='0123456789', psm=8)
    digits = re.sub(r'\D', '', raw)
    if digits and int(digits) <= 12:
        return int(digits)
    return None

def _read_preview_power() -> int | None:
    raw = _ocr_crop(PREVIEW_POWER_BBOX, whitelist='0123456789+', psm=7)
    digits = re.sub(r'\D', '', raw)
    return int(digits) if digits else None

def _read_don_active(hover_pos: tuple) -> int:
    pag.moveTo(*hover_pos, duration=0.04)
    time.sleep(0.5)
    bbox = _badge_bbox(*hover_pos)
    raw = _ocr_crop(bbox, whitelist='0123456789()', psm=8, scale=6)
    m = re.search(r'(\d+)\((\d+)\)', raw)
    if m:
        return max(0, int(m.group(1)) - int(m.group(2)))
    digits = re.findall(r'\d+', raw)
    return int(digits[0]) if digits else 0

# ── Scan completo (feito UMA VEZ por Main Phase) ───────────────────────────────

def scan_hand() -> list[dict]:
    """Varre posições da mão via hover+OCR. Hover wait = HOVER_WAIT."""
    cards: list[dict] = []
    seen: set[str] = set()
    empty_streak = 0

    x = HAND_X_START
    while x <= HAND_X_END + HAND_STEP:
        pag.moveTo(x, HAND_Y, duration=0.04)
        time.sleep(HOVER_WAIT)

        name  = _read_preview_name()
        cost  = _read_preview_cost()
        power = _read_preview_power()

        if not name:
            empty_streak += 1
            if empty_streak >= 3:
                break
            x += HAND_STEP
            continue

        empty_streak = 0
        key = name.lower()
        if key not in seen:
            seen.add(key)
            db  = _lookup_by_name(name, cost)
            cards.append({
                'x': x, 'name': name, 'cost': cost, 'power': power,
                'code': db.get('code') if db else None,
                'db': db,
            })
        x += HAND_STEP

    return cards

def scan_board_p2() -> list[dict]:
    """Escaneia personagens no campo P2 via hover+OCR."""
    POSITIONS = [
        (510, 430), (575, 430), (640, 430), (705, 430),
        (770, 430), (835, 430),
    ]
    cards: list[dict] = []
    seen: set[str] = set()
    for bx, by in POSITIONS:
        pag.moveTo(bx, by, duration=0.04)
        time.sleep(HOVER_WAIT)
        name  = _read_preview_name()
        cost  = _read_preview_cost()
        power = _read_preview_power()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        db = _lookup_by_name(name, cost)
        cards.append({'x': bx, 'y': by, 'name': name, 'cost': cost,
                      'power': power, 'code': db.get('code') if db else None})
    return cards

def scan_opp_board() -> list[dict]:
    """Escaneia personagens no campo P1 (oponente) via hover+OCR."""
    POSITIONS = [
        (510, 310), (575, 310), (640, 310), (705, 310),
        (770, 310), (835, 310),
    ]
    cards: list[dict] = []
    seen: set[str] = set()
    for bx, by in POSITIONS:
        pag.moveTo(bx, by, duration=0.04)
        time.sleep(HOVER_WAIT)
        name  = _read_preview_name()
        cost  = _read_preview_cost()
        power = _read_preview_power()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        db = _lookup_by_name(name, cost)
        cards.append({'x': bx, 'y': by, 'name': name, 'cost': cost,
                      'power': power, 'code': db.get('code') if db else None})
    return cards

def full_scan(gs, opp_gs) -> tuple[list[dict], list[dict]]:
    """
    Scan completo do estado visual: mão, campo P2, campo P1, DON.
    Sincroniza gs e opp_gs. Retorna (hand_cards, board_cards) para referência de posição.
    """
    bridge = _get_bridge()

    hand_cards  = scan_hand()
    board_cards = scan_board_p2()
    opp_board   = scan_opp_board()
    don_p2      = _read_don_active(DON_P2_HOVER)
    don_p1      = _read_don_active(DON_P1_HOVER)

    if bridge:
        bridge.sync_hand(gs, hand_cards)
        bridge.sync_field(gs, board_cards)
        bridge.sync_field(opp_gs, opp_board)
    gs.don_available     = don_p2
    opp_gs.don_available = don_p1

    return hand_cards, board_cards

# ── Detecção de botões ─────────────────────────────────────────────────────────
BTN_LO = (115, 100, 75)
BTN_HI = (235, 215, 170)

def _is_beige(rgb) -> bool:
    return all(BTN_LO[i] <= rgb[i] <= BTN_HI[i] for i in range(3))

def _scan_buttons() -> tuple[bool, bool]:
    img = ImageGrab.grab()
    top  = _is_beige(img.getpixel((1220, 578)))
    main = _is_beige(img.getpixel((1220, 643)))
    return top, main

# ── Foco na janela ─────────────────────────────────────────────────────────────

def _focus_sim() -> bool:
    try:
        import pygetwindow as gw
        wins = [w for w in gw.getAllWindows() if 'OPTCGSim' in w.title]
        if wins:
            wins[0].activate()
            time.sleep(0.4)
            return True
    except Exception:
        pass
    return False

# ── Tratamento de prompts ──────────────────────────────────────────────────────
_game_phase = 0

def _handle_prompts(max_steps: int = 20) -> None:
    """Resolve prompts pós-ação clicando Pass/Cancel (C_BTN_MAIN)."""
    idle = 0
    for _ in range(max_steps):
        time.sleep(0.35)
        top, main = _scan_buttons()
        if not top and not main:
            idle += 1
            if idle >= 5:
                return
            continue
        idle = 0
        if top and main:
            pag.click(*C_BTN_MAIN)   # Pass / No Counter / Skip effect
        else:
            return

def _try_deploy_card(hand_x: int) -> bool:
    pag.click(hand_x, HAND_Y)
    time.sleep(0.45)
    top, main = _scan_buttons()
    if top and main:
        pag.click(*C_BTN_TOP)
        time.sleep(0.45)
        _handle_prompts()
        return True
    pag.click(700, 380)
    time.sleep(0.2)
    return False

def _try_attack_leader() -> None:
    pag.moveTo(*C_P2_LEADER, duration=0.12)
    pag.mouseDown()
    time.sleep(0.08)
    pag.moveTo(C_P2_LEADER[0], C_P1_CHAR_AREA[1], duration=0.18)
    pag.moveTo(*C_P1_LEADER, duration=0.18)
    pag.mouseUp()
    time.sleep(0.5)
    top, main = _scan_buttons()
    if top or main:
        _handle_prompts()

def _try_attack_char(field_x: int, field_y: int) -> None:
    pag.moveTo(field_x, field_y, duration=0.12)
    pag.mouseDown()
    time.sleep(0.08)
    pag.moveTo(C_P1_CHAR_AREA[0], C_P1_CHAR_AREA[1], duration=0.25)
    pag.mouseUp()
    time.sleep(0.5)
    top, main = _scan_buttons()
    if top or main:
        _handle_prompts()

# ── Execução de ação do engine ─────────────────────────────────────────────────

def _execute_engine_action(action: tuple, hand_cards: list[dict],
                            board_cards: list[dict]) -> bool:
    if not action:
        return False
    score       = action[0]
    action_type = action[1] if len(action) > 1 else 'end_turn'
    card        = action[2] if len(action) > 2 else None

    if score < 0 or action_type == 'end_turn':
        return False

    if action_type == 'play' and card is not None:
        code   = getattr(card, 'code', None)
        hand_x = None
        for h in hand_cards:
            if h.get('code') == code or \
               h.get('name', '').lower() == getattr(card, 'name', '').lower():
                hand_x = h['x']
                break
        if hand_x is None and hand_cards:
            hand_x = hand_cards[0]['x']
        return _try_deploy_card(hand_x) if hand_x else False

    if action_type == 'attack' and card is not None:
        if getattr(card, 'card_type', '') == 'LEADER':
            _try_attack_leader()
            return True
        for b in board_cards:
            if b.get('code') == getattr(card, 'code', None):
                _try_attack_char(b['x'], b['y'])
                return True
        _try_attack_leader()
        return True

    return False

# ── Seleção de deck no dropdown ────────────────────────────────────────────────

def _select_deck_dropdown(dd_coord: tuple, deck_name: str) -> bool:
    """
    Clica no dropdown em dd_coord, espera a lista abrir, procura o item
    cujo nome coincide com deck_name e clica nele.
    Retorna True se encontrou e clicou.
    """
    pag.click(*dd_coord)
    time.sleep(0.6)

    # OCR da lista aberta (cobre area do dropdown expandido)
    LIST_BBOX = (190, 160, 400, 500)
    img = ImageGrab.grab(bbox=LIST_BBOX)
    img_big = img.resize((img.width * 3, img.height * 3), Image.LANCZOS)
    img_big = img_big.convert('L')
    img_big = ImageEnhance.Contrast(img_big).enhance(2.0)
    raw = pytesseract.image_to_string(img_big, config='--psm 6').strip()
    lines = [l.strip() for l in raw.splitlines() if l.strip()]

    target = deck_name.lower()
    for i, line in enumerate(lines):
        if target in line.lower():
            # Estima y pela posição da linha na bbox
            y_offset = int((i + 0.5) * (LIST_BBOX[3] - LIST_BBOX[1]) / max(len(lines), 1))
            y_click = LIST_BBOX[1] + y_offset
            pag.click(dd_coord[0], y_click)
            time.sleep(0.4)
            return True

    # Fallback: clica no primeiro item após o título
    if len(lines) > 1:
        y_offset = int(1.5 * (LIST_BBOX[3] - LIST_BBOX[1]) / max(len(lines), 1))
        pag.click(dd_coord[0], LIST_BBOX[1] + y_offset)
        time.sleep(0.4)
    else:
        pag.key('escape')
    return False


# ── Fluxo de uma partida ───────────────────────────────────────────────────────

def play_match(deck_name: str | None = None, timeout: int = 600) -> bool:
    global _game_phase
    _game_phase = 0
    _reset_log()

    bridge = _get_bridge()
    gs = opp_gs = match = None

    if bridge and deck_name:
        try:
            from optcg_engine.decision_engine import OPTCGMatch
            deck_tuple = bridge.load_sim_deck(deck_name)
            match  = OPTCGMatch(deck_tuple, deck_tuple)
            gs     = match.state_b
            opp_gs = match.state_a
            print(f"  Deck: {deck_name} (líder: {gs.leader.name})", end=" ")
        except Exception as e:
            print(f"  [engine indisponível: {e}]", end=" ")
            bridge = None

    print("  Solo v Self...", end=" ", flush=True)
    pag.click(*C_SOLO_V_SELF)
    time.sleep(1.5)

    # ── Seleciona deck nos dropdowns P1/P2 (se deck_name fornecido) ───────────
    if deck_name:
        _select_deck_dropdown(C_DECK_P1_DD, deck_name)
        _select_deck_dropdown(C_DECK_P2_DD, deck_name)

    print("Start!", end=" ", flush=True)
    pag.click(*C_START)
    time.sleep(2.5)

    start      = time.time()
    idle_ticks = 0
    MAX_IDLE   = 20

    # Estado da Main Phase
    hand_cards  : list[dict] = []   # posições visuais da mão (para cliques)
    board_cards : list[dict] = []   # posições visuais do campo P2
    in_main     = False
    attacked    = False
    actions_this_turn = 0
    MAX_ACTIONS_PER_TURN = 6

    while time.time() - start < timeout:
        has_top, has_main = _scan_buttons()

        if not has_top and not has_main:
            idle_ticks += 1
            if idle_ticks >= MAX_IDLE:
                print("\n  [fim detectado]", end=" ", flush=True)
                break
            time.sleep(0.3)
            continue
        idle_ticks = 0

        # ── Dois botões ────────────────────────────────────────────────────────
        if has_top and has_main:
            in_main = False
            if _game_phase == 0:
                pag.click(*C_BTN_MAIN)   # Keep
                _game_phase = 1
            else:
                pag.click(*C_BTN_MAIN)   # Pass / No Counter / Skip
            time.sleep(0.35)
            continue

        # ── Botão único ────────────────────────────────────────────────────────
        if _game_phase >= 1 and not in_main:
            # Proba Main Phase tentando deploy em posições da mão (P2, y=HAND_Y).
            # Durante o turno do oponente, cliques em y=HAND_Y não abrem prompt.
            probe_positions = ([h['x'] for h in hand_cards]
                               if hand_cards else list(range(HAND_X_START, HAND_X_END + 1, HAND_STEP)))
            deployed = False
            for px in probe_positions[:5]:
                if _try_deploy_card(px):
                    deployed = True
                    break
            if deployed:
                in_main = True
                print("D", end="", flush=True)
                _reset_log()
                # Pular full_scan (muito lento) — usa log delta direto
                hand_cards = []
                board_cards = []
                _log_lines_seen[:] = _read_log_lines()
                continue

            # Probe falhou → avança o botão atual (Draw, Don, End Turn oponente, etc.)
            top2, main2 = _scan_buttons()
            if top2 and main2:
                _handle_prompts()
                continue
            in_main = False
            hand_cards = []
            board_cards = []
            attacked = False
            actions_this_turn = 0
            pag.click(*C_BTN_MAIN)
            time.sleep(0.5)
            continue

        if in_main:
            # Segurança: se excedeu ações por turno, encerra turno sem loop infinito
            if actions_this_turn >= MAX_ACTIONS_PER_TURN:
                in_main = False
                hand_cards = []
                board_cards = []
                attacked = False
                actions_this_turn = 0
                pag.click(*C_BTN_MAIN)
                time.sleep(0.5)
                print("X", end="", flush=True)
                continue

            # ── Decide via engine ──────────────────────────────────────────────
            action_executed = False

            if gs and bridge and match and hand_cards:
                try:
                    action = bridge.choose_action(gs, opp_gs, match, timeout=2.0)
                    if action:
                        action_executed = _execute_engine_action(
                            action, hand_cards, board_cards)
                        if action_executed:
                            actions_this_turn += 1
                            print(f"E({action[1][0]})", end="", flush=True)
                            time.sleep(0.3)

                            # ── DELTA DO LOG (sem rescan completo) ────────────
                            new_lines = read_log_delta()
                            needs_rescan = apply_log_delta(gs, opp_gs, new_lines)

                            if needs_rescan:
                                # Sacou carta — só rescaneamos a mão
                                hand_cards = scan_hand()
                                if bridge:
                                    bridge.sync_hand(gs, hand_cards)
                                print("R", end="", flush=True)

                            # Atualiza posições visuais da mão para cliques futuros
                            hand_cards = [h for h in hand_cards
                                          if any(c.code == h.get('code')
                                                 for c in gs.hand)]
                            continue
                except Exception as e:
                    print(f"[eng:{e}]", end="", flush=True)

            if not action_executed:
                if not attacked:
                    attacked = True
                    actions_this_turn += 1
                    _try_attack_leader()
                    print("A", end="", flush=True)
                    continue
                # Encerra turno
                in_main = False
                hand_cards = []
                board_cards = []
                attacked = False
                actions_this_turn = 0
                pag.click(*C_BTN_MAIN)
                time.sleep(0.5)
                print(".", end="", flush=True)
                continue

        pag.click(*C_BTN_MAIN)
        if _game_phase == 0:
            _game_phase = 1
        time.sleep(0.35)

    time.sleep(0.5)
    print(" Download...", end=" ", flush=True)
    pag.click(*C_DOWNLOAD_LOG)
    time.sleep(1.5)
    pag.click(*C_BACK_MAIN)
    time.sleep(2.0)
    return True

# ── CLI ────────────────────────────────────────────────────────────────────────

def _select_deck(deck_arg: str | None) -> str | None:
    bridge = _get_bridge()
    if not bridge:
        return None
    decks = bridge.list_decks()
    if not decks:
        print("[AVISO] Nenhum deck encontrado em", bridge.DECKS_DIR)
        return None
    if deck_arg:
        matches = [d for d in decks if deck_arg.lower() in d.lower()]
        if matches:
            return matches[0]
        print(f"Deck '{deck_arg}' não encontrado. Disponíveis:")
    print("Decks disponíveis:")
    for i, d in enumerate(decks, 1):
        print(f"  {i:2d}. {d}")
    try:
        idx = int(input("Escolha o número do deck: ")) - 1
        return decks[idx]
    except (ValueError, IndexError):
        return decks[0]

def main() -> None:
    ap = argparse.ArgumentParser(description="Bot OPTCGSim — P2 com engine")
    ap.add_argument("--deck",         default=None)
    ap.add_argument("--partidas",     type=int, default=3)
    ap.add_argument("--importar",     action="store_true")
    ap.add_argument("--delay-inicio", type=int, default=4)
    args = ap.parse_args()

    deck_name = _select_deck(args.deck)
    print(f"\nBot OPTCGSim — deck: {deck_name or '(sem engine)'} | {args.partidas} partidas")
    print(f"Aguardando {args.delay_inicio}s...")
    time.sleep(args.delay_inicio)

    if not _focus_sim():
        print("AVISO: janela OPTCGSim não encontrada")

    ok = 0
    for i in range(args.partidas):
        print(f"\n[{i+1}/{args.partidas}] ", end="", flush=True)
        _focus_sim()
        try:
            if play_match(deck_name=deck_name):
                ok += 1
                print("OK")
        except Exception as e:
            print(f"ERRO: {e}")
            try:
                pag.click(*C_BACK_MAIN)
                time.sleep(2)
            except Exception:
                pass

    print(f"\nConcluído: {ok}/{args.partidas} partidas.")

    if args.importar:
        autosaved = r"E:\Games\OnePieceSimulador\Builds_Windows\CombatLogs\AutoSaved"
        script    = _SCRIPTS_DIR / "importar_logs_autosaved.py"
        print("Importando logs...")
        subprocess.run([sys.executable, str(script), autosaved], check=False)


if __name__ == "__main__":
    main()
