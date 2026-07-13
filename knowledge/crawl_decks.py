"""
crawl_decks.py — Crawler dos guias oficiais de deck (trilha conhecimento/dados)
==============================================================================
Baixa a página índice de https://en.onepiece-cardgame.com/feature/deck/ ,
descobre todos os `deck_[N].php` e salva o HTML cru de cada um em
knowledge/data/raw/. NÃO parseia (isso é o parse_decks.py) — princípio do
PDF: "nunca mais dependemos do site". Educado: delay entre requests, pula o
que já baixou, User-Agent identificável.

Uso:
  python crawl_decks.py                # baixa tudo que falta
  python crawl_decks.py --limit 3      # só os 3 mais recentes (teste)
  python crawl_decks.py --force        # rebaixa mesmo o que já existe
"""
from __future__ import annotations
import argparse
import re
import time
import urllib.request
from pathlib import Path

BASE = 'https://en.onepiece-cardgame.com/feature/deck/'
RAW_DIR = Path(__file__).parent / 'data' / 'raw'
_UA = 'Mozilla/5.0 (OPTCG deck-analyzer research crawler; contact via repo)'


def _get(url: str, timeout: int = 25) -> str:
    req = urllib.request.Request(url, headers={'User-Agent': _UA})
    return urllib.request.urlopen(req, timeout=timeout).read().decode('utf-8', 'replace')


def discover_deck_ids(index_html: str) -> list[str]:
    """IDs de deck no índice, ordem cronológica reversa (mais novo primeiro)."""
    seen, out = set(), []
    for m in re.findall(r'deck_(\d+)\.php', index_html):
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0, help='0 = todos')
    ap.add_argument('--delay', type=float, default=1.0, help='segundos entre requests')
    ap.add_argument('--force', action='store_true')
    args = ap.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    print(f'[crawler] índice: {BASE}')
    index = _get(BASE)
    (RAW_DIR / '_index.html').write_text(index, encoding='utf-8')
    ids = discover_deck_ids(index)
    if args.limit:
        ids = ids[:args.limit]
    print(f'[crawler] {len(ids)} decks a considerar')

    baixados = pulados = erros = 0
    for i, did in enumerate(ids, 1):
        dest = RAW_DIR / f'deck_{did}.html'
        if dest.exists() and not args.force:
            pulados += 1
            continue
        url = f'{BASE}deck_{did}.php'
        try:
            html = _get(url)
            dest.write_text(html, encoding='utf-8')
            baixados += 1
            print(f'  [{i}/{len(ids)}] deck_{did} ({len(html)} bytes)')
            time.sleep(args.delay)   # educado
        except Exception as e:
            erros += 1
            print(f'  [{i}/{len(ids)}] deck_{did} ERRO: {type(e).__name__} {e}')

    print(f'[crawler] baixados={baixados} pulados={pulados} erros={erros} '
          f'-> {RAW_DIR}')


if __name__ == '__main__':
    main()
