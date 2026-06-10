import requests
from bs4 import BeautifulSoup
import re

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

r = requests.get('https://onepiece.limitlesstcg.com/decks/list/6272', headers=HEADERS)
soup = BeautifulSoup(r.text, 'html.parser')
lines = [l.strip() for l in soup.get_text().split('\n') if l.strip()]

print('=== Primeiras 60 linhas da página ===')
for i, line in enumerate(lines[:60]):
    print(f'{i:3}: {line}')