"""Carta que falta no deck, e o motivo (pedido do usuario, 13/10/2026).

Dois caminhos, escolhidos pelo DADO disponivel para o lider:

1. **Lider com decks de torneio** (>= MIN_DECKS_LIDER em `decklists_raw.csv`):
   a carta que mais decks de torneio daquele lider usam e o seu nao tem. O
   motivo e o proprio numero ("31 de 40 decks de torneio usam, media 3,6
   copias").
2. **Lider sem decks de torneio** (ex: Krieg OP15-001, zero na base): o PAPEL
   em que o deck mais fica atras da mediana dos 184 decks de torneio
   (compra, busca, blocker, counter 2000, trigger, remocao) e, nele, a carta
   legal nas cores do lider mais usada em torneio -- preferindo as do mesmo
   tipo do lider.

O que cada carta FAZ vem do `card_analysis_db.json` (efeitos parseados pelo
motor), nunca de texto -- a mesma fonte das flags que a tela de analise ja usa.
"""
from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from functools import lru_cache
from statistics import median

import pandas as pd

AQUI = os.path.dirname(os.path.abspath(__file__))
MIN_DECKS_LIDER = 3

# papel -> (rotulo, teste sobre o registro do card_analysis_db)
PAPEIS = {
    # draws_ativo: compra so pelo [Trigger] da vida nao conta (mesma flag do 'Draw Power' da tela)
    'compra':   ('cartas de compra', lambda c: bool(c.get('draws_ativo'))),
    'busca':    ('buscadores', lambda c: bool(c.get('is_searcher'))),
    'blocker':  ('blockers', lambda c: bool(c.get('is_blocker'))),
    'counter2k': ('counters de 2000', lambda c: (c.get('counter') or 0) >= 2000),
    'trigger':  ('cartas com [Trigger]', lambda c: bool(c.get('has_trigger'))),
    'remocao':  ('cartas de remocao (KO/rest/bounce)',
                 lambda c: bool(c.get('is_removal') or c.get('kos') or c.get('bounces'))),
}


def _base(code: str) -> str:
    return (code or '').split('_')[0]


@lru_cache(maxsize=1)
def _db() -> dict:
    with open(os.path.join(AQUI, 'card_analysis_db.json'), encoding='utf-8') as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _torneio() -> tuple[dict, dict]:
    """(lider de cada deck, {deck: {codigo: qtd}}) dos decks de torneio."""
    db = _db()
    df = pd.read_csv(os.path.join(AQUI, 'decklists_raw.csv'))
    decks: dict = defaultdict(dict)
    lider: dict = {}
    for url, code, qty in zip(df['deck_url'], df['card_code'], df['qty']):
        code = _base(str(code))
        info = db.get(code) or {}
        if (info.get('type') or '').upper() == 'LEADER':
            lider[url] = code
        else:
            # limite de 4 copias: a base tem linhas repetidas (media de 4,5 medida)
            decks[url][code] = min(4, decks[url].get(code, 0) + int(qty))
    return lider, dict(decks)


@lru_cache(maxsize=1)
def _imagens() -> dict:
    """Arte de cada carta (a URL que o front ja usa, de `cards_rows.csv`)."""
    df = pd.read_csv(os.path.join(AQUI, 'cards_rows.csv'), usecols=['id', 'card_image'])
    return {str(i): str(u) for i, u in zip(df['id'], df['card_image']) if isinstance(u, str) and u}


def _cores(info: dict) -> set:
    return set((info.get('color') or '').split())


@lru_cache(maxsize=1)
def _vocab_tipos() -> frozenset:
    """Nomes de tipo conhecidos. O banco separa varios tipos com '/' so em parte
    das cartas (126 de 2839); nas outras vem colado ("Krieg Pirates East
    Blue"). O vocabulario sai dos pedacos separados por '/' e dos tipos que
    efeitos citam (`referenced_types`)."""
    v = set()
    for info in _db().values():
        st = info.get('sub_types') or ''
        if '/' in st:
            v.update(t.strip().lower() for t in st.split('/') if t.strip())
        v.update(t.lower() for t in info.get('referenced_types') or [])
    return frozenset(t for t in v if len(t) > 2)


def _tipos(info: dict) -> set:
    st = (info.get('sub_types') or '').lower()
    return {t for t in _vocab_tipos() if t in st}


@lru_cache(maxsize=1)
def _efeitos() -> dict:
    with open(os.path.join(AQUI, 'card_effects_db.json'), encoding='utf-8') as f:
        return json.load(f)


