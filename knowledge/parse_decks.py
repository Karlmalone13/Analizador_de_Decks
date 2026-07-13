"""
parse_decks.py — Extrai dados estruturados do HTML cru dos guias oficiais
=========================================================================
Lê knowledge/data/raw/deck_*.html (baixado por crawl_decks.py) e produz:
  - knowledge/data/parsed/deck_<id>.json  — {leader, colors, strategy, decklist}
  - knowledge/decks/<Slug>.deck            — formato do motor (NxCODE), p/ gauntlet

Fonte de verdade das MECÂNICAS continua sendo o card_effects_db; a estratégia
raspada é REFERÊNCIA humana (camada 'official' do PDF), não peso de motor.

Uso:
  python parse_decks.py
"""
from __future__ import annotations
import json
import re
from pathlib import Path

HERE = Path(__file__).parent
RAW = HERE / 'data' / 'raw'
PARSED = HERE / 'data' / 'parsed'
DECKS = HERE / 'decks'
_EFFECTS = HERE.parent / 'scriptis_da_ia' / 'card_effects_db.json'

_CODE = r'(?:OP|ST|EB)\d\d-\d\d\d|P-\d\d\d'


def _load_leaders() -> dict[str, str]:
    """nome-normalizado -> código, só cartas LEADER do banco (resolver líder)."""
    db = json.loads(_EFFECTS.read_text(encoding='utf-8'))
    out = {}
    for code, c in db.items():
        if (c.get('type') or '').upper() == 'LEADER':
            out[_norm(c.get('name', ''))] = code
    return out


def _norm(s: str) -> str:
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def parse_html(html: str, deck_id: str, leaders: dict) -> dict:
    title = (re.findall(r'<title>(.*?)</title>', html, re.S) or [''])[0].strip()
    # "(Red) Portgas.D.Ace − FEATURE｜..." -> cores + nome do líder
    cores = re.findall(r'\(([A-Za-z/]+)\)', title)
    colors = cores[0].split('/') if cores else []
    nome = re.sub(r'\(.*?\)', '', title.split('−')[0].split('|')[0]).strip()

    # estratégia = parágrafos humanos longos (exclui boilerplate do site)
    paras = [re.sub(r'<.*?>', '', p).strip()
             for p in re.findall(r'<p[^>]*>(.*?)</p>', html, re.S)]
    strategy = ' '.join(p for p in paras
                        if len(p) > 60 and 'ONE PIECE CARD GAME website' not in p)

    # decklist: cada <li> tem a imagem da carta + <p class="cards_N">xN</p>
    decklist = []
    for li in re.split(r'<li>', html):
        cm = re.search(r'/images/cardlist/card/(' + _CODE + r')\.png', li)
        qm = re.search(r'cards_\d[^>]*>\s*[x×]\s*(\d)', li)
        if cm and qm:
            decklist.append({'code': cm.group(1), 'qty': int(qm.group(1))})
    # dedup preservando ordem (o code aparece em href+src no mesmo li já tratado)
    total = sum(d['qty'] for d in decklist)

    # líder: código citado na estratégia OU resolvido pelo nome no banco
    lead_code = None
    m = re.search(r'"(' + _CODE + r')\s+' + re.escape(nome[:6]), strategy)
    if m:
        lead_code = m.group(1)
    if not lead_code:
        lead_code = leaders.get(_norm(nome))

    return {
        'id': deck_id,
        'source': f'https://en.onepiece-cardgame.com/feature/deck/deck_{deck_id}.php',
        'leader': {'name': nome, 'code': lead_code, 'colors': colors},
        'strategy': strategy[:2000],
        'decklist': decklist,
        'total_cards': total,
    }


def _slug(name: str, colors: list) -> str:
    base = re.sub(r'[^A-Za-z0-9.]', '', name) or 'Unknown'
    col = ''.join(c[0] for c in colors) if colors else ''
    return f'{base}-{col}' if col else base


def write_deck_file(data: dict):
    """Export .deck (NxCODE, líder primeiro) pro motor — só se líder resolvido."""
    lead = data['leader']['code']
    if not lead or not data['decklist']:
        return None
    DECKS.mkdir(parents=True, exist_ok=True)
    path = DECKS / f"{_slug(data['leader']['name'], data['leader']['colors'])}.deck"
    # o guia oficial exibe o LÍDER na grade (x1) junto das 50 do deck — exclui
    # pra não duplicar (linha do líder + cópia na main list quebraria o motor)
    main = [d for d in data['decklist'] if d['code'] != lead]
    lines = [f'1x{lead}'] + [f"{d['qty']}x{d['code']}" for d in main]
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return path, sum(d['qty'] for d in main)


def main():
    PARSED.mkdir(parents=True, exist_ok=True)
    leaders = _load_leaders()
    raws = sorted(RAW.glob('deck_*.html'))
    ok = semlider = completos = 0
    for raw in raws:
        did = raw.stem.replace('deck_', '')
        data = parse_html(raw.read_text(encoding='utf-8'), did, leaders)
        (PARSED / f'deck_{did}.json').write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
        res = write_deck_file(data)
        if res:
            deckfile, main_n = res
            data['main_deck_cards'] = main_n
            ok += 1
            if main_n == 50:
                completos += 1
        else:
            deckfile, main_n = None, 0
            semlider += 1
        print(f"deck_{did}: {data['leader']['name'][:22]:22s} "
              f"[{'/'.join(data['leader']['colors'])}] "
              f"main={main_n} lider={data['leader']['code']} "
              f"{'-> ' + deckfile.name if deckfile else '(sem .deck)'}")
    print(f"\n{len(raws)} guias parseados | {ok} com .deck | {completos} completos (main=50) "
          f"| {semlider} sem líder resolvido")


if __name__ == '__main__':
    main()
