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
PROMPT_TEXT_BBOXES = [
    (930, 608, 1275, 682),  # caixa bege de prompt (Choose/Select) — fundo-direita
    (930, 490, 1275, 610),  # texto de fase (Blocker Step, Counter Step, Drag to Choose...)
]

# DON e outros counters
DON_P2_HOVER = (495, 634)
DON_P1_HOVER = (865, 100)
OPP_HAND_HOVER = (250, 90)

# Trash P2: pilha de descarte (lado direito do campo P2)
TRASH_P2      = (863, 634)
# Posicoes das cartas visiveis na view de trash (abre sobre a area da mao)
TRASH_VIEW_Y  = 550
TRASH_VIEW_XS = [120, 195, 265, 335, 395]  # ate 5 cartas visiveis
TRASH_ARROW_R = (427, 550)  # seta direita para paginar o trash

def _badge_bbox(hover_x: int, hover_y: int) -> tuple:
    x, y = hover_x, hover_y - 45
    return (x - 25, y - 20, x + 25, y + 20)

# -- Leitura direta do arquivo de log do OPTCGSim --------------------------------
COMBAT_LOG_DIR = Path(r"E:\Games\OnePieceSimulador\Builds_Windows\CombatLogs")

# Regex para parsear codes no formato do arquivo: <link="CODE">CODE</link>
# tambem aceita o formato antigo [CODE] como fallback
_RE_CODE      = re.compile(r'<link="([A-Z]{1,4}\d{2}-\d{3}[a-z]?)">')
_RE_CODE_BARE = re.compile(r'\[([A-Z]{1,4}\d{2}-\d{3}[a-z]?)\]')
_RE_DRAW_N    = re.compile(r'Draw (\d+) Card')
_RE_REST_N    = re.compile(r'Rest (\d+) Don')
_RE_SEND_LIFE = re.compile(r'Send (\d+) Life to Hand')
_RE_HIT       = re.compile(r'hit for (\d+) damage')
# Snapshots de estado emitidos apos cada turno:
# "[NAME] Hand: [CODE1,CODE2,...]" / "Board:" / "Trash:" / "Life: N"
_RE_SNAP_HAND  = re.compile(r'^\[([^\]]+)\] Hand: \[([^\]]*)\]')
_RE_SNAP_BOARD = re.compile(r'^\[([^\]]+)\] Board: \[([^\]]*)\]')
_RE_SNAP_TRASH = re.compile(r'^\[([^\]]+)\] Trash: \[([^\]]*)\]')
_RE_SNAP_LIFE  = re.compile(r'^\[([^\]]+)\] Life: (\d+)')
# Linha "NAME Has Connected" identifica o jogador local
_RE_CONNECTED  = re.compile(r'^([^\s\[]+) Has Connected')

# Estado do arquivo de log (reset a cada partida)
_current_log_file: Path | None = None
_log_file_offset: int = 0
_our_name: str = ""          # ex: "Karlmalone#2854"
_opp_name: str = ""          # ex: "gombomb#2131"
_log_search_after: float = 0.0  # timestamp minimo do arquivo de log a procurar


def _find_current_log() -> Path | None:
    """Retorna o arquivo .log mais recente criado apos _log_search_after."""
    candidates = list(COMBAT_LOG_DIR.glob("AutoSaved/*.log"))
    if not candidates:
        candidates = list(COMBAT_LOG_DIR.glob("*.log"))
    if not candidates:
        return None
    # Filtra arquivos criados antes do reset (partidas anteriores)
    fresh = [p for p in candidates
             if p.stat().st_mtime >= _log_search_after - 5]
    if not fresh:
        fresh = candidates  # fallback: usa o mais recente de qualquer forma
    return max(fresh, key=lambda p: p.stat().st_mtime)


def _detect_names_from_log(path: Path) -> tuple[str, str]:
    """
    Le o cabecalho do arquivo de log para detectar o nome do jogador local
    ('NAME Has Connected') e o nome do oponente (outro [NAME] Leader is).
    Retorna (our_name, opp_name).
    """
    try:
        header = path.read_text(encoding="utf-8", errors="replace")[:4096]
    except OSError:
        return "", ""

    our = ""
    all_leaders: list[str] = []

    for line in header.splitlines():
        m = _RE_CONNECTED.match(line)
        if m:
            our = m.group(1)
        m2 = re.match(r'^\[([^\]]+)\] Leader is ', line)
        if m2:
            n = m2.group(1)
            if n not in all_leaders:
                all_leaders.append(n)

    opp = next((n for n in all_leaders if n != our), "")
    # Se nao achou "Has Connected", usa primeiro lider como nosso
    if not our and all_leaders:
        our = all_leaders[0]
        opp = all_leaders[1] if len(all_leaders) > 1 else ""
    return our, opp


def _reset_log():
    global _current_log_file, _log_file_offset, _our_name, _opp_name, _log_search_after
    _current_log_file  = None
    _log_file_offset   = 0
    _our_name          = ""
    _opp_name          = ""
    _log_search_after  = time.time()  # so aceita arquivos criados daqui em diante


