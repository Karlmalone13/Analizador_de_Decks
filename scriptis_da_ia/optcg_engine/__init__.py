"""
optcg_engine
============
Motor de simulação do OPTCG — extraído do Assembly-CSharp.dll v1.40a.

Uso rápido:
    from optcg_engine import Simulator, DeckConfig
    from optcg_engine.enums import CardType, CardColor, CardCategory
    from optcg_engine.models import CardDefinition, LiveCard, PlayerState

Estrutura:
    enums.py          → CardType, CardColor, CardCategory (165), StrikeType,
                        ActionChoice, RemovalEffect, GameplayState
    models.py         → CardDefinition, LiveCard, PlayerState, GameState
    action_system.py  → ActV3Base, ActV3Proc, ActV3Step, ActV3StepDetails,
                        ActV3Target, ActV3Effect, ActV3Choice,
                        ActivatedCardAction, CardAction
    card_power.py     → card_power(), get_card_cost(), get_card_original_power()
    validators.py     → can_use_v3_action(), v3_passive_in_effect(),
                        check_card_is_viable_target_v3(),
                        can_use_v3_action_step()
    card_queries.py   → card_has_blocker(), card_has_rush(),
                        card_has_double_attack(), card_has_banish(),
                        card_is_immune_to_all(), card_is_combat_immune(),
                        card_cant_attack()
    card_loader.py    → CardLoader
    decision_engine.py → Card, GameStateSim, DecisionEngine, EffectExecutor,
                         OPTCGMatch, simular_matchup, load_cards_db,
                         build_real_deck, validar_deck, get_card_effects
"""

# Enums — sempre importáveis
from .enums import (
    CardType,
    CardColor,
    CardCategory,
    StrikeType,
    ActionChoice,
    RemovalEffect,
    GameplayState,
    ReplaySyncZone,
)

# Modelos de dados (das 34k linhas)
from .models import (
    CardDefinition,
    LiveCard,
    PlayerState,
    GameState,
    CategoryCount,
    StringCount,
)

# Sistema de ações (das 34k linhas)
from .action_system import (
    ActV3Base,
    ActV3Proc,
    ActV3Step,
    ActV3StepDetails,
    ActV3Target,
    ActV3Effect,
    ActV3Choice,
    ActivatedCardAction,
    CardAction,
    ActionTrigger,
    ActionEffect,
)

# Cálculo de poder e custo (das 34k linhas)
from .card_power import (
    card_power,
    get_card_cost,
    get_card_original_power,
    get_card_original_cost,
    calculate_base_power_changes,
)

# Validadores (das 34k linhas)
from .validators import (
    can_use_v3_action,
    v3_passive_in_effect,
    can_use_v3_action_step,
    check_card_is_viable_target_v3,
    remaining_valid_v3_targets,
    temp_check_viable_target,
)

# Queries de estado (das 34k linhas)
from .card_queries import (
    card_has_blocker,
    card_has_rush,
    card_has_double_attack,
    card_has_banish,
    card_is_immune_to_all,
    card_is_immune_to_noncombat,
    card_is_combat_immune,
    card_cant_be_removed_from_field,
    card_cant_attack,
)

# Loader de cartas reais
from .card_loader import CardLoader

# Motor de simulação
from .decision_engine import (
    Card,
    GameState as GameStateSim,
    DecisionEngine,
    EffectExecutor,
    OPTCGMatch,
    simular_matchup,
    load_cards_db,
    build_real_deck,
    validar_deck,
    get_card_effects,
)

__version__ = "1.0.0"
__game_version__ = "1.40a"