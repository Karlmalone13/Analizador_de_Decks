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
POR_FRAQUEZA = 4

# papel -> (rotulo, teste sobre o registro do card_analysis_db)
PAPEIS = {
    # draws_ativo: compra so pelo [Trigger] da vida nao conta (mesma flag do 'Draw Power' da tela)
    'compra':   ('Draw Power', lambda c: bool(c.get('draws_ativo')), 'uma carta de compra'),
    'busca':    ('Searcher', lambda c: bool(c.get('is_searcher')), 'um buscador'),
    'blocker':  ('Blocker', lambda c: bool(c.get('is_blocker')), 'um blocker'),
    'counter2k': ('Counter 2000', lambda c: (c.get('counter') or 0) >= 2000, 'um counter de 2000'),
    'trigger':  ('Trigger', lambda c: bool(c.get('has_trigger')), 'uma carta com [Trigger]'),
    # custo <= 2, a mesma conta do tile 'Carta custo <=2 na mao'
    'barata':   ('Jogadas baratas (custo até 2)', lambda c: (c.get('cost') or 0) <= 2, 'uma jogada barata'),
}

# Golden Ratio (nome em `analyze_deck`) -> papel
RATIO_PAPEL = {'counters': 'counter2k', 'searchers': 'busca', 'blockers': 'blocker'}


def _chance(N: int, K: int, n: int) -> float:
    """P(pelo menos 1 de K em n cartas de N) -- hipergeometrica, a mesma
    conta da tela (\"Distribuicao Hipergeometrica\")."""
    from math import comb
    if K <= 0:
        return 0.0
    return 1 - comb(N - K, n) / comb(N, n)


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


def sugerir(cards: list[dict], n: int = 3, benchmarks: dict | None = None,
            ratios: list | None = None) -> dict:
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

    # ── AS FRAQUEZAS QUE A TELA MOSTRA (pedido do usuario, 13/10/2026) ──────
    # A sugestao parte do que o sistema JA aponta na analise, com os mesmos
    # numeros: a chance de ter a peca na mao inicial contra as faixas do meta
    # (`opening_benchmarks`, o "ultimos 25% do meta" da tela) e os Golden
    # Ratios marcados como "baixo".
    N = sum(deck.values()) or 50
    fraquezas = {}   # papel -> (gravidade, texto)
    for metrica, papel, mao in (('draw', 'compra', 5), ('searcher', 'busca', 5),
                                ('counter2k', 'counter2k', 5), ('blocker', 'blocker', 5),
                                ('trigger_vida', 'trigger', 4), ('low2', 'barata', 5)):
        faixa = (benchmarks or {}).get(metrica)
        if not faixa:
            continue
        K = _papel_conta(deck, papel)
        pr = _chance(N, K, mao)
        if pr < faixa['p25']:
            onde = 'na vida (4 cartas)' if metrica == 'trigger_vida' else 'na mão inicial'
            g = (faixa['mediana'] - pr) / max(faixa['mediana'], 1e-9)
            fraquezas[papel] = max(fraquezas.get(papel, (0, '')), (g, (
                f'{PAPEIS[papel][0]} {onde}: {pr:.1%} -- nos últimos 25% do meta '
                f'(mediana {faixa["mediana"]:.1%}; seu deck tem {K}).')))
    for r in ratios or []:
        papel = RATIO_PAPEL.get(r.get('name'))
        if papel and r.get('status') == 'baixo':
            a_, b_ = r.get('ideal') or (0, 0)
            g = (a_ - r.get('count', 0)) / max(a_, 1)
            fraquezas[papel] = max(fraquezas.get(papel, (0, '')), (g, (
                f'Golden Ratio de {PAPEIS[papel][0]}: {r.get("count")} (ideal {a_}-{b_}).')))
    if not fraquezas:
        return {'modo': 'sem_fraqueza', 'grupos': []}

    # De onde vem a carta: dos decks de torneio do PROPRIO lider quando eles
    # existem; senao, das cartas legais nas cores dele, preferindo o tipo do
    # lider e as mais usadas em torneio. Ate POR_FRAQUEZA cartas por fraqueza
    # (pedido do usuario, 14/10/2026: "1 carta so de sugestao" era pouco).
    do_lider = [d for url, d in torneio.items() if lideres.get(url) == lider]
    usa_lider = Counter(code for d in do_lider for code in d)
    com_torneio = len(do_lider) >= MIN_DECKS_LIDER
    nomes_no_deck = {(db.get(c) or {}).get('name') for c in deck}

    def chave(c):
        info = db[c]
        return (-usa_lider[c] if com_torneio else 0,
                -len(_tipos(info) & tipos_l),
                0 if (info.get('type') or '').upper() == 'CHARACTER' else 1,
                -uso_total[c],
                info.get('cost') or 0)

    grupos, usadas = [], set()
    for papel, (_, motivo) in sorted(fraquezas.items(), key=lambda kv: -kv[1][0]):
        teste = PAPEIS[papel][1]
        cands = sorted((c for c in db if c not in deck and c not in usadas and legal(c) and teste(db[c])
                        and db[c].get('name') not in nomes_no_deck), key=chave)
        cartas, nomes = [], set()
        for code in cands:
            info = db[code]
            if info.get('name') in nomes:      # mesma carta em outra impressao
                continue
            porque = [PAPEIS[papel][2].capitalize()]
            mesmo_tipo = sorted(_tipos(info) & tipos_l)
            if mesmo_tipo:
                porque.append(f'do tipo {mesmo_tipo[0].title()}, como o seu líder')
            if com_torneio and usa_lider[code]:
                porque.append(f'em {usa_lider[code]} de {len(do_lider)} decks de torneio deste líder')
            elif uso_total[code]:
                porque.append(f'em {uso_total[code]} decks de torneio')
            cartas.append(carta(code, ', '.join(porque) + '.'))
            nomes.add(info.get('name'))
            usadas.add(code)
            if len(cartas) >= POR_FRAQUEZA:
                break
        if cartas:
            grupos.append({'papel': papel, 'titulo': PAPEIS[papel][0], 'motivo': motivo, 'cartas': cartas})
        if len(grupos) >= n:
            break
    return {'modo': 'torneio_do_lider' if com_torneio else 'papel_em_falta',
            'decks_do_lider': len(do_lider), 'grupos': grupos}


if __name__ == '__main__':
    import sys
    print(json.dumps(sugerir([{'code': a.split('x')[1], 'qty': int(a.split('x')[0])}
                              for a in sys.argv[1:]]), ensure_ascii=False, indent=2))