def read_log_delta() -> list[str]:
    """
    Le as linhas novas do arquivo .log do OPTCGSim desde a ultima chamada.
    Ignora linhas de protocolo RZ1 (maquina) e devolve so texto legivel.
    """
    global _current_log_file, _log_file_offset, _our_name, _opp_name

    # Na primeira chamada da partida, encontra o arquivo mais recente
    if _current_log_file is None:
        _current_log_file = _find_current_log()
        if _current_log_file is None:
            return []
        _our_name, _opp_name = _detect_names_from_log(_current_log_file)
        if _our_name:
            print(f"[LOG] arquivo={_current_log_file.name} "
                  f"nos={_our_name} opp={_opp_name}", flush=True)
        # Arquivo novo da partida atual: le desde o inicio
        _log_file_offset = 0
        return []

    # Le apenas os bytes novos desde a ultima chamada
    try:
        size = _current_log_file.stat().st_size
    except OSError:
        return []
    if size <= _log_file_offset:
        return []

    try:
        with _current_log_file.open("rb") as f:
            f.seek(_log_file_offset)
            raw_bytes = f.read(size - _log_file_offset)
    except OSError:
        return []

    _log_file_offset = size
    raw = raw_bytes.decode("utf-8", errors="replace")
    lines = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        # Ignora linhas do protocolo RZ1 (telemetria de maquina)
        if line.startswith("RZ1|"):
            continue
        lines.append(line)
    return lines

def _codes_from_log_line(line: str) -> list[str]:
    """Extrai codigos de carta de uma linha do log (formato link= ou [CODE])."""
    found = _RE_CODE.findall(line)
    if not found:
        found = _RE_CODE_BARE.findall(line)
    return found


