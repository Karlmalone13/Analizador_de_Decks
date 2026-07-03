"""
bot_optcgsim.py  Bot para jogar partidas automaticas no OPTCGSim
=================================================================
O bot joga como P2 (jogador de baixo). Decisoes sao tomadas pelo
engine de decisao real (decision_engine.py) via sim_bridge.py.

Fluxo por turno:
  1. Detecta fase via pixels (botoes no canto inferior direito)
  2. Scan completo UMA VEZ no inicio da Main Phase (hover+OCR)
  3. Apos cada acao: OCR do painel de log (esquerda) -> aplica delta
     ao GameState sem rescanear o tabuleiro inteiro
  4. engine.choose_action() decide a melhor acao
  5. Executa a acao no simulador (clique/drag)

Uso:
    python bot_optcgsim.py [--deck NOME] [--partidas N] [--delay-inicio N]

Coordenadas: resolucao 1366x768, janela maximizada.
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

# -- Path do engine -------------------------------------------------------------
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
            print(f"[AVISO] sim_bridge nao disponivel: {e}")
    return _bridge

# -- Banco de cartas (nome -> codigo) -------------------------------------------
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

# -- Coordenadas fixas (1366x768) -----------------------------------------------
C_SOLO_V_SELF  = (684, 438)
C_DECK_P1_DD   = (297, 178)   # dropdown P1 na tela de selecao
C_DECK_P2_DD   = (297, 275)   # dropdown P2 na tela de selecao
C_START        = (297, 407)   # botao Start na tela de selecao
DECK_DD_SCROLL_X = 392
DECK_DD_ITEM_H = 26
DECK_DD_VISIBLE_COUNT = 8
DECK_DD_SCROLL_FACTOR = 8.5
C_BTN_TOP      = (1101, 578)
C_BTN_MAIN     = (1101, 643)
C_BACK_MAIN    = (1165, 82)
C_DOWNLOAD_LOG = (1165, 172)
C_P2_LEADER    = (700, 527)
C_P1_LEADER    = (632, 223)
C_P1_CHAR_AREA = (680, 310)
C_P2_STAGE     = (765, 545)

# Mao P2
HAND_Y       = 648
HAND_X_START = 107
HAND_X_END   = 410
HAND_STEP    = 35
HOVER_WAIT   = 0.30   # reduzido de 0.65 -> 0.30s

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

# -- Painel de log (esquerda) ---------------------------------------------------
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
    """OCR do painel de log. Retorna lista de linhas visiveis."""
    img = ImageGrab.grab(bbox=LOG_BBOX)
    img = img.convert('L')
    img = ImageOps.invert(img)   # texto claro em fundo escuro -> inverte
    img = img.resize((img.width * 3, img.height * 3), Image.LANCZOS)
    img = ImageEnhance.Contrast(img).enhance(2.0)
    raw = pytesseract.image_to_string(img, config='--psm 6').strip()
    return [l.strip() for l in raw.splitlines() if l.strip()]

def read_log_delta() -> list[str]:
    """
    Le o painel de log e retorna apenas as linhas novas
    desde a ultima chamada.
    """
    global _log_lines_seen
    current = _read_log_lines()
    if not current:
        return []
    if not _log_lines_seen:
        _log_lines_seen = current
        return current

    # Procura a ultima linha conhecida dentro do current para encontrar o delta
    last = _log_lines_seen[-1]
    try:
        idx = len(current) - 1 - list(reversed(current)).index(last)
        new_lines = current[idx + 1:]
    except ValueError:
        # OCR leu diferente  tudo e novo
        new_lines = current

    _log_lines_seen = current
    return new_lines

def apply_log_delta(gs, opp_gs, lines: list[str]) -> bool:
    """
    Aplica novas linhas do log ao GameState do bot e do oponente.

    Retorna True se a mao do bot mudou (carta sacada/recebida)
    e portanto precisa de rescan parcial da mao.
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

        # -- Deploy ------------------------------------------------------------
        if 'Deploy' in line and codes:
            code = codes[-1]
            if is_you:
                # Remove da mao
                gs.hand = [c for c in gs.hand if c.code != code]
                # Adiciona ao campo se ainda nao estiver
                if not any(c.code == code for c in gs.field_chars):
                    card = _get_card(code)
                    if card:
                        gs.field_chars.append(card)
            elif is_opp:
                if not any(c.code == code for c in opp_gs.field_chars):
                    card = _get_card(code)
                    if card:
                        opp_gs.field_chars.append(card)

        # -- Saque de cartas ---------------------------------------------------
        elif 'Draw' in line and 'Card' in line:
            if is_you:
                needs_hand_rescan = True
                gs.turn = max(gs.turn + 1, 2)  # garante ataques habilitados
            elif is_opp:
                m = _RE_DRAW_N.search(line)
                opp_gs.hand.extend([None] * int(m.group(1))) if m else None

        # -- Vida para mao (ON PLAY de certas cartas) --------------------------
        elif 'Life to Hand' in line and is_you:
            m = _RE_SEND_LIFE.search(line)
            if m:
                n = int(m.group(1))
                gs.life = gs.life[n:] if len(gs.life) >= n else []
                needs_hand_rescan = True  # carta nova na mao

        # -- Ganho de DON (fase de DON do turno) --------------------------------
        elif 'Draw' in line and 'Don' in line and is_you:
            m = re.search(r'Draw (\d+) Don', line)
            if m:
                gs.don_available += int(m.group(1))
                print(f"[DON+{m.group(1)}={gs.don_available}]", end="", flush=True)

        # -- DON restado por efeito --------------------------------------------
        elif 'Rest' in line and 'Don' in line and is_you:
            m = _RE_REST_N.search(line)
            if m:
                gs.don_available = max(0, gs.don_available - int(m.group(1)))

        # -- K.O. -------------------------------------------------------------
        elif 'K.O.' in line and codes:
            code = codes[-1]
            if is_you:
                gs.field_chars = [c for c in gs.field_chars if c.code != code]
            elif is_opp:
                opp_gs.field_chars = [c for c in opp_gs.field_chars
                                       if c.code != code]

        # -- Dano na vida ------------------------------------------------------
        elif 'hit for' in line:
            m = _RE_HIT.search(line)
            if m:
                dmg = int(m.group(1))
                # Heuristica: se "You" foi atingido -> nossa vida diminui
                if is_you or 'Player 2' in line:
                    gs.life = gs.life[dmg:] if len(gs.life) >= dmg else []
                else:
                    opp_gs.life = (opp_gs.life[dmg:]
                                   if len(opp_gs.life) >= dmg else [])

    return needs_hand_rescan

