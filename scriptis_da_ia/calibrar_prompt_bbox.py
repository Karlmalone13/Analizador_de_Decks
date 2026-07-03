r"""Calibra OCR do texto de prompt do OPTCGSim.

Uso:
    1. Deixe o simulador aberto exatamente em um prompt.
    2. Rode: python scriptis_da_ia\calibrar_prompt_bbox.py
    3. Veja os PNGs em scriptis_da_ia\_debug_prompt_bbox e o OCR impresso.

Nao joga partida nem clica em nada; apenas captura a tela atual.
"""
from __future__ import annotations

from pathlib import Path
import re

from PIL import ImageDraw, ImageEnhance, ImageFilter, ImageGrab
import pytesseract

pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)

OUT_DIR = Path(__file__).parent / "_debug_prompt_bbox"
OUT_DIR.mkdir(exist_ok=True)

# Candidatos ao painel de texto no lado direito. O primeiro e o valor atual.
CANDIDATES = [
    ("ATUAL", (930, 608, 1275, 682)),   # caixa bege de prompt (Choose/Select)
    ("prompt_wider", (920, 600, 1280, 690)),
    ("prompt_taller", (930, 595, 1275, 695)),
    ("right_lower_full", (910, 500, 1265, 690)),
    ("full_right_text", (900, 380, 1275, 700)),
]


def ocr_crop(img, bbox: tuple[int, int, int, int]) -> str:
    crop = img.crop(bbox)
    crop = crop.resize((crop.width * 3, crop.height * 3))
    crop = crop.convert("L")
    crop = ImageEnhance.Contrast(crop).enhance(2.6)
    crop = crop.filter(ImageFilter.SHARPEN)
    raw = pytesseract.image_to_string(crop, config="--psm 6")
    return re.sub(r"\s+", " ", raw).strip()


def main() -> None:
    full = ImageGrab.grab()
    full.save(OUT_DIR / "full.png")

    overlay = full.copy()
    draw = ImageDraw.Draw(overlay)

    for label, bbox in CANDIDATES:
        crop = full.crop(bbox)
        crop.save(OUT_DIR / f"{label}.png")
        text = ocr_crop(full, bbox)
        draw.rectangle(bbox, outline="red", width=2)
        draw.text((bbox[0], max(0, bbox[1] - 14)), label, fill="red")
        print(f"{label}: {bbox}")
        print(f"  OCR: {text or '<vazio>'}")

    overlay.save(OUT_DIR / "overlay.png")
    print(f"\nArquivos salvos em: {OUT_DIR}")


if __name__ == "__main__":
    main()