def apply_log_delta(gs, opp_gs, lines: list[str]) -> bool:
    """
    Aplica novas linhas do log ao GameState do bot e do oponente.

    Retorna True se a mao do bot mudou (carta sacada/recebida)
    e portanto precisa de rescan parcial da mao.
    """
    needs_hand_rescan = False

    try:
        from optcg_engine.decision_engine import _make_card
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

    def _snap_codes(raw: str) -> list[str]:
        """Parseia lista de codigos de snapshot: 'CODE1,CODE2,...'"""
        return [c.strip() for c in raw.split(',') if c.strip()]

    for line in lines:
        # --- Snapshots completos de estado (emitidos apos cada turno) ----------
        m = _RE_SNAP_HAND.match(line)
        if m:
            name, raw = m.group(1), m.group(2)
            is_snap_ours = (_our_name and name == _our_name) or (
                not _our_name and name not in (_opp_name,))
            codes_list = _snap_codes(raw)
            if is_snap_ours:
                # Sync completo da mao: reconstroi a partir dos codigos
                new_hand = []
                for code in codes_list:
                    card = _get_card(code)
                    if card:
                        # Preserva _sim_x se ja existia na mao
                        old = next((c for c in gs.hand if c.code == code), None)
                        card._sim_x = getattr(old, '_sim_x', 0)
                        new_hand.append(card)
                if new_hand or not codes_list:
                    gs.hand = new_hand
                    needs_hand_rescan = True
            else:
                # Mao do oponente: so contamos (sem posicoes)
                opp_gs.hand = [c for c in (_get_card(c) for c in codes_list) if c]
            continue

        m = _RE_SNAP_BOARD.match(line)
        if m:
            name, raw = m.group(1), m.group(2)
            codes_list = _snap_codes(raw)
            target_gs = gs if (_our_name and name == _our_name) else opp_gs
            new_field = []
            for code in codes_list:
                card = _get_card(code)
                if card:
                    old = next((c for c in target_gs.field_chars if c.code == code), None)
                    card._sim_x = getattr(old, '_sim_x', 0)
                    card._sim_y = getattr(old, '_sim_y', 0)
                    new_field.append(card)
            target_gs.field_chars = new_field
            continue

        m = _RE_SNAP_TRASH.match(line)
        if m:
            name, raw = m.group(1), m.group(2)
            codes_list = _snap_codes(raw)
            target_gs = gs if (_our_name and name == _our_name) else opp_gs
            target_gs.trash = [c for c in (_get_card(c) for c in codes_list) if c]
            continue

        m = _RE_SNAP_LIFE.match(line)
        if m:
            name, n = m.group(1), int(m.group(2))
            target_gs = gs if (_our_name and name == _our_name) else opp_gs
            # Ajusta tamanho da lista de vida sem alterar os objetos existentes
            while len(target_gs.life) > n:
                target_gs.life.pop(0)
            while len(target_gs.life) < n:
                target_gs.life.append(None)
            continue

        # --- Linhas de acao (formato legivel) ----------------------------------
        codes = _codes_from_log_line(line)
        # Detecta de quem e a linha: pelo nome registrado ou fallback texto
        if _our_name:
            is_you = line.startswith(f'[{_our_name}]')
            is_opp = line.startswith(f'[{_opp_name}]') if _opp_name else (
                not is_you and line.startswith('['))
        else:
            is_you = '[You]' in line or line.startswith('You')
            is_opp = '[Opponent]' in line or line.startswith('Opponent')

        # -- Deploy (da mao) ---------------------------------------------------
        # Log.Deploy / Log.ActionDeploy — "Deploy CODE" (da mao)
        # Nota: "from Trash" e "from Deck" sao tratados abaixo separadamente
        if 'Deploy' in line and codes and 'from Trash' not in line and 'from Deck' not in line:
            code = codes[-1]
            if is_you:
                gs.hand = [c for c in gs.hand if c.code != code]
                if not any(c.code == code for c in gs.field_chars):
                    card = _get_card(code)
                    if card:
                        card.rested = False
                        card.just_played = True
                        gs.field_chars.append(card)
            elif is_opp:
                if not any(c.code == code for c in opp_gs.field_chars):
                    card = _get_card(code)
                    if card:
                        card.just_played = True
                        opp_gs.field_chars.append(card)

        # -- Deploy do trash (Log.PlayFromTrash / Log.PlayOtherFromTrash) -----
        elif 'Deploy' in line and codes and 'from Trash' in line:
            code = codes[-1]
            tgs = gs if is_you else (opp_gs if is_opp else None)
            if tgs:
                tgs.trash = [c for c in tgs.trash if c.code != code]
                if not any(c.code == code for c in tgs.field_chars):
                    card = _get_card(code)
                    if card:
                        card.just_played = True
                        tgs.field_chars.append(card)

        # -- Deploy do deck (Log.DeployFromDeck / Log.ActionDeployFromDeck) ---
        elif 'Deploy' in line and codes and 'from Deck' in line:
            code = codes[-1]
            tgs = gs if is_you else (opp_gs if is_opp else None)
            if tgs:
                if not any(c.code == code for c in tgs.field_chars):
                    card = _get_card(code)
                    if card:
                        card.just_played = True
                        tgs.field_chars.append(card)

        # -- Saque de cartas (Draw #N Card — inicio de turno) -----------------
        elif 'Draw' in line and 'Card' in line and 'from' not in line.lower():
            if is_you:
                needs_hand_rescan = True
                gs.turn = max(gs.turn + 1, 2)
                # Novo turno: personagens recém-deployados no turno anterior
                # agora podem atacar (just_played limpo via log também,
                # alem do clear feito no inicio da Main Phase detection).
                for c in gs.field_chars:
                    c.just_played = False
            elif is_opp:
                m = _RE_DRAW_N.search(line)
                opp_gs.hand.extend([None] * int(m.group(1))) if m else None

        # -- Vida para mao (ON PLAY de certas cartas) --------------------------
        elif 'Life to Hand' in line and is_you:
            m = _RE_SEND_LIFE.search(line)
            if m:
                n = int(m.group(1))
                gs.life = gs.life[n:] if len(gs.life) >= n else []
                needs_hand_rescan = True

        # -- Carta retorna para a mao (Log.SelfToHand / Log.OpponentToHand) --
        # "Return $2 to Hand" / "Send $2 to Hand"
        elif 'to Hand' in line and codes and 'Life' not in line:
            code = codes[-1]
            if is_you:
                # Carta nossa voltou para a mao (via efeito)
                gs.field_chars = [c for c in gs.field_chars if c.code != code]
                gs.trash       = [c for c in gs.trash       if c.code != code]
                card = _get_card(code)
                if card and not any(c.code == code for c in gs.hand):
                    gs.hand.append(card)
                needs_hand_rescan = True
            elif is_opp:
                # Carta do oponente voltou para a mao dele
                opp_gs.field_chars = [c for c in opp_gs.field_chars if c.code != code]

        # -- Ganho de DON (Log.DrawDon / Log.ActionDrawDon) -------------------
        elif 'Draw' in line and 'Don' in line and is_you:
            m = re.search(r'Draw (\d+) Don', line)
            if m:
                gs.don_available += int(m.group(1))
                print(f"[DON+{m.group(1)}={gs.don_available}]", end="", flush=True)

        # -- DON ativado no fim do turno (Log.ActionActivateDon) ---------------
        # "$1: Activate #1 Don" — nosso DON volta a ficar disponivel
        elif 'Activate' in line and 'Don' in line and is_you:
            m = re.search(r'Activate (\d+) Don', line)
            if m:
                restored = int(m.group(1))
                gs.don_available += restored
                gs.don_rested    = max(0, gs.don_rested - restored)
                print(f"[DON~{restored}={gs.don_available}]", end="", flush=True)

        # -- DON removido permanentemente (Log.DonMinus) ----------------------
        elif 'Minus' in line and 'Don' in line and is_you:
            m = re.search(r'Minus (\d+) Don', line)
            if m:
                lost = int(m.group(1))
                if gs.don_available >= lost:
                    gs.don_available -= lost
                else:
                    gs.don_rested = max(0, gs.don_rested - (lost - gs.don_available))
                    gs.don_available = 0
                print(f"[DON-perm{lost}={gs.don_available}]", end="", flush=True)

        # -- DON restado por efeito (Log.RestDon) -----------------------------
        elif 'Rest' in line and 'Don' in line and is_you:
            m = _RE_REST_N.search(line)
            if m:
                n = int(m.group(1))
                moved = min(n, gs.don_available)
                gs.don_available -= moved
                gs.don_rested    += moved

        # -- Personagem restado por efeito (Log.SetOtherRest) -----------------
        # "$1: Rest $2" — marca o personagem como rested no campo
        elif 'Rest' in line and codes and 'Don' not in line:
            code = codes[-1]
            tgs = gs if is_you else (opp_gs if is_opp else None)
            if tgs:
                for c in tgs.field_chars:
                    if c.code == code:
                        c.rested = True

        # -- Personagem ativado (Log.SetActive / Log.SetOtherActive) ----------
        # "Set to Active" / "Set $2 to Active"
        elif 'Set' in line and 'Active' in line:
            if codes:
                code = codes[-1]
                tgs = gs if is_you else (opp_gs if is_opp else None)
                if tgs:
                    for c in tgs.field_chars:
                        if c.code == code:
                            c.rested = False
            elif is_you and 'to Active' in line:
                # Refresh geral (sem codigo especifico)
                for c in gs.field_chars:
                    c.rested = False

        # -- Descarte para counter (Log.Counter) ------------------------------
        elif 'Discard' in line and 'Counter' in line and codes:
            code = codes[0]
            if is_you:
                gs.hand = [c for c in gs.hand if c.code != code]
                card = _get_card(code)
                if card and not any(c.code == code for c in gs.trash):
                    gs.trash.append(card)

        # -- Trash de carta (Log.TrashCard / Log.ActionTrashCard) -------------
        # Exclui: "from Trash" (saques do trash), "Remaining" (limpeza de turno)
        # e "Draw" (que podem conter "Trash" no contexto)
        elif ('Trash' in line and codes
              and 'Remaining' not in line
              and 'from Trash' not in line
              and 'Draw' not in line):
            code = codes[0]
            if is_you:
                gs.hand       = [c for c in gs.hand       if c.code != code]
                gs.field_chars = [c for c in gs.field_chars if c.code != code]
                card = _get_card(code)
                if card and not any(c.code == code for c in gs.trash):
                    gs.trash.append(card)
            elif is_opp:
                opp_gs.field_chars = [c for c in opp_gs.field_chars if c.code != code]
                card = _get_card(code)
                if card and not any(c.code == code for c in opp_gs.trash):
                    opp_gs.trash.append(card)

        # -- K.O. / Destroyed -------------------------------------------------
        elif ('K.O.' in line or 'Destroyed' in line) and codes:
            code = codes[-1]
            if is_you:
                card = next((c for c in gs.field_chars if c.code == code), None)
                gs.field_chars = [c for c in gs.field_chars if c.code != code]
                if card and not any(c.code == code for c in gs.trash):
                    gs.trash.append(card)
            elif is_opp:
                card = next((c for c in opp_gs.field_chars if c.code == code), None)
                opp_gs.field_chars = [c for c in opp_gs.field_chars if c.code != code]
                if card and not any(c.code == code for c in opp_gs.trash):
                    opp_gs.trash.append(card)

        # -- Ataque (Log.Attack) — atacante fica rested -----------------------
        elif 'attacking' in line and codes:
            attacker_code = codes[0]
            if is_you:
                for c in gs.field_chars:
                    if c.code == attacker_code:
                        c.rested = True

        # -- Dano na vida (Log.LeaderHit) -------------------------------------
        elif 'hit for' in line:
            m = _RE_HIT.search(line)
            if m:
                dmg = int(m.group(1))
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

