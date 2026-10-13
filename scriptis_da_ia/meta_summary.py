"""Resumo do meta pros jogadores (pagina /meta do front, 13/10/2026).

Tudo sai dos decks de torneio de `decklists_raw.csv` (limitlesstcg), lidos
pelos mesmos helpers da sugestao de carta (`suggest_card`), e do que cada carta
FAZ segundo o motor (`card_analysis_db.json`) -- nada de leitura de texto.

  * `resumo()`               -> lideres do meta: quantos decks, % do meta,
                                melhor colocacao, perfil de funcoes (mediana)
  * `lider(code)`            -> como aquele lider e montado: cartas centrais
  * `comparar(cards)`        -> o deck do usuario contra a mediana do meta
"""
from __future__ import annotations

from collections import Counter, defaultdict
from statistics import median

import pandas as pd

import suggest_card as sc

PAPEIS_META = ('compra', 'busca', 'counter2k', 'blocker', 'trigger')


def _colocacoes() -> dict:
    df = pd.read_csv(sc.os.path.join(sc.AQUI, 'decklists_raw.csv'), usecols=['deck_url', 'placing'])
    return df.groupby('deck_url')['placing'].min().to_dict()


def _perfil(decks: list[dict]) -> dict:
    return {p: median(sc._papel_conta(d, p) for d in decks) if decks else 0 for p in PAPEIS_META}


def _carta(code: str) -> dict:
    info = sc._db().get(code) or {}
    return {'code': code, 'name': info.get('name'), 'cost': info.get('cost'),
            'color': info.get('color'), 'type': info.get('type'),
            'image': sc._imagens().get(code)}


def resumo() -> dict:
    lideres, torneio = sc._torneio()
    coloc = _colocacoes()
    por_lider = defaultdict(list)
    for url, d in torneio.items():
        if url in lideres:
            por_lider[lideres[url]].append(url)
    total = sum(len(v) for v in por_lider.values())
    out = []
    for code, urls in sorted(por_lider.items(), key=lambda kv: -len(kv[1])):
        decks = [torneio[u] for u in urls]
        out.append({**_carta(code), 'decks': len(urls), 'pct_meta': len(urls) / total,
                    'melhor_colocacao': min(coloc.get(u, 99) for u in urls),
                    'perfil': _perfil(decks)})
    return {'total_decks': total, 'lideres': out,
            'perfil_meta': _perfil(list(torneio.values())),
            'rotulos': {p: sc.PAPEIS[p][0] for p in PAPEIS_META}}


def lider(code: str, n: int = 16) -> dict:
    lideres, torneio = sc._torneio()
    decks = [d for u, d in torneio.items() if lideres.get(u) == code]
    usa, copias = Counter(), defaultdict(list)
    for d in decks:
        for c, q in d.items():
            usa[c] += 1
            copias[c].append(q)
    cartas = [{**_carta(c), 'pct_decks': k / len(decks),
               'copias_media': sum(copias[c]) / len(copias[c])}
              for c, k in usa.most_common(n)] if decks else []
    return {**_carta(code), 'decks': len(decks), 'perfil': _perfil(decks), 'cartas': cartas}


def comparar(cards: list[dict]) -> dict:
    db = sc._db()
    deck = {}
    lider_code = None
    for c in cards:
        code = sc._base(c.get('code', ''))
        if (db.get(code, {}).get('type') or '').upper() == 'LEADER':
            lider_code = code
        else:
            deck[code] = deck.get(code, 0) + int(c.get('qty', 1))
    _, torneio = sc._torneio()
    meta = _perfil(list(torneio.values()))
    return {'lider': lider_code,
            'linhas': [{'papel': p, 'rotulo': sc.PAPEIS[p][0], 'seu': sc._papel_conta(deck, p),
                        'mediana_meta': meta[p]} for p in PAPEIS_META]}
