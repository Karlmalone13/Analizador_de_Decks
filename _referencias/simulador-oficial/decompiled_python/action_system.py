"""
optcg_engine/action_system.py
==============================
Sistema de ações V3 do OPTCG — extraído do Assembly-CSharp.dll v1.40a.

Hierarquia:
    CardDefinition.action_v3s: List[ActV3Base]
        ActV3Base
            ├── proc: ActV3Proc         (QUANDO dispara + requisitos)
            └── steps: List[ActV3Step]
                    ├── details: ActV3StepDetails  (condições por passo)
                    ├── target:  List[ActV3Target] (quem é alvo)
                    └── effect:  ActV3Effect       (o que acontece)

Runtime:
    ActivatedCardAction  — snapshot de uma ação em execução
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .enums import (
    CardType, CardColor, StrikeType, CardCategory,
    ActionChoice, RemovalEffect
)

if TYPE_CHECKING:
    from .models import LiveCard, PlayerState, GameState


# ===========================================================================
# ActV3Choice  (Token 0x02000057)
# Ramificação de escolha dentro de um ActV3Effect
# ===========================================================================

@dataclass
class ActV3Choice:
    """
    Representa uma opção de escolha apresentada ao jogador.
    Ex: "KO ou Bounce?" → dois ActV3Choice, cada um com jump_to_step diferente.
    """
    button_text: str = ""    # texto do botão na UI
    jump_to_step: int = 0    # índice do step a executar se escolhido


# ===========================================================================
# ActV3Effect  (Token 0x02000058)
# O QUE o efeito faz — struct com ~200 campos booleanos/inteiros
# ===========================================================================

@dataclass
class ActV3Effect:
    """
    Todos os campos de efeito do sistema V3.
    Campos com valor padrão False/0 são "desligados".
    """

    # ── Vitória / derrota ───────────────────────────────────────────────────
    win_the_game: bool = False
    lose_the_game: bool = False
    zoro_don: bool = False                     # Easter egg April Fools

    # ── Comprar / mill ──────────────────────────────────────────────────────
    draw_cards: int = 0
    draw_saved_count: bool = False             # compra sSavedInt cartas
    mill_deck: int = 0
    mill_for_x_previous_targets: bool = False  # mill = nº de prev_targets

    # ── Vida ────────────────────────────────────────────────────────────────
    peek_self_life: bool = False
    peek_opp_life: bool = False
    peek_opp_top_deck_flip: bool = False
    leave_life_in_position: bool = False
    send_top_life_to_bot: bool = False
    send_opp_top_life_to_bot: bool = False
    trash_top_life: bool = False
    trash_bottom_life: bool = False
    trash_life_to: int = 0                     # deixa X vidas, descarta o resto
    trash_opp_life: int = 0
    flip_top_life_up: int = 0
    flip_top_life_down: int = 0
    take_top_life: bool = False
    take_bottom_life: bool = False
    opp_take_life: int = 0
    heal: int = 0                              # adiciona X vidas (deck→vida)
    top_deck_to_life: bool = False
    top_deck_to_opp_life: bool = False
    add_deck_to_life: int = 0
    add_life_to_deck: int = 0
    send_top_life_to_hand: bool = False
    banish_opponent_life: int = 0
    no_take_life_to_turn_start: bool = False
    trash_all_face_up_life: bool = False

    # ── Don ─────────────────────────────────────────────────────────────────
    don_tap: int = 0                           # custo em don (tap)
    don_minus: int = 0                         # retornar X don ao deck
    don_minus_to_opp_count: bool = False       # retornar até igualar oponente
    optional_return_don: bool = False
    gain_active_don: int = 0
    gain_rested_don: int = 0
    give_self_up_to_2_rested_don: bool = False
    attach_rested_don: bool = False
    dont_return_don_end_of_turn: bool = False
    activate_don: int = 0                      # ativa X don repousados
    dont_return_attached_don: bool = False
    attach_all_active_don: bool = False
    don_deck_override: int = 0                 # override do máximo de don
    end_of_turn_eq_don: bool = False           # iguala don no fim de turno

    # ── Power buffs ─────────────────────────────────────────────────────────
    buff_power: int = 0
    buff_combat_power: int = 0
    buff_self_to_turn_start: int = 0
    buff_x_per_prev_targets: int = 0
    buff_x_per_given_don: int = 0
    buff_x_per_top_deck_cost: int = 0
    buff_1k_per_x_targets: int = 0
    buff_other: int = 0
    buff_leader: int = 0
    set_base_power: int = 0
    set_base_power_to_start: int = 0
    set_base_power_to_opp_end: int = 0
    match_leader_to_base_power: bool = False
    match_leader_to_base_power_to_start: bool = False
    match_leader_to_base_power_to_opp_end: bool = False
    set_power_to_zero: bool = False
    field_base_power_change: int = -1          # -1 = não ativo (override total)
    passive_power_change: int = 0
    passive_base_power_match_leader: bool = False
    passive_1k_per_x_trash: int = 0
    passive_1k_per_x_event_trash: int = 0
    passive_1k_per_x_rested_don: int = 0
    passive_power_per_unique_deploy: int = 0
    passive_cost_change: int = 0
    hand_cost_change: int = 0
    passive_1_cost_per_x_trash: int = 0
    passive_2_cost_per_x_trash: int = 0
    passive_cant_attack: bool = False
    ally_field_cost_change: int = 0
    ally_hand_play_cost_reduce: int = 0
    opponent_field_cost_change: int = 0

    # ── Keywords (conceder/remover) ──────────────────────────────────────────
    gain_banish: bool = False
    gain_blocker: bool = False
    gain_blocker_to_opp_end: bool = False
    lose_blocker: bool = False
    gain_double_attack: bool = False
    gain_rush: bool = False
    rush_characters: bool = False              # personagens do campo ganham Rush
    gain_unblockable: bool = False
    gain_can_attack_active: bool = False
    cant_attack: bool = False
    cant_rest: bool = False
    cant_be_deployed_via_effect: bool = False
    blocker_must_be_x_or_more: int = 0
    blocker_must_be_x_or_less: int = 0

    # ── Imunidades ──────────────────────────────────────────────────────────
    immune_to_battle: bool = False             # ImmuneToBattle = CombatImmune
    immune_to_noncombat: bool = False
    immune_to_removal: bool = False
    immune_to_removal_from_chars_x_base_power_or_less: int = 0
    immune_to_rest: bool = False
    immune_to_rest_from_leader_or_char: bool = False
    immune_to_strikes: list[StrikeType] = field(default_factory=list)
    immune_to_leader_strikes: list[StrikeType] = field(default_factory=list)
    immune_to_all_strikes: list[StrikeType] = field(default_factory=list)
    immune_to_strikes_includes_leaders: bool = False
    vulnerable_to_strikes: list[StrikeType] = field(default_factory=list)
    vulnerable_to_noncombat: bool = False
    cant_leave_field_from_effects: bool = False
    effect_immune: bool = False
    gain_immune: bool = False
    all_chars_effect_immune: bool = False

    # ── Remoção de cartas ────────────────────────────────────────────────────
    ko_card: bool = False
    ko_if_cost_x_or_less: int = 0
    trash_card: bool = False
    send_to_hand: bool = False
    send_to_deck_top: bool = False
    send_to_deck_bottom: bool = False
    send_to_top_life: bool = False
    send_to_bottom_life: bool = False
    bounce_self: bool = False
    rest_self: bool = False
    rest: bool = False
    activate: bool = False
    activate_main_of_card: bool = False
    freeze: bool = False                       # bSkipNextActive
    freeze_stage: bool = False
    freeze_don: bool = False

    # ── Deploy / jogar cartas ────────────────────────────────────────────────
    deploy_self: bool = False
    deploy_character: bool = False
    deploy_character_from_hand_after_top_deck: str = ""
    play_from_trash: bool = False
    play_from_deck: bool = False

    # ── Silêncio ────────────────────────────────────────────────────────────
    silence: bool = False
    silence_to_owners_end: bool = False
    rosinate_leader: bool = False

    # ── Busca / topdeck ──────────────────────────────────────────────────────
    start_top_deck: int = 0
    start_top_deck_from_life: bool = False
    start_top_deck_opp: int = 0
    start_top_deck_from_life_all: bool = False
    start_top_deck_from_opp_life_all: bool = False
    start_top_deck_from_hand: bool = False
    start_top_deck_from_opp_hand: bool = False
    start_top_deck_from_trash: bool = False
    start_top_deck_from_opp_trash: bool = False
    start_top_deck_from_deck: bool = False
    reveal_top_deck_to_opponent: bool = False
    top_deck_top_or_bottom: bool = False
    top_deck_to_deck_bottom: bool = False
    top_deck_to_deck_top: bool = False
    infinite_return_to_deck: bool = False
    searching_deck: bool = False

    # ── Salvar dados mid-ação ────────────────────────────────────────────────
    save_target_name: bool = False
    save_hand_size: bool = False
    save_target_count: bool = False
    saved_int: int = 0
    copy_targets_at_end: bool = False
    declare_string: bool = False
    declare_cost: bool = False
    transform_to_saved_string: bool = False

    # ── Transferência de don ─────────────────────────────────────────────────
    transfer_don: bool = False
    zoro_don_transfer: bool = False

    # ── Mudança de custo ─────────────────────────────────────────────────────
    change_cost: int = 0
    change_cost_to_opp_end: int = 0
    reduce_card_costs: int = 0

    # ── Efeitos globais / campo ──────────────────────────────────────────────
    opp_no_blocker_this_turn: bool = False
    opp_no_on_play_to_turn_end: bool = False
    field_cant_attack_leader: bool = False
    cant_activate_don_to_turn_end: bool = False
    cant_play_any_characters_to_field: bool = False
    cant_play_any_cards_from_hand: bool = False
    my_field_unblockable: bool = False
    no_on_plays: bool = False                  # bloqueia OnPlay do oponente
    heal_end_of_turn: int = 0

    # ── Filas de ações ───────────────────────────────────────────────────────
    queue_up_end_of_turn_action: int = 0       # índice da ação a enfileirar
    queue_up_opp_main_phase_action: int = 0

    # ── Shuffle ──────────────────────────────────────────────────────────────
    shuffle_hand_into_deck: bool = False
    cycle_entire_hand_to_deck_bottom: bool = False
    shuffle_deck: bool = False

    # ── Dano ─────────────────────────────────────────────────────────────────
    deal_damage: int = 0
    take_damage: int = 0

    # ── Escolhas (ramificação) ───────────────────────────────────────────────
    choices: list[ActV3Choice] = field(default_factory=list)

    # ── Film ─────────────────────────────────────────────────────────────────
    activate_all_film_chars_end_of_turn: bool = False
    trash_film_characters: bool = False

    # ── Outros ───────────────────────────────────────────────────────────────
    counts_as_everything: bool = False         # conta como qualquer nome
    usopp_leader: bool = False
    kinemon_leader_effect: bool = False
    take_another_turn: bool = False
    force_opponent: bool = False


# ===========================================================================
# ActV3Target  (Token 0x02000065)
# QUEM pode ser alvo
# ===========================================================================

@dataclass
class ActV3Target:
    """Define quem pode ser selecionado como alvo em um passo."""

    # ── Seleção automática ───────────────────────────────────────────────────
    auto_self: bool = False
    auto_copy_previous_targets: bool = False
    auto_all_matching_targets: bool = False
    auto_main_target: bool = False
    target_count: int = 1
    target_count_saved_count: bool = False     # usa sSavedInt como contagem
    target_count_hand_overflow: int = 0
    override_ui_target_count: int = 0
    no_duplicate_names: bool = False

    # ── Localização do alvo ──────────────────────────────────────────────────
    deployed_character: bool = False
    leader: bool = False
    hand_card: bool = False
    top_deck_card: bool = False
    deck_card: bool = False
    trash_card: bool = False
    life_card: bool = False
    attached_don: bool = False
    don_area_card: bool = False
    stage_card: bool = False

    # ── Filtros de lado ──────────────────────────────────────────────────────
    friendly_only: bool = False
    enemy_only: bool = False

    # ── Filtros de estado ────────────────────────────────────────────────────
    active_only: bool = False                  # só cartas ativas (não tapped)
    rested_only: bool = False
    only_self: bool = False
    not_self: bool = False
    face_up: bool = False

    # ── Filtros de tipo/cor/categoria ────────────────────────────────────────
    only_types: list[CardType] = field(default_factory=list)
    only_colors: list[CardColor] = field(default_factory=list)
    only_categories: list[CardCategory] = field(default_factory=list)
    only_strike_types: list[StrikeType] = field(default_factory=list)
    only_names: list[str] = field(default_factory=list)
    not_names: list[str] = field(default_factory=list)
    name_matches_saved: bool = False

    # ── Filtros de poder ─────────────────────────────────────────────────────
    power_x_or_less: int = 0
    power_x_or_more: int = 0
    power_zero: bool = False
    base_power_zero: bool = False
    original_power_x_or_less: int = 0
    original_power_x_or_more: int = 0
    second_original_power_x_or_less: int = 0
    combined_power_x_or_less: int = 0
    original_cost_x_or_less: int = 0
    original_cost_x_or_more: int = 0
    second_original_cost_x_or_less: int = 0

    # ── Filtros de custo ─────────────────────────────────────────────────────
    cost_or_less: int = 0
    cost_or_more: int = 0
    cost_zero: bool = False
    cost_don_or_less: bool = False
    cost_my_life_or_less: bool = False
    cost_opp_life_or_less: bool = False
    cost_combined_life_or_less: bool = False
    cost_equal_given_don: bool = False

    # ── Filtros de habilidade ────────────────────────────────────────────────
    has_activate_main: bool = False
    has_trigger: bool = False
    has_blocker: bool = False
    has_no_on_play: bool = False
    has_no_on_attack: bool = False
    has_no_effects: bool = False

    # ── Outros ───────────────────────────────────────────────────────────────
    given_don: int = 0
    different_color_from_prev_target: bool = False
    strike_type_overrides: list[StrikeType] = field(default_factory=list)
    name_overrides: list[str] = field(default_factory=list)


# ===========================================================================
# ActV3StepDetails  (Token 0x02000066)
# Condições SE para um passo ser executável
# ===========================================================================

@dataclass
class ActV3StepDetails:
    """Condições que devem ser verdadeiras para o passo ser executado."""

    # ── Controle do passo ────────────────────────────────────────────────────
    required: bool = False                     # se False e falhar, pula o passo
    confirm_action: bool = False               # exige confirmação do jogador
    no_cancel: bool = False                    # não pode cancelar
    end_after_step: bool = False               # termina a ação após este passo
    full_targets_required: list[int] = field(default_factory=list)
    searching_deck: bool = False

    # ── Requisitos de líderes ────────────────────────────────────────────────
    leader_name_required: list[str] = field(default_factory=list)
    leader_category_required: list[CardCategory] = field(default_factory=list)
    leader_has_colors: list[CardColor] = field(default_factory=list)
    leader_color_count_or_more: int = 0

    # ── Requisitos de campo ──────────────────────────────────────────────────
    characters_or_more: int = 0
    two_character_base_power_x: int = 0
    field_is_only_category: list[CardCategory] = field(default_factory=list)
    field_is_full_and_unique: bool = False
    ally_name_in_play: list[str] = field(default_factory=list)
    ally_name_in_play_count: int = 0
    ally_name_not_in_play: list[str] = field(default_factory=list)
    name_not_in_any_deploy: list[str] = field(default_factory=list)
    names_with_exact_base_power_in_your_deploy: list = field(default_factory=list)  # List[StringCount]
    require_all: bool = False
    category_in_play_required: list[CardCategory] = field(default_factory=list)
    category_in_play_count: int = 0
    can_use_on_plays: bool = False
    board_less_than_cost_x: int = 0
    on_board: bool = False

    # ── Requisitos de don ────────────────────────────────────────────────────
    don_x_or_more: int = 0
    don_x_or_less: int = 0
    available_don: int = 0
    less_than_x_available_don: int = 0
    opp_available_don: int = 0
    less_or_eq_don: bool = False
    less_don: bool = False
    self_attached_don: int = 0
    opp_don_x_or_more: int = 0
    opp_don_x_or_less: int = 0

    # ── Requisitos de mão ────────────────────────────────────────────────────
    hand_x_or_less: int = 0
    hand_x_or_more: int = 0
    hand_empty: bool = False
    opp_hand_x_or_more: int = 0
    hand_diff_x_or_more: int = 0

    # ── Requisitos de vida ───────────────────────────────────────────────────
    life_x_or_less: int = 0
    life_x_or_more: int = 0
    life_is_zero: bool = False
    life_less: bool = False
    life_less_or_equal: bool = False
    opp_life_x_or_less: int = 0
    opp_life_x_or_more: int = 0
    combined_life_x_or_less: int = 0
    combined_life_x_or_more: int = 0
    face_down_life: int = 0

    # ── Requisitos de deck/trash ─────────────────────────────────────────────
    trash_x_or_more: int = 0
    trash_events_x_or_more: int = 0
    trash_events_x_or_less: int = 0
    deck_out: bool = False
    top_deck_count_or_more: int = 0
    top_deck_has_category: list[CardCategory] = field(default_factory=list)
    top_deck_has_type: list[CardType] = field(default_factory=list)
    top_deck_cost_or_less: int = 0
    top_deck_cost_or_more: int = 0
    top_deck_matches_saved_cost: bool = False
    last_trashed_cost_x_or_more: int = 0

    # ── Requisitos de personagens ────────────────────────────────────────────
    character_cost_x_or_more: int = 0
    cost_zero_or_x_or_more_exists: int = 0
    opp_cost_zero_or_x_or_more_exists: int = 0
    character_power_x_or_more: int = 0
    opp_power_x_or_more: int = 0
    any_power_x_or_more: int = 0
    opp_characters_or_more: int = 0
    opp_characters_or_less: int = 0
    opp_x_more_or_more_characters: int = 0
    ally_cost_or_more: int = 0
    ally_cost_count: int = 0
    self_rested_characters: int = 0
    self_rested_cards: int = 0
    opp_rested_characters: int = 0
    self_rested_character_category: object = None  # CategoryCount
    self_character_category: object = None          # CategoryCount
    cost_x_or_higher_character_category: object = None  # CategoryCount

    # ── Interrupt / previous targets ─────────────────────────────────────────
    has_previous_targets: bool = False
    has_valid_targets: bool = False
    no_previous_targets: bool = False
    previous_target_now_in_life: bool = False
    previous_target_now_in_hand: bool = False
    previous_target_now_in_deck: bool = False
    previous_target_now_in_trash: bool = False

    # ── Outros ───────────────────────────────────────────────────────────────
    activated_event_x_or_more: int = 0
    any_opp_character_kod: bool = False
    opp_rested_don: int = 0
    first_turn_only: bool = False
    attacker_has_strike_types: list[StrikeType] = field(default_factory=list)
    attacker_has_card_types: list[CardType] = field(default_factory=list)


# ===========================================================================
# ActV3Step  (Token 0x02000066)
# Uma unidade atômica de efeito: SE (details) → QUEM (target) → O QUÊ (effect)
# ===========================================================================

@dataclass
class ActV3Step:
    """
    Struct ActV3Step — uma etapa de uma ação V3.
    "Para estes targets, com estas condições, aplica estes efeitos."
    """
    internal_description: str = ""
    details: ActV3StepDetails = field(default_factory=ActV3StepDetails)
    target: list[ActV3Target] = field(default_factory=list)
    effect: ActV3Effect = field(default_factory=ActV3Effect)


# ===========================================================================
# ActV3Proc  (Token 0x02000056)
# QUANDO a ação dispara + requisitos de ativação
# ===========================================================================

@dataclass
class ActV3Proc:
    """
    Define o trigger e os requisitos de ativação de uma ActV3Base.
    Extraído do struct ActV3Proc do Assembly-CSharp.dll.
    """

    # ── Triggers principais ──────────────────────────────────────────────────
    passive: bool = False
    activate_main: bool = False
    once_per_turn: bool = False
    on_play: bool = False
    on_play2: bool = False
    on_play_from_trigger: bool = False
    trigger: bool = False
    counter: bool = False
    on_attack: bool = False
    on_attack_leader: bool = False
    on_block: bool = False
    on_ko: bool = False
    on_ko_effect_only: bool = False
    after_battle_character: bool = False
    after_failed_ko: bool = False
    after_ko_character: bool = False
    end_of_turn: bool = False
    start_of_game: bool = False
    start_of_turn: bool = False
    start_of_main_phase: bool = False

    # ── Triggers de eventos ──────────────────────────────────────────────────
    card_drawn: bool = False
    drew_don_for_turn: bool = False
    on_rest: bool = False
    on_rest_by_opponent: bool = False
    my_don_is_returned: bool = False
    x_my_don_is_returned: int = 0
    you_deployed: bool = False
    you_deployed_trigger_character: bool = False
    you_rested_character: bool = False
    you_removed_character: bool = False
    you_bounced_opp_character: bool = False
    opp_activates_event: bool = False
    opp_plays_event: bool = False
    opp_activates_trigger: bool = False
    you_activate_trigger: bool = False
    opp_activates_event_cost_x_or_more: int = 0
    opponent_activates_blocker: bool = False
    opp_deploys_through_character: bool = False
    i_hit_leader: bool = False
    my_leader_hit: bool = False
    any_hit_leader: bool = False
    any_character_kod: bool = False
    opponent_character_kod: bool = False
    opp_loses_life: bool = False
    on_opponent_attack: bool = False
    life_sent_to_hand: bool = False
    life_sent_to_trash: bool = False
    life_sent_to_deck: bool = False
    life_sent_to_field: bool = False
    life_added_to_hand: bool = False
    don_is_returned: bool = False
    hand_sent_to_trash_my_effect: bool = False
    card_trashed_from_my_category: list[CardCategory] = field(default_factory=list)
    deck_out: bool = False

    # ── Replacement effects (interrupt) ──────────────────────────────────────
    pre_ko: bool = False
    pre_rest: bool = False
    pre_bounce: bool = False
    pre_trash: bool = False
    pre_deck_bottom: bool = False
    pre_send_to_top_life: bool = False
    pre_send_to_bottom_life: bool = False
    pre_character_ko_effect_only: list[CardCategory] = field(default_factory=list)
    pre_ally_ko: bool = False
    pre_ally_ko_effect_only: bool = False
    pre_ally_bounce: bool = False
    pre_ally_trash: bool = False
    pre_ally_deck_bottom: bool = False
    pre_ally_send_to_top_life: bool = False
    pre_ally_send_to_bottom_life: bool = False

    # ── Requisitos de ativação ────────────────────────────────────────────────
    don_x: int = 0
    available_don: int = 0
    don_x_or_more: int = 0
    don_x_or_less: int = 0
    opp_don_x_or_more: int = 0
    either_don_x_or_more: int = 0
    don_x_less_than_opp: bool = False
    self_rested_don: int = 0
    opp_rested_don: int = 0
    self_attached_don: int = 0
    opp_attached_don: int = 0
    your_turn: bool = False
    opponent_turn: bool = False
    leader_active: bool = False
    active: bool = False
    rested: bool = False
    first_turn_only: bool = False
    turn_x_or_later: int = 0
    trash_x_or_more: int = 0
    trash_events_x_or_more: int = 0
    cost_zero_exists: bool = False
    my_cost_x_or_more: int = 0
    characters_or_more: int = 0
    characters_or_less: int = 0
    opp_characters_or_more: int = 0
    opp_characters_or_less: int = 0
    hand_x_or_less: int = 0
    hand_x_or_more: int = 0
    life_x_or_more: int = 0
    life_x_or_less: int = 0
    combined_life_x_or_less: int = 0
    opp_life_x_or_more: int = 0
    opp_life_x_or_less: int = 0
    opp_lost_life: bool = False
    ally_cost_or_more: int = 0
    ally_cost_count: int = 0
    ally_name_not_in_play: str = ""
    ally_vanilla: bool = False
    cost_x_or_more_exists: int = 0
    self_cost_x_or_more_not_exists: int = 0
    ally_total_cost_or_more: int = 0
    face_down_life: int = 0
    face_up_life: int = 0
    any_face_up_life: bool = False
    less_or_eq_don: bool = False
    has_battled_character: bool = False
    any_opp_character_kod: bool = False
    either_player_zero_life: bool = False
    zero_life: bool = False
    leader_power_x_or_more: int = 0
    leader_power_zero: bool = False
    leader_category_required: list[CardCategory] = field(default_factory=list)
    strike_type_required: list[StrikeType] = field(default_factory=list)
    name_required: list[str] = field(default_factory=list)
    name_includes: str = ""
    color_count_or_more: int = 0
    field_is_only_category: list[CardCategory] = field(default_factory=list)
    leader_name_required: list[str] = field(default_factory=list)
    leader_name_includes: str = ""
    self_no_2_chars_pow_x_or_more: int = 0
    power_x_or_more: int = 0
    character_power_x_or_more: int = 0
    opp_char_power_x_or_more: int = 0
    character_category_x_power_or_more: object = None   # CategoryCount
    character_category_x_cost_or_more: object = None    # CategoryCount
    not_character_category_x_cost_or_more: list = field(default_factory=list)
    self_attached_don_count: int = 0
    self_rested_cards: int = 0
    self_rested_characters: int = 0
    self_rested_character_category: object = None       # CategoryCount
    self_character_category: object = None              # CategoryCount
    names_in_your_trash: list[str] = field(default_factory=list)

    # ── Special ──────────────────────────────────────────────────────────────
    usopp_leader: bool = False
    roger_silence: bool = False

    # ── Condições de aliados (V3PassiveInEffect extras) ──────────────────────
    no_base_x_or_more: int = 0
    opp_any_base_x_or_more: int = 0
    self_any_base_x_or_more: int = 0
    opp_char_base_x_or_more: int = 0
    self_no_char_base_x_or_more: int = 0
    opp_2_chars_base_x_or_more: int = 0
    opp_no_2_chars_base_x_or_more: int = 0
    name_in_your_deploy: str = ""
    name_owned: bool = False
    names_with_base_power_in_your_deploy: list = field(default_factory=list)
    names_with_power_on_your_side: list = field(default_factory=list)
    no_other_name_with_base_cost_in_your_deploy: list = field(default_factory=list)
    name_is_rested: str = ""
    another_character_of_category: list[CardCategory] = field(default_factory=list)
    acoc_color_req: list[CardColor] = field(default_factory=list)
    ally_base_cost_or_more: int = 0

    def is_replacement_effect(self) -> bool:
        """Verifica se é um replacement effect (PreKO, PreBounce, etc.)."""
        return (self.pre_ko or self.pre_rest or self.pre_bounce or
                self.pre_trash or self.pre_deck_bottom or
                self.pre_send_to_top_life or self.pre_send_to_bottom_life or
                bool(self.pre_character_ko_effect_only))

    def is_self_replacement_effect(self) -> bool:
        """Só replacement effects da própria carta (não aliados)."""
        return (self.pre_ko or self.pre_rest or self.pre_bounce or
                self.pre_trash or self.pre_deck_bottom or
                self.pre_send_to_top_life or self.pre_send_to_bottom_life)

    def is_ally_replacement_effect(self) -> bool:
        return (self.pre_ally_ko or self.pre_ally_ko_effect_only or
                self.pre_ally_bounce or self.pre_ally_trash or
                self.pre_ally_deck_bottom or self.pre_ally_send_to_top_life or
                self.pre_ally_send_to_bottom_life or
                bool(self.pre_character_ko_effect_only))


# ===========================================================================
# ActV3Base  (Token 0x02000055)
# Uma ação completa: proc + lista de steps
# ===========================================================================

@dataclass
class ActV3Base:
    """
    Struct ActV3Base — uma ação completa do sistema V3.
    Cada carta tem uma lista de ActV3Base em card_def.action_v3s.
    """
    internal_desc: str = ""
    status_text: str = ""          # texto exibido na UI (ex: "Rush", "Blocker")
    proc: ActV3Proc = field(default_factory=ActV3Proc)
    steps: list[ActV3Step] = field(default_factory=list)
    temp: bool = False             # True = ação concedida por efeito externo

    def __repr__(self) -> str:
        return f"ActV3Base({self.internal_desc!r}, temp={self.temp})"


# ===========================================================================
# CardAction  — sistema legado (ainda usado por algumas cartas antigas)
# ===========================================================================

@dataclass
class ActionTrigger:
    """Sistema legado de triggers."""
    passive: bool = False
    activate_main: bool = False
    once_per_turn: bool = False
    on_play: bool = False
    on_attack: bool = False
    on_block: bool = False
    on_ko: bool = False
    trigger: bool = False
    counter: bool = False
    end_of_turn: bool = False
    your_turn: bool = False
    opponent_turn: bool = False
    don_x: int = 0
    don_tap: int = 0
    don_minus: int = 0
    trash_x: int = 0
    self_tap: bool = False
    self_tap_characters: int = 0
    mandatory: bool = False
    life_reaches_zero: bool = False
    after_battle_character: bool = False
    after_ko_character: bool = False
    failed_ko: bool = False
    ally_character_pre_ko: bool = False
    ally_character_pre_ko_power_or_more: int = 0
    life_added_to_hand: bool = False
    don_is_returned: bool = False
    my_don_is_returned: bool = False
    opponent_deploys: bool = False
    opponent_attack: bool = False
    name_in_your_deploy: str = ""
    name_in_your_field: str = ""
    another_character_of_category: list[CardCategory] = field(default_factory=list)


@dataclass
class ActionEffect:
    """Sistema legado de efeitos."""
    draw_cards: int = 0
    buff_power: int = 0
    buff_combat: int = 0
    buff_leader: int = 0
    buff_other: int = 0
    ko_cost_or_less: int = 0
    ko_any_cost_or_less: bool = False
    return_cost_or_lower: int = 0
    cost_or_less: int = 0
    cost_or_more: int = 0
    gain_active_don: int = 0
    gain_rested_don: int = 0
    trash_cards: int = 0
    send_me_to_bottom: bool = False
    no_blocker: bool = False
    immune_in_combat: bool = False
    gain_rush: bool = False


@dataclass
class CardAction:
    """
    Sistema legado de ações (CardAction do C#).
    Ainda usado por algumas cartas de sets antigos.
    """
    action_trigger: ActionTrigger = field(default_factory=ActionTrigger)
    action_effect: ActionEffect = field(default_factory=ActionEffect)


# ===========================================================================
# ActivatedCardAction  — estado de execução em runtime
# ===========================================================================

@dataclass
class ActivatedCardAction:
    """
    Snapshot de uma ação sendo executada no GameplayLogicScript.
    Equivale à classe ActivatedCardAction do C#.

    Ciclo de vida:
        QueueUpV3Action() → acaPending.append()
        CheckPendingActions() → acaActive = acaPending.pop()
        DoV3ActionStep() → executa efeitos
        NextV3ActionStep() → avança step
        FinalizeV3Action() → limpa e resolve
    """

    # ── Ponteiros ────────────────────────────────────────────────────────────
    player_id: int = 0             # iPlayerID — dono da ação
    actor_id: int = 0              # iActorID — deck_unique_id do ator (UsesV3 = id != 0)
    action_idx: int = 0            # iActionIdx — índice em card_def.action_v3s
    action_step: int = 0           # iActionStep — passo atual
    action_target_idx: int = 0     # iActionTargetIdx — slot de alvo atual

    # Lista de listas: [step][slot] = [deck_unique_id, ...]
    target_ids: list[list[int]] = field(default_factory=list)

    # ── Alvos ────────────────────────────────────────────────────────────────
    prev_targets: list[int] = field(default_factory=list)    # alvos do passo anterior
    prev_names: list[str] = field(default_factory=list)      # nomes (NoDuplicateNames)

    # ── Dados salvos mid-ação ─────────────────────────────────────────────────
    saved_string: str = ""         # sSavedString (ex: nome declarado)
    saved_int: int = 0             # sSavedInt (ex: custo declarado)
    action_choices_stack: int = 0  # iActionChoicesStack

    # ── Escolha do jogador ───────────────────────────────────────────────────
    choice: ActionChoice = ActionChoice.NONE
    end_choice: bool = False
    use_end_choice: bool = False
    chose_top: bool = False        # bChoseTop (topo vs fundo da vida)
    chose_self: bool = False       # bChoseSelf

    # ── Contadores de progresso ──────────────────────────────────────────────
    cards_drawn: int = 0
    cards_trashed: int = 0
    don_returned: int = 0
    optional_don_returned: int = 0
    cards_tapped: int = 0
    cards_recalled: int = 0
    cards_deployed: int = 0
    cards_added_to_life: int = 0
    cards_sent_to_deck: int = 0
    cards_returned_from_trash: int = 0
    total_uses: int = 0

    # ── Flags de estado ──────────────────────────────────────────────────────
    is_free: bool = False              # bFree — sem custo de don
    is_trigger_chance: bool = False    # bIsTriggerChance
    ended_combat: bool = False         # bEndedCombat
    started_trigger: bool = False      # bStartedTrigger (vida do oponente)
    started_self_trigger: bool = False # bStartedSelfTrigger (própria vida)
    opponent_reaction: bool = False    # bOpponentReaction (ForceOpponent)
    action_finished: bool = False      # bActionFinished
    revealed_card: bool = False        # bRevealedCard

    # ── Remoção ──────────────────────────────────────────────────────────────
    removal_type: RemovalEffect = RemovalEffect.NONE
    removal_player: int = -1

    # ── Referência ao GameState (injetada pelo engine) ───────────────────────
    # Não serializado — referência viva durante execução
    _game_state: object = field(default=None, repr=False)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def uses_v3(self) -> bool:
        """UsesV3() do C# — ação usa o sistema V3 se actor_id != 0."""
        return self.actor_id != 0

    def actor_object(self, game_state=None) -> object:
        """Retorna o LiveCard ator pelo actor_id."""
        gs = game_state or self._game_state
        if gs:
            return gs.find_card_by_id(self.actor_id)
        return None

    def v3_base(self, game_state=None) -> ActV3Base | None:
        """V3Base() do C# — retorna a ActV3Base desta ação."""
        actor = self.actor_object(game_state)
        if actor and actor.card_def.action_v3s:
            actions = (actor.l_granted_actions +
                       actor.card_def.action_v3s)
            if 0 <= self.action_idx < len(actions):
                return actions[self.action_idx]
        return None

    def v3_step(self, game_state=None) -> ActV3Step | None:
        """V3Step() do C# — retorna o passo atual."""
        base = self.v3_base(game_state)
        if base and 0 <= self.action_step < len(base.steps):
            return base.steps[self.action_step]
        return None

    def v3_target(self, game_state=None) -> ActV3Target | None:
        """V3Target() do C# — retorna o ActV3Target atual."""
        step = self.v3_step(game_state)
        if step and 0 <= self.action_target_idx < len(step.target):
            return step.target[self.action_target_idx]
        return None

    def is_replacement_effect(self) -> bool:
        base = self.v3_base()
        return base is not None and base.proc.is_replacement_effect()

    def __repr__(self) -> str:
        return (f"ActivatedCardAction(actor={self.actor_id}, "
                f"action={self.action_idx}, step={self.action_step}, "
                f"v3={self.uses_v3()})")