_PROMPT_KEYWORDS = re.compile(
    r'\b(choose|select|drag|return|blocker|counter|don|trash|hand|reveal|life|'
    r'cancel|attack|target|character|friendly|opponent|draw|place|rest|add|use|card|action)\b',
    re.IGNORECASE)

def _read_prompt_text() -> str:
    texts = []
    for bbox in PROMPT_TEXT_BBOXES:
        raw = _ocr_crop(bbox, psm=6, scale=3)
        clean = re.sub(r'\s+', ' ', raw).strip()
        # Filtra lixo de OCR: so inclui se tiver pelo menos 1 palavra-chave de prompt
        if clean and _PROMPT_KEYWORDS.search(clean):
            texts.append(clean)
    return " | ".join(texts)

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
    img  = ImageGrab.grab()
    top  = _is_beige(img.getpixel((1220, 578)))
    # Botao main: verifica pixel padrao (1220,643) e tambem centro do botao largo
    # "Return Cards to Deck" que aparece na mesma area mas com cor ligeiramente diferente
    main = (_is_beige(img.getpixel((1220, 643)))
            or _is_beige(img.getpixel((1101, 643)))
            or _is_beige(img.getpixel((1180, 643))))
    return top, main

# Bboxes dos textos dos botoes TOP e MAIN (usado para detectar Trigger step)
_BTN_TOP_TEXT_BBOX  = (990, 562, 1215, 598)
_BTN_MAIN_TEXT_BBOX = (990, 628, 1215, 663)

def _read_button_text(bbox: tuple) -> str:
    """OCR rapido de baixa resolucao do texto de um botao."""
    raw = _ocr_crop(bbox, psm=7, scale=2)
    return raw.strip().lower()