# -- OCR do preview de carta ----------------------------------------------------
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

# -- Scan completo (feito UMA VEZ por Main Phase) -------------------------------

def scan_hand() -> list[dict]:
    """Varre posicoes da mao via hover+OCR. Hover wait = HOVER_WAIT."""
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
    Scan completo do estado visual: mao, campo P2, campo P1, DON.
    Sincroniza gs e opp_gs. Retorna (hand_cards, board_cards) para referencia de posicao.
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

# -- Deteccao de botoes ---------------------------------------------------------
BTN_LO = (115, 100, 75)
BTN_HI = (235, 215, 170)

def _is_beige(rgb) -> bool:
    return all(BTN_LO[i] <= rgb[i] <= BTN_HI[i] for i in range(3))

def _scan_buttons() -> tuple[bool, bool]:
    img = ImageGrab.grab()
    top  = _is_beige(img.getpixel((1220, 578)))
    main = _is_beige(img.getpixel((1220, 643)))
    return top, main

# -- Foco na janela -------------------------------------------------------------

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

# -- Tratamento de prompts ------------------------------------------------------
_game_phase = 0

def _handle_prompts(max_steps: int = 20) -> None:
    """Resolve prompts pos-acao clicando Pass/Cancel (C_BTN_MAIN)."""
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

def _resolve_post_deploy() -> None:
    """Apos deploy, resolve apenas prompts de 2 botoes (counter do oponente).
    Para imediatamente em 1 botao — seja End Turn ou modal On Play.
    O loop principal resolve o que restar."""
    for _ in range(10):
        time.sleep(0.3)
        top, main = _scan_buttons()
        if not top and not main:
            break
        if top and main:
            pag.click(*C_BTN_MAIN)   # Pass / No Counter
            continue
        break  # 1 botao: End Turn ou On Play modal — parar aqui

def _try_deploy_card(hand_x: int) -> bool:
    pag.click(hand_x, HAND_Y)
    time.sleep(0.45)
    top, main = _scan_buttons()
    if top and main:
        pag.click(*C_BTN_TOP)
        time.sleep(0.45)
        _resolve_post_deploy()
        return True
    pag.click(700, 380)
    time.sleep(0.2)
    return False


def _probe_main_phase(hand_x: int) -> bool:
    """Detecta Main Phase clicando carta e cancelando o prompt sem deploia-la.
    Retorna True se estamos na Main Phase (prompt Deploy/Cancel apareceu)."""
    pag.click(hand_x, HAND_Y)
    time.sleep(0.45)
    top, main = _scan_buttons()
    if top and main:
        pag.click(*C_BTN_MAIN)  # Cancela sem deploia
        time.sleep(0.3)
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

