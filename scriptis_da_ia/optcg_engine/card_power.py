"""
optcg_engine/card_power.py
===========================
Cálculo de poder e custo de cartas.

Reimplementação fiel de:
  - CardPower()              linhas 24427–24632 do GameplayLogicScript
  - CalculateBasePowerChanges()
  - GetCardCost()            linhas 27588–27709
  - GetCardOriginalPower()   linha 27476
  - GetCardOriginalCost()    linha 27582

Todas as decisões de lógica foram extraídas diretamente do
Assembly-CSharp.dll v1.40a via dnSpy.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from .enums import CardType, CardCategory, CardColor

if TYPE_CHECKING:
    from .models import LiveCard, PlayerState, GameState


# ===========================================================================
# Helpers internos
# ===========================================================================

def _find_owner(game_state: GameState, card: LiveCard) -> PlayerState | None:
    return game_state.find_card_owner(card)


def _find_opposite(game_state: GameState, ps: PlayerState) -> PlayerState | None:
    for p in game_state.players:
        if p is not ps:
            return p
    return None


def _card_in_deploy(game_state: GameState, card: LiveCard) -> bool:
    owner = _find_owner(game_state, card)
    return owner is not None and card in owner.deploy


def _is_owners_turn(game_state: GameState, card: LiveCard) -> bool:
    owner = _find_owner(game_state, card)
    if owner is None:
        return False
    return game_state.players.index(owner) == game_state.player_turn


# ===========================================================================
# CalculateBasePowerChanges
# ===========================================================================

def calculate_base_power_changes(
    game_state: GameState,
    ps_owner: PlayerState,
    card: LiveCard,
) -> int:
    """
    Calcula a mudança total no BASE POWER de uma carta.

    Lógica exata do C# (CalculateBasePowerChanges):
    1. Se CardV3PassiveFieldPowerChange != -1 → retorna ele (override total)
    2. Senão: soma cardBasePowerChange + cardBasePowerChangeToStart +
              cardBasePowerChangeToOppEnd + cardCombatBasePower +
              CardV3PassiveBasePowerChanges

    O valor -1 no field_base_power_change indica "não ativo".
    """
    lc = card

    # 1. Field override — verifica passivos que definem base power absoluto
    field_override = _get_v3_passive_field_power_change(game_state, ps_owner, card)
    if field_override != -1:
        return field_override

    # 2. Soma incremental
    total = (lc.card_base_power_change +
             lc.card_base_power_change_to_start +
             lc.card_base_power_change_to_opp_end +
             lc.card_combat_base_power)

    # V3 passive base power changes (passive effects do próprio card)
    total += _get_v3_passive_base_power_changes(game_state, ps_owner, card)

    return total


def _get_v3_passive_field_power_change(
    game_state: GameState,
    ps_owner: PlayerState,
    card: LiveCard,
) -> int:
    """
    Retorna o field_base_power_change se algum passivo define o base power
    absoluto da carta. Retorna -1 se nenhum está ativo.
    """
    from .validators import v3_passive_in_effect

    for i, action in enumerate(card.card_def.action_v3s):
        if (action.proc.passive and
                action.steps and
                action.steps[0].effect.field_base_power_change != -1 and
                v3_passive_in_effect(game_state, ps_owner, card, i)):
            return action.steps[0].effect.field_base_power_change

    return -1


def _get_v3_passive_base_power_changes(
    game_state: GameState,
    ps_owner: PlayerState,
    card: LiveCard,
) -> int:
    """
    Soma todos os passivos que modificam o BASE POWER incrementalmente:
    PassivePowerChange, Passive1KPerXTrash, Passive1KPerXEventTrash,
    Passive1KPerXRestedDon, PassivePowerPerUniqueDeploy.
    """
    from .validators import v3_passive_in_effect
    from .enums import CardType

    total = 0
    for i, action in enumerate(card.card_def.action_v3s):
        if not action.proc.passive:
            continue
        if not v3_passive_in_effect(game_state, ps_owner, card, i):
            continue
        ef = action.steps[0].effect if action.steps else None
        if ef is None:
            continue

        if ef.passive_power_change:
            total += ef.passive_power_change

        if ef.passive_1k_per_x_trash and ef.passive_1k_per_x_trash > 0:
            total += (len(ps_owner.trash) // ef.passive_1k_per_x_trash) * 1000

        if ef.passive_1k_per_x_event_trash and ef.passive_1k_per_x_event_trash > 0:
            events = sum(1 for c in ps_owner.trash
                         if c.card_def.card_type == CardType.EVENT)
            total += (events // ef.passive_1k_per_x_event_trash) * 1000

        if ef.passive_1k_per_x_rested_don and ef.passive_1k_per_x_rested_don > 0:
            rested = sum(1 for d in ps_owner.don_cost_area if d.b_tapped)
            total += (rested // ef.passive_1k_per_x_rested_don) * 1000

        if ef.passive_power_per_unique_deploy and ef.passive_power_per_unique_deploy > 0:
            unique_names = {c.card_def.character_name for c in ps_owner.deploy}
            total += len(unique_names) * ef.passive_power_per_unique_deploy

    return total


# ===========================================================================
# CardPower — fórmula principal
# ===========================================================================

def card_power(
    game_state: GameState,
    card: LiveCard,
    b_attacking: bool,
    b_ignore_don: bool = False,
) -> int:
    """
    Calcula o poder total de uma carta.
    Reimplementação de CardPower() — linhas 24427–24632.

    Args:
        game_state:   estado atual da partida
        card:         carta a calcular
        b_attacking:  True se a carta está atacando
        b_ignore_don: True para ignorar don equipado (ex: no cálculo de base)

    Returns:
        Poder total como inteiro.
    """
    lc = card
    ps_owner = _find_owner(game_state, card)
    if ps_owner is None:
        return 0

    # ── Passo 1: poder base + modificadores de tempo ─────────────────────
    power = (lc.card_power +
             lc.card_combat_power +
             lc.card_power_to_start +
             lc.card_power_to_owners_turn_end +
             lc.card_power_to_opp_turn_end)

    # ── Passo 2: mudanças de base power ──────────────────────────────────
    power += calculate_base_power_changes(game_state, ps_owner, card)

    # ── Passo 3: carta não está no campo → retorna aqui ──────────────────
    if not _card_in_deploy(game_state, card) and card not in ps_owner.leader:
        return max(0, power)

    ps_opp = _find_opposite(game_state, ps_owner)
    owners_turn = _is_owners_turn(game_state, card)

    # ── Passo 4: buffs de ataque ──────────────────────────────────────────
    if b_attacking:
        # Buffs legados OnAttack (NameInYourDeploy, NameInYourField)
        power += _get_legacy_on_attack_buffs(game_state, ps_owner, card)

        # Buffs V3 de aliados (deploy + líder)
        for ally in ps_owner.deploy + ps_owner.leader:
            power += _get_v3_field_buffs(game_state, ps_owner, ally, card, attacking=True)
            power += _get_legacy_ally_buffs(game_state, ps_owner, ally, card)

        # Buffs de stage
        power += _get_stage_buffs(game_state, ps_owner, card, attacking=True)

        # Debuffs do oponente
        if ps_opp:
            for ally in ps_opp.deploy + ps_opp.leader:
                power -= _get_v3_field_debuffs(game_state, ps_opp, ally, card)

    else:
        # Defendendo / passivo
        for ally in ps_owner.deploy + ps_owner.leader:
            power += _get_v3_field_buffs(game_state, ps_owner, ally, card, attacking=False)

        if ps_opp:
            for ally in ps_opp.deploy + ps_opp.leader:
                power -= _get_v3_field_debuffs(game_state, ps_opp, ally, card)

        power += _get_stage_buffs(game_state, ps_owner, card, attacking=False)

    # ── Passo 5: stage buffs globais (ambos os lados) ─────────────────────
    for ps in game_state.players:
        for stage_card in ps.stage:
            power += _get_v3_stage_field_buffs(game_state, ps, stage_card, card)

    # ── Passo 6: don equipado ─────────────────────────────────────────────
    if b_attacking and not b_ignore_don:
        power += 1000 * lc.attached_don_count

    # ── Passo 7: buffs de ação legados passivos ───────────────────────────
    power += _get_legacy_passive_action_buffs(game_state, ps_owner, card)

    # ── Passo 8: CardV3PassivePowerChanges ───────────────────────────────
    power += _get_v3_passive_power_changes(game_state, ps_owner, card)

    return max(0, power)


# ===========================================================================
# Helpers de buffs (simplificados — expandir conforme necessário)
# ===========================================================================

def _get_legacy_on_attack_buffs(
    game_state: GameState,
    ps_owner: PlayerState,
    card: LiveCard,
) -> int:
    """Buffs legados ativados no ataque (NameInYourDeploy, NameInYourField)."""
    total = 0
    for ally in ps_owner.deploy + ps_owner.leader:
        for action in ally.card_def.card_actions:
            trigger = action.action_trigger
            effect = action.action_effect
            if not trigger.on_attack:
                continue
            if (trigger.name_in_your_deploy and
                    _name_in_deploy(ps_owner, trigger.name_in_your_deploy)):
                total += effect.buff_power
            if (trigger.name_in_your_field and
                    _name_in_field(ps_owner, trigger.name_in_your_field)):
                total += effect.buff_power
    return total


def _get_v3_field_buffs(
    game_state: GameState,
    ps_owner: PlayerState,
    ally: LiveCard,
    target: LiveCard,
    attacking: bool,
) -> int:
    """
    Buffs V3 de campo: CardV3PassiveFieldBuffs.
    Passivos de aliados que buffam o alvo quando atacando/defendendo.
    """
    from .validators import v3_passive_in_effect

    total = 0
    for i, action in enumerate(ally.card_def.action_v3s):
        if not action.proc.passive:
            continue
        if not v3_passive_in_effect(game_state, ps_owner, ally, i):
            continue
        ef = action.steps[0].effect if action.steps else None
        if ef is None:
            continue
        # BuffPower aplicado a aliados no campo
        if ef.buff_power and _card_matches_target_filter(game_state, target, action.steps[0]):
            total += ef.buff_power
    return total


def _get_v3_field_debuffs(
    game_state: GameState,
    ps_opp: PlayerState,
    ally: LiveCard,
    target: LiveCard,
) -> int:
    """Debuffs V3 do oponente sobre a carta."""
    from .validators import v3_passive_in_effect

    total = 0
    for i, action in enumerate(ally.card_def.action_v3s):
        if not action.proc.passive:
            continue
        if not v3_passive_in_effect(game_state, ps_opp, ally, i):
            continue
        ef = action.steps[0].effect if action.steps else None
        if ef and ef.buff_other < 0:
            total += abs(ef.buff_other)
    return total


def _get_stage_buffs(
    game_state: GameState,
    ps_owner: PlayerState,
    card: LiveCard,
    attacking: bool,
) -> int:
    """Buffs de stage cards."""
    total = 0
    for stage in ps_owner.stage:
        for action in stage.card_def.card_actions:
            trigger = action.action_trigger
            effect = action.action_effect
            if trigger.your_turn and attacking:
                total += effect.buff_power
    return total


def _get_v3_stage_field_buffs(
    game_state: GameState,
    ps: PlayerState,
    stage_card: LiveCard,
    target: LiveCard,
) -> int:
    """V3 stage buffs globais (todos os stages de ambos os lados)."""
    from .validators import v3_passive_in_effect

    total = 0
    ps_target = _find_owner(game_state, target)
    for i, action in enumerate(stage_card.card_def.action_v3s):
        if not action.proc.passive:
            continue
        if not v3_passive_in_effect(game_state, ps, stage_card, i):
            continue
        ef = action.steps[0].effect if action.steps else None
        if ef and ef.buff_power and ps_target is ps:
            total += ef.buff_power
    return total


def _get_legacy_ally_buffs(
    game_state: GameState,
    ps_owner: PlayerState,
    ally: LiveCard,
    target: LiveCard,
) -> int:
    """Buffs legados de aliados (YourTurn, WhileRested, etc.)."""
    total = 0
    owners_turn = _is_owners_turn(game_state, target)
    for action in ally.card_def.card_actions:
        trigger = action.action_trigger
        effect = action.action_effect
        if trigger.passive and trigger.your_turn and owners_turn:
            total += effect.buff_power
    return total


def _get_legacy_passive_action_buffs(
    game_state: GameState,
    ps_owner: PlayerState,
    card: LiveCard,
) -> int:
    """BuffSelf, BuffWhenAttacking, BuffPerHand, etc. — legado."""
    total = 0
    for action in card.card_def.card_actions:
        trigger = action.action_trigger
        effect = action.action_effect
        if trigger.passive:
            if effect.buff_power:
                total += effect.buff_power
    return total


def _get_v3_passive_power_changes(
    game_state: GameState,
    ps_owner: PlayerState,
    card: LiveCard,
) -> int:
    """
    PassivePowerChange, Passive1KPerXTrash, etc. no próprio card.
    Igual a _get_v3_passive_base_power_changes mas para o poder (não base).
    """
    return _get_v3_passive_base_power_changes(game_state, ps_owner, card)


def _card_matches_target_filter(
    game_state: GameState,
    card: LiveCard,
    step,
) -> bool:
    """Verifica se a carta corresponde aos filtros de um ActV3Step (simplificado)."""
    # Implementação completa está em validators.py (CheckCardIsViableTargetV3)
    # Aqui: só verifica tipos/cores como filtro básico
    ef = step.effect
    target_list = step.target
    if not target_list:
        return True
    tgt = target_list[0]
    if tgt.only_types and card.card_def.card_type not in tgt.only_types:
        return False
    if tgt.only_colors:
        if not any(c in card.card_def.card_colors for c in tgt.only_colors):
            return False
    return True


def _name_in_deploy(ps: PlayerState, name: str) -> bool:
    return any(c.card_def.character_name == name or name in c.card_def.extra_names
               for c in ps.deploy + ps.leader)


def _name_in_field(ps: PlayerState, name: str) -> bool:
    return _name_in_deploy(ps, name)


# ===========================================================================
# GetCardOriginalPower
# ===========================================================================

def get_card_original_power(game_state: GameState, card: LiveCard) -> int:
    """
    GetCardOriginalPower() — base power + CalculateBasePowerChanges.
    Usado em verificações de condições (ex: OriginalPowerXOrLess).
    """
    ps_owner = _find_owner(game_state, card)
    if ps_owner is None:
        return card.card_def.card_power
    return (card.card_def.card_power +
            calculate_base_power_changes(game_state, ps_owner, card))


def get_card_original_power_no_base_change(card: LiveCard) -> int:
    """Retorna apenas cardDef.cardPower sem nenhum modificador."""
    return card.card_def.card_power


# ===========================================================================
# GetCardCost — fórmula completa
# ===========================================================================

def get_card_cost(
    game_state: GameState,
    card: LiveCard,
    play_cost: bool = False,
    ignore_cost_changes_of: LiveCard | None = None,
    ignore_field: bool = False,
) -> int:
    """
    Calcula o custo atual de uma carta.
    Reimplementação de GetCardCost() — linhas 27588–27709.

    Args:
        game_state:               estado atual
        card:                     carta a calcular
        play_cost:                True quando é o custo de jogar (ativa Kinemon/Rosinate)
        ignore_cost_changes_of:   ignora mudanças de custo vindas desta carta
        ignore_field:             ignora modificadores de campo

    Returns:
        Custo como inteiro (nunca negativo).
    """
    lc = card
    cd = card.card_def
    ps_owner = _find_owner(game_state, card)

    cost = cd.card_cost + lc.i_cost_change + lc.i_cost_change_to_opp_end

    if ps_owner is None:
        return max(0, cost)

    leader = ps_owner.get_leader()
    kinemon_active = (leader and leader.card_def and
                      leader.b_kinemon_leader_effect and play_cost)
    rosinate_active = (leader and leader.card_def and
                       leader.b_rosinante_leader_effect and play_cost)

    # ── Carta na mão: redutores ───────────────────────────────────────────
    if card in ps_owner.hand:
        # Legado: ReduceCardCosts de aliados no deploy
        for ally in ps_owner.deploy:
            for action in ally.card_def.card_actions:
                trigger = action.action_trigger
                effect = action.action_effect
                if (effect.reduce_card_costs > 0 and
                        ally.attached_don_count >= trigger.don_x):
                    if (_card_matches_type(card, action) and
                            _card_matches_color(card, action)):
                        cost -= effect.reduce_card_costs

        # Legado: ReduceCardCosts de stages
        for stage in ps_owner.stage:
            for action in stage.card_def.card_actions:
                effect = action.action_effect
                if (effect.reduce_card_costs > 0 and
                        _card_matches_type(card, action) and
                        _card_matches_color(card, action) and
                        _card_matches_category(card, action) and
                        cd.card_cost >= action.action_trigger.cost_or_more):
                    cost -= effect.reduce_card_costs

            # V3 stage: AllyHandPlayCostReduce
            if play_cost:
                from .validators import v3_passive_in_effect, temp_check_viable_target
                for i, action in enumerate(stage.card_def.action_v3s):
                    ef = action.steps[0].effect if action.steps else None
                    if (action.proc.passive and
                            ef and ef.ally_hand_play_cost_reduce > 0 and
                            v3_passive_in_effect(game_state, ps_owner, stage, i) and
                            temp_check_viable_target(game_state, stage, i, 0, card, None)):
                        cost -= ef.ally_hand_play_cost_reduce

    # ── Carta no campo: modificadores de custo ────────────────────────────
    if card in ps_owner.deploy and not ignore_field:
        # V3 ally field cost changes
        for source in [ps_owner.get_leader()] + list(ps_owner.stage) + list(ps_owner.deploy):
            if source is None:
                continue
            if source is ignore_cost_changes_of:
                continue
            cost += _get_v3_ally_field_cost_change(game_state, ps_owner, card, source)

        # Oponente no seu turno pode aplicar OpponentFieldCostChange
        if not _is_owners_turn(game_state, card):
            for ps_other in game_state.players:
                if ps_other is ps_owner:
                    continue
                # Legado
                if ps_other.leader:
                    ldr = ps_other.leader[0]
                    for action in ldr.card_def.card_actions:
                        trigger = action.action_trigger
                        effect = action.action_effect
                        if (trigger.your_turn and
                                effect.opponent_field_cost_change != 0 and
                                ldr.attached_don_count >= trigger.don_x):
                            cost += effect.opponent_field_cost_change
                # V3
                for ally in ps_other.deploy:
                    cost += _get_v3_opp_field_cost_change(game_state, ps_other, ally)

    # ── Kinemon: WanoCountry -1 se custo >= 3 ────────────────────────────
    if (kinemon_active and cost >= 3 and
            CardCategory.WANO_COUNTRY in cd.card_categories and
            card in ps_owner.hand):
        cost -= 1

    # ── Rosinate: Trafalgar Law -2 se custo >= 4 ─────────────────────────
    if (rosinate_active and cost >= 4 and
            cd.character_name == "Trafalgar Law" and
            card in ps_owner.hand):
        cost -= 2

    # ── V3 self cost changes ──────────────────────────────────────────────
    cost += _get_v3_cost_changes(game_state, ps_owner, card, ignore_cost_changes_of)

    # ── Usopp cost change: +1 ────────────────────────────────────────────
    if ignore_cost_changes_of is not ps_owner.get_leader():
        _update_usopp_cost_changes(game_state, ps_owner, card)
    if card.b_usopp_cost_change:
        cost += 1

    return max(0, cost)


def _get_v3_cost_changes(
    game_state: GameState,
    ps_owner: PlayerState,
    card: LiveCard,
    ignore_of: LiveCard | None,
) -> int:
    """
    GetCardV3CostChanges() — passivos da própria carta que alteram custo.
    HandCostChange, PassiveCostChange, Passive1CostPerXTrash, Passive2CostPerXTrash.
    """
    from .validators import v3_passive_in_effect

    for i, action in enumerate(card.card_def.action_v3s):
        if not action.proc.passive:
            continue
        ef = action.steps[0].effect if action.steps else None
        if ef is None:
            continue
        if not v3_passive_in_effect(game_state, ps_owner, card, i):
            continue

        if ef.hand_cost_change and card in ps_owner.hand:
            return ef.hand_cost_change
        if ef.passive_cost_change:
            return ef.passive_cost_change
        if ef.passive_1_cost_per_x_trash and ef.passive_1_cost_per_x_trash > 0:
            return len(ps_owner.trash) // ef.passive_1_cost_per_x_trash
        if ef.passive_2_cost_per_x_trash and ef.passive_2_cost_per_x_trash > 0:
            return 2 * (len(ps_owner.trash) // ef.passive_2_cost_per_x_trash)
    return 0


def _get_v3_ally_field_cost_change(
    game_state: GameState,
    ps_owner: PlayerState,
    target: LiveCard,
    source: LiveCard,
) -> int:
    """GetCardV3AllyFieldCostChanges() — aliado modifica custo de carta no campo."""
    from .validators import v3_passive_in_effect, temp_check_viable_target

    for i, action in enumerate(source.card_def.action_v3s):
        ef = action.steps[0].effect if action.steps else None
        if (action.proc.passive and
                ef and ef.ally_field_cost_change != 0 and
                v3_passive_in_effect(game_state, ps_owner, source, i) and
                temp_check_viable_target(game_state, source, i, 0, target, None)):
            return ef.ally_field_cost_change
    return 0


def _get_v3_opp_field_cost_change(
    game_state: GameState,
    ps_opp: PlayerState,
    source: LiveCard,
) -> int:
    """GetCardV3OpponentFieldCostChanges() — oponente modifica custo de cartas no campo."""
    from .validators import v3_passive_in_effect

    for i, action in enumerate(source.card_def.action_v3s):
        ef = action.steps[0].effect if action.steps else None
        if (action.proc.passive and
                ef and ef.opponent_field_cost_change != 0 and
                v3_passive_in_effect(game_state, ps_opp, source, i)):
            return ef.opponent_field_cost_change
    return 0


def _update_usopp_cost_changes(
    game_state: GameState,
    ps_owner: PlayerState,
    card: LiveCard,
) -> None:
    """UpdateUsoppCostChanges() — verifica se o líder Usopp aplica +1 custo."""
    from .validators import temp_check_viable_target

    leader = ps_owner.get_leader()
    if leader is None:
        return

    if not card.b_usopp_cost_change:
        for i, action in enumerate(leader.card_def.action_v3s):
            if (action.proc.usopp_leader and
                    temp_check_viable_target(game_state, leader, i, 0, card, None)):
                card.b_usopp_cost_change = True
                return
    else:
        if card not in ps_owner.deploy:
            card.b_usopp_cost_change = False
            return
        for i, action in enumerate(leader.card_def.action_v3s):
            if (action.proc.usopp_leader and
                    not temp_check_viable_target(game_state, leader, i, 0, card, None)):
                card.b_usopp_cost_change = False
                return


def get_card_original_cost(card: LiveCard) -> int:
    """GetCardOriginalCost() — retorna cardDef.cardCost sem modificadores."""
    return card.card_def.card_cost


# ===========================================================================
# Helpers de match para sistema legado
# ===========================================================================

def _card_matches_type(card: LiveCard, action) -> bool:
    types = getattr(action.action_trigger, 'only_types', [])
    if not types:
        return True
    return card.card_def.card_type in types


def _card_matches_color(card: LiveCard, action) -> bool:
    colors = getattr(action.action_trigger, 'only_colors', [])
    if not colors:
        return True
    return any(c in card.card_def.card_colors for c in colors)


def _card_matches_category(card: LiveCard, action) -> bool:
    cats = getattr(action.action_trigger, 'only_categories', [])
    if not cats:
        return True
    return any(c in card.card_def.card_categories for c in cats)