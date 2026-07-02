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


def _is_searcher(c: HandCard) -> bool:
    t = c.card_text.lower()
    return (
        'search your deck' in t
        or ('look at the top' in t and 'add' in t)
        or 'look at up to' in t
    )


def _is_event_counter(c: HandCard) -> bool:
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

def score_hand(
    hand: list[HandCard],
    going_first: bool = True,
    arq: str = 'midrange',
    sq: float = 0.7,
    bomb_code: Optional[str] = None,
) -> int:
    """
    Pontua uma mão de abertura de 5 cartas.
    Retorna score inteiro (quanto maior, melhor).
    Mesma lógica de avaliarMao() no TypeScript.
    """
    mod = _archetype_mod(arq)

    has_t1 = has_t2 = has_t3 = False
    only_cost1 = True
    n_searcher = n_c2k = n_c1k = n_ectr = n_blocker = n_rush = n_bomb = 0
    has_deck_bomb = False

    for c in hand:
        is2k = c.counter == 2000
        if not is2k and c.cost > 1:
            only_cost1 = False
        if not is2k:
            if going_first:
                if c.cost <= 1:                   has_t1 = True
                elif c.cost <= 3:                 has_t2 = True
                elif c.cost <= 5:                 has_t3 = True
            else:
                if c.cost <= 2:                   has_t1 = True
                elif c.cost <= 4:                 has_t2 = True
                elif c.cost <= 6:                 has_t3 = True

        if _is_searcher(c):          n_searcher += 1
        if is2k:                     n_c2k      += 1
        elif c.counter == 1000:      n_c1k      += 1
        if _is_event_counter(c):     n_ectr     += 1
        if _has_kw(c, '[blocker]'):  n_blocker  += 1
        if _has_kw(c, '[rush]'):     n_rush     += 1
        if _is_bomb(c):              n_bomb     += 1
        if bomb_code and c.code == bomb_code:
            has_deck_bomb = True

    eff_t2 = has_t2 or n_searcher >= 1
    eff_t3 = has_t3 or (n_searcher >= 1 and has_t2)

    sv = round(35 * sq)
    score = 0

    # Searcher
    if n_searcher >= 1: score += sv + mod['search']
    if n_searcher >= 2: score += 12 if not going_first else 3
    if n_searcher >= 3: score -= (n_searcher - 2) * 20

    # Curva
    if has_t1: score += 28 + mod['t1']
    if has_t2: score += 25 + mod['t2']
    if has_t3: score += 10
    if has_t1 and has_t2: score += 12
    if has_t1 and eff_t2 and eff_t3: score += 5

    # Counters
    c2k_val = round((20 if not going_first else 16) * mod['c2k'])
    score += min(n_c2k, 2) * c2k_val
    score -= max(0, n_c2k - 2) * 8
    score += min(n_c1k, 2) * 8
    score += min(n_ectr, 1) * 10

    # Blocker / Rush
    score += min(n_blocker, 1) * (12 + mod['blocker'])
    score += min(n_rush, 2)    * (7  + mod['rush'])

    # Bomba
    if has_deck_bomb: score += 6
    if n_bomb >= 2:   score -= round((n_bomb - 1) * 22 * mod['bomb'])

    # Punições
    if not has_t1 and not eff_t2:           score -= round(35 * mod['pen'])
    if not has_t1 and not eff_t2 and not eff_t3: score -= 20

    # Mão toda custo 1 sem gasolina
    cost1_count = sum(1 for c in hand if c.cost == 1 and c.counter != 2000)
    if only_cost1 and cost1_count >= 3:     score -= 15

    # Vida como recurso: mão defensiva demais em deck ofensivo
    n_def = n_c2k + n_c1k + n_ectr
    n_off = (1 if has_t1 else 0) + (1 if has_t2 else 0) + n_rush + n_searcher
    if n_def >= 3 and n_off == 0:           score -= round(25 * mod['pen'])
    elif n_def >= 3 and mod['c2k'] < 1.0:  score -= 12

    return score


# ── Utilitário: converter Card do engine → HandCard ───────────────────────────

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