def _is_trigger_step() -> bool:
    """Retorna True se o botao TOP for 'Use Trigger Effect' (Trigger Step)."""
    txt = _read_button_text(_BTN_TOP_TEXT_BBOX)
    return 'trigger' in txt and 'no' not in txt

def _should_use_trigger(gs=None) -> bool:
    """Delega decisao de trigger para sim_bridge (toda logica de carta fica la)."""
    bridge = _get_bridge()
    if not bridge or not gs:
        return True
    name = _read_preview_name()
    db   = _lookup_by_name(name) if name else None
    code = db.get('code') if db else None
    return bridge.resolve_trigger_choice(gs, code)

def _click_detected_button(top: bool, main: bool, prefer_main: bool = True) -> bool:
    """Clica em um botao detectado; retorna False se nao ha botao."""
    if prefer_main and main:
        pag.click(*C_BTN_MAIN)
        return True
    if top:
        pag.click(*C_BTN_TOP)
        return True
    if main:
        pag.click(*C_BTN_MAIN)
        return True
    return False

def _click_activate_button(top: bool, main: bool) -> bool:
    """Clica no botao de acao apos selecionar carta com Activate:Main.
    Detecta botao extra em y~515 para cartas com multiplas opcoes de efeito (ex: Oden)."""
    img = ImageGrab.grab()
    # Botao extra: efeito ativo aparece acima do botao top normal
    if (_is_beige(img.getpixel((1220, 515)))
            or _is_beige(img.getpixel((1101, 515)))):
        pag.click(1101, 515)
        return True
    if top:
        pag.click(*C_BTN_TOP)
        return True
    if main:
        pag.click(*C_BTN_MAIN)
        return True
    return False

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

def _handle_prompts(max_steps: int = 20, gs=None) -> None:
    """Resolve prompts pos-acao clicando Pass/Cancel (C_BTN_MAIN).
    Detecta Trigger Step e decide usar ou nao baseado nos efeitos da carta."""
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
            if _is_trigger_step():
                # Trigger Step: decide se usa ou nao
                if _should_use_trigger(gs):
                    print("T+", end="", flush=True)
                    pag.click(*C_BTN_TOP)   # Use Trigger Effect
                else:
                    print("T-", end="", flush=True)
                    pag.click(*C_BTN_MAIN)  # No Trigger Effect
            else:
                pag.click(*C_BTN_MAIN)  # Pass / No Counter / Skip effect
        else:
            return

def _resolve_post_deploy(gs=None, opp_gs=None, hand_cards: list[dict] | None = None,
                         board_cards: list[dict] | None = None,
                         opp_board_cards: list[dict] | None = None,
                         card_code: str | None = None) -> None:
    """Apos deploy/activate, resolve prompts de 2 botoes e modais On Play/Activate de 1 botao.
    Para quando detecta 3 botoes unicos consecutivos (= End Turn estavel).
    Se `card_code` for informado, usa os steps do on_play para filtrar alvos com precisao."""
    hand_cards = hand_cards or []
    board_cards = board_cards or []
    opp_board_cards = opp_board_cards or []
    # Carrega steps do on_play para guiar selecao de alvos
    bridge = _get_bridge()
    on_play_steps: list[dict] = []
    if card_code and bridge:
        try:
            on_play_steps = bridge.get_card_on_play_steps(card_code)
        except Exception:
            pass
    single_streak = 0
    for _ in range(25):  # 25 para cobrir sequencias longas (Five Elders: DON+trash+5 elders)
        time.sleep(0.3)
        top, main = _scan_buttons()
        if not top and not main:
            break
        if top and main:
            pag.click(*C_BTN_MAIN)   # Pass / No Counter / Skip
            single_streak = 0
            continue
        single_streak += 1
        if single_streak >= 3:
            break  # End Turn estavel; nao clicar
        if _resolve_prompt_with_engine(gs, opp_gs, hand_cards, board_cards,
                                       opp_board_cards, top, main,
                                       on_play_steps=on_play_steps):
            single_streak = 0
            continue
        _click_detected_button(top, main)  # Confirmar modal On Play

def _try_deploy_card(hand_x: int, gs=None, opp_gs=None,
                     hand_cards: list[dict] | None = None,
                     board_cards: list[dict] | None = None,
                     opp_board_cards: list[dict] | None = None,
                     card_code: str | None = None) -> bool:
    pag.click(hand_x, HAND_Y)
    time.sleep(0.45)
    top, main = _scan_buttons()
    if top and main:
        pag.click(*C_BTN_TOP)
        time.sleep(0.45)
        _resolve_post_deploy(gs, opp_gs, hand_cards, board_cards, opp_board_cards,
                             card_code=card_code)
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

def _try_attack_leader(source: tuple = C_P2_LEADER) -> None:
    pag.moveTo(*source, duration=0.12)
    pag.mouseDown()
    time.sleep(0.08)
    pag.moveTo(source[0], C_P1_CHAR_AREA[1], duration=0.18)
    pag.moveTo(*C_P1_LEADER, duration=0.18)
    pag.mouseUp()
    time.sleep(0.5)
    top, main = _scan_buttons()
    if top or main:
        _handle_prompts()