# -- Execucao de acao do engine -----------------------------------------------

def _click_card_source(card, board_cards: list[dict]) -> bool:
    """Clica na fonte de uma acao do engine: leader, stage ou personagem."""
    if card is None:
        return False
    ctype = getattr(card, 'card_type', '')
    code = getattr(card, 'code', None)
    if ctype == 'LEADER':
        pag.click(*C_P2_LEADER)
        return True
    if ctype == 'STAGE':
        pag.click(*C_P2_STAGE)
        return True
    for b in board_cards:
        if b.get('code') == code:
            pag.click(b['x'], b['y'])
            return True
    return False


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
        print(f"[PLAY] code={code} hand_x={hand_x} vis={[(h.get('code'),h['x']) for h in hand_cards[:3]]}", flush=True)
        result = _try_deploy_card(hand_x) if hand_x else False
        print(f"[PLAY] _try_deploy_card={result}", flush=True)
        return result

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

    if action_type == 'activate' and card is not None:
        if not _click_card_source(card, board_cards):
            return False
        time.sleep(0.45)
        top, main = _scan_buttons()
        if top and main:
            pag.click(*C_BTN_TOP)
            time.sleep(0.35)
            _resolve_post_deploy()
            return True
        if top or main:
            _handle_prompts()
            return True
        return False

    if action_type == 'attach_don' and card is not None:
        amount = int(action[3]) if len(action) > 3 and isinstance(action[3], int) else 1
        source = DON_P2_HOVER
        target = None
        if getattr(card, 'card_type', '') == 'LEADER':
            target = C_P2_LEADER
        else:
            for b in board_cards:
                if b.get('code') == getattr(card, 'code', None):
                    target = (b['x'], b['y'])
                    break
        if not target:
            return False
        for _ in range(max(1, amount)):
            pag.moveTo(*source, duration=0.08)
            pag.mouseDown()
            time.sleep(0.05)
            pag.moveTo(*target, duration=0.18)
            pag.mouseUp()
            time.sleep(0.15)
        return True

    return False


def _consume_engine_action_locally(action: tuple) -> None:
    """Marca no estado local a parte da acao que o OCR do log pode nao ver."""
    if not action or len(action) < 3:
        return
    action_type = action[1]
    card = action[2]
    if action_type in ('attack', 'activate') and card is not None:
        try:
            card.rested = True
        except Exception:
            pass


def _action_debug_label(action: tuple) -> str:
    if not action or len(action) < 2:
        return "?"
    action_type = str(action[1])
    card = action[2] if len(action) > 2 else None
    code = getattr(card, 'code', '') if card is not None else ''
    name = getattr(card, 'name', '') if card is not None else ''
    label = code or name[:12] or '-'
    return f"{action_type}:{label}"


def _action_once_key(action: tuple) -> tuple[str, str] | None:
    if not action or len(action) < 3:
        return None
    action_type = str(action[1])
    if action_type not in ('activate', 'attack'):
        return None
    card = action[2]
    code = getattr(card, 'code', '') if card is not None else ''
    return (action_type, code)

# -- Selecao de deck no dropdown ----------------------------------------------

def _select_deck_dropdown(dd_coord: tuple, deck_name: str) -> bool:
    """
    Seleciona deck no dropdown sem depender de OCR.
    Usa lista de arquivos .deck (ordem alfabetica = ordem do dropdown Unity)
    para calcular o indice e navegar com teclado ate o item correto.
    Retorna True se conseguiu selecionar, False se usou fallback cego.
    """
    from optcg_engine.sim_bridge import DECKS_DIR

    # Lista decks ordenados — Unity exibe em ordem alfabetica
    try:
        all_decks = sorted(p.stem for p in DECKS_DIR.glob("*.deck"))
    except Exception:
        all_decks = []

    # Acha indice do deck alvo (case-insensitive)
    target_idx = next(
        (i for i, d in enumerate(all_decks) if d.lower() == deck_name.lower()),
        None,
    )
    if target_idx is None:
        # Match parcial
        target_idx = next(
            (i for i, d in enumerate(all_decks) if deck_name.lower() in d.lower()),
            None,
        )

    pag.click(*dd_coord)
    time.sleep(0.7)

    if target_idx is None:
        # Sem info de posicao: clica no primeiro item
        pag.click(dd_coord[0], 195)
        time.sleep(0.4)
        return False

    # Navega com teclado: Home vai para o primeiro item, Down avanca
    pag.press('home')
    time.sleep(0.1)
    for _ in range(target_idx):
        pag.press('down')
        time.sleep(0.05)
    pag.press('return')
    time.sleep(0.4)
    return True


