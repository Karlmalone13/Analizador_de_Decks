"""
bot_optcgsim.py — Bot para jogar partidas automáticas no OPTCGSim
=================================================================
O bot joga como P2 (jogador de baixo). Decisões são tomadas pelo
engine de decisão real (decision_engine.py) via sim_bridge.py.

Fluxo por turno:
  1. Detecta fase via pixels (botões no canto inferior direito)
  2. Lê estado visual: mão (hover+OCR), campo, DON
  3. Sincroniza com GameState via sim_bridge
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

try:
    import pyautogui as pag
    from PIL import ImageGrab, Image, ImageEnhance, ImageFilter
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
except ImportError:
    print("Instale: pip install pyautogui pillow pytesseract")
    sys.exit(1)

pag.PAUSE = 0.05

# ── Adiciona o dir do engine ao path ──────────────────────────────────────────
_SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(_SCRIPTS_DIR))

# Import do bridge (lazy para não crashar se faltar dependência)
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

# ── Banco de cartas para lookup nome → código ─────────────────────────────────
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
# Menu principal
C_SOLO_V_SELF = (684, 438)
C_START        = (297, 407)

# Botões de ação (canto inferior direito)
C_BTN_TOP  = (1101, 578)   # Deploy / Confirm / Mulligan
C_BTN_MAIN = (1101, 643)   # Cancel / End Turn / Draw Card / Keep

# Controles em jogo
C_BACK_MAIN   = (1165, 82)
C_DOWNLOAD_LOG = (1165, 172)

# Líderes e alvos de ataque
C_P2_LEADER    = (700, 527)
C_P1_LEADER    = (632, 223)
C_P1_CHAR_AREA = (680, 310)

# Mão P2: strip inferior esquerda
HAND_Y       = 648
HAND_X_START = 107
HAND_X_END   = 410
HAND_STEP    = 35

# Preview de carta (lado direito, aparece ao hover)
PREVIEW_NAME_BBOX  = (945, 415, 1185, 445)
PREVIEW_COST_BBOX  = (930,  58,  975,  98)
PREVIEW_POWER_BBOX = (1130,  58, 1230,  95)

# Posições de hover para counters (mostram badge com número)
DON_P2_HOVER   = (495, 634)      # hover → badge "N(M)" = total(restados)
DON_P1_HOVER   = (865, 100)      # hover → badge P1 DON
DECK_P2_HOVER  = (480, 545)      # hover → badge count do deck P2
DECK_P1_HOVER  = (870, 200)      # hover → badge count do deck P1
LIFE_P2_HOVER  = (480, 460)      # hover → badge count das vidas P2 (posição estimada)
LIFE_P1_HOVER  = (463, 210)      # hover → badge count das vidas P1 (posição estimada)
TRASH_P2_HOVER = (855, 640)      # hover → preview do topo do trash P2
TRASH_P1_HOVER = (463, 160)      # hover → preview do topo do trash P1
OPP_HAND_HOVER = (250, 90)       # hover → badge com número de cartas na mão do oponente

# Bboxes dos badges de counter (aparecem após hover, círculo com número)
# Localização aproximada: canto superior do objeto hovereado
_BADGE_OFFSET_Y = -45   # badge fica ~45px acima do centro do objeto hovereado

def _badge_bbox(hover_x: int, hover_y: int) -> tuple:
    """Bbox estimado do badge de counter baseado na posição de hover."""
    x, y = hover_x, hover_y + _BADGE_OFFSET_Y
    return (x - 25, y - 20, x + 25, y + 20)

# ── OCR utilitário ─────────────────────────────────────────────────────────────
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
    clean = re.sub(r'^[^A-Z]+', '', clean)
    return clean

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

def _read_counter_badge(hover_pos: tuple) -> int | None:
    """
    Hover sobre hover_pos, aguarda badge aparecer, OCR para ler número.
    Retorna int ou None.
    """
    pag.moveTo(*hover_pos, duration=0.04)
    time.sleep(0.7)
    bbox = _badge_bbox(*hover_pos)
    raw = _ocr_crop(bbox, whitelist='0123456789()', psm=8, scale=6)
    digits = re.findall(r'\d+', raw)
    return int(digits[0]) if digits else None

def _read_don_active(hover_pos: tuple) -> int:
    """
    Lê DON ativo de um jogador via hover.
    Badge mostra "N(M)" onde N=total DON, M=restados. Ativo = N - M.
    Retorna 0 se falhar.
    """
    pag.moveTo(*hover_pos, duration=0.04)
    time.sleep(0.7)
    bbox = _badge_bbox(*hover_pos)
    raw = _ocr_crop(bbox, whitelist='0123456789()', psm=8, scale=6)
    m = re.search(r'(\d+)\((\d+)\)', raw)
    if m:
        total, rested = int(m.group(1)), int(m.group(2))
        return max(0, total - rested)
    digits = re.findall(r'\d+', raw)
    return int(digits[0]) if digits else 0

# ── Scan de mão e campo ────────────────────────────────────────────────────────

def scan_hand() -> list[dict]:
    """Varre posições da mão via hover+OCR. Retorna lista de dicts por carta."""
    cards: list[dict] = []
    seen: set[str] = set()
    empty_streak = 0

    x = HAND_X_START
    while x <= HAND_X_END + HAND_STEP:
        pag.moveTo(x, HAND_Y, duration=0.04)
        time.sleep(0.65)

        name  = _read_preview_name()
        cost  = _read_preview_cost()
        power = _read_preview_power()

        if not name:
            empty_streak += 1
            if empty_streak >= 4:
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
    """Escaneia cartas na Character Area P2 via hover+OCR."""
    POSITIONS = [
        (510, 430), (575, 430), (640, 430), (705, 430),
        (770, 430), (835, 430), (510, 460), (575, 460),
    ]
    cards: list[dict] = []
    seen: set[str] = set()
    for bx, by in POSITIONS:
        pag.moveTo(bx, by, duration=0.04)
        time.sleep(0.55)
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

# ── Leitura de estado completo ─────────────────────────────────────────────────

def read_game_state() -> dict:
    """
    Lê o estado completo do jogo via hover+OCR.
    Retorna dict com: hand, board_p2, don_p2_active, don_p1_active, opp_hand_count.
    """
    state: dict = {}

    # DON
    state['don_p2_active'] = _read_don_active(DON_P2_HOVER)
    state['don_p1_active'] = _read_don_active(DON_P1_HOVER)

    # Mão e campo
    state['hand']     = scan_hand()
    state['board_p2'] = scan_board_p2()

    # Contagem mão oponente (badge)
    opp = _read_counter_badge(OPP_HAND_HOVER)
    state['opp_hand_count'] = opp if opp is not None else 5

    return state

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

def _wait_for_button(timeout: float = 8.0) -> tuple[bool, bool]:
    end = time.time() + timeout
    while time.time() < end:
        t, m = _scan_buttons()
        if t or m:
            return t, m
        time.sleep(0.2)
    return False, False

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

def _handle_prompts(max_steps: int = 30) -> None:
    """
    Clica prompts de efeito (ON PLAY, Choose Target, etc.) até
    botão único reaparecer ou inatividade.
    """
    idle = 0
    for _ in range(max_steps):
        time.sleep(0.35)
        top, main = _scan_buttons()
        if not top and not main:
            idle += 1
            if idle >= 6:
                return
            continue
        idle = 0
        if top and main:
            pag.click(*C_BTN_TOP)   # Confirm / Use / escolhe primeiro alvo
        else:
            return

def _try_deploy_card(hand_x: int) -> bool:
    """
    Clica carta em hand_x. Se aparecer Deploy (dois botões) → deploya e trata ON PLAY.
    Retorna True se jogou, False se não (carta cara ou sem Deploy).
    """
    pag.click(hand_x, HAND_Y)
    time.sleep(0.45)
    top, main = _scan_buttons()
    if top and main:
        pag.click(*C_BTN_TOP)   # Deploy
        time.sleep(0.45)
        _handle_prompts()
        return True
    # Fecha preview clicando no tabuleiro
    pag.click(700, 380)
    time.sleep(0.2)
    return False

def _try_attack_leader() -> None:
    """Arrasta líder P2 até líder P1 para atacar."""
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
    """Arrasta personagem P2 no campo até a área de personagens P1."""
    pag.moveTo(field_x, field_y, duration=0.12)
    pag.mouseDown()
    time.sleep(0.08)
    pag.moveTo(C_P1_CHAR_AREA[0], C_P1_CHAR_AREA[1], duration=0.25)
    pag.mouseUp()
    time.sleep(0.5)
    top, main = _scan_buttons()
    if top or main:
        _handle_prompts()

# ── Execução de ação do engine ──────────────────────────────────────────────────

def _execute_engine_action(action: tuple, hand_cards: list[dict],
                           board_cards: list[dict]) -> bool:
    """
    Recebe a tupla de ação do engine e a executa no simulador.
    Retorna True se executou algo, False se não houve ação.

    Formatos de action conhecidos (decision_engine.py):
      (score, 'play',    card, ...)
      (score, 'attack',  attacker, target, ...)
      (score, 'activate', card, ...)
      (score, 'don_attach', card, ...)
      (score, 'end_turn')
    """
    if not action:
        return False

    score      = action[0]
    action_type = action[1] if len(action) > 1 else 'end_turn'
    card       = action[2] if len(action) > 2 else None

    if score < 0 or action_type == 'end_turn':
        return False

    if action_type == 'play' and card is not None:
        # Encontra posição na mão pelo código da carta
        code = getattr(card, 'code', None)
        hand_x = None
        for h in hand_cards:
            if h.get('code') == code or h.get('name', '').lower() == getattr(card, 'name', '').lower():
                hand_x = h['x']
                break
        if hand_x is None and hand_cards:
            hand_x = hand_cards[0]['x']   # fallback: primeira carta
        if hand_x:
            return _try_deploy_card(hand_x)
        return False

    if action_type == 'attack' and card is not None:
        attacker_code = getattr(card, 'code', None)
        # Verifica se é o líder
        if card and getattr(card, 'card_type', '') == 'LEADER':
            _try_attack_leader()
            return True
        # Personagem no campo
        for b in board_cards:
            if b.get('code') == attacker_code:
                _try_attack_char(b['x'], b['y'])
                return True
        # Fallback: ataca com líder
        _try_attack_leader()
        return True

    # Outros tipos de ação (activate, don_attach) não implementados ainda
    return False

# ── Fluxo de uma partida ───────────────────────────────────────────────────────

def play_match(deck_name: str | None = None, timeout: int = 600) -> bool:
    """
    Joga uma partida completa usando o engine para decidir.
    Retorna True se concluída normalmente.
    """
    global _game_phase
    _game_phase = 0

    bridge = _get_bridge()

    # Carrega o deck e monta estado inicial
    gs      = None
    opp_gs  = None
    match   = None

    if bridge and deck_name:
        try:
            from optcg_engine.decision_engine import OPTCGMatch
            deck_tuple = bridge.load_sim_deck(deck_name)
            # Cria partida com dois decks iguais (bot vs bot - o oponente é stub)
            match  = OPTCGMatch(deck_tuple, deck_tuple)
            # state_b = P2 = nós; state_a = P1 = oponente
            gs     = match.state_b
            opp_gs = match.state_a
            leader = gs.leader
            print(f"  Deck: {deck_name} (líder: {leader.name})", end=" ")
        except Exception as e:
            print(f"  [engine indisponível: {e}]", end=" ")
            bridge = None

    print("  Solo v Self...", end=" ", flush=True)
    pag.click(*C_SOLO_V_SELF)
    time.sleep(1.5)

    print("Start!", end=" ", flush=True)
    pag.click(*C_START)
    time.sleep(2.5)

    start      = time.time()
    idle_ticks = 0
    MAX_IDLE   = 20

    hand_cards  : list[dict] = []
    board_cards : list[dict] = []
    in_main     = False
    attacked    = False
    main_actions_done = 0

    while time.time() - start < timeout:
        has_top, has_main = _scan_buttons()

        # ── Sem botão ──────────────────────────────────────────────────────────
        if not has_top and not has_main:
            idle_ticks += 1
            if idle_ticks >= MAX_IDLE:
                print("\n  [fim detectado]", end=" ", flush=True)
                break
            time.sleep(0.3)
            continue
        idle_ticks = 0

        # ── Dois botões (TOP + MAIN) ────────────────────────────────────────────
        if has_top and has_main:
            in_main = False
            if _game_phase == 0:
                pag.click(*C_BTN_MAIN)   # Keep (Mulligan)
                _game_phase = 1
            else:
                pag.click(*C_BTN_TOP)    # Confirm / Use Action
            time.sleep(0.35)
            continue

        # ── Botão único (MAIN) ─────────────────────────────────────────────────
        # Pode ser: Draw Card, Draw Don, End Turn, Return Cards...
        # Detecção de Main Phase: testa clicando na mão (se Deploy aparecer = Main Phase)

        if _game_phase >= 1 and not in_main:
            # Testa se estamos na Main Phase clicando na primeira carta da mão
            test_x = hand_cards[0]['x'] if hand_cards else HAND_X_START
            if _try_deploy_card(test_x):
                # Confirmado: Main Phase
                in_main = True
                main_actions_done = 1
                print("D", end="", flush=True)

                # Lê estado completo e sincroniza com engine
                state = read_game_state()
                hand_cards  = state['hand']
                board_cards = state['board_p2']

                if gs and bridge:
                    bridge.sync_hand(gs, hand_cards)
                    bridge.sync_field(gs, board_cards)
                    gs.don_available = state['don_p2_active']
                    opp_gs.hand = [None] * state['opp_hand_count']  # stub mão oponente

                continue

            # Deploy não apareceu → não é Main Phase (Draw Card/Don ou fim)
            top2, main2 = _scan_buttons()
            if top2 and main2:
                _handle_prompts()
                continue
            # Botão único ainda presente → clica (Draw Card, Draw Don, etc.)
            in_main = False
            hand_cards  = []
            board_cards = []
            attacked    = False
            main_actions_done = 0
            pag.click(*C_BTN_MAIN)
            time.sleep(0.5)
            continue

        if in_main:
            # ── Main Phase: usa engine para decidir ────────────────────────────
            action_executed = False

            if gs and bridge and match:
                try:
                    action = bridge.choose_action(gs, opp_gs, match)
                    if action:
                        action_executed = _execute_engine_action(action, hand_cards, board_cards)
                        if action_executed:
                            main_actions_done += 1
                            print(f"E({action[1][0]})", end="", flush=True)
                            # Re-sincroniza estado após ação
                            time.sleep(0.3)
                            state = read_game_state()
                            hand_cards  = state['hand']
                            board_cards = state['board_p2']
                            bridge.sync_hand(gs, hand_cards)
                            bridge.sync_field(gs, board_cards)
                            gs.don_available = state['don_p2_active']
                            continue
                except Exception as e:
                    print(f"[eng:{e}]", end="", flush=True)

            if not action_executed:
                # Sem ação do engine (ou engine indisponível) → ataca e encerra
                if not attacked:
                    attacked = True
                    _try_attack_leader()
                    print("A", end="", flush=True)
                    continue
                # Encerra turno
                in_main    = False
                hand_cards  = []
                board_cards = []
                attacked    = False
                main_actions_done = 0
                pag.click(*C_BTN_MAIN)
                time.sleep(0.5)
                print(".", end="", flush=True)
                continue

        # Fase 0 / botão pre-jogo
        pag.click(*C_BTN_MAIN)
        if _game_phase == 0:
            _game_phase = 1
        time.sleep(0.35)

    # Download log e volta ao menu
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
    # Menu interativo
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
    ap.add_argument("--deck",          default=None, help="Nome do deck (.deck)")
    ap.add_argument("--partidas",      type=int, default=3)
    ap.add_argument("--importar",      action="store_true")
    ap.add_argument("--delay-inicio",  type=int, default=4)
    args = ap.parse_args()

    deck_name = _select_deck(args.deck)
    print(f"\nBot OPTCGSim — deck: {deck_name or '(sem engine)'} | {args.partidas} partidas")
    print(f"Aguardando {args.delay_inicio}s para focar o simulador...")
    time.sleep(args.delay_inicio)

    if not _focus_sim():
        print("AVISO: janela OPTCGSim não encontrada — certifique-se que está aberta no menu principal")

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