def _try_attack_char(source: tuple, target: tuple) -> None:
    pag.moveTo(*source, duration=0.12)
    pag.mouseDown()
    time.sleep(0.08)
    pag.moveTo(target[0], C_P1_CHAR_AREA[1], duration=0.18)
    pag.moveTo(*target, duration=0.18)
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
    x = getattr(card, '_sim_x', 0)
    y = getattr(card, '_sim_y', 0)
    if x and y:
        pag.click(x, y)
        return True
    for b in board_cards:
        if b.get('code') == code:
            pag.click(b['x'], b['y'])
            return True
    return False

def _visual_pos_for_card(card, board_cards: list[dict]) -> tuple | None:
    """Retorna a posicao visual conhecida de leader, stage ou personagem."""
    if card is None:
        return None
    ctype = getattr(card, 'card_type', '')
    code = getattr(card, 'code', None)
    if ctype == 'LEADER':
        return C_P2_LEADER
    if ctype == 'STAGE':
        return C_P2_STAGE
    x = getattr(card, '_sim_x', 0)
    y = getattr(card, '_sim_y', 0)
    if x and y:
        return (x, y)
    for b in board_cards:
        if b.get('code') == code:
            return (b['x'], b['y'])
    return None

def _visual_pos_for_opp_target(card, opp_board_cards: list[dict]) -> tuple | None:
    """Retorna a posicao visual de um alvo do oponente."""
    if card is None:
        return C_P1_LEADER
    code = getattr(card, 'code', None)
    x = getattr(card, '_sim_x', 0)
    y = getattr(card, '_sim_y', 0)
    if x and y:
        return (x, y)
    for b in opp_board_cards:
        if b.get('code') == code:
            return (b['x'], b['y'])
    return None

def _click_card_by_code(code: str, cards: list[dict]) -> bool:
    for info in cards:
        if info.get('code') == code:
            x = info.get('x', 0)
            y = info.get('y', HAND_Y)
            if x:
                pag.click(x, y)
                return True
    return False

def _click_card_in_trash_view(target_code: str) -> bool:
    """
    Abre a view de trash de P2 e clica na carta com o codigo alvo.
    Pagina com a seta direita ate 3 vezes se nao encontrar na primeira pagina.
    """
    pag.click(*TRASH_P2)
    time.sleep(0.55)
    for _page in range(4):
        for tx in TRASH_VIEW_XS:
            pag.moveTo(tx, TRASH_VIEW_Y, duration=0.04)
            time.sleep(HOVER_WAIT)
            name = _read_preview_name()
            if not name:
                continue
            db = _lookup_by_name(name)
            code = db.get('code') if db else None
            if code and code == target_code:
                pag.click(tx, TRASH_VIEW_Y)
                print(f"[TRASH] clicou {target_code} em x={tx}", flush=True)
                return True
        # Nao encontrou nessa pagina — pagina
        pag.click(*TRASH_ARROW_R)
        time.sleep(0.35)
    # Fallback: clica primeira posicao visivel
    print(f"[TRASH] {target_code} nao encontrado — clicando primeira posicao", flush=True)
    pag.click(TRASH_VIEW_XS[0], TRASH_VIEW_Y)
    return True


def _execute_prompt_intent(intent: dict | None, hand_cards: list[dict],
                           board_cards: list[dict],
                           opp_board_cards: list[dict],
                           top: bool, main: bool) -> bool:
    if not intent:
        return False
    action = intent.get('action')
    if action == 'click_button':
        return _click_detected_button(top, main)
    # Clicar em um DON para pagar custo de Activate:Main (ex: Five Elders)
    if action == 'click_don':
        pag.click(*DON_P2_HOVER)
        time.sleep(0.25)
        return True
    if action != 'click_card':
        return False

    code = intent.get('code', '')
    zone = intent.get('zone', '')
    if zone == 'hand':
        return _click_card_by_code(code, hand_cards)
    if zone == 'own_board':
        return _click_card_by_code(code, board_cards)
    if zone == 'opp_board':
        return _click_card_by_code(code, opp_board_cards)
    if zone == 'trash':
        return _click_card_in_trash_view(code)
    return False

def _resolve_prompt_with_engine(gs, opp_gs, hand_cards: list[dict],
                                board_cards: list[dict],
                                opp_board_cards: list[dict],
                                top: bool, main: bool,
                                on_play_steps: list[dict] | None = None) -> bool:
    bridge = _get_bridge()
    if not bridge or not gs or not opp_gs:
        return False
    prompt_text = _read_prompt_text()
    intent = bridge.resolve_prompt_choice(gs, opp_gs, prompt_text,
                                          steps=on_play_steps or [])
    label  = intent.get('zone', intent.get('action', '?')) if intent else 'None'
    reason = intent.get('reason', '') if intent else ''
    print(f"P[{prompt_text[:35]}->{label}:{reason[:15]}]", end="", flush=True)
    if intent and _execute_prompt_intent(
            intent, hand_cards, board_cards, opp_board_cards, top, main):
        time.sleep(0.35)
        return True
    return False


