"""
hand_scorer.py — Scoring de mão de abertura em Python
======================================================
Espelho da lógica avaliarMao() do front (src/app/analysis/page.tsx).
Mantido separado para poder ser usado pelo endpoint /hand-stats sem
depender do browser.

Regras de negócio documentadas em _referencias/dicas_gameplay_optcg.md.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


@dataclass
class HandCard:
    """Representação mínima de uma carta para scoring de mão."""
    code: str
    name: str
    cost: int
    card_type: str      # CHARACTER / EVENT / STAGE / LEADER
    counter: int        # 0 / 1000 / 2000
    power: int
    card_text: str = ''
    attribute: str = ''  # inclui [Rush], [Blocker] etc.


# ── Classificacao POR CARTA: vem do PARSER, nao de substring ───────────────
# Achado 07/09, ao calibrar os pesos: `_is_searcher` procurava a substring
# `'look at the top'` e devolvia FALSO pra uma carta cujo texto e "Look at 4
# cards from the top of your deck; reveal up to 1 [Sanji]..." -- e EXATAMENTE
# o bug do bloco 751, que foi corrigido no front e sobreviveu aqui. Efeito
# pratico: num deck de torneio real, `is_searcher` ativava em 0 de 50 cartas,
# e a calibracao dos pesos rodou sobre features mutiladas (o peso do searcher
# aparecia como "sem variacao na amostra").
#
# A fonte certa e `card_analysis_db.json`, o mesmo que `/analyze` ja usa.
_ADB = None


def _adb() -> dict:
    global _ADB
    if _ADB is None:
        import json as _json
        import os as _os
        caminho = _os.path.join(_os.path.dirname(__file__), 'card_analysis_db.json')
        try:
            with open(caminho, encoding='utf-8') as f:
                _ADB = _json.load(f)
        except (OSError, ValueError):
            _ADB = {}
    return _ADB


def _flag(c: HandCard, nome: str) -> Optional[bool]:
    """Flag parseada da carta, ou None se ela nao estiver no analysis_db."""
    e = _adb().get((c.code or '').split('_')[0])
    return bool(e.get(nome)) if e else None


def _is_searcher(c: HandCard) -> bool:
    f = _flag(c, 'is_searcher')
    if f is not None:
        return f
    # Rede de seguranca pra carta fora do analysis_db -- nunca fonte unica.
    t = c.card_text.lower()
    return ('search your deck' in t
            or ('look at' in t and 'top of your deck' in t)
            or 'look at up to' in t)


def _is_event_counter(c: HandCard) -> bool:
    f = _flag(c, 'has_counter_event')
    if f is not None:
        return f
    return c.card_type.upper() == 'EVENT' and c.counter > 0


def _is_bomb(c: HandCard) -> bool:
    return c.cost >= 7 or c.power >= 8000


def _has_kw(c: HandCard, kw: str) -> bool:
    kw = kw.lower()
    return kw in c.card_text.lower() or kw in c.attribute.lower()


# ── Arquétipo ─────────────────────────────────────────────────────────────────

def detect_archetype(deck_cards: list[HandCard]) -> str:
    total = len(deck_cards)
    if total == 0:
        return 'midrange'

    rush_n    = sum(1 for c in deck_cards if _has_kw(c, '[rush]'))
    blocker_n = sum(1 for c in deck_cards if _has_kw(c, '[blocker]'))
    ramp_n    = sum(1 for c in deck_cards if 'don' in c.card_text.lower() and 'add' in c.card_text.lower())

    playable  = [c for c in deck_cards if c.counter != 2000 and c.cost > 0]
    avg_cost  = sum(c.cost for c in playable) / len(playable) if playable else 3.0

    if ramp_n / total >= 0.12:
        return 'ramp'
    if rush_n / total >= 0.28:
        return 'rush'
    if rush_n / total >= 0.14 and avg_cost <= 3.5:
        return 'aggro'
    if blocker_n / total >= 0.18 and avg_cost >= 4.0:
        return 'control'
    if avg_cost >= 4.5:
        return 'control'
    return 'midrange'


def _archetype_mod(arq: str) -> dict:
    mods = {
        'rush':     dict(t1=15, t2=8,  rush=10, blocker=0,  c2k=0.70, search=5,  pen=1.4, bomb=1.3),
        'aggro':    dict(t1=8,  t2=5,  rush=5,  blocker=3,  c2k=0.85, search=3,  pen=1.2, bomb=1.2),
        'control':  dict(t1=-5, t2=3,  rush=0,  blocker=12, c2k=1.30, search=8,  pen=0.7, bomb=0.8),
        'ramp':     dict(t1=0,  t2=5,  rush=0,  blocker=5,  c2k=1.00, search=15, pen=0.8, bomb=0.6),
        'midrange': dict(t1=0,  t2=0,  rush=0,  blocker=0,  c2k=1.00, search=0,  pen=1.0, bomb=1.0),
    }
    return mods.get(arq, mods['midrange'])


def searcher_quality(deck_cards: list[HandCard]) -> float:
    total = sum(1 for c in deck_cards)
    if total == 0:
        return 0.5
    good = sum(1 for c in deck_cards if c.counter != 2000 and c.cost > 0 and c.cost < 8)
    return min(1.0, good / total)


# ── Score principal ────────────────────────────────────────────────────────────

# ── Pesos: MEDIDOS, não escolhidos ─────────────────────────────────────────
# Os números abaixo são só FALLBACK. Os reais vêm de `pesos_mao.json`,
# ajustados por regressão logística sobre partidas simuladas de verdade
# (`calibrar_pesos_mao.py`), ligando mão de abertura -> vitória.
#
# POR QUE MUDOU (07/09): os pesos eram inventados à mão -- 28 pro T1, 25 pro
# T2, 35 pro searcher, 16/20 pro counter... -- e a mesma tabela estava
# DUPLICADA em `avaliarMao()` no TypeScript, com o comentário "Mesma lógica
# de avaliarMao()" como única garantia de que não divergissem. Duas cópias de
# números inventados é o pior dos dois mundos.
PESOS_FALLBACK = {
    'searcher1': 35.0, 'searcher2': 3.0, 'searcher2_indo_depois': 12.0,
    'searcher_excesso': -20.0,
    't1': 28.0, 't2': 25.0, 't3': 10.0, 't1_t2': 12.0, 'curva_completa': 5.0,
    'c2k': 16.0, 'c2k_indo_depois': 20.0, 'c2k_excesso': -8.0,
    'c1k': 8.0, 'evento_counter': 10.0,
    'blocker': 12.0, 'rush': 7.0,
    'bomba_do_deck': 6.0, 'bomba_excesso': -22.0,
    'sem_t1_t2': -35.0, 'sem_nada': -20.0, 'so_custo1': -15.0,
    'defesa_sem_ofensiva': -25.0, 'defesa_demais_aggro': -12.0,
}


def _carrega_pesos() -> dict:
    import json as _json
    import os as _os
    caminho = _os.path.join(_os.path.dirname(__file__), 'pesos_mao.json')
    try:
        with open(caminho, encoding='utf-8') as f:
            dados = _json.load(f)
    except (OSError, ValueError):
        return dict(PESOS_FALLBACK)
    pesos = dict(PESOS_FALLBACK)
    pesos.update({k: float(v) for k, v in (dados.get('pesos') or {}).items()
                  if k in PESOS_FALLBACK})
    return pesos


PESOS = _carrega_pesos()


def extract_features(
    hand: list[HandCard],
    going_first: bool = True,
    sq: float = 0.7,
    bomb_code: Optional[str] = None,
    aggro: bool = False,
) -> dict:
    """
    Traduz uma mão de 5 cartas nas ATIVAÇÕES de cada termo do score.

    Separado de `score_hand` de propósito (07/09): enquanto features e pesos
    estavam no mesmo bloco de `if`s, não havia como ajustar os pesos contra
    dado nenhum -- era preciso reescrever a função. Agora
    `score = soma(feature * peso)`, e `calibrar_pesos_mao.py` ajusta só os
    pesos.
    """
    has_t1 = has_t2 = has_t3 = False
    only_cost1 = True
    n_searcher = n_c2k = n_c1k = n_ectr = n_blocker = n_rush = n_bomb = 0
    has_deck_bomb = False
    cost1_count = 0

    for c in hand:
        is2k = c.counter >= 2000
        if not is2k and c.cost > 1:
            only_cost1 = False
        if not is2k and c.cost == 1:
            cost1_count += 1
        if not is2k:
            if going_first:
                if c.cost <= 1:   has_t1 = True
                elif c.cost <= 3: has_t2 = True
                elif c.cost <= 5: has_t3 = True
            else:
                if c.cost <= 2:   has_t1 = True
                elif c.cost <= 4: has_t2 = True
                elif c.cost <= 6: has_t3 = True

        if _is_searcher(c):         n_searcher += 1
        if is2k:                    n_c2k += 1
        elif c.counter == 1000:     n_c1k += 1
        if _is_event_counter(c):    n_ectr += 1
        if _has_kw(c, '[blocker]'): n_blocker += 1
        if _has_kw(c, '[rush]'):    n_rush += 1
        if _is_bomb(c):             n_bomb += 1
        if bomb_code and c.code == bomb_code:
            has_deck_bomb = True

    eff_t2 = has_t2 or n_searcher >= 1
    eff_t3 = has_t3 or (n_searcher >= 1 and has_t2)
    n_def = n_c2k + n_c1k + n_ectr
    n_off = (1 if has_t1 else 0) + (1 if has_t2 else 0) + n_rush + n_searcher

    return {
        # `sq` entra aqui (e não no peso): buscar num deck raso vale menos,
        # e isso é propriedade do DECK, não do peso global.
        'searcher1': sq if n_searcher >= 1 else 0.0,
        'searcher2': 1.0 if (n_searcher >= 2 and going_first) else 0.0,
        'searcher2_indo_depois': 1.0 if (n_searcher >= 2 and not going_first) else 0.0,
        'searcher_excesso': float(max(0, n_searcher - 2)),
        't1': 1.0 if has_t1 else 0.0,
        't2': 1.0 if has_t2 else 0.0,
        't3': 1.0 if has_t3 else 0.0,
        't1_t2': 1.0 if (has_t1 and has_t2) else 0.0,
        'curva_completa': 1.0 if (has_t1 and eff_t2 and eff_t3) else 0.0,
        'c2k': float(min(n_c2k, 2)) if going_first else 0.0,
        'c2k_indo_depois': float(min(n_c2k, 2)) if not going_first else 0.0,
        'c2k_excesso': float(max(0, n_c2k - 2)),
        'c1k': float(min(n_c1k, 2)),
        'evento_counter': float(min(n_ectr, 1)),
        'blocker': float(min(n_blocker, 1)),
        'rush': float(min(n_rush, 2)),
        'bomba_do_deck': 1.0 if has_deck_bomb else 0.0,
        'bomba_excesso': float(max(0, n_bomb - 1)),
        'sem_t1_t2': 1.0 if (not has_t1 and not eff_t2) else 0.0,
        'sem_nada': 1.0 if (not has_t1 and not eff_t2 and not eff_t3) else 0.0,
        'so_custo1': 1.0 if (only_cost1 and cost1_count >= 3) else 0.0,
        'defesa_sem_ofensiva': 1.0 if (n_def >= 3 and n_off == 0) else 0.0,
        'defesa_demais_aggro': 1.0 if (n_def >= 3 and n_off > 0 and aggro) else 0.0,
    }


def score_hand(
    hand: list[HandCard],
    going_first: bool = True,
    arq: str = 'midrange',
    sq: float = 0.7,
    bomb_code: Optional[str] = None,
    pesos: Optional[dict] = None,
) -> int:
    """
    Pontua uma mão de abertura de 5 cartas (maior = melhor).

    Agora é `soma(feature * peso)` com os pesos vindos de `pesos_mao.json`.
    Os modificadores por arquétipo continuam multiplicando/somando por cima,
    como antes -- eles NÃO foram calibrados (não há amostra por arquétipo que
    sustente isso), e isso está declarado em `calibrar_pesos_mao.py`.
    """
    mod = _archetype_mod(arq)
    w = pesos if pesos is not None else PESOS
    f = extract_features(hand, going_first, sq, bomb_code,
                         aggro=mod['c2k'] < 1.0)

    score = sum(f[k] * w.get(k, 0.0) for k in f)

    # Ajustes por arquétipo (não calibrados -- ver docstring)
    if f['searcher1']:  score += mod['search']
    if f['t1']:         score += mod['t1']
    if f['t2']:         score += mod['t2']
    if f['blocker']:    score += mod['blocker']
    if f['rush']:       score += mod['rush'] * f['rush']
    if f['c2k'] or f['c2k_indo_depois']:
        base = (f['c2k'] * w.get('c2k', 0.0)
                + f['c2k_indo_depois'] * w.get('c2k_indo_depois', 0.0))
        score += base * (mod['c2k'] - 1.0)
    if f['bomba_excesso']:
        score += f['bomba_excesso'] * w.get('bomba_excesso', 0.0) * (mod['bomb'] - 1.0)
    for k in ('sem_t1_t2', 'defesa_sem_ofensiva'):
        if f[k]:
            score += f[k] * w.get(k, 0.0) * (mod['pen'] - 1.0)

    return round(score)


def card_to_handcard(c) -> HandCard:
    """Converte um objeto Card do OPTCGMatch em HandCard para scoring."""
    try:
        cost    = int(c.cost or 0)
        power   = int(c.power or 0)
        counter = int(c.counter or 0)
        ctype   = str(c.card_type or '')
        text    = str(getattr(c, 'effect', '') or getattr(c, 'card_text', '') or '')
        attr    = str(getattr(c, 'attribute', '') or '')
        return HandCard(
            code=str(c.code), name=str(c.name),
            cost=cost, card_type=ctype, counter=counter,
            power=power, card_text=text, attribute=attr,
        )
    except Exception:
        return HandCard(code='?', name='?', cost=0, card_type='CHARACTER',
                        counter=0, power=0)


def deck_to_handcards(cards: list) -> list[HandCard]:
    return [card_to_handcard(c) for c in cards]
