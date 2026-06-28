"""
optcg_engine/validators.py
===========================
Funções de validação — quando uma ação pode ser usada e quem pode ser alvo.

Reimplementação de:
  - CanUseV3Action()              linhas 1944–2360
  - V3PassiveInEffect()           linhas 2362–2828
  - CanUseV3ActionStep()          linhas 2830–3180
  - CheckCardIsViableTargetV3()   linhas 3180–3535
  - RemainingValidV3Targets()     linhas 3538–3710
  - TempCheckCardIsViableTargetV3() — wrapper para validação temporária

Fonte: Assembly-CSharp.dll v1.40a via dnSpy.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from .enums import CardType, CardCategory, CardColor, StrikeType

if TYPE_CHECKING:
    from .models import LiveCard, PlayerState, GameState
    from .action_system import ActV3Base, ActV3Step, ActV3Target, ActivatedCardAction


# ===========================================================================
# Helpers internos
# ===========================================================================

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


def _in_deploy(gs: GameState, card: LiveCard) -> bool:
    ps = _owner(gs, card)
    return ps is not None and card in ps.deploy


def _in_either_deploy(gs: GameState, card: LiveCard) -> bool:
    return any(card in ps.deploy for ps in gs.players)


def _card_has_name(card: LiveCard, name: str, exact: bool = True) -> bool:
    if exact:
        return (card.card_def.character_name == name or
                name in card.card_def.extra_names)
    return (name in card.card_def.character_name or
            any(name in n for n in card.card_def.extra_names))


def _card_has_category(card: LiveCard, cat: CardCategory) -> bool:
    return cat in card.card_def.card_categories


def _card_has_color(card: LiveCard, color: CardColor) -> bool:
    return color in card.card_def.card_colors


def _card_has_strike_type(card: LiveCard, st: StrikeType) -> bool:
    return (card.card_def.strike_type == st or
            st in card.card_def.extra_strike_types or
            st in card.l_extra_strike_types)


def _name_in_deploy(gs: GameState, actor: LiveCard, name: str) -> bool:
    ps = _owner(gs, actor)
    if ps is None:
        return False
    for c in ps.deploy + ps.leader:
        if _card_has_name(c, name):
            return True
    return False


def _don_on_field(ps: PlayerState) -> int:
    return ps.don_on_field()


def _available_don(ps: PlayerState) -> int:
    return ps.available_don()


def _rested_don(ps: PlayerState) -> int:
    return ps.rested_don()


# ===========================================================================
# CanUseV3Action
# ===========================================================================

def can_use_v3_action(
    gs: GameState,
    card: LiveCard,
    action_idx: int,
) -> bool:
    """
    Verifica se uma ActV3Base pode ser ativada agora.
    Reimplementa CanUseV3Action() — linhas 1944–2360.
    """
    # Recupera a ação
    all_actions = card.l_granted_actions + card.card_def.action_v3s
    if action_idx < 0 or action_idx >= len(all_actions):
        return False
    action = all_actions[action_idx]
    proc = action.proc

    ps = _owner(gs, card)
    if ps is None:
        return False
    ps_opp = _opposite(gs, ps)

    # Silenciado
    if card.b_silenced or card.b_silenced_to_owners_end or card.b_roger_silence:
        if proc.activate_main or proc.on_play or proc.trigger or proc.counter:
            return False

    # OncePerTurn
    if proc.once_per_turn:
        if action_idx < len(card.lb_actions_used) and card.lb_actions_used[action_idx]:
            return False

    # Active: carta deve estar ativa
    if proc.active and card.b_tapped:
        return False

    # Rested: carta deve estar repousada
    if proc.rested and not card.b_tapped:
        return False

    # YourTurn / OpponentTurn
    owners_turn = _owners_turn(gs, card)
    if proc.your_turn and not owners_turn:
        return False
    if proc.opponent_turn and owners_turn:
        return False

    # LeaderActive: líder deve estar ativo
    if proc.leader_active and ps.leader and ps.leader[0].b_tapped:
        return False

    # Don
    if proc.don_x > 0 and card.attached_don_count < proc.don_x:
        return False
    if proc.available_don > 0 and _available_don(ps) < proc.available_don:
        return False
    if proc.don_x_or_more > 0 and _don_on_field(ps) < proc.don_x_or_more:
        return False
    if proc.don_x_or_less > 0 and _don_on_field(ps) > proc.don_x_or_less:
        return False
    if proc.opp_don_x_or_more > 0 and ps_opp and _don_on_field(ps_opp) < proc.opp_don_x_or_more:
        return False
    if proc.either_don_x_or_more > 0:
        my_don = _don_on_field(ps)
        opp_don = _don_on_field(ps_opp) if ps_opp else 0
        if my_don < proc.either_don_x_or_more and opp_don < proc.either_don_x_or_more:
            return False
    if proc.don_x_less_than_opp and ps_opp:
        if _don_on_field(ps) >= _don_on_field(ps_opp):
            return False
    if proc.self_rested_don > 0 and _rested_don(ps) < proc.self_rested_don:
        return False
    if proc.opp_rested_don > 0 and ps_opp and _rested_don(ps_opp) < proc.opp_rested_don:
        return False
    if proc.self_attached_don > 0 and card.attached_don_count < proc.self_attached_don:
        return False

    # Trash
    if proc.trash_x_or_more > 0 and len(ps.trash) < proc.trash_x_or_more:
        return False
    if proc.trash_events_x_or_more > 0:
        events = sum(1 for c in ps.trash if c.card_def.card_type == CardType.EVENT)
        if events < proc.trash_events_x_or_more:
            return False

    # Cost zero exists
    if proc.cost_zero_exists:
        if not any(c.card_def.card_cost == 0
                   for ps2 in gs.players for c in ps2.deploy):
            return False

    # Characters
    if proc.characters_or_more > 0 and len(ps.deploy) < proc.characters_or_more:
        return False
    if proc.characters_or_less > 0 and len(ps.deploy) > proc.characters_or_less:
        return False

    # Hand
    if proc.hand_x_or_less > 0 and len(ps.hand) > proc.hand_x_or_less:
        return False
    if proc.hand_x_or_more > 0 and len(ps.hand) < proc.hand_x_or_more:
        return False

    # Life
    if proc.life_x_or_more > 0 and len(ps.life_deck) < proc.life_x_or_more:
        return False
    if proc.life_x_or_less > 0 and len(ps.life_deck) > proc.life_x_or_less:
        return False
    if proc.zero_life and len(ps.life_deck) > 0:
        return False
    if proc.either_player_zero_life:
        if ps.life_deck and (not ps_opp or ps_opp.life_deck):
            return False

    # Opp life
    if ps_opp:
        if proc.opp_life_x_or_more > 0 and len(ps_opp.life_deck) < proc.opp_life_x_or_more:
            return False
        if proc.opp_life_x_or_less > 0 and len(ps_opp.life_deck) > proc.opp_life_x_or_less:
            return False
        if proc.combined_life_x_or_less > 0:
            if len(ps.life_deck) + len(ps_opp.life_deck) > proc.combined_life_x_or_less:
                return False

    # Has battled character
    if proc.has_battled_character and not card.b_has_battled_character:
        return False

    # Any opp character KO'd
    if proc.any_opp_character_kod:
        leader = ps.leader[0] if ps.leader else None
        if not (leader and leader.b_opp_character_kod):
            return False

    # Leader requirements
    leader_card = ps.leader[0] if ps.leader else None
    if proc.leader_name_required and leader_card:
        if not any(_card_has_name(leader_card, n) for n in proc.leader_name_required):
            return False
    if proc.leader_category_required and leader_card:
        if not any(_card_has_category(leader_card, c) for c in proc.leader_category_required):
            return False

    # Power requirements
    if proc.power_x_or_more > 0:
        from .card_power import card_power
        if card_power(gs, card, owners_turn) < proc.power_x_or_more:
            return False

    # Turn number
    if proc.turn_x_or_later > 0 and gs.turn_number < proc.turn_x_or_later:
        return False

    # First turn only
    if proc.first_turn_only and not card.b_first_turn:
        return False

    # Ally name not in play
    if proc.ally_name_not_in_play:
        if _name_in_deploy(gs, card, proc.ally_name_not_in_play):
            return False

    # Names in trash
    if proc.names_in_your_trash:
        if not _names_in_trash(ps, proc.names_in_your_trash):
            return False

    return True


def _names_in_trash(ps: PlayerState, names: list[str]) -> bool:
    remaining = list(names)
    for card in ps.trash:
        for i in range(len(remaining) - 1, -1, -1):
            if _card_has_name(card, remaining[i]):
                remaining.pop(i)
    return len(remaining) == 0


# ===========================================================================
# V3PassiveInEffect
# ===========================================================================

def v3_passive_in_effect(
    gs: GameState,
    ps_owner: PlayerState,
    card: LiveCard,
    action_idx: int,
) -> bool:
    """
    Verifica se um efeito PASSIVO está ativo agora.
    Reimplementa V3PassiveInEffect() — linhas 2362–2828.
    Inclui todas as condições extras além do CanUseV3Action.
    """
    # Mesmas verificações base
    if not can_use_v3_action(gs, card, action_idx):
        return False

    all_actions = card.l_granted_actions + card.card_def.action_v3s
    if action_idx >= len(all_actions):
        return False
    action = all_actions[action_idx]
    proc = action.proc

    ps_opp = _opposite(gs, ps_owner)

    # Condições extras exclusivas do V3PassiveInEffect:

    # AnotherCharacterOfCategory
    if proc.another_character_of_category:
        found = False
        for ally in ps_owner.deploy:
            if (ally is not card and
                    ally.card_def.character_name != card.card_def.character_name):
                if any(_card_has_category(ally, c) for c in proc.another_character_of_category):
                    if not proc.acoc_color_req or any(_card_has_color(ally, c) for c in proc.acoc_color_req):
                        found = True
                        break
        if not found:
            return False

    # NoBaseXOrMore: nenhum personagem aliado tem base cost >= X
    if proc.no_base_x_or_more > 0:
        from .card_power import get_card_original_cost
        if any(get_card_original_cost(c) >= proc.no_base_x_or_more
               for c in ps_owner.deploy if c is not card):
            return False

    # OppAnyBaseXOrMore
    if proc.opp_any_base_x_or_more > 0 and ps_opp:
        from .card_power import get_card_original_cost
        if not any(get_card_original_cost(c) >= proc.opp_any_base_x_or_more
                   for c in ps_opp.deploy + ps_opp.leader):
            return False

    # NameInYourDeploy
    if proc.name_in_your_deploy:
        if not _name_in_deploy(gs, card, proc.name_in_your_deploy):
            return False

    # NameIsRested
    if proc.name_is_rested:
        found = any(
            _card_has_name(c, proc.name_is_rested) and c.b_tapped
            for c in ps_owner.deploy + ps_owner.leader
        )
        if not found:
            return False

    return True


# ===========================================================================
# CheckCardIsViableTargetV3
# ===========================================================================

def check_card_is_viable_target_v3(
    gs: GameState,
    aca: ActivatedCardAction,
    target: LiveCard,
    override_target_idx: int = -1,
) -> bool:
    """
    Verifica se uma carta específica é um alvo válido para o passo atual.
    Reimplementa CheckCardIsViableTargetV3() — linhas 3180–3535.
    """
    from .card_power import card_power, get_card_original_power, get_card_original_cost

    step = aca.v3_step(gs)
    if step is None:
        return False

    tgt_idx = override_target_idx if override_target_idx >= 0 else aca.action_target_idx
    if tgt_idx >= len(step.target):
        return False

    tgt = step.target[tgt_idx]
    actor = aca.actor_object(gs)
    if actor is None:
        return False

    ps_actor = _owner(gs, actor)
    ps_target = _owner(gs, target)
    if ps_actor is None:
        return False

    # ── Localização válida ────────────────────────────────────────────────
    if not _valid_target_location(gs, tgt, target, ps_actor, ps_target):
        return False

    # ── Friendly / Enemy ──────────────────────────────────────────────────
    if tgt.friendly_only and ps_target is not ps_actor:
        return False
    if tgt.enemy_only and ps_target is ps_actor:
        return False

    # ── Not self ─────────────────────────────────────────────────────────
    if tgt.not_self and target is actor:
        return False
    if tgt.only_self and target is not actor:
        return False

    # ── Estado ────────────────────────────────────────────────────────────
    if tgt.active_only and target.b_tapped:
        return False
    if tgt.rested_only and not target.b_tapped:
        return False
    if tgt.face_up and not target.b_face_up and not target.b_forced_face_up:
        return False

    # ── Tipo / cor / categoria / strikeType ──────────────────────────────
    if tgt.only_types and target.card_def.card_type not in tgt.only_types:
        return False
    if tgt.only_colors:
        if not any(_card_has_color(target, c) for c in tgt.only_colors):
            return False
    if tgt.only_categories:
        if not any(_card_has_category(target, c) for c in tgt.only_categories):
            return False
    if tgt.only_strike_types:
        if not any(_card_has_strike_type(target, st) for st in tgt.only_strike_types):
            return False

    # ── Nomes ─────────────────────────────────────────────────────────────
    if tgt.only_names:
        if not any(_card_has_name(target, n) for n in tgt.only_names):
            return False
    if tgt.not_names:
        if any(_card_has_name(target, n) for n in tgt.not_names):
            return False
    if tgt.name_matches_saved:
        if not _card_has_name(target, aca.saved_string):
            return False

    # ── No duplicate names ────────────────────────────────────────────────
    if tgt.no_duplicate_names and aca.prev_names:
        if target.card_def.character_name in aca.prev_names:
            return False

    # ── Poder ─────────────────────────────────────────────────────────────
    owners_turn = _owners_turn(gs, target)
    if tgt.power_x_or_less > 0:
        if card_power(gs, target, owners_turn) > tgt.power_x_or_less:
            return False
    if tgt.power_x_or_more > 0:
        if card_power(gs, target, owners_turn) < tgt.power_x_or_more:
            return False
    if tgt.power_zero and card_power(gs, target, owners_turn) != 0:
        return False
    if tgt.original_power_x_or_less > 0:
        if get_card_original_power(gs, target) > tgt.original_power_x_or_less:
            return False
    if tgt.original_power_x_or_more > 0:
        if get_card_original_power(gs, target) < tgt.original_power_x_or_more:
            return False
    if tgt.base_power_zero and target.card_def.card_power != 0:
        return False

    # ── Custo ─────────────────────────────────────────────────────────────
    from .card_power import get_card_cost
    if tgt.cost_or_less > 0:
        if get_card_cost(gs, target) > tgt.cost_or_less:
            return False
    if tgt.cost_or_more > 0:
        if get_card_cost(gs, target) < tgt.cost_or_more:
            return False
    if tgt.cost_zero and get_card_cost(gs, target) != 0:
        return False
    if tgt.original_cost_x_or_less > 0:
        if get_card_original_cost(target) > tgt.original_cost_x_or_less:
            return False
    if tgt.original_cost_x_or_more > 0:
        if get_card_original_cost(target) < tgt.original_cost_x_or_more:
            return False

    # ── Life cost constraints ─────────────────────────────────────────────
    ps_me = ps_actor
    if tgt.cost_my_life_or_less:
        if get_card_cost(gs, target) > len(ps_me.life_deck):
            return False
    if tgt.cost_opp_life_or_less and ps_actor:
        ps_opp = _opposite(gs, ps_actor)
        if ps_opp and get_card_cost(gs, target) > len(ps_opp.life_deck):
            return False

    # ── Imunidades (KO) ───────────────────────────────────────────────────
    ef = step.effect
    if ef.ko_card and target.is_immune_to_all:
        return False

    # ── Rest + CantRest ───────────────────────────────────────────────────
    if ef.rest and target.b_cant_rest:
        return False

    # ── Habilidades ───────────────────────────────────────────────────────
    if tgt.has_activate_main:
        if not any(a.proc.activate_main for a in target.card_def.action_v3s):
            return False
    if tgt.has_trigger:
        if not any(a.proc.trigger for a in target.card_def.action_v3s):
            return False
    if tgt.has_blocker:
        from .card_queries import card_has_blocker
        if not card_has_blocker(gs, target):
            return False
    if tgt.has_no_on_play:
        if any(a.proc.on_play for a in target.card_def.action_v3s):
            return False
    if tgt.has_no_effects:
        has_effects = (bool(target.card_def.action_v3s) or
                       bool(target.card_def.card_actions))
        if has_effects:
            return False

    return True


def _valid_target_location(
    gs: GameState,
    tgt,
    target: LiveCard,
    ps_actor: PlayerState,
    ps_target: PlayerState | None,
) -> bool:
    """Verifica se a carta está na zona correta para ser alvo."""
    in_deploy = any(target in ps.deploy for ps in gs.players)
    in_leader = any(target in ps.leader for ps in gs.players)
    in_hand = any(target in ps.hand for ps in gs.players)
    in_life = any(target in ps.life_deck for ps in gs.players)
    in_deck = any(target in ps.deck for ps in gs.players)
    in_trash = any(target in ps.trash for ps in gs.players)
    in_stage = any(target in ps.stage for ps in gs.players)
    in_don = any(target in ps.don_cost_area for ps in gs.players)

    # Verifica se pelo menos uma zona válida bate
    valid = False
    if tgt.deployed_character and in_deploy:
        valid = True
    if tgt.leader and in_leader:
        valid = True
    if tgt.hand_card and in_hand:
        valid = True
    if tgt.life_card and in_life:
        valid = True
    if tgt.deck_card and in_deck:
        valid = True
    if tgt.trash_card and in_trash:
        valid = True
    if tgt.stage_card and in_stage:
        valid = True
    if tgt.don_area_card and in_don:
        valid = True

    # AttachedDon
    if tgt.attached_don:
        for ps in gs.players:
            for c in ps.deploy + ps.leader:
                if target in c.attached_don:
                    valid = True

    # Top deck card
    if tgt.top_deck_card:
        for ps in gs.players:
            if ps.deck and target is ps.deck[-1]:
                valid = True

    return valid


# ===========================================================================
# TempCheckCardIsViableTargetV3 — validação sem ActivatedCardAction completo
# ===========================================================================

def temp_check_viable_target(
    gs: GameState,
    actor: LiveCard,
    action_idx: int,
    step_idx: int,
    target: LiveCard,
    saved_string: str | None,
) -> bool:
    """
    TempCheckCardIsViableTargetV3() do C#.
    Cria um ActivatedCardAction temporário para validar um alvo.
    Usado por GetCardCost, CardPower, etc. para verificar condições.
    """
    from .action_system import ActivatedCardAction

    ps = gs.find_card_owner(actor)
    if ps is None:
        return False

    aca = ActivatedCardAction(
        actor_id=actor.deck_unique_id,
        action_idx=action_idx,
        action_step=step_idx,
        action_target_idx=0,
        player_id=gs.players.index(ps) if ps in gs.players else 0,
        saved_string=saved_string or "",
        _game_state=gs,
    )
    all_actions = actor.l_granted_actions + actor.card_def.action_v3s
    if action_idx < len(all_actions):
        step = all_actions[action_idx].steps[step_idx] if step_idx < len(all_actions[action_idx].steps) else None
        if step:
            aca.target_ids = [[] for _ in step.target]

    return check_card_is_viable_target_v3(gs, aca, target)


# ===========================================================================
# RemainingValidV3Targets
# ===========================================================================

def remaining_valid_v3_targets(
    gs: GameState,
    aca: ActivatedCardAction,
    add_to_targets: bool = False,
) -> bool:
    """
    RemainingValidV3Targets() — verifica se existem alvos válidos para o passo.
    Se add_to_targets=True, adiciona automaticamente (AutoAllMatchingTargets).
    Retorna True se pelo menos um alvo válido existe.
    """
    step = aca.v3_step(gs)
    if step is None:
        return False

    tgt_idx = aca.action_target_idx
    if tgt_idx >= len(step.target):
        return False

    tgt = step.target[tgt_idx]
    found_any = False

    # Itera todas as zonas relevantes
    for ps in gs.players:
        zones = []
        if tgt.deployed_character:
            zones.extend(ps.deploy)
        if tgt.leader:
            zones.extend(ps.leader)
        if tgt.hand_card:
            zones.extend(ps.hand)
        if tgt.life_card:
            zones.extend(ps.life_deck)
        if tgt.deck_card:
            zones.extend(ps.deck)
        if tgt.trash_card:
            zones.extend(ps.trash)
        if tgt.stage_card:
            zones.extend(ps.stage)
        if tgt.don_area_card:
            zones.extend(ps.don_cost_area)
        if tgt.attached_don:
            for c in ps.deploy + ps.leader:
                zones.extend(c.attached_don)
        if tgt.top_deck_card and ps.deck:
            zones.append(ps.deck[-1])

        for card in zones:
            if check_card_is_viable_target_v3(gs, aca, card):
                found_any = True
                if add_to_targets:
                    if tgt_idx < len(aca.target_ids):
                        aca.target_ids[tgt_idx].append(card.deck_unique_id)
                else:
                    return True

    return found_any


# ===========================================================================
# CanUseV3ActionStep
# ===========================================================================

def can_use_v3_action_step(
    gs: GameState,
    aca: ActivatedCardAction,
) -> bool:
    """
    Verifica se o PASSO ATUAL de uma ação pode ser executado.
    Reimplementa CanUseV3ActionStep() — linhas 2830–3180.
    """
    step = aca.v3_step(gs)
    if step is None:
        return False

    details = step.details
    actor = aca.actor_object(gs)
    if actor is None:
        return False

    ps = gs.players[aca.player_id] if aca.player_id < len(gs.players) else None
    if ps is None:
        return False
    ps_opp = _opposite(gs, ps)

    # Leader name / category / colors
    leader = ps.leader[0] if ps.leader else None
    if details.leader_name_required and leader:
        if not any(_card_has_name(leader, n) for n in details.leader_name_required):
            return False
    if details.leader_category_required and leader:
        if not any(_card_has_category(leader, c) for c in details.leader_category_required):
            return False
    if details.leader_has_colors and leader:
        if not any(_card_has_color(leader, c) for c in details.leader_has_colors):
            return False
    if details.leader_color_count_or_more > 0 and leader:
        if len(leader.card_def.card_colors) < details.leader_color_count_or_more:
            return False

    # Don cost do passo
    from .action_system import ActivatedCardAction as ACA
    step_don = _v3_action_don_to_tap(gs, aca)
    if step_don > _available_don(ps):
        return False

    # RestSelf + CantRest
    if step.effect.rest_self and actor.b_cant_rest:
        return False

    # Field conditions
    if details.characters_or_more > 0:
        allies = [c for c in ps.deploy if c is not actor]
        if len(allies) < details.characters_or_more:
            return False

    if details.field_is_only_category:
        if not _player_field_is_only_categories(ps, details.field_is_only_category):
            return False

    if details.self_rested_characters > 0:
        rested = sum(1 for c in ps.deploy if c.b_tapped)
        if rested < details.self_rested_characters:
            return False

    if details.opp_rested_characters > 0 and ps_opp:
        rested = sum(1 for c in ps_opp.deploy if c.b_tapped)
        if rested < details.opp_rested_characters:
            return False

    # Previous targets
    if details.has_previous_targets and not aca.prev_targets:
        return False
    if details.no_previous_targets and aca.prev_targets:
        return False
    if details.has_valid_targets and not remaining_valid_v3_targets(gs, aca, False):
        return False

    # Hand
    if details.hand_x_or_less > 0 and len(ps.hand) > details.hand_x_or_less:
        return False
    if details.hand_x_or_more > 0 and len(ps.hand) < details.hand_x_or_more:
        return False
    if details.hand_empty and len(ps.hand) > 0:
        return False
    if details.opp_hand_x_or_more > 0 and ps_opp:
        if len(ps_opp.hand) < details.opp_hand_x_or_more:
            return False

    # Don
    if details.don_x_or_more > 0 and _don_on_field(ps) < details.don_x_or_more:
        return False
    if details.don_x_or_less > 0 and _don_on_field(ps) > details.don_x_or_less:
        return False
    if details.available_don > 0 and _available_don(ps) < details.available_don:
        return False
    if details.less_or_eq_don and ps_opp:
        if _don_on_field(ps) > _don_on_field(ps_opp):
            return False
    if details.less_don and ps_opp:
        if _don_on_field(ps) >= _don_on_field(ps_opp):
            return False
    if details.opp_don_x_or_more > 0 and ps_opp:
        if _don_on_field(ps_opp) < details.opp_don_x_or_more:
            return False
    if details.opp_rested_don > 0 and ps_opp:
        if _rested_don(ps_opp) < details.opp_rested_don:
            return False

    # Life
    if details.life_x_or_less > 0 and len(ps.life_deck) > details.life_x_or_less:
        return False
    if details.life_x_or_more > 0 and len(ps.life_deck) < details.life_x_or_more:
        return False
    if details.life_is_zero and len(ps.life_deck) != 0:
        return False
    if details.life_less and ps_opp:
        if len(ps.life_deck) >= len(ps_opp.life_deck):
            return False
    if details.life_less_or_equal and ps_opp:
        if len(ps.life_deck) > len(ps_opp.life_deck):
            return False
    if details.opp_life_x_or_less > 0 and ps_opp:
        if len(ps_opp.life_deck) > details.opp_life_x_or_less:
            return False
    if details.opp_life_x_or_more > 0 and ps_opp:
        if len(ps_opp.life_deck) < details.opp_life_x_or_more:
            return False

    # Trash / deck
    if details.trash_x_or_more > 0 and len(ps.trash) < details.trash_x_or_more:
        return False
    if details.deck_out and len(ps.deck) > 0:
        return False
    if details.on_board and not _in_either_deploy(gs, actor):
        return False
    if details.trash_events_x_or_more > 0:
        ev = sum(1 for c in ps.trash if c.card_def.card_type == CardType.EVENT)
        if ev < details.trash_events_x_or_more:
            return False
    if details.trash_events_x_or_less > 0:
        ev = sum(1 for c in ps.trash if c.card_def.card_type == CardType.EVENT)
        if ev > details.trash_events_x_or_less:
            return False

    # Opp characters
    if details.opp_characters_or_more > 0 and ps_opp:
        if len(ps_opp.deploy) < details.opp_characters_or_more:
            return False
    if details.opp_characters_or_less > 0 and ps_opp:
        if len(ps_opp.deploy) > details.opp_characters_or_less:
            return False

    # Activated event
    if details.activated_event_x_or_more > 0:
        if ps.i_highest_event_played < details.activated_event_x_or_more:
            return False

    # Any opp character KO'd
    if details.any_opp_character_kod:
        leader_card = ps.leader[0] if ps.leader else None
        if not (leader_card and leader_card.b_opp_character_kod):
            return False

    # Ally name conditions
    for name in details.ally_name_not_in_play:
        if _name_in_deploy(gs, actor, name):
            return False
    for name in details.ally_name_in_play:
        if not _name_in_deploy(gs, actor, name):
            return False

    return True


def _v3_action_don_to_tap(gs: GameState, aca: ActivatedCardAction) -> int:
    """V3ActionDonToTap() — custo em don do passo atual."""
    if aca.action_step == 0 and aca.is_free:
        return 0
    step = aca.v3_step(gs)
    if step is None:
        return 0
    return step.effect.don_tap if hasattr(step.effect, 'don_tap') else 0


def _player_field_is_only_categories(
    ps: PlayerState,
    categories: list[CardCategory],
) -> bool:
    """Todos os personagens no campo têm pelo menos uma das categorias."""
    if not ps.deploy:
        return False
    for card in ps.deploy:
        if not any(_card_has_category(card, c) for c in categories):
            return False
    return True