# -- Fluxo de uma partida -------------------------------------------------------

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
            match.setup()   # inicializa mao + vida (5 cartas) para o engine funcionar
            gs     = match.state_b
            opp_gs = match.state_a
            gs.turn = 2     # can_attack_this_turn() = turn > 1: começa em 2
            opp_gs.turn = 2
            print(f"  Deck: {deck_name} (lider: {gs.leader.name})", end=" ")
        except Exception as e:
            print(f"  [engine indisponivel: {e}]", end=" ")
            bridge = None

    print("  Solo v Self...", end=" ", flush=True)
    pag.click(*C_SOLO_V_SELF)
    time.sleep(1.5)

    # -- Seleciona deck nos dropdowns P1/P2 (se deck_name fornecido) -----------
    if deck_name:
        p1_ok = _select_deck_dropdown(C_DECK_P1_DD, deck_name)
        p2_ok = _select_deck_dropdown(C_DECK_P2_DD, deck_name)
        print(f"SelectDeck(P1={p1_ok},P2={p2_ok})", end=" ", flush=True)

    print("Start!", end=" ", flush=True)
    pag.click(*C_START)
    time.sleep(2.5)

    start      = time.time()
    idle_ticks = 0
    MAX_IDLE   = 50  # ~15s — aguarda animacoes longas de On Play effects

    # Estado da Main Phase
    hand_cards  : list[dict] = []   # posicoes visuais da mao (para cliques)
    board_cards : list[dict] = []   # posicoes visuais do campo P2
    in_main     = False
    attacked    = False
    actions_this_turn = 0
    MAX_ACTIONS_PER_TURN = 6
    used_engine_actions: set[tuple[str, str]] = set()

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

        # -- Dois botoes --------------------------------------------------------
        if has_top and has_main:
            in_main = False
            if _game_phase == 0:
                pag.click(*C_BTN_MAIN)   # Keep
                _game_phase = 1
            else:
                pag.click(*C_BTN_MAIN)   # Pass / No Counter / Skip
            time.sleep(0.35)
            continue

        # -- Botao unico --------------------------------------------------------
        if _game_phase >= 1 and not in_main:
            # Proba Main Phase tentando deploy em posicoes da mao (P2, y=HAND_Y).
            # Durante o turno do oponente, cliques em y=HAND_Y nao abrem prompt.
            probe_xs = ([h['x'] for h in hand_cards[:5]]
                        if hand_cards
                        else list(range(HAND_X_START, HAND_X_END + 1, HAND_STEP))[:5])
            detected = False
            for px in probe_xs:
                if _probe_main_phase(px):
                    detected = True
                    break
            if detected:
                in_main = True
                print("M", end="", flush=True)
                # Le DON real da tela (sem deploy: DON nao foi gasto pelo probe)
                if gs and opp_gs:
                    pre_lines = read_log_delta()
                    apply_log_delta(gs, opp_gs, pre_lines)
                    print(f"[DON={gs.don_available}]", end="", flush=True)
                _reset_log()
                # Scan rapido: so a mao (full_scan ~11s trava o loop)
                hand_cards = scan_hand()
                board_cards = []
                if bridge and gs:
                    bridge.sync_hand(gs, hand_cards)
                _log_lines_seen[:] = _read_log_lines()
                continue

            # Probe falhou -> avanca o botao atual (Draw, Don, End Turn oponente, etc.)
            top2, main2 = _scan_buttons()
            if top2 and main2:
                _handle_prompts()
                continue
            in_main = False
            hand_cards = []
            board_cards = []
            attacked = False
            actions_this_turn = 0
            used_engine_actions.clear()
            pag.click(*C_BTN_MAIN)
            time.sleep(0.5)
            continue

        if in_main:
            # Seguranca: se excedeu acoes por turno, encerra turno sem loop infinito
            if actions_this_turn >= MAX_ACTIONS_PER_TURN:
                in_main = False
                hand_cards = []
                board_cards = []
                attacked = False
                actions_this_turn = 0
                used_engine_actions.clear()
                pag.click(*C_BTN_MAIN)
                time.sleep(0.5)
                print("X", end="", flush=True)
                continue

            # -- Decide via engine ----------------------------------------------
            action_executed = False

            if gs and bridge and match:
                try:
                    print(f"[BOT] calling engine hand={len(gs.hand)} don={gs.don_available} turn={gs.turn} vis={len(hand_cards)}", flush=True)
                    action = bridge.choose_action(gs, opp_gs, match, timeout=2.0)
                    print(f"[BOT] engine->{'None' if action is None else action[:2]}", flush=True)
                    if action:
                        once_key = _action_once_key(action)
                        if once_key and once_key in used_engine_actions:
                            _consume_engine_action_locally(action)
                            print(f"S({_action_debug_label(action)})", end="", flush=True)
                            actions_this_turn = MAX_ACTIONS_PER_TURN
                            continue
                        action_executed = _execute_engine_action(
                            action, hand_cards, board_cards)
                        if action_executed:
                            idle_ticks = 0  # reseta idle apos acao (animacoes On Play)
                            once_key = _action_once_key(action)
                            if once_key:
                                used_engine_actions.add(once_key)
                            actions_this_turn += 1
                            if action[1] == 'attack':
                                attacked = True  # evita tentativa dupla via fallback A
                            print(f"E({_action_debug_label(action)})", end="", flush=True)
                            time.sleep(0.3)
                            _consume_engine_action_locally(action)
                            # Apos ataque: aguarda e resolve prompts do oponente
                            if action[1] == 'attack':
                                time.sleep(0.8)
                                for _ in range(15):
                                    t2, m2 = _scan_buttons()
                                    if not t2 and not m2:
                                        break
                                    pag.click(*C_BTN_MAIN)
                                    time.sleep(0.35)
                            # Remove carta jogada de gs.hand imediatamente (log pode perder)
                            if gs and action[1] == 'play' and len(action) > 2 and action[2] is not None:
                                played = action[2]
                                for i, c in enumerate(gs.hand):
                                    if c is played or c.code == played.code:
                                        gs.hand.pop(i)
                                        break

                            # -- DELTA DO LOG (sem rescan completo) ------------
                            new_lines = read_log_delta()
                            needs_rescan = apply_log_delta(gs, opp_gs, new_lines)

                            if needs_rescan:
                                # Sacou carta - so rescaneamos a mao
                                hand_cards = scan_hand()
                                if bridge:
                                    bridge.sync_hand(gs, hand_cards)
                                print("R", end="", flush=True)

                            # Atualiza posicoes visuais da mao para cliques futuros
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
                used_engine_actions.clear()
                idle_ticks = 0  # reseta idle — P1 pode ter animacoes longas
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

