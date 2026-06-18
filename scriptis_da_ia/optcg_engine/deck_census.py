"""
deck_census.py
==============
Censo completo de um deck — a IA conhece as próprias cartas (como o jogador
que montou o deck). Cataloga tudo que é relevante para decisões: contagem por
custo, searchers, rush, blockers, eventos, stages, counters, triggers, banish,
draw power.

Serve:
- Mulligan (avaliar se a mão aproveita os primeiros turnos, se tem trigger demais)
- Perfil de deck (documento pág. 34)
- Leitura do oponente (estimar o que o oponente tem)
"""
from collections import defaultdict


def deck_census(deck) -> dict:
    """
    Percorre as cartas do deck e conta tudo que importa para decisão.
    Recebe a lista de Card do deck (idealmente as 50, antes de comprar).
    """
    total = len(deck)
    by_cost = defaultdict(int)          # quantas cartas de cada custo
    searchers_by_cost = defaultdict(int)
    rush_by_cost = defaultdict(int)
    blockers_by_cost = defaultdict(int)
    events_by_cost = defaultdict(int)
    stages_by_cost = defaultdict(int)

    n_searchers = n_rush = n_blockers = n_events = n_stages = 0
    n_trigger = n_banish = n_double = 0
    n_counter_1000 = n_counter_2000 = 0
    n_draw = 0

    for c in deck:
        cost = getattr(c, 'cost', 0)
        by_cost[cost] += 1

        if getattr(c, 'is_searcher', False):
            n_searchers += 1
            searchers_by_cost[cost] += 1
        if getattr(c, 'has_rush', False):
            n_rush += 1
            rush_by_cost[cost] += 1
        if getattr(c, 'has_blocker', False):
            n_blockers += 1
            blockers_by_cost[cost] += 1
        if getattr(c, 'card_type', '') == 'EVENT':
            n_events += 1
            events_by_cost[cost] += 1
        if getattr(c, 'card_type', '') == 'STAGE':
            n_stages += 1
            stages_by_cost[cost] += 1
        if getattr(c, 'has_trigger', False):
            n_trigger += 1
        if getattr(c, 'has_banish', False):
            n_banish += 1
        if getattr(c, 'has_double_attack', False):
            n_double += 1

        counter = getattr(c, 'counter', 0)
        if counter == 1000:
            n_counter_1000 += 1
        elif counter >= 2000:
            n_counter_2000 += 1

        # draw power: efeito que compra carta
        txt = (getattr(c, 'card_text', '') or '').lower()
        if 'draw' in txt:
            n_draw += 1

    return {
        'total': total,
        'by_cost': dict(by_cost),
        'searchers': {'total': n_searchers, 'by_cost': dict(searchers_by_cost)},
        'rush': {'total': n_rush, 'by_cost': dict(rush_by_cost)},
        'blockers': {'total': n_blockers, 'by_cost': dict(blockers_by_cost)},
        'events': {'total': n_events, 'by_cost': dict(events_by_cost)},
        'stages': {'total': n_stages, 'by_cost': dict(stages_by_cost)},
        'trigger': n_trigger,
        'banish': n_banish,
        'double_attack': n_double,
        'counter_1000': n_counter_1000,
        'counter_2000': n_counter_2000,
        'draw_power': n_draw,
    }


def deck_profile(census: dict) -> dict:
    """
    Classifica o perfil do deck (agressivo / controle / midrange) a partir do
    censo. Limiares calibrados com decks reais do Limitless:

      Agressivo (Red Zoro, Red Sanji):  custo médio ~1.7, ~85% cartas <=2
      Controle  (Enel, Blackbeard):     custo médio ~4.06, ~20% <=2, ~20% >=6
      Midrange: a faixa intermediária

    Retorna {'profile', 'avg_cost', 'pct_cheap', 'pct_heavy', 'reason'}.
    """
    by_cost = census['by_cost']
    total = census['total'] or 1

    soma = sum(custo * qtd for custo, qtd in by_cost.items())
    avg_cost = soma / total
    cheap = sum(qtd for custo, qtd in by_cost.items() if custo <= 2)
    heavy = sum(qtd for custo, qtd in by_cost.items() if custo >= 6)
    pct_cheap = cheap / total
    pct_heavy = heavy / total

    # Sinais de agressividade que reforçam a curva
    n_rush = census['rush']['total']
    n_blockers = census['blockers']['total']

    # Classificação por curva (o separador mais forte nos dados reais)
    if avg_cost <= 2.5 and pct_cheap >= 0.55:
        profile = 'aggressive'
        reason = f'curva baixa (médio {avg_cost:.1f}, {pct_cheap*100:.0f}% custo<=2)'
    elif avg_cost >= 3.5 or pct_heavy >= 0.15:
        profile = 'control'
        reason = f'curva alta (médio {avg_cost:.1f}, {pct_heavy*100:.0f}% custo>=6)'
    else:
        profile = 'midrange'
        reason = f'curva equilibrada (médio {avg_cost:.1f})'

    return {
        'profile': profile,
        'avg_cost': round(avg_cost, 2),
        'pct_cheap': round(pct_cheap, 2),
        'pct_heavy': round(pct_heavy, 2),
        'rush': n_rush,
        'blockers': n_blockers,
        'reason': reason,
    }


if __name__ == '__main__':
    print("Módulo de censo + perfil. Use deck_census(deck) e deck_profile(census).")