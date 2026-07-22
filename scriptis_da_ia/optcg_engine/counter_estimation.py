"""
counter_estimation.py
=====================
Estimativa probabilística do counter na mão do oponente, para a IA decidir
se vale anexar DON a um ataque.

Combina:
  1. Hipergeométrica — dada uma densidade de counter no deck, qual a chance
     de o oponente ter counter na mão (de N cartas).
  2. Desconto do que já foi visto — counters já gastos / cartas no trash
     reduzem os counters restantes.

NÃO ajusta por cor: os dados mostram densidade de counter ~uniforme entre
cores (63-67%), então ajuste por cor não muda o resultado.

Densidades de DECK competitivo típico (não do pool de cartas):
  - ~30% das cartas têm counter
  - counter 1000 é comum; 2000 é bem mais raro (~1/4 dos de 1000)
"""
from math import comb

# Densidade típica de counter num deck competitivo de 50 cartas
DECK_SIZE = 50
TYPICAL_COUNTER_1000 = 12   # ~12 cartas de counter 1000 num deck
TYPICAL_COUNTER_2000 = 4    # ~4 cartas de counter 2000 num deck


def _hypergeom_at_least_one(pop_size: int, successes: int, draws: int) -> float:
    """
    Probabilidade de tirar PELO MENOS UM 'sucesso' ao sacar `draws` cartas
    de uma população de `pop_size` com `successes` sucessos.
    P(>=1) = 1 - P(0) = 1 - C(pop-succ, draws) / C(pop, draws)
    """
    if draws <= 0 or successes <= 0 or pop_size <= 0:
        return 0.0
    if successes >= pop_size:
        return 1.0
    if draws > pop_size:
        draws = pop_size
    p_zero = comb(pop_size - successes, draws) / comb(pop_size, draws)
    return 1.0 - p_zero


def estimate_opp_counter(
    opp_hand_size: int,
    counters_seen_used: int = 0,
    cards_seen_total: int = 0,
    deck_counter_1000: int | None = None,
    deck_counter_2000: int | None = None,
) -> dict:
    """
    Estima a probabilidade de o oponente ter counter na mão.

    Args:
        opp_hand_size: nº de cartas na mão do oponente (observável)
        counters_seen_used: nº de cartas de counter que o oponente já gastou
                            (descontadas do total estimado)
        cards_seen_total: nº de cartas do oponente já vistas (jogadas+trash),
                          para refinar a estimativa de quantas restam
        deck_counter_1000/2000: contagem REAL de counters na decklist do
                          oponente, quando conhecida (produto sempre informa
                          a lista — mesma premissa do OpponentModel). None =
                          cai na densidade típica de formato (TYPICAL_*).
                          Passe valores JÁ LÍQUIDOS das cópias visíveis
                          (trash/board) e use counters_seen_used=0 nesse
                          caso, pra não descontar duas vezes.

    Returns:
        {
          'p_any_counter': prob de ter >=1 counter (1000 ou 2000) na mão,
          'p_counter_2000': prob de ter >=1 counter 2000 na mão,
          'expected_counter_value': counter esperado (ponderado) que o
                                    oponente pode somar à defesa,
        }
    """
    if opp_hand_size <= 0:
        return {'p_any_counter': 0.0, 'p_counter_2000': 0.0,
                'expected_counter_value': 0}

    # Counters restantes no deck+mão: decklist REAL quando conhecida,
    # senão densidade típica de formato descontando os já usados
    base_1000 = deck_counter_1000 if deck_counter_1000 is not None \
        else TYPICAL_COUNTER_1000
    base_2000 = deck_counter_2000 if deck_counter_2000 is not None \
        else TYPICAL_COUNTER_2000
    rem_1000 = max(0, base_1000 - max(0, counters_seen_used))
    rem_2000 = max(0, base_2000)
    rem_counter_total = rem_1000 + rem_2000

    # População da qual a mão do oponente foi tirada: deck menos o que já saiu
    pop = max(opp_hand_size, DECK_SIZE - max(0, cards_seen_total))

    p_any = _hypergeom_at_least_one(pop, rem_counter_total, opp_hand_size)
    p_2000 = _hypergeom_at_least_one(pop, rem_2000, opp_hand_size)

    # Counter esperado que o oponente provavelmente usa num único bloqueio:
    # pondera o valor mais provável (1000) pela chance de tê-lo.
    # Se tem alta chance de 2000, usa 2000; senão 1000 ponderado.
    if p_2000 >= 0.5:
        expected = 2000
    elif p_any >= 0.5:
        expected = 1000
    else:
        expected = int(round(p_any * 1000))

    return {
        'p_any_counter': round(p_any, 3),
        'p_counter_2000': round(p_2000, 3),
        'expected_counter_value': expected,
    }