# -- CLI ------------------------------------------------------------------------

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
        print(f"Deck '{deck_arg}' nao encontrado. Disponiveis:")
    print("Decks disponiveis:")
    for i, d in enumerate(decks, 1):
        print(f"  {i:2d}. {d}")
    try:
        idx = int(input("Escolha o numero do deck: ")) - 1
        return decks[idx]
    except (ValueError, IndexError):
        return decks[0]

def main() -> None:
    ap = argparse.ArgumentParser(description="Bot OPTCGSim - P2 com engine")
    ap.add_argument("--deck",         default=None)
    ap.add_argument("--partidas",     type=int, default=3)
    ap.add_argument("--timeout",      type=int, default=600)
    ap.add_argument("--importar",     action="store_true")
    ap.add_argument("--delay-inicio", type=int, default=4)
    args = ap.parse_args()

    deck_name = _select_deck(args.deck)
    print(f"\nBot OPTCGSim - deck: {deck_name or '(sem engine)'} | {args.partidas} partidas")
    print(f"Aguardando {args.delay_inicio}s...")
    time.sleep(args.delay_inicio)

    if not _focus_sim():
        print("AVISO: janela OPTCGSim nao encontrada")

    ok = 0
    for i in range(args.partidas):
        print(f"\n[{i+1}/{args.partidas}] ", end="", flush=True)
        _focus_sim()
        try:
            if play_match(deck_name=deck_name, timeout=args.timeout):
                ok += 1
                print("OK")
        except Exception as e:
            print(f"ERRO: {e}")
            try:
                pag.click(*C_BACK_MAIN)
                time.sleep(2)
            except Exception:
                pass

    print(f"\nConcluido: {ok}/{args.partidas} partidas.")

    if args.importar:
        autosaved = r"E:\Games\OnePieceSimulador\Builds_Windows\CombatLogs\AutoSaved"
        script    = _SCRIPTS_DIR / "importar_logs_autosaved.py"
        print("Importando logs...")
        subprocess.run([sys.executable, str(script), autosaved], check=False)


if __name__ == "__main__":
    main()