def _checa_lider(lider_code: str):
    """Funcao `code -> bool`: a carta nao tem efeito preso a OUTRO lider.

    Achado do usuario (13/10/2026): Coffin Boat (OP14-039) foi sugerida pro
    Krieg, mas os dois efeitos dela exigem "If your Leader is [Dracule
    Mihawk]". Quem decide se a condicao vale e o MOTOR (`_check_conditions`),
    com o lider deste deck -- so as condicoes sobre o lider (`leader_*`), que
    nao dependem do estado da partida."""
    from simulation_worker import load_deck
    from optcg_engine.decision_engine import EffectExecutor, GameState
    lider = load_deck([{'code': lider_code, 'qty': 1}])[0]
    ee = EffectExecutor(GameState(leader=lider), GameState(leader=lider))
    efs = _efeitos()

    def ok(code: str) -> bool:
        for blk in ((efs.get(code) or {}).get('effects') or {}).values():
            conds = blk.get('conditions') if isinstance(blk, dict) else None
            so_lider = {k: v for k, v in (conds or {}).items() if k.startswith('leader')}
            if so_lider:
                try:
                    if not ee._check_conditions(so_lider, lider):
                        return False
                except Exception:
                    return False
        return True
    return ok


def _papel_conta(deck: dict, papel: str) -> int:
    teste = PAPEIS[papel][1]
    db = _db()
    return sum(q for c, q in deck.items() if teste(db.get(c) or {}))


def sugerir(cards: list[dict], n: int = 3) -> dict:
    """`cards` = [{code, qty}] com o lider. Devolve {modo, sugestoes:[...]}."""
    db = _db()
    lider = None
    deck: dict = {}
    for c in cards:
        code = _base(c.get('code', ''))
        info = db.get(code) or {}
        if (info.get('type') or '').upper() == 'LEADER':
            lider = code
        else:
            deck[code] = deck.get(code, 0) + int(c.get('qty', 1))
    if lider is None:
        return {'modo': None, 'sugestoes': []}
    info_l = db.get(lider) or {}
    cores_l = _cores(info_l)
    tipos_l = _tipos(info_l)

    lideres, torneio = _torneio()
    uso_total = Counter(code for d in torneio.values() for code in d)

    checa_lider = _checa_lider(lider)

    def legal(code: str) -> bool:
        info = db.get(code) or {}
        if (info.get('type') or '').upper() == 'LEADER':
            return False
        cores = _cores(info)
        return bool(cores) and cores <= cores_l and checa_lider(code)

    def carta(code: str, motivo: str, extra: dict | None = None) -> dict:
        info = db.get(code) or {}
        return {'code': code, 'name': info.get('name'), 'cost': info.get('cost'),
                'color': info.get('color'), 'image': _imagens().get(code),
                'motivo': motivo, **(extra or {})}

    # ── 1. o lider tem decks de torneio ──────────────────────────────────────
    do_lider = [d for url, d in torneio.items() if lideres.get(url) == lider]
    if len(do_lider) >= MIN_DECKS_LIDER:
        usa = Counter()
        copias = defaultdict(list)
        for d in do_lider:
            for code, q in d.items():
                usa[code] += 1
                copias[code].append(q)
        out = []
        for code, k in usa.most_common():
            if code in deck or not legal(code):
                continue
            media = sum(copias[code]) / len(copias[code])
            out.append(carta(code, (
                f'{k} de {len(do_lider)} decks de torneio com este lider usam esta carta '
                f'({round(100 * k / len(do_lider))}%), com {media:.1f} copias em media -- '
                f'e o seu deck nao tem nenhuma.'),
                {'decks_que_usam': k, 'decks_do_lider': len(do_lider)}))
            if len(out) >= n:
                break
        return {'modo': 'torneio_do_lider', 'decks_do_lider': len(do_lider), 'sugestoes': out}

    # ── 2. sem decks do lider: o papel mais em falta contra o meta ───────────
    falta = []
    for papel, (rotulo, _) in PAPEIS.items():
        med = median(_papel_conta(d, papel) for d in torneio.values())
        meu = _papel_conta(deck, papel)
        if med > 0 and meu < med:
            falta.append((meu / med, papel, rotulo, meu, med))
    falta.sort()
    out = []
    for _, papel, rotulo, meu, med in falta:
        teste = PAPEIS[papel][1]
        cands = [c for c in db if c not in deck and legal(c) and teste(db[c])]
        cands.sort(key=lambda c: (-len(_tipos(db[c]) & tipos_l), -uso_total[c], db[c].get('cost') or 0))
        for code in cands[:1]:
            info = db[code]
            mesmo_tipo = sorted(_tipos(info) & tipos_l)
            partes = [f'Seu deck tem {meu} {rotulo}; a mediana dos {len(torneio)} decks de torneio tem {med:g}.']
            partes.append(f'{info.get("name")} cobre isso')
            if mesmo_tipo:
                partes[-1] += f', e do tipo {mesmo_tipo[0].title()} como o seu lider'
            if uso_total[code]:
                partes[-1] += f' e aparece em {uso_total[code]} decks de torneio'
            partes[-1] += '.'
            out.append(carta(code, ' '.join(partes), {'papel': papel, 'meu': meu, 'mediana': med}))
        if len(out) >= n:
            break
    return {'modo': 'papel_em_falta', 'sugestoes': out}


if __name__ == '__main__':
    import sys
    print(json.dumps(sugerir([{'code': a.split('x')[1], 'qty': int(a.split('x')[0])}
                              for a in sys.argv[1:]]), ensure_ascii=False, indent=2))
