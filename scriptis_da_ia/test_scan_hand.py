"""
test_scan_hand.py — testa hover + OCR para mapear a mão no OPTCGSim.
Rode com o jogo aberto na Main Phase (End Turn visível) e a mão visível.

Uso: python test_scan_hand.py
"""
from __future__ import annotations
import time, re
import pyautogui as pag
from PIL import ImageGrab, Image, ImageFilter, ImageEnhance
import pytesseract

pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# Posição do preview (lado direito da tela, resolução 1366×768)
PREVIEW_BBOX  = (935, 55, 1235, 480)   # caixa da imagem da carta
NAME_BBOX     = (935, 415, 1235, 470)  # nome da carta (texto grande)
CODE_BBOX     = (935, 455, 1235, 480)  # código (texto pequeno, ex: EB03-042)
COST_BBOX     = (935, 55, 975, 100)    # custo (número no canto superior esquerdo)
POWER_BBOX    = (1140, 55, 1235, 100)  # poder (número no canto superior direito)

HAND_Y       = 648
HAND_X_START = 107
HAND_X_END   = 410
HAND_STEP    = 35

# Regex para código de carta OPTCG: OP01-001, EB03-042, ST01-001, etc.
CODE_RE = re.compile(r'\b([A-Z]{2,3}\d{2}-\d{3})\b')


def _ocr_region(bbox: tuple, config: str = '--psm 7') -> str:
    img = ImageGrab.grab(bbox=bbox)
    # Upscale + sharpen para OCR mais preciso em texto pequeno
    img = img.resize((img.width * 3, img.height * 3), Image.LANCZOS)
    img = ImageEnhance.Contrast(img).enhance(2.0)
    img = img.filter(ImageFilter.SHARPEN)
    return pytesseract.image_to_string(img, config=config).strip()


def _read_preview() -> dict | None:
    """Lê nome, código e custo do preview aberto no lado direito."""
    name = _ocr_region(NAME_BBOX, '--psm 7')
    code_text = _ocr_region(CODE_BBOX, '--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-')
    cost_text = _ocr_region(COST_BBOX, '--psm 8 -c tessedit_char_whitelist=0123456789')
    power_text = _ocr_region(POWER_BBOX, '--psm 7 -c tessedit_char_whitelist=0123456789+')

    m = CODE_RE.search(code_text)
    code = m.group(1) if m else None

    try:
        cost = int(cost_text) if cost_text.isdigit() else None
    except Exception:
        cost = None

    power_clean = re.sub(r'\D', '', power_text)
    try:
        power = int(power_clean) if power_clean else None
    except Exception:
        power = None

    return {
        'name':  name,
        'code':  code,
        'cost':  cost,
        'power': power,
        'raw_code': code_text,
    }


def scan_hand() -> list[dict]:
    """
    Varre todas as posições da mão com hover.
    Retorna lista de cartas identificadas (sem duplicatas por código).
    """
    print("Aguardando 3s — posicione o jogo na Main Phase...")
    time.sleep(3)

    seen_codes: set[str] = set()
    cards: list[dict] = []
    prev_code: str | None = None
    consecutive_empty = 0

    x = HAND_X_START
    while x <= HAND_X_END + HAND_STEP:
        pag.moveTo(x, HAND_Y, duration=0.05)
        time.sleep(0.5)   # aguarda preview carregar

        info = _read_preview()
        code = info.get('code')

        print(f"  x={x:3d}  código={code or '?':12s}  nome={info['name'][:30]}")

        if code and code not in seen_codes:
            seen_codes.add(code)
            info['x'] = x
            cards.append(info)
            prev_code = code
            consecutive_empty = 0
        elif code == prev_code:
            # Mesma carta — ainda no mesmo pixel, avança mais
            pass
        else:
            consecutive_empty += 1
            if consecutive_empty >= 4:
                break  # fim da mão

        x += HAND_STEP

    return cards


def scan_board_p2() -> list[dict]:
    """Escaneia cartas na Character Area de P2 (posições fixas aproximadas)."""
    # Character area P2 fica em y≈390-480, x≈450-900
    BOARD_POSITIONS = [
        (530, 430), (620, 430), (710, 430), (800, 430), (890, 430),
        (530, 470), (620, 470), (710, 470),
    ]
    print("\nEscaneando campo P2...")
    seen_codes: set[str] = set()
    cards: list[dict] = []

    for (bx, by) in BOARD_POSITIONS:
        pag.moveTo(bx, by, duration=0.05)
        time.sleep(0.5)
        info = _read_preview()
        code = info.get('code')
        print(f"  ({bx},{by})  código={code or '?':12s}  nome={info['name'][:30]}")
        if code and code not in seen_codes:
            seen_codes.add(code)
            info['x'] = bx
            info['y'] = by
            cards.append(info)

    return cards


if __name__ == '__main__':
    hand  = scan_hand()
    board = scan_board_p2()

    print("\n=== MÃO ===")
    for c in hand:
        print(f"  [{c.get('code','?')}] {c.get('name','?')} | custo={c.get('cost')} poder={c.get('power')}")

    print("\n=== CAMPO P2 ===")
    for c in board:
        print(f"  [{c.get('code','?')}] {c.get('name','?')} | custo={c.get('cost')} poder={c.get('power')}")
