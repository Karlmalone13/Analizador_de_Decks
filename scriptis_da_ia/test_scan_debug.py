"""Debug: hover em x=107, aguarda preview, salva crops para inspecionar."""
import time
import pyautogui as pag
from PIL import ImageGrab, Image, ImageFilter, ImageEnhance
import pytesseract

pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

HAND_Y = 648
OUT = r"C:\Users\arthu\AppData\Local\Temp\claude\scan_debug"

import os; os.makedirs(OUT, exist_ok=True)

print("Aguardando 3s...")
time.sleep(3)

for i, x in enumerate([107, 177, 247, 317]):
    pag.moveTo(x, HAND_Y, duration=0.05)
    time.sleep(0.8)   # espera preview carregar

    # Captura tela inteira e salva
    full = ImageGrab.grab()
    full.save(f"{OUT}\\full_{i}_x{x}.png")

    # Crops específicos
    for label, bbox in [
        ("full_preview", (935, 55, 1235, 485)),
        ("name",         (935, 415, 1235, 475)),
        ("code",         (1060, 455, 1235, 485)),
        ("cost",         (930, 55, 975, 100)),
        ("power",        (1140, 55, 1235, 100)),
    ]:
        crop = full.crop(bbox)
        crop.save(f"{OUT}\\{i}_x{x}_{label}.png")

        # OCR no crop upscalado
        big = crop.resize((crop.width*4, crop.height*4), Image.LANCZOS)
        big = ImageEnhance.Contrast(big).enhance(2.5)
        big = big.filter(ImageFilter.SHARPEN)
        txt = pytesseract.image_to_string(big, config='--psm 7').strip()
        print(f"  x={x} [{label:15s}]: '{txt}'")

print(f"\nImagens salvas em: {OUT}")
