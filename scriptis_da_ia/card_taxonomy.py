"""
card_taxonomy.py — VOCABULÁRIO ÚNICO "ação de carta → significado"
=================================================================
Fonte de verdade compartilhada por:
  - deck_analyzer.py  (FRONT-END: analisador estático de deck, api.py)
  - deck_profile.py   (MOTOR: eixos/papéis que alimentam a evaluate_state)

Antes essas tabelas viviam DUPLICADAS/PARTIDAS (arquétipo no deck_analyzer,
disrupção/papéis no deck_profile). Unificado 13/07 a pedido do usuário — um
lugar só, sem confusão. É DADO/VOCABULÁRIO puro (tabelas), NÃO lógica de
decisão: não fere a regra "um motor só" (essa é sobre decisão; isto é um
dicionário comum, como o card_effects_db).

Qualquer mudança de gramática (ex: saliência relativa, separar denial de
remoção) acontece AQUI e beneficia front + motor de uma vez. Depois de mexer:
re-rodar `knowledge/crosscheck_archetypes.py` (QA nos 55 decks reais).
"""

# ── Arquétipos (4 classes) ────────────────────────────────────────────────────
AGGRO = 'Aggro'
CONTROLE = 'Controle'
RAMP = 'Tempo/Ramp'
VIDA = 'Vida/Triggers'
ARCHETYPES = (AGGRO, CONTROLE, RAMP, VIDA)


# ── Pesos: ação da carta → arquétipo (× confiabilidade do gatilho) ────────────
# has_counter_value foi REMOVIDO (era ruído onipresente). Ramp e Controle
# separados. KO/debuff desinflados (comuns demais).
ACTION_WEIGHTS: dict[str, dict[str, int]] = {
    # Aggro
    'keyword_rush':          {AGGRO: 3},
    'gain_rush':             {AGGRO: 3},
    'keyword_double_attack': {AGGRO: 3},
    'gain_double_attack':    {AGGRO: 3},
    'keyword_unblockable':   {AGGRO: 3},
    'gain_unblockable':      {AGGRO: 3},
    'keyword_banish':        {AGGRO: 2},
    'gain_banish':           {AGGRO: 2},
    'buff_power':            {AGGRO: 2},
    'give_don':              {AGGRO: 2},
    # Controle
    'ko':                    {CONTROLE: 2},
    'debuff_power':          {CONTROLE: 2},
    'rest_opp_character':    {CONTROLE: 2},
    'bounce':                {CONTROLE: 2},
    'debuff_cost':           {CONTROLE: 2},
    'trash_from_hand':       {CONTROLE: 2},
    'give_don_opp':          {CONTROLE: 2},
    'lock_opp_don':          {CONTROLE: 2},
    # Ramp / Aceleração
    'add_don':               {RAMP: 3},
    'set_don_active':        {RAMP: 3},
    'buff_cost':             {RAMP: 2},
    'play_card':             {RAMP: 2},
    'play_from_deck':        {RAMP: 2},
    'play_from_trash':       {RAMP: 2},
    'add_from_trash':        {RAMP: 2},
    # Vida
    'gain_life':             {VIDA: 4},
    'attack_life':           {AGGRO: 2, CONTROLE: 1},
    'trash_own_life':        {VIDA: 1, RAMP: 1},
    # Defensivo
    'keyword_blocker':       {CONTROLE: 1, RAMP: 1},
    'gain_blocker':          {CONTROLE: 1, RAMP: 1},
}

# Confiabilidade por gatilho (multiplica o peso da ação)
TRIGGER_RELIABILITY: dict[str, float] = {
    'on_play': 1.0, 'activate_main': 1.0, 'main': 1.0, 'passive': 1.0,
    'your_turn': 0.7, 'opp_turn': 0.6, 'end_of_turn': 0.6,
    'when_attacking': 0.55,
    'counter': 0.4,
    'on_ko': 0.3,
    'trigger': 0.25,
}


# ── Disrupção/denial (miram o OPONENTE) — eixo do deck_profile ────────────────
DISRUPTION_ACTIONS = {
    'give_don_opp', 'lock_opp_don', 'lock_opp_character_refresh',
    'lock_opp_character_attack', 'rest_opp_character', 'debuff_power',
    'debuff_cost', 'bounce', 'ko', 'trash_character', 'negate_effect',
    'opp_trash_from_hand', 'place_opp_character_bottom_deck',
}

# Magnitude relativa do que cada AÇÃO destrava (prior de cold-start p/ ordenar
# eixos; a tunagem por self-play ajusta depois).
ACTION_MAGNITUDE = {
    'immunity': 30, 'negate_effect': 35, 'ko': 40, 'trash_character': 40,
    'bounce': 30, 'debuff_power': 20, 'gain_blocker': 25, 'gain_rush': 25,
    'gain_double_attack': 25, 'gain_unblockable': 20, 'buff_power': 15,
    'play_from_trash': 50, 'play_card': 30, 'give_don': 20,
    'draw': 20, 'look_top_deck': 15, 'add_to_hand': 15, 'add_from_trash': 25,
}

# Papéis de carta (universal, por AÇÃO/estrutura). Uma carta pode ter vários.
ROLE_BY_ACTION = {
    'look_top_deck': 'searcher', 'add_to_hand': 'searcher',
    'draw': 'draw_engine',
    'ko': 'removal', 'trash_character': 'removal',
    'debuff_power': 'power_reduction',
    'debuff_cost': 'cost_reduction', 'buff_cost': 'cost_reduction',
    'rest_opp_character': 'rest', 'lock_opp_character_refresh': 'freeze',
    'lock_opp_character_attack': 'freeze', 'lock_opp_don': 'don_denial',
    'give_don_opp': 'don_denial',
    'bounce': 'bounce', 'place_opp_character_bottom_deck': 'bounce',
    'add_don': 'ramp', 'set_don_active': 'ramp', 'give_don': 'ramp',
    'play_from_trash': 'recursion', 'add_from_trash': 'recursion',
    'gain_life': 'life_manipulation', 'trash_life': 'life_manipulation',
    'attack_life': 'life_manipulation',
    'gain_blocker': 'blocker', 'keyword_blocker': 'blocker',
    'immunity': 'protector', 'substitute_ko': 'protector',
    'substitute_removal': 'protector', 'negate_effect': 'protector',
    'trash_from_hand': 'trash_setup', 'trash_rest': 'trash_setup',
    'gain_rush': 'rush', 'keyword_rush': 'rush',
    'gain_double_attack': 'evasive', 'keyword_double_attack': 'evasive',
    'gain_unblockable': 'evasive', 'keyword_unblockable': 'evasive',
    'set_don_active': 'don_recovery', 'add_don': 'ramp',
    'play_card': 'combo_piece', 'play_from_deck': 'combo_piece',
}

# Condições que INVERTEM o sinal do termo (recurso "ruim" = ativa cartas)
INVERSION_CONDS = {'life_lte'}
# RECURSOS acumuláveis reais que viram escadaria (whitelist)
RESOURCE_CONDS = {
    'trash_gte', 'trash_lte', 'don_gte', 'don_lte',
    'don_on_field_gte', 'don_on_field_lte', 'deck_gte', 'deck_lte',
    'hand_gte', 'events_in_trash_gte', 'chars_gte',
}
