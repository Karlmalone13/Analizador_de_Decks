"""
Debug — analisa estrutura HTML do endpoint com winrates
"""
import requests
from bs4 import BeautifulSoup
import re

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'HX-Request': 'true',
}

r = requests.get(
    'https://op-leaderboard.com/api/leaderboard?meta_format=OP15&region=all',
    headers=HEADERS, timeout=10
)

soup = BeautifulSoup(r.text, 'html.parser')

# Mostra todas as linhas de tabela
print('=== LINHAS DA TABELA ===')
for row in soup.select('tr')[:10]:
    print(repr(row.get_text(separator='|', strip=True)))

print('\n=== LINKS COM CÓDIGOS ===')
for a in soup.find_all('a', href=True)[:20]:
    href = a['href']
    text = a.get_text(strip=True)
    if any(c in href for c in ['OP', 'ST', 'EB']):
        print(f'href={href} | text={text}')

print('\n=== IMAGENS COM CÓDIGOS ===')
for img in soup.find_all('img')[:20]:
    src = img.get('src', '') or img.get('data-src', '')
    alt = img.get('alt', '')
    if any(c in src+alt for c in ['OP', 'ST', 'EB']):
        print(f'src={src[:80]} | alt={alt}')

print('\n=== HTML COMPLETO (primeiros 3000 chars) ===')
print(r.text[:3000])