# Counter impresso máximo por carta na mão (a maioria é 1000, algumas 2000)
MAX_PRINTED_COUNTER_PER_CARD = 2000
# Boost típico de um evento de counter (varia 1000-4000; usamos um teto plausível)
TYPICAL_COUNTER_EVENT_BOOST = 2000


def max_plausible_defense(
    target_base_power: int,
    opp_hand_size: int,
    opp_active_don: int,
    counters_seen_used: int = 0,
) -> dict:
    """
    Calcula a defesa MÁXIMA REAL de um alvo — o máximo que o oponente consegue
    montar com os recursos que tem AGORA. Sem tetos artificiais: representa o
    pior caso verdadeiro, para a IA decidir com informação honesta.

    Regra do jogo:
      - Counter impresso (cartas da mão) NÃO custa DON. Cada carta pode somar
        até 2000 (counter máximo impresso).
      - Eventos de counter CUSTAM DON. Cada evento (~1 DON) soma até ~2000.
      - O oponente usa cada carta UMA vez: ou como counter impresso, ou jogada
        como evento (não os dois). Então o limite é o nº de cartas na mão.

    Pior caso: todas as cartas da mão contribuem counter. As que ele tem DON
    para jogar como evento somam o boost de evento; o resto soma counter impresso.
    """
    if opp_hand_size <= 0:
        return {'base': target_base_power, 'max_printed_counter': 0,
                'max_event_counter': 0, 'max_defense': target_base_power}

    # Quantas cartas ele consegue jogar como EVENTO de counter (limite: DON)
    n_events = min(opp_active_don, opp_hand_size)
    # As demais cartas podem somar counter IMPRESSO (não custa DON)
    n_printed = opp_hand_size - n_events

    max_event = n_events * TYPICAL_COUNTER_EVENT_BOOST
    max_printed = n_printed * MAX_PRINTED_COUNTER_PER_CARD

    max_defense = target_base_power + max_printed + max_event
    return {
        'base': target_base_power,
        'max_printed_counter': max_printed,
        'max_event_counter': max_event,
        'max_defense': max_defense,
    }


def don_to_guarantee_hit(
    attacker_power: int,
    target_base_power: int,
    opp_hand_size: int,
    opp_active_don: int,
    counters_seen_used: int = 0,
    don_per_attach: int = 1000,
) -> dict:
    """
    Quantos DON anexar para GARANTIR que o ataque acerta o alvo, mesmo contra
    o counter máximo plausível do oponente.

    Regra do jogo: ataque ACERTA se poder_ataque >= poder_defesa (igualar já
    vence). Então preciso que (attacker_power + DON*1000) >= max_defense.

    Returns:
        {
          'max_defense': defesa máxima plausível do alvo,
          'don_needed': DON para garantir o acerto (0 se já garante),
          'guaranteed_without_don': True se o ataque já passa sem DON,
        }
    """
    defense = max_plausible_defense(
        target_base_power, opp_hand_size, opp_active_don, counters_seen_used
    )
    max_def = defense['max_defense']

    if attacker_power >= max_def:
        return {'max_defense': max_def, 'don_needed': 0,
                'guaranteed_without_don': True}

    gap = max_def - attacker_power
    don_needed = (gap + don_per_attach - 1) // don_per_attach  # arredonda p/ cima
    return {'max_defense': max_def, 'don_needed': don_needed,
            'guaranteed_without_don': False}


