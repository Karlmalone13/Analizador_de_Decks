"""
optcg_engine
============
Motor de simulação de partidas do OPTCG (produção).

Fonte única de verdade das regras: decision_engine.py (Card, GameState,
DecisionEngine, EffectExecutor, OPTCGMatch, simular_matchup, load_cards_db,
build_real_deck, validar_deck, get_card_effects). Demais módulos do pacote:
    rules_facade.py        → eligible_cards, card_matches_filter, etc.
    counter_estimation.py  → decisão de DON em defesa/contra-ataque
    deck_census.py         → perfil estatístico do deck (aggro/control/etc)
    opponent_model.py      → Opponent Reading (Monte Carlo)

Este pacote NÃO importa nada automaticamente — cada módulo é importado
explicitamente por quem precisa dele (decision_engine.py, replay_optcg.py,
api.py, simulation_worker.py).

Nota: o porte Python fiel ao simulador oficial decompilado (Assembly-CSharp.dll
v1.40a — enums/models/action_system/card_power/validators/card_queries/
card_loader) NÃO está mais aqui. Foi movido para
_referencias/simulador-oficial/decompiled_python/ em 28/06/2026: é material
de consulta (nunca esteve integrado a este motor), não pacote de produção.
"""

__version__ = "1.0.0"
__game_version__ = "1.40a"