def _execute_engine_action(action: tuple, hand_cards: list[dict],
                            board_cards: list[dict],
                            opp_board_cards: list[dict],
                            gs=None, opp_gs=None) -> bool:
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
        result = (_try_deploy_card(hand_x, gs, opp_gs, hand_cards,
                                   board_cards, opp_board_cards,
                                   card_code=code)
                  if hand_x else False)
        print(f"[PLAY] _try_deploy_card={result}", flush=True)
        return result

    if action_type == 'attack' and card is not None:
        source = _visual_pos_for_card(card, board_cards)
        if not source:
            return False
        target_type = action[3] if len(action) > 3 else 'leader'
        target_card = action[4] if len(action) > 4 else None
        if target_type == 'leader':
            _try_attack_leader(source)
            return True
        target = _visual_pos_for_opp_target(target_card, opp_board_cards)
        if not target:
            return False
        _try_attack_char(source, target)
        return True

    if action_type == 'activate' and card is not None:
        code = getattr(card, 'code', '?')
        ctype = getattr(card, 'card_type', '')
        # Se campo nao escaneado ainda mas eh leader/stage, posicao e conhecida
        local_board = board_cards
        if not local_board and ctype not in ('LEADER', 'STAGE'):
            local_board = scan_board_p2()
        clicked = _click_card_source(card, local_board)
        print(f"[ACT] code={code} type={ctype} clicked={clicked}", flush=True)
        if not clicked:
            return False
        time.sleep(0.5)
        top, main = _scan_buttons()
        print(f"[ACT] buttons top={top} main={main}", flush=True)
        if not top and not main:
            # Nenhum botao — carta sem activate disponivel ou ja usada
            pag.click(700, 380)  # deseleciona
            return False
        if not _click_activate_button(top, main):
            return False
        time.sleep(0.35)
        _resolve_post_deploy(gs, opp_gs, hand_cards, local_board, opp_board_cards)
        return True

    if action_type == 'attach_don' and card is not None:
        amount = int(action[3]) if len(action) > 3 and isinstance(action[3], int) else 1
        source = DON_P2_HOVER
        target = _visual_pos_for_card(card, board_cards)
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