# ── Peso de ameaça de uma carta (quão custosa é se ficar viva) ─────────────
# Ordem de perigo validada: double_attack e active_main no topo, depois banish,
# when_attacking/on_ko médio, gatilho médio, poder base.
def threat_weight(card) -> int:
    """
    Quão perigosa é uma carta do oponente SE continuar viva e me atacar.
    Não é 'quão boa' — é 'quão custosa para mim'. Quanto maior, mais vale
    gastar DON para garantir a destruição.
    """
    w = 0
    # poder base (ataca mais forte = mais ameaça)
    w += getattr(card, 'power', 0) // 1000
    # double attack: dobra a pressão — o mais perigoso
    if getattr(card, 'has_double_attack', False):
        w += 6
    # active main: engine repetível todo turno
    if getattr(card, 'has_activate_main', False) or getattr(card, 'has_active_main', False):
        w += 6
    # banish: remoção pior (manda pro fundo do deck, não pro trash)
    if getattr(card, 'has_banish', False):
        w += 4
    # when attacking / on ko: efeito ao atacar ou ao morrer
    if getattr(card, 'has_when_attacking', False):
        w += 3
    if getattr(card, 'has_on_ko', False):
        w += 3
    # gatilho: risco quando vira dano
    if getattr(card, 'has_trigger', False):
        w += 2
    # blocker: protege o oponente (vale remover)
    if getattr(card, 'has_blocker', False):
        w += 3
    return w


# Limiar de peso a partir do qual vale GARANTIR a destruição (gastar DON extra)
THREAT_WORTH_GUARANTEEING = 8


def decide_don_for_attack(
    attacker_power: int,
    target_base_power: int,
    objective: str,            # 'pressure' | 'destroy' | 'lethal'
    opp_hand_size: int,
    opp_active_don: int,
    don_available: int,
    target_threat: int = 0,    # peso de ameaça do alvo (para 'destroy')
    counters_seen_used: int = 0,
) -> dict:
    """
    Tijolo 1a: decide quantos DON anexar a UM ataque.

    objective:
      - 'lethal'   : este ataque pode matar — garante contra a defesa máxima
      - 'destroy'  : quero remover um personagem — garante SE o peso justificar
      - 'pressure' : quero forçar o oponente a gastar 1-2 cartas (não garante)
    """
    est = estimate_opp_counter(opp_hand_size, counters_seen_used,
                               cards_seen_total=0)
    expected_counter = est['expected_counter_value']

    # defesa provável (não a máxima): base + counter esperado
    likely_defense = target_base_power + expected_counter

    if objective == 'lethal':
        # garante contra a defesa MÁXIMA (ele defende com tudo para não morrer)
        guar = don_to_guarantee_hit(attacker_power, target_base_power,
                                    opp_hand_size, opp_active_don, counters_seen_used)
        don = min(guar['don_needed'], don_available)
        return {'don': don, 'mode': 'lethal-guarantee',
                'reason': f'lethal: garantir contra defesa máx {guar["max_defense"]}'}

    if objective == 'destroy':
        # só vale garantir se a ameaça do alvo justificar
        if target_threat >= THREAT_WORTH_GUARANTEEING:
            guar = don_to_guarantee_hit(attacker_power, target_base_power,
                                        opp_hand_size, opp_active_don, counters_seen_used)
            don = min(guar['don_needed'], don_available)
            return {'don': don, 'mode': 'destroy-guarantee',
                    'reason': f'alvo ameaçador (peso {target_threat}): garantir destruição'}
        # ameaça baixa: trata como pressão (não vale gastar DON garantindo)
        objective = 'pressure'

    # PRESSÃO: anexa para forçar o oponente a gastar >= 1 counter.
    # Mira superar (base + 1 counter esperado), forçando-o a usar 2 cartas
    # ou deixar passar. Não despeja DON — usa o mínimo para criar a ameaça.
    if attacker_power >= likely_defense:
        # já força decisão difícil sem DON extra
        return {'don': 0, 'mode': 'pressure',
                'reason': 'já força o oponente a gastar counter sem DON extra'}
    gap = likely_defense - attacker_power
    don_needed = (gap + 999) // 1000
    don = min(don_needed, don_available)
    return {'don': don, 'mode': 'pressure',
            'reason': f'pressão: forçar gasto de counter (alvo provável {likely_defense})'}


