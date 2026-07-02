"""Testa diferentes preprocessamentos no crop do código OP15-105."""
import os
from PIL import Image, ImageFilter, ImageEnhance, ImageOps
import pytesseract

pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

src = r"C:\Users\arthu\AppData\Local\Temp\claude\scan_debug2\3_x317_code.png"
img = Image.open(src)

configs = [
    ('psm7_raw',     img.resize((img.width*4, img.height*4), Image.LANCZOS),
     '--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-'),
    ('psm8_raw',     img.resize((img.width*4, img.height*4), Image.LANCZOS),
     '--psm 8 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-'),
    ('psm7_gray',    img.resize((img.width*4, img.height*4), Image.LANCZOS).convert('L'),
     '--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-'),
    ('psm8_gray',    img.resize((img.width*4, img.height*4), Image.LANCZOS).convert('L'),
     '--psm 8 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-'),
    ('psm7_inv',     ImageOps.invert(img.resize((img.width*4, img.height*4), Image.LANCZOS).convert('L')),
     '--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-'),
    ('psm8_inv',     ImageOps.invert(img.resize((img.width*4, img.height*4), Image.LANCZOS).convert('L')),
     '--psm 8 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-'),
    ('psm13_gray',   img.resize((img.width*6, img.height*6), Image.LANCZOS).convert('L'),
     '--psm 13 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-'),
    ('psm6_nowhite', img.resize((img.width*4, img.height*4), Image.LANCZOS).convert('L'),
     '--psm 6'),
]

for name, proc_img, cfg in configs:
    txt = pytesseract.image_to_string(proc_img, config=cfg).strip().replace('\n', ' ')
    print(f"  {name:20s}: '{txt}'")
