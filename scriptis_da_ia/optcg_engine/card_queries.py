"""
optcg_engine/card_queries.py
=============================
Queries de estado de carta — verificações de keywords e imunidades.

Reimplementação de:
  - CardHasBlocker()                     linhas 12111–12173
  - CardHasRush() / CardHasRushLeader()  linhas 7821–7861
  - CardHasDoubleAttack()                linhas 25013–25050
  - CardHasBanish()                      linhas 25053–25077
  - CardIsImmuneToAll()                  linha 12922
  - CardIsImmuneToNoncombat()            linhas 12834–12864
  - CardIsCombatImmune()                 linha 12915
  - CardCantBeRemovedFromFieldViaOpponentEffects()  linhas 12770–12810
  - CardCantAttack()                     linhas 7913–7936

Fonte: Assembly-CSharp.dll v1.40a via dnSpy.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from .enums import CardType, CardCategory

if TYPE_CHECKING:
    from .models import LiveCard, PlayerState, GameState


def _owner(gs: GameState, card: LiveCard) -> PlayerState | None:
    return gs.find_card_owner(card)


def _opposite(gs: GameState, ps: PlayerState) -> PlayerState | None:
    for p in gs.players:
        if p is not ps:
            return p
    return None


def _owners_turn(gs: GameState, card: LiveCard) -> bool:
    ps = _owner(gs, card)
    if ps is None:
        return False
    return gs.players.index(ps) == gs.player_turn


# ===========================================================================
# CardIsImmuneToAll
# ===========================================================================

def card_is_immune_to_all(gs: GameState, card: LiveCard) -> bool:
    """
    CardIsImmuneToAll() — imune a combate E efeitos.
    bMyCharsImmune (somente Characters) OU bImmune.
    """
    return (card.b_immune or
            (card.b_my_chars_immune and card.card_def.card_type == CardType.CHARACTER))


# ===========================================================================
# CardIsImmuneToNoncombat
# ===========================================================================

def card_is_immune_to_noncombat(
    gs: GameState,
    card: LiveCard,
    cards_owners_turn: bool,
    killer: LiveCard | None = None,
) -> bool:
    """
    CardIsImmuneToNoncombat() — imune a efeitos não-combate.
    Linhas 12834–12864.
    """
    from .validators import v3_passive_in_effect

    if card.b_effect_immune:
        return True

    ps = _owner(gs, card)
    if ps is None:
        return False

    # V3 Passivo: NonCombatImmunity
    for i, action in enumerate(card.card_def.action_v3s):
        if not action.proc.passive:
            continue
        if not v3_passive_in_effect(gs, ps, card, i):
            continue
        ef = action.steps[0].effect if action.steps else None
        if ef and ef.immune_to_noncombat:
            return True

    # V3 Field: FieldNoncombatImmunity de aliados
    for ally in ps.deploy + ps.leader:
        for i, action in enumerate(ally.card_def.action_v3s):
            if not action.proc.passive:
                continue
            if not v3_passive_in_effect(gs, ps, ally, i):
                continue
            ef = action.steps[0].effect if action.steps else None
            if ef and ef.immune_to_noncombat:
                # Verifica se o target (card) corresponde ao filtro
                if action.steps and action.steps[0].target:
                    from .validators import temp_check_viable_target
                    if not temp_check_viable_target(gs, ally, i, 0, card, None):
                        continue
                return True

    return False


# ===========================================================================
# CardIsCombatImmune
# ===========================================================================

def card_is_combat_immune(gs: GameState, card: LiveCard) -> bool:
    """
    CardIsCombatImmune() — imune especificamente a combate.
    Linha 12915.
    """
    from .validators import v3_passive_in_effect

    if (card.b_combat_immune or
            card.b_combat_immune_to_start or
            card.b_combat_immune_to_end):
        return True

    ps = _owner(gs, card)
    if ps is None:
        return False

    # V3 Passive ImmuneToBattle
    for i, action in enumerate(card.card_def.action_v3s):
        if not action.proc.passive:
            continue
        if not v3_passive_in_effect(gs, ps, card, i):
            continue
        ef = action.steps[0].effect if action.steps else None
        if ef and ef.immune_to_battle:
            return True

    return False


# ===========================================================================
# CardCantBeRemovedFromFieldViaOpponentEffects
# ===========================================================================

def card_cant_be_removed_from_field(
    gs: GameState,
    card: LiveCard,
    remover: LiveCard | None = None,
) -> bool:
    """
    CardCantBeRemovedFromFieldViaOpponentEffects() — linhas 12770–12810.
    """
    from .validators import v3_passive_in_effect
    from .card_power import get_card_original_power

    ps = _owner(gs, card)
    if ps is None:
        return False

    # V3 Passive
    for i, action in enumerate(card.card_def.action_v3s):
        if not action.proc.passive:
            continue
        if not v3_passive_in_effect(gs, ps, card, i):
            continue
        ef = action.steps[0].effect if action.steps else None
        if ef is None:
            continue
        if ef.immune_to_removal:
            return True
        if (ef.immune_to_removal_from_chars_x_base_power_or_less > 0 and
                remover is not None):
            remover_power = get_card_original_power(gs, remover)
            if remover_power <= ef.immune_to_removal_from_chars_x_base_power_or_less:
                return True

    # Legacy: CantLeaveFieldFromEffects
    for action in card.card_def.card_actions:
        if action.action_effect.cant_leave_field_from_effects:
            # Legado: AllDonRested = todos os don repousados
            if ps.don_cost_area and all(d.b_tapped for d in ps.don_cost_area):
                return True

    return False


# ===========================================================================
# CardHasBlocker
# ===========================================================================

def card_has_blocker(gs: GameState, card: LiveCard) -> bool:
    """
    CardHasBlocker() — linhas 12111–12173.
    Ordem de verificação:
    1. bLoseBlocker tem prioridade absoluta
    2. bBlocker / bBlockerToOppTurnEnd
    3. V3PassiveBlocker
    4. Legacy (HandX, DonDeficit, FieldCategoryCharacter, etc.)
    5. GrantNameBlocker
    """
    from .validators import v3_passive_in_effect

    # 1. LoseBlocker override
    if card.b_lose_blocker:
        return False

    # 2. Flags diretas
    if card.b_blocker or card.b_blocker_to_opp_turn_end:
        return True

    ps = _owner(gs, card)
    if ps is None:
        return False
    ps_opp = _opposite(gs, ps)

    # 3. V3 Passive Blocker
    for i, action in enumerate(card.card_def.action_v3s):
        if not action.proc.passive:
            continue
        if not v3_passive_in_effect(gs, ps, card, i):
            continue
        ef = action.steps[0].effect if action.steps else None
        if ef and ef.gain_blocker:
            return True

    # 4. Legacy
    for action in card.card_def.card_actions:
        trigger = action.action_trigger
        ef = action.action_effect
        if not hasattr(ef, 'gain_blocker') or not ef.gain_blocker:
            continue
        # HandX: baseado no tamanho da mão
        if hasattr(trigger, 'hand_x_or_less') and trigger.hand_x_or_less > 0:
            if len(ps.hand) <= trigger.hand_x_or_less:
                return True
        # DonX: don equipado
        if trigger.don_x > 0 and card.attached_don_count >= trigger.don_x:
            return True

    # 5. V3 Field Blocker de aliados (GrantNameBlocker)
    for ally in ps.deploy + ps.leader:
        for i, action in enumerate(ally.card_def.action_v3s):
            if not action.proc.passive:
                continue
            if not v3_passive_in_effect(gs, ps, ally, i):
                continue
            ef = action.steps[0].effect if action.steps else None
            if ef and ef.gain_blocker:
                from .validators import temp_check_viable_target
                if temp_check_viable_target(gs, ally, i, 0, card, None):
                    return True

    return False


# ===========================================================================
# CardHasRush
# ===========================================================================

def card_has_rush(gs: GameState, card: LiveCard) -> bool:
    """CardHasRush() — linhas 7821–7861."""
    from .validators import v3_passive_in_effect

    # Verifica líder primeiro
    ps = _owner(gs, card)
    if ps and ps.leader:
        if _card_has_rush_leader(gs, card, ps):
            return True

    if card.b_rush_characters:
        return True

    if ps is None:
        return False

    # V3 Passive
    for i, action in enumerate(card.card_def.action_v3s):
        if not action.proc.passive:
            continue
        if not v3_passive_in_effect(gs, ps, card, i):
            continue
        ef = action.steps[0].effect if action.steps else None
        if ef and ef.gain_rush:
            return True

    # Stage GrantFieldRushCharacter
    for stage in ps.stage:
        for i, action in enumerate(stage.card_def.action_v3s):
            if not action.proc.passive:
                continue
            if not v3_passive_in_effect(gs, ps, stage, i):
                continue
            ef = action.steps[0].effect if action.steps else None
            if ef and ef.rush_characters:
                return True

    # Líder V3 FieldRushCharacters
    for leader in ps.leader:
        for i, action in enumerate(leader.card_def.action_v3s):
            if not action.proc.passive:
                continue
            if not v3_passive_in_effect(gs, ps, leader, i):
                continue
            ef = action.steps[0].effect if action.steps else None
            if ef and ef.rush_characters:
                return True

    return False


def _card_has_rush_leader(gs: GameState, card: LiveCard, ps: PlayerState) -> bool:
    """Verifica rush via efeito de líder."""
    from .validators import v3_passive_in_effect
    for leader in ps.leader:
        for i, action in enumerate(leader.card_def.action_v3s):
            if not action.proc.passive:
                continue
            if not v3_passive_in_effect(gs, ps, leader, i):
                continue
            ef = action.steps[0].effect if action.steps else None
            if ef and ef.rush_characters:
                from .validators import temp_check_viable_target
                if temp_check_viable_target(gs, leader, i, 0, card, None):
                    return True
    return False


# ===========================================================================
# CardHasDoubleAttack
# ===========================================================================

def card_has_double_attack(gs: GameState, card: LiveCard) -> bool:
    """CardHasDoubleAttack() — linhas 25013–25050."""
    from .validators import v3_passive_in_effect

    if card.b_double_attack or card.b_temp_double_attack:
        return True

    ps = _owner(gs, card)
    if ps is None:
        return False

    # V3 Passive
    for i, action in enumerate(card.card_def.action_v3s):
        if not action.proc.passive:
            continue
        if not v3_passive_in_effect(gs, ps, card, i):
            continue
        ef = action.steps[0].effect if action.steps else None
        if ef and ef.gain_double_attack:
            return True

    # V3 Field DoubleAttack de aliados
    for ally in ps.deploy + ps.leader:
        for i, action in enumerate(ally.card_def.action_v3s):
            if not action.proc.passive:
                continue
            if not v3_passive_in_effect(gs, ps, ally, i):
                continue
            ef = action.steps[0].effect if action.steps else None
            if ef and ef.gain_double_attack:
                from .validators import temp_check_viable_target
                if temp_check_viable_target(gs, ally, i, 0, card, None):
                    return True

    return False


# ===========================================================================
# CardHasBanish
# ===========================================================================

def card_has_banish(gs: GameState, card: LiveCard) -> bool:
    """CardHasBanish() — linhas 25053–25077."""
    from .validators import v3_passive_in_effect

    if card.b_banish or card.b_temp_banish:
        return True

    ps = _owner(gs, card)
    if ps is None:
        return False

    # V3 Passive
    for i, action in enumerate(card.card_def.action_v3s):
        if not action.proc.passive:
            continue
        if not v3_passive_in_effect(gs, ps, card, i):
            continue
        ef = action.steps[0].effect if action.steps else None
        if ef and ef.gain_banish:
            return True

    return False


# ===========================================================================
# CardCantAttack
# ===========================================================================

def card_cant_attack(gs: GameState, card: LiveCard) -> bool:
    """CardCantAttack() — linhas 7913–7936."""
    from .validators import v3_passive_in_effect

    if card.b_cant_attack or card.b_cant_rest:
        return True

    ps = _owner(gs, card)
    if ps is None:
        return False

    # V3 PassiveCantAttack
    for i, action in enumerate(card.card_def.action_v3s):
        if not action.proc.passive:
            continue
        if not v3_passive_in_effect(gs, ps, card, i):
            continue
        ef = action.steps[0].effect if action.steps else None
        if ef and ef.passive_cant_attack:
            return True

    # FieldCantAttack de aliados
    for ally in ps.deploy + ps.leader:
        for i, action in enumerate(ally.card_def.action_v3s):
            if not action.proc.passive:
                continue
            if not v3_passive_in_effect(gs, ps, ally, i):
                continue
            ef = action.steps[0].effect if action.steps else None
            if ef and ef.cant_attack:
                from .validators import temp_check_viable_target
                if temp_check_viable_target(gs, ally, i, 0, card, None):
                    return True

    return False