def _consume_engine_action_locally(action: tuple, current_turn: int | None = None) -> None:
    """Marca no estado local a parte da acao que o OCR do log pode nao ver."""
    if not action or len(action) < 3:
        return
    action_type = action[1]
    card = action[2]
    if action_type == 'attack' and card is not None:
        try:
            card.rested = True
        except Exception:
            pass
    elif action_type == 'activate' and card is not None:
        try:
            from optcg_engine.decision_engine import get_card_effects
            if current_turn is not None:
                card._am_used_turn = current_turn
            am = get_card_effects(card.code).get('activate_main', {})
            costs = am.get('costs', []) if isinstance(am, dict) else []
            if any(c.get('type') in ('rest_self', 'rest_self_and_trash_hand',
                                     'rest_self_and_leader_or_stage')
                   for c in costs if isinstance(c, dict)):
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
    if action_type not in ('activate', 'attack', 'play'):
        return None
    card = action[2]
    code = getattr(card, 'code', '') if card is not None else ''
    x = getattr(card, '_sim_x', 0) if card is not None else 0
    y = getattr(card, '_sim_y', 0) if card is not None else 0
    # play nao usa coordenada (carta sai da mao apos deploy)
    suffix = f"@{x},{y}" if x and y and action_type != 'play' else ""
    return (action_type, f"{code}{suffix}")

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
    opp_board_cards: list[dict] = []  # posicoes visuais do campo P1
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
                pag.click(*C_BTN_MAIN)   # Keep (mao inicial)
                _game_phase = 1
            elif _is_trigger_step():
                # Trigger Step: carta de vida revelada com trigger
                if _should_use_trigger(gs):
                    print("T+", end="", flush=True)
                    pag.click(*C_BTN_TOP)   # Use Trigger Effect
                    time.sleep(0.4)
                    # Resolve prompts do trigger (pode pedir alvo)
                    _resolve_post_deploy(gs, opp_gs, hand_cards,
                                        board_cards, opp_board_cards)
                else:
                    print("T-", end="", flush=True)
                    pag.click(*C_BTN_MAIN)  # No Trigger Effect
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
                # Aplica delta do log acumulado desde o ultimo turno
                if gs and opp_gs:
                    pre_lines = read_log_delta()
                    apply_log_delta(gs, opp_gs, pre_lines)
                # Bug fix: NÃO chamar _reset_log() aqui — zeraria o offset
                # do arquivo de log e faria o bot parar de receber eventos.
                # O log file e unico por partida; o offset continua valido.

                # Fix DON drift: sincroniza DON via OCR hover badge (fonte mais
                # confiavel no inicio da Main Phase, antes de qualquer gasto).
                if gs:
                    don_ocr = _read_don_active(DON_P2_HOVER)
                    if don_ocr > 0 or gs.don_available == 0:
                        gs.don_available = don_ocr
                    print(f"[DON={gs.don_available}]", end="", flush=True)

                # Fix just_played: novo turno = personagens podem atacar.
                if gs:
                    for c in gs.field_chars:
                        c.just_played = False

                # Scan leve: mao + campos para posicoes visuais de clique.
                hand_cards = scan_hand()
                board_cards = scan_board_p2()
                opp_board_cards = scan_opp_board()
                if bridge and gs:
                    bridge.sync_hand(gs, hand_cards)
                    bridge.sync_field(gs, board_cards)
                    bridge.sync_field(opp_gs, opp_board_cards)
                continue

            # Probe falhou -> avanca o botao atual (Draw, Don, End Turn oponente, etc.)
            top2, main2 = _scan_buttons()
            if top2 and main2:
                _handle_prompts(gs=gs)
                continue
            in_main = False
            hand_cards = []
            board_cards = []
            opp_board_cards = []
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
                opp_board_cards = []
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
                            print(f"S({_action_debug_label(action)})", end="", flush=True)
                            if action[1] == 'play':
                                # Remove carta da mao local para engine nao re-propor (loop infinito)
                                skip_card = action[2] if len(action) > 2 else None
                                if skip_card is not None and gs is not None:
                                    skip_code = getattr(skip_card, 'code', '')
                                    gs.hand = [c for c in gs.hand
                                               if c is not skip_card and c.code != skip_code]
                                continue
                            _consume_engine_action_locally(action, getattr(gs, 'turn', None))
                            actions_this_turn = MAX_ACTIONS_PER_TURN
                            continue
                        # Pre-validacao: checa se a acao ainda e executavel
                        # com o estado local atual (DON, posicao, rested)
                        ok, reason = bridge.can_execute_action(action, gs)
                        if not ok:
                            print(f"[PRE-FAIL] {_action_debug_label(action)}: {reason}", flush=True)
                            if action[1] == 'play':
                                # Remove da mao para engine nao re-propor
                                skip_card = action[2] if len(action) > 2 else None
                                if skip_card is not None:
                                    gs.hand = [c for c in gs.hand
                                               if c is not skip_card
                                               and c.code != getattr(skip_card, 'code', '')]
                            elif action[1] == 'attack':
                                _consume_engine_action_locally(action, getattr(gs, 'turn', None))
                                actions_this_turn = MAX_ACTIONS_PER_TURN
                            continue

                        action_executed = _execute_engine_action(
                            action, hand_cards, board_cards, opp_board_cards,
                            gs, opp_gs)
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
                            _consume_engine_action_locally(action, getattr(gs, 'turn', None))
                            # Apos ataque: aguarda e resolve prompts do oponente
                            if action[1] == 'attack':
                                time.sleep(0.8)
                                for _ in range(15):
                                    t2, m2 = _scan_buttons()
                                    if not t2 and not m2:
                                        break
                                    if _resolve_prompt_with_engine(
                                            gs, opp_gs, hand_cards, board_cards,
                                            opp_board_cards, t2, m2):
                                        continue
                                    _click_detected_button(t2, m2)
                                    time.sleep(0.35)
                            # Remove carta jogada de gs.hand e desconta DON imediatamente
                            if gs and action[1] == 'play' and len(action) > 2 and action[2] is not None:
                                played = action[2]
                                cost = getattr(played, 'cost', 0) or 0
                                gs.don_available = max(0, gs.don_available - cost)
                                print(f"[DON-{cost}={gs.don_available}]", end="", flush=True)
                                for i, c in enumerate(gs.hand):
                                    if c is played or c.code == played.code:
                                        gs.hand.pop(i)
                                        break
                                board_cards = scan_board_p2()
                                if bridge:
                                    bridge.sync_field(gs, board_cards)

                            # -- DELTA DO LOG (sem rescan completo) ------------
                            new_lines = read_log_delta()
                            needs_rescan = apply_log_delta(gs, opp_gs, new_lines)

                            if needs_rescan:
                                print("R", end="", flush=True)

                            # Sempre rescaneamos a mao apos play bem-sucedido:
                            # o simulador reposiciona as cartas restantes ao retirar uma,
                            # entao as posicoes x antigas ficam stale e causam F em cascata.
                            hand_cards = scan_hand()
                            if bridge:
                                bridge.sync_hand(gs, hand_cards)
                            continue
                except Exception as e:
                    print(f"[eng:{e}]", end="", flush=True)

            if not action_executed:
                # Play falhou (carta nao encontrada visualmente ou DON insuficiente):
                # registra o codigo na lista de bloqueio e re-chama o engine
                if action and action[1] == 'play' and len(action) > 2 and action[2] is not None:
                    failed_code = getattr(action[2], 'code', '')
                    if failed_code:
                        used_engine_actions.add(('play', failed_code))
                    print(f"F({failed_code})", end="", flush=True)
                    # Rescan mao para garantir posicoes frescas antes da proxima tentativa
                    hand_cards = scan_hand()
                    if bridge:
                        bridge.sync_hand(gs, hand_cards)
                    continue  # engine vai propor proxima melhor acao

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
                opp_board_cards = []
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