if __name__ == '__main__':
    print('=== CASOS EXTREMOS (teste que importa) ===')
    print()
    print('Extremo 1: ataco 15k na vida, oponente 6 cartas + 5 DON (defesa máxima):')
    r = don_to_guarantee_hit(15000, 0, opp_hand_size=6, opp_active_don=5)
    print(f'   defesa máx={r["max_defense"]}, DON p/ garantir={r["don_needed"]}, já passa={r["guaranteed_without_don"]}')
    print()
    print('Extremo 2: ataco 15k, oponente MÃO VAZIA (não pode defender):')
    r = don_to_guarantee_hit(15000, 0, opp_hand_size=0, opp_active_don=0)
    print(f'   defesa máx={r["max_defense"]}, DON p/ garantir={r["don_needed"]}, já passa={r["guaranteed_without_don"]}')
    print()
    print('Extremo 3: ataco 5k, oponente mão vazia:')
    r = don_to_guarantee_hit(5000, 0, opp_hand_size=0, opp_active_don=0)
    print(f'   defesa máx={r["max_defense"]}, DON p/ garantir={r["don_needed"]}, já passa={r["guaranteed_without_don"]}')
    print()
    print('=== CASO DO USUÁRIO (1 carta, 0 DON) ===')
    r = don_to_guarantee_hit(5000, 5000, opp_hand_size=1, opp_active_don=0)
    print(f'   Eu 5k vs alvo 5k: defesa máx={r["max_defense"]}, DON p/ garantir={r["don_needed"]}')
    print()
    print('=== CASOS NORMAIS (ficam entre os extremos) ===')
    r = don_to_guarantee_hit(5000, 5000, opp_hand_size=3, opp_active_don=1)
    print(f'   Eu 5k vs alvo 5k, opp 3 cartas 1 DON: defesa máx={r["max_defense"]}, DON={r["don_needed"]}')
    r = don_to_guarantee_hit(6000, 4000, opp_hand_size=2, opp_active_don=0)
    print(f'   Eu 6k vs alvo 4k, opp 2 cartas 0 DON: defesa máx={r["max_defense"]}, DON={r["don_needed"]}')
    print()
    print('=== DECISÃO 1a — quanto DON num ataque ===')
    print('Pressão na vida (5k), opp 3 cartas 1 DON, tenho 6 DON:')
    print('  ', decide_don_for_attack(5000, 0, 'pressure', 3, 1, 6))
    print('Destruir personagem AMEAÇADOR (peso 10), alvo 5k, opp 2 cartas:')
    print('  ', decide_don_for_attack(5000, 5000, 'destroy', 2, 0, 6, target_threat=10))
    print('Destruir personagem FRACO (peso 3), alvo 5k, opp 2 cartas:')
    print('  ', decide_don_for_attack(5000, 5000, 'destroy', 2, 0, 6, target_threat=3))
    print('Ataque LETHAL (vida), opp 1 carta 0 DON, tenho 4 DON:')
    print('  ', decide_don_for_attack(5000, 0, 'lethal', 1, 0, 4))