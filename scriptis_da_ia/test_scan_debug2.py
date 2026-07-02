"""Debug v2: bboxes ajustados com base na imagem real capturada."""
import time, re, os
import pyautogui as pag
from PIL import ImageGrab, Image, ImageFilter, ImageEnhance, ImageOps
import pytesseract

pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

OUT = r"C:\Users\arthu\AppData\Local\Temp\claude\scan_debug2"
os.makedirs(OUT, exist_ok=True)

# Bboxes ajustados (screen coords 1366×768, preview no lado direito)
# Baseado na imagem: "Jewelry Bonney" + "OP15-105" ficam em:
NAME_BBOX  = (945, 415, 1185, 445)   # nome grande centralizado
CODE_BBOX  = (1150, 448, 1233, 468)  # código pequeno canto inferior direito
COST_BBOX  = (930,  58,  975,  98)   # número de custo (canto superior esq)
POWER_BBOX = (1130, 58, 1230,  95)   # poder (canto superior direito)

HAND_Y = 648
CODE_RE = re.compile(r'([A-Z]{1,3}\d{2}-\d{3}[a-z]?)')

def _preprocess(img: Image.Image, scale: int = 4, binarize: bool = False) -> Image.Image:
    img = img.resize((img.width * scale, img.height * scale), Image.LANCZOS)
    img = img.convert('L')  # grayscale
    img = ImageEnhance.Contrast(img).enhance(3.0)
    if binarize:
        img = img.point(lambda p: 255 if p > 128 else 0)
    img = img.filter(ImageFilter.SHARPEN)
    return img

def _ocr(bbox, config='--psm 7', binarize=False, whitelist=None):
    full = ImageGrab.grab()
    crop = full.crop(bbox)
    proc = _preprocess(crop, scale=4, binarize=binarize)
    cfg = config
    if whitelist:
        cfg += f' -c tessedit_char_whitelist={whitelist}'
    return pytesseract.image_to_string(proc, config=cfg).strip(), crop

print("Aguardando 3s...")
time.sleep(3)

for i, x in enumerate([107, 177, 247, 317, 352]):
    pag.moveTo(x, HAND_Y, duration=0.05)
    time.sleep(1.0)

    # Salva nome e código crop para inspeção visual
    full = ImageGrab.grab()
    full.crop(NAME_BBOX).save(f"{OUT}\\{i}_x{x}_name.png")
    full.crop(CODE_BBOX).save(f"{OUT}\\{i}_x{x}_code.png")
    full.crop(COST_BBOX).save(f"{OUT}\\{i}_x{x}_cost.png")
    full.crop(POWER_BBOX).save(f"{OUT}\\{i}_x{x}_power.png")

    name_txt,  _ = _ocr(NAME_BBOX,  '--psm 7', binarize=False)
    code_txt,  _ = _ocr(CODE_BBOX,  '--psm 8 --oem 1', binarize=True,
                         whitelist='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-')
    cost_txt,  _ = _ocr(COST_BBOX,  '--psm 8', binarize=True,
                         whitelist='0123456789')
    power_txt, _ = _ocr(POWER_BBOX, '--psm 7', binarize=True,
                         whitelist='0123456789+')

    m = CODE_RE.search(code_txt)
    code = m.group(1) if m else None

    print(f"x={x:3d} | nome='{name_txt[:30]}' | code_raw='{code_txt}' | code={code} | custo='{cost_txt}' | poder='{power_txt}'")

print(f"\nImagens em: {OUT}")
