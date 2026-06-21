# -*- coding: utf-8 -*-
"""
Propostas de effects para as 209 cartas nao classificadas.
confidence: "certo" | "provavel" | "palpite"
"""

propostas = {}

def add(cid, effects, confidence, notes=""):
    propostas[cid] = {"effects": effects, "confidence": confidence, "notes": notes}

# ===== LOTE 1 (1-10) - revisado com decisoes do usuario =====

add("EB01-008",
    {"passive": {"once_per_turn": True, "steps": [{"action": "substitute_ko", "cost": {"action": "trash_from_hand", "filter_type": ["event", "stage"], "count": 1}}]}},
    "certo")

add("EB01-026",
    {"when_attacking": {"don_requirement": 1, "conditions": {"hand_lte": 1}, "steps": [{"action": "bounce", "count": 1, "cost_lte": 3, "target": "opp_character"}]}},
    "certo")

add("EB01-047",
    {"on_any_ko": {"steps": [{"action": "draw", "count": 1}, {"action": "trash_from_hand", "count": 1}]}},
    "certo")

add("EB02-009",
    {"activate_main": {"costs": [{"type": "rest_self_stage"}], "steps": [{"action": "transfer_don", "count": 1, "target": "friendly_character", "filter_type": "straw hat crew"}]}},
    "palpite", "transfer_don: move DON ja anexado entre characters, distinto de give_don/add_don")

add("EB02-039",
    {"main": {"costs": [{"type": "trash_from_hand", "filter_type": "germa 66", "power_lte": 4000, "count": 1}], "conditions": {"don_field_lte_opp": True}, "steps": [{"action": "play_from_trash", "count": 1, "power_range": [5000, 7000], "same_name_as_cost_target": True}]}},
    "certo", "corrigido apos esclarecimento do usuario")

add("EB03-008",
    {"on_play": {"steps": [{"action": "gain_attack_active", "count": 1, "filter_type": "sword"}]}, "when_attacking": {"steps": [{"action": "gain_attack_active", "count": 1, "filter_type": "sword"}]}, "activate_main": {"once_per_turn": True, "steps": [{"action": "debuff_power", "amount": 1000, "target": "opp_character", "duration": "this_turn"}]}},
    "provavel")

add("EB03-012",
    {"activate_main": {"costs": [{"type": "rest_self"}], "steps": [{"action": "choice", "options": [
        {"action": "rest_opp_don", "count": 1},
        {"action": "rest_opp_character", "count": 1, "filter_type": ["animal", "smile"], "cost_lte": 3}
    ]}]}},
    "certo", "estrutura choice conforme decisao do usuario")

add("EB03-027",
    {"on_play": {"steps": [{"action": "bounce", "count": 1, "power_eq": 7000, "power_base_only": True}]}},
    "certo")

add("EB04-012",
    {"activate_main": {"once_per_turn": True, "conditions": {"self_played_this_turn": True}, "steps": [{"action": "set_leader_active", "filter_type": "land of wano"}]}},
    "certo")

# ===== LOTE 2 (11-30) =====

add("OP01-008",
    {"on_play": {"steps": [{"action": "choice", "options": [
        {"action": "add_to_hand", "source": "life_area", "count": 1},
        {"action": "gain_rush", "duration": "this_turn"}
    ]}]}},
    "palpite", "texto sugere custo opcional ('you may') que habilita Rush -- nao e choice entre dois efeitos independentes, e um CUSTO opcional pra ganhar Rush. Revisar: pode ser so {cost: add_to_hand_from_life, steps:[gain_rush]}")

add("OP01-032",
    {"passive": {"don_requirement": 1, "conditions": {"opp_rested_characters_gte": 2}, "steps": [{"action": "buff_power", "amount": 2000, "target": "self"}]}},
    "certo")

add("OP01-062",
    {"passive": {"don_requirement": 1, "conditions": {"hand_lte": 4, "once_per_turn": True}, "steps": [{"action": "draw", "count": 1, "trigger_on": "activate_event"}]}},
    "provavel", "trigger_on='activate_event' e conceito novo -- efeito dispara quando VOCE ativa um Event, nao e on_play tradicional")

add("OP01-069",
    {"on_ko": {"steps": [{"action": "play_card", "source": "deck", "filter_name": "smiley", "count": 1}, {"action": "shuffle_deck"}]}},
    "provavel", "action 'shuffle_deck' pode ja existir implicito em outras -- conferir; senao e nova")

add("OP01-085",
    {"on_play": {"conditions": {"leader_type": "baroque works"}, "steps": [{"action": "lock_opp_character_attack", "count": 1, "cost_lte": 4, "duration": "until_end_of_opp_next_turn"}]}},
    "provavel", "lock_opp_character_attack (impedir atacar) e distinto de lock_opp_character_refresh (impedir ficar ativo) -- duas mecanicas diferentes, confirmar nome")

add("OP01-089",
    {"counter": {"conditions": {"leader_type": "the seven warlords of the sea"}, "steps": [{"action": "bounce", "count": 1, "cost_lte": 5}]}},
    "certo")

add("OP01-098",
    {"on_play": {"steps": [{"action": "look_top_deck", "reveal_filter": "artificial devil fruit smile", "count": 1, "add_to_hand": True}, {"action": "shuffle_deck"}]}},
    "provavel")

add("OP01-105",
    {"on_play": {"steps": [{"action": "reveal_opp_hand", "count": 2, "chosen_by": "self"}]}},
    "palpite", "action 'reveal_opp_hand' com escolha de quais 2 cards nao existe -- efeito de informacao pura, sem alterar estado de jogo alem da revelacao")

add("OP02-008",
    {"passive": {"don_requirement": 1, "conditions": {"life_lte": 2, "leader_type": "whitebeard pirates"}, "steps": [{"action": "gain_rush"}]}},
    "certo")

add("OP02-025",
    {"activate_main": {"once_per_turn": True, "conditions": {"own_characters_lte": 1}, "steps": [{"action": "buff_cost_discount", "amount": 1, "filter_type": "land of wano", "cost_gte": 3, "duration": "next_play_this_turn"}]}},
    "palpite", "desconto de custo para a PROXIMA carta jogada (nao instantaneo) -- buff_cost ja existe mas presume aplicar a um alvo em campo, nao a uma jogada futura da mao")

add("OP02-027",
    {"passive": {"conditions": {"all_own_don_rested": True}, "steps": [{"action": "immune_to_opp_removal"}]}},
    "provavel", "immune_to_opp_removal pode ser redundante com substitute_removal sem custo -- ou e protecao absoluta diferente (nao remove, ponto), revisar com substitute_removal de custo zero/nulo")

add("OP02-095",
    {"passive": {"conditions": {"any_character_cost_eq": 0}, "steps": [{"action": "gain_banish"}]}},
    "certo", "gain_banish ja existe no vocabulario (visto em keyword_only)")

add("OP03-001",
    {"when_attacking": {"steps": [{"action": "buff_power_per_trash", "cost_action": "trash_from_hand", "filter_type": ["event", "stage"], "amount_per_card": 1000, "duration": "battle_only", "target": "leader"}]}, "on_block": {"steps": [{"action": "buff_power_per_trash", "cost_action": "trash_from_hand", "filter_type": ["event", "stage"], "amount_per_card": 1000, "duration": "battle_only", "target": "leader"}]}},
    "palpite", "'buff_power_per_trash' com quantidade variavel (any number) e custo proporcional -- nao existe action assim, e bem diferente de buff_power fixo")

add("OP03-049",
    {"on_play": {"conditions": {"deck_lte": 20}, "steps": [{"action": "bounce", "count": 1, "cost_lte": 3}]}},
    "certo")

add("OP03-053",
    {"passive": {"don_requirement": 1, "conditions": {"deck_lte": 20}, "steps": [{"action": "buff_power", "amount": 2000, "target": "self"}]}},
    "certo")

add("OP03-070",
    {"on_play": {"costs": [{"type": "return_don", "count": 1}], "steps": [{"action": "choice", "options": [
        {"cost": {"action": "trash_from_hand", "filter_cost_eq": 5, "filter_type": "character"}, "action": "gain_rush", "duration": "this_turn"}
    ]}]}},
    "palpite", "estrutura aninhada custo-dentro-de-choice e nova combinacao -- revisar se choice deveria ser so no nivel de steps, nao dentro de custo composto")

add("OP03-091",
    {"on_play": {"steps": [{"action": "set_power_to_zero", "count": 1, "target": "opp_character", "conditions_target": {"no_base_effect": True}, "duration": "this_turn"}]}},
    "provavel", "set_power_to_zero (definir valor absoluto) e distinto de debuff_power (subtrair) -- conferir se ja existe algo assim no banco")

add("OP04-031",
    {"on_play": {"steps": [{"action": "lock_opp_character_refresh", "count": 3, "target": "rested_only", "applies_to": ["leader", "character"]}]}},
    "certo")

add("OP04-043",
    {"when_attacking": {"don_requirement": 1, "steps": [{"action": "choice", "options": [
        {"action": "bounce", "count": 1, "cost_lte": 2},
        {"action": "deck_bottom_rest", "count": 1, "cost_lte": 2, "target": "opp_character"}
    ]}]}},
    "provavel")

add("OP04-044",
    {"on_play": {"steps": [{"action": "bounce", "count": 1, "cost_lte": 8}, {"action": "bounce", "count": 1, "cost_lte": 3}]}},
    "certo", "dois bounces independentes, cada com seu teto de custo")


# correcoes do lote 2 apos decisoes do usuario
propostas["OP01-062"] = {"effects": {"on_activate_event": {"don_requirement": 1, "once_per_turn": True, "conditions": {"hand_lte": 4}, "steps": [{"action": "draw", "count": 1}]}}, "confidence": "certo", "notes": "don_requirement especifico desta carta, nao regra geral do trigger"}

propostas["OP03-001"] = {"effects": {"when_attacking": {"steps": [{"action": "buff_power_per_trash", "cost_action": "trash_from_hand", "filter_type": ["event", "stage"], "amount_per_card": 1000, "duration": "battle_only", "target": "leader", "count": "any"}]}, "on_block": {"steps": [{"action": "buff_power_per_trash", "cost_action": "trash_from_hand", "filter_type": ["event", "stage"], "amount_per_card": 1000, "duration": "battle_only", "target": "leader", "count": "any"}]}}, "confidence": "certo", "notes": "action nova buff_power_per_trash confirmada pelo usuario"}

propostas["OP03-070"] = {"effects": {"on_play": {"costs": [{"type": "return_don", "count": 1}], "steps": [{"action": "choice", "options": [
    {"cost": {"action": "trash_from_hand", "filter_cost_eq": 5, "filter_type": "character"}, "action": "gain_rush", "duration": "this_turn"}
]}]}}, "confidence": "certo", "notes": "estrutura aninhada (custo dentro de opcao de choice) confirmada pelo usuario"}

propostas["OP01-105"] = {"effects": {"on_play": {"steps": [{"action": "reveal_opp_hand_choice", "count": 2, "chosen_by": "self"}]}}, "confidence": "certo", "notes": "action de informacao pura, confirmada pelo usuario"}

# ===== LOTE 3 (31-50) =====

add("OP04-048",
    {"on_play": {"steps": [{"action": "return_hand_to_deck_and_draw_equal", "count": "hand_size"}, {"action": "shuffle_deck"}]}},
    "palpite", "action 'return_hand_to_deck_and_draw_equal' e mecanica de mulligan tardio -- combina return+shuffle+draw em sequencia atomica, talvez precise ser 3 steps separados em vez de 1 action composta")

add("OP04-072",
    {"opp_turn": {"once_per_turn": True, "don_requirement": -2, "costs": [{"type": "rest_self"}], "steps": [{"action": "ko", "count": 1, "cost_lte": 4, "target": "opp_character"}]}},
    "provavel", "don_requirement negativo (-2) representa retornar DON ao deck como custo -- confirmar se esse e o padrao usado em outras cartas com 'DON!! -N'")

add("OP04-080",
    {"on_play": {"steps": [{"action": "gain_attack_active", "count": 1, "filter_type": "dressrosa"}]}},
    "certo", "reusa gain_attack_active do lote 1")

add("OP04-086",
    {"passive": {"don_requirement": 1, "trigger_on": "battle_ko_opp", "steps": [{"action": "draw", "count": 2}, {"action": "trash_from_hand", "count": 2}]}},
    "provavel", "trigger_on='battle_ko_opp' e especifico -- dispara quando ESTE character battles E KOs o oponente, distinto de on_ko (que e quando ELE morre) ou on_any_ko (qualquer um)")

add("OP04-096",
    {"passive": {"conditions": {"leader_type": "dressrosa"}, "steps": [{"action": "gain_attack_on_play_turn", "filter_type": "dressrosa"}]}},
    "provavel", "gain_attack_on_play_turn = pode atacar Characters no turno em que e jogado (diferente de Rush, que e atacar Leader no turno em que e jogado -- aqui e atacar CHARACTERS no turno de jogada)")

add("OP05-003",
    {"passive": {"conditions": {"other_character_power_gte": 7000}, "steps": [{"action": "gain_rush"}]}},
    "certo")

add("OP05-040",
    {"passive": {"conditions": {"leader_name": "donquixote doflamingo"}, "steps": [{"action": "lock_opp_character_refresh", "cost_lte": 5, "applies_to": ["self", "opponent"]}]}, "end_of_turn": {"conditions": {"don_field_eq": 10}, "steps": [{"action": "ko", "target": "all_rested_characters", "cost_lte": 5, "applies_to": ["self", "opponent"]}, {"action": "trash_self_stage"}]}},
    "palpite", "lock_opp_character_refresh aplicado a AMBOS os lados (self e opponent) e novo -- a action ate agora so cobria oponente. Tambem 'trash_self_stage' (trashar a si mesmo, sendo um Stage) e novo")

add("OP05-042",
    {"on_play": {"steps": [{"action": "lock_opp_character_attack", "count": 1, "cost_lte": 7, "duration": "until_start_of_my_next_turn"}]}},
    "certo", "reusa lock_opp_character_attack")

add("OP05-049",
    {"when_attacking": {"don_requirement": 1, "steps": [{"action": "bounce", "count": 1, "cost_lte": 3}]}},
    "certo")

add("OP05-070",
    {"passive": {"don_requirement": 1, "conditions": {"don_field_gte": 8}, "steps": [{"action": "gain_rush"}]}},
    "certo")

add("OP05-079",
    {"on_play": {"steps": [{"action": "deck_bottom_rest", "count": 3, "source": "opp_trash", "order": "any"}]}},
    "provavel", "deck_bottom_rest hoje provavelmente assume source=self trash -- aqui o source e o TRASH DO OPONENTE, confirmar se campo source aceita esse valor")

add("OP05-097",
    {"your_turn": {"steps": [{"action": "buff_cost_discount_hand", "amount": 1, "filter_type": "celestial dragons", "cost_gte": 2}]}},
    "certo", "reusa buff_cost_discount_hand -- mas aqui e passivo durante seu turno (sem gatilho unico), nao 'proxima carta' como OP02-025. Diferenca: aplica a TODAS as compras desse tipo durante o turno, nao so a primeira")

add("OP05-099",
    {"opp_turn": {"costs": [{"type": "rest_self"}], "steps": [{"action": "choice", "options": [
        {"action": "opp_may_trash_top_life", "count": 1},
        {"action": "debuff_power", "amount": 2000, "target": "opp_character_or_leader", "duration": "this_turn"}
    ]}]}},
    "palpite", "'opp_may_trash_top_life' e action nova -- e uma escolha do OPONENTE, nao sua (se oponente nao trashar Life, VOCE aplica debuff). Choice aqui tem agente diferente do choice anterior (era sempre o jogador ativo escolhendo)")

add("OP06-002",
    {"passive": {"conditions": {"self_power_gte": 7000}, "steps": [{"action": "gain_banish"}]}},
    "certo")

add("OP06-014",
    {"opp_turn": {"steps": [{"action": "buff_power_per_trash", "cost_action": "trash_from_hand", "filter_type": "film", "amount_per_card": 1000, "duration": "battle_only", "target": "leader_or_character", "count": "any"}]}},
    "certo", "reusa buff_power_per_trash")

add("OP06-047",
    {"on_play": {"steps": [{"action": "opp_return_hand_to_deck_and_draw", "draw_count": 5}, {"action": "shuffle_deck", "target": "opponent"}]}},
    "palpite", "versao do OP04-048 mas aplicada ao OPONENTE com numero FIXO de draws (5), nao igual ao tamanho da mao -- mecanica parecida mas parametros diferentes, action separada ou reusar com 'target' e 'draw_count' parametrico?")

add("OP06-083",
    {"passive": {"steps": [{"action": "cannot_attack"}]}, "activate_main": {"costs": [{"type": "ko_self_or_other", "filter_type": "thriller bark pirates"}], "steps": [{"action": "negate_effect", "target": "self", "duration": "this_turn"}]}},
    "provavel", "'cannot_attack' como restricao permanente (nao condicional) e novo. negate_effect ja deve existir (visto em OP09 cartas la na frente) -- confirmar nome exato quando chegar la")

add("OP06-086",
    {"on_play": {"steps": [{"action": "play_from_trash", "count": 1, "cost_lte": 4}, {"action": "play_from_trash", "count": 1, "cost_lte": 2, "rested": True}]}},
    "certo", "reusa play_from_trash, um ativo e um rested -- confirmar se campo 'rested' (bool) ja existe no vocabulario para play_from_trash")

add("OP06-088",
    {"passive": {"conditions": {"leader_type": "dressrosa", "leader_active": True}, "steps": [{"action": "buff_power", "amount": 2000, "target": "self"}]}},
    "certo", "condicao 'leader_active' (leader nao estar rested) e nova combinacao -- confirmar se campo existe")

add("OP06-092",
    {"on_play": {"steps": [{"action": "choice", "options": [
        {"action": "ko", "count": 1, "cost_lte": 4, "target": "opp_character"},
        {"action": "deck_bottom_rest", "count": 3, "source": "opp_trash", "order": "any"}
    ]}]}},
    "certo", "choice entre dois efeitos completos -- reusa deck_bottom_rest com source=opp_trash do OP05-079")

add("OP06-098",
    {"activate_main": {"costs": [{"type": "rest_don", "count": 1}, {"type": "rest_self_stage"}], "conditions": {"leader_type": "thriller bark pirates"}, "steps": [{"action": "play_from_trash", "count": 1, "filter_type": "thriller bark pirates", "cost_lte": 2, "rested": True}]}},
    "certo")


# correcoes lote 3 apos decisoes do usuario
propostas["OP04-048"]["effects"] = {"on_play": {"steps": [{"action": "mulligan_hand_equal"}]}}
propostas["OP04-048"]["confidence"] = "certo"
propostas["OP06-047"]["effects"] = {"on_play": {"steps": [{"action": "mulligan_hand_fixed", "draw_count": 5, "target": "opponent"}]}}
propostas["OP06-047"]["confidence"] = "certo"
propostas["OP04-086"]["effects"] = {"on_battle_ko_opp": {"don_requirement": 1, "steps": [{"action": "draw", "count": 2}, {"action": "trash_from_hand", "count": 2}]}}
propostas["OP04-086"]["confidence"] = "certo"
propostas["OP04-096"]["effects"] = {"passive": {"conditions": {"leader_type": "dressrosa"}, "steps": [{"action": "gain_attack_characters_on_play", "filter_type": "dressrosa"}]}}
propostas["OP04-096"]["confidence"] = "certo"
propostas["OP05-040"]["effects"] = {"passive": {"conditions": {"leader_name": "donquixote doflamingo"}, "steps": [{"action": "lock_opp_character_refresh", "cost_lte": 5}, {"action": "lock_self_character_refresh", "cost_lte": 5}]}, "end_of_turn": {"conditions": {"don_field_eq": 10}, "steps": [{"action": "ko", "target": "all_rested_characters", "cost_lte": 5, "applies_to": ["self", "opponent"]}, {"action": "trash_self_stage"}]}}
propostas["OP05-040"]["confidence"] = "certo"
propostas["OP05-099"]["effects"] = {"opp_turn": {"costs": [{"type": "rest_self"}], "steps": [{"action": "choice", "decided_by": "opponent", "options": [
    {"action": "opp_may_trash_top_life", "count": 1},
    {"action": "debuff_power", "amount": 2000, "target": "opp_character_or_leader", "duration": "this_turn"}
]}]}}
propostas["OP05-099"]["confidence"] = "certo"
propostas["OP06-086"]["effects"]["on_play"]["steps"][1]["rested"] = True

# ===== LOTE 4 (51-70) =====

add("OP06-117",
    {"activate_main": {"once_per_turn": True, "costs": [{"type": "rest_self"}, {"type": "rest_named", "filter_name": "enel"}], "steps": [{"action": "ko", "target": "all_opp_characters", "cost_lte": 2}]}},
    "certo", "custo composto: rest self + rest carta nomeada propria")

add("OP07-001",
    {"activate_main": {"once_per_turn": True, "steps": [{"action": "transfer_don", "count": 2, "target": "friendly_character"}]}},
    "certo", "reusa transfer_don sem filtro de tipo")

add("OP07-002",
    {"on_play": {"steps": [{"action": "set_power", "amount": 0, "count": 1, "target": "opp_character", "duration": "this_turn"}]}},
    "certo", "reusa set_power")

add("OP07-026",
    {"on_play": {"steps": [{"action": "choice", "options": [
        {"action": "lock_opp_character_refresh", "count": 1, "target": "rested_only"},
        {"action": "lock_opp_don_refresh", "count": 1, "target": "rested_only"}
    ]}]}},
    "certo", "choice entre travar character OU don do oponente")

add("OP07-047",
    {"activate_main": {"costs": [{"type": "return_self_to_hand"}], "conditions": {"opp_hand_gte": 6}, "steps": [{"action": "deck_bottom_rest", "count": 1, "source": "opp_hand", "chosen_by": "opponent"}]}},
    "palpite", "'return_self_to_hand' como custo (voltar o proprio character pra mao) e novo. 'source: opp_hand, chosen_by: opponent' tambem novo -- oponente escolhe qual carta da PROPRIA mao vai pro fundo do deck")

add("OP07-090",
    {"on_play": {"steps": [{"action": "opp_trash_from_hand", "count": 1, "chosen_by": "opponent"}, {"action": "opp_reveal_hand"}, {"action": "draw", "count": 1, "target": "opponent"}]}},
    "provavel", "opp_trash_from_hand (oponente trasha propria carta) e opp_reveal_hand (informacao) sao novas, mas seguem padrao ja estabelecido de prefixo opp_ pra efeitos que afetam estado do oponente")

add("OP08-001",
    {"activate_main": {"once_per_turn": True, "steps": [{"action": "transfer_don", "count": 3, "target": "friendly_character", "filter_type": ["animal", "drum kingdom"], "split": True}]}},
    "palpite", "'split: true' indica que os 3 DON podem ir pra characters DIFERENTES (1 cada, ate 3) -- diferente de transfer_don simples que manda todos pro mesmo alvo. Confirmar se e essa a leitura")

add("OP08-022",
    {"on_play": {"conditions": {"leader_type": "minks"}, "steps": [{"action": "lock_opp_character_refresh", "count": 2, "cost_lte": 5, "target": "rested_only"}]}},
    "certo")

add("OP08-023",
    {"on_play": {"steps": [{"action": "lock_opp_character_refresh", "count": 1, "cost_lte": 7, "target": "rested_only"}]}, "when_attacking": {"steps": [{"action": "lock_opp_character_refresh", "count": 1, "cost_lte": 7, "target": "rested_only"}]}},
    "certo")

add("OP08-024",
    {"when_attacking": {"steps": [{"action": "lock_opp_character_refresh", "count": 1, "cost_lte": 4, "target": "rested_only"}]}},
    "certo")

add("OP08-025",
    {"on_play": {"steps": [{"action": "lock_opp_character_refresh", "count": 1, "cost_lte": 3, "target": "rested_only"}]}},
    "certo")

add("OP08-026",
    {"when_attacking": {"don_requirement": 1, "steps": [{"action": "lock_opp_character_refresh", "count": 1, "cost_lte": 1, "target": "rested_only"}]}},
    "certo")

add("OP08-042",
    {"when_attacking": {"don_requirement": 1, "steps": [{"action": "bounce", "count": 1, "cost_lte": 3}]}},
    "certo")

add("OP08-043",
    {"on_play": {"conditions": {"leader_type": "whitebeard pirates", "life_lte": 2}, "steps": [{"action": "lock_opp_character_attack", "target": "all_opp_characters", "duration": "until_end_of_opp_next_turn", "unless_opp_pays": {"action": "trash_from_hand", "count": 2}}]}},
    "palpite", "'unless_opp_pays' e estrutura totalmente nova -- efeito condicional que o OPONENTE pode pagar um custo recorrente (a cada ataque) pra ignorar a restricao. Mais complexo que choice simples")

add("OP08-045",
    {"passive": {"steps": [{"action": "substitute_removal", "cost": {"action": "trash_self"}, "extra_steps": [{"action": "draw", "count": 1}]}]}},
    "certo", "reusa substitute_removal -- custo e trashar a si mesmo, com efeito extra de draw")

add("OP08-046",
    {"your_turn": {"once_per_turn": True, "trigger_on": "own_character_removed_by_own_effect", "conditions": {"opp_hand_gte": 5}, "steps": [{"action": "deck_bottom_rest", "count": 1, "source": "opp_hand", "chosen_by": "opponent"}, {"action": "rest_self"}]}},
    "palpite", "trigger_on='own_character_removed_by_own_effect' e muito especifico -- dispara quando VOCE remove um proprio character com seu proprio efeito. Raro, mas preciso confirmar se vale trigger novo ou encaixar em outro existente")


# correcoes lote 4 apos decisoes do usuario
propostas["OP07-047"]["effects"] = {"activate_main": {"costs": [{"type": "return_self_to_hand"}], "conditions": {"opp_hand_gte": 6}, "steps": [{"action": "deck_bottom_rest", "count": 1, "source": "opp_hand", "chosen_by": "opponent"}]}}
propostas["OP07-047"]["confidence"] = "certo"
propostas["OP08-001"]["effects"] = {"activate_main": {"once_per_turn": True, "steps": [{"action": "transfer_don", "count": 3, "target": "friendly_character", "filter_type": ["animal", "drum kingdom"], "distribution": "free"}]}}
propostas["OP08-001"]["confidence"] = "certo"
propostas["OP08-043"]["effects"] = {"on_play": {"conditions": {"leader_type": "whitebeard pirates", "life_lte": 2}, "steps": [{"action": "lock_opp_character_attack", "target": "all_opp_characters", "duration": "until_end_of_opp_next_turn", "unless_opp_pays": {"action": "trash_from_hand", "count": 2}}]}}
propostas["OP08-043"]["confidence"] = "certo"
propostas["OP08-046"]["effects"] = {"your_turn": {"once_per_turn": True, "trigger": "on_character_removed_by_my_effect", "conditions": {"opp_hand_gte": 5}, "steps": [{"action": "deck_bottom_rest", "count": 1, "source": "opp_hand", "chosen_by": "opponent"}, {"action": "rest_self"}]}}
propostas["OP08-046"]["confidence"] = "certo"

# ===== LOTE 5 (71-90) =====

add("OP08-047",
    {"on_play": {"steps": [{"action": "choice", "options": [
        {"cost": {"action": "bounce_self_other", "exclude_self": True, "count": 1}, "action": "bounce", "count": 1, "cost_lte": 6}
    ]}]}},
    "palpite", "'bounce_self_other' (devolver outro proprio character, nao este) e custo opcional que habilita um segundo bounce -- estrutura custo-opcional-habilita-efeito, ja vista em OP01-008")

add("OP08-049",
    {"on_play": {"steps": [{"action": "look_top_deck", "count": 1, "place": "top_or_bottom", "chosen_by": "self"}, {"action": "gain_rush", "conditions": {"revealed_type": "whitebeard pirates"}, "duration": "this_turn"}]}},
    "certo")

add("OP08-082",
    {"activate_main": {"costs": [{"type": "rest_don", "count": 1}, {"type": "rest_self"}]}, "steps_note": "custo composto opcional (rest self e 'you may')"},
    "palpite", "erro de estrutura -- preciso revisar, custo 'rest self' e opcional (you may) mas 'rest 1 don' nao e marcado como opcional no texto. Revisar antes de finalizar")

add("OP08-083",
    {"passive": {"don_requirement": 1, "trigger": "your_turn", "steps": [{"action": "debuff_cost", "amount": 1, "target": "all_opp_characters"}]}},
    "certo")

add("OP08-088",
    {"on_play": {"steps": [{"action": "buff_cost", "amount": 1, "count": 1, "target": "own_character", "duration": "until_end_of_opp_next_turn"}]}},
    "certo", "buff_cost aumentando custo do PROPRIO character -- efeito negativo intencional (ex: pra evitar synergy de oponente ou setup futuro)")

add("OP09-001",
    {"opp_turn": {"once_per_turn": True, "trigger": "on_opp_attack_declared", "steps": [{"action": "buff_power", "amount": 1000, "target": "opp_leader_or_character", "duration": "this_turn"}]}},
    "palpite", "buff_power no ALVO DO OPONENTE de +1000 parece contraintuitivo (por que eu buffaria o oponente?) -- mas o texto diz isso literalmente. Pode ser efeito de baixo custo pra habilitar outra sinergia (ex: 'power gte X'). Confirmar leitura")

add("OP09-003",
    {"when_attacking": {"steps": [{"action": "buff_power", "amount": 2000, "target": "opp_character", "duration": "this_turn"}]}},
    "palpite", "mesma estranheza do OP09-001 -- buff no character do OPONENTE durante seu proprio ataque. Pode ser carta de suporte a combo proprio (ex: ativar 'opp power gte' de outra carta), mas seria bom confirmar se nao e erro de leitura minha (devia ser debuff?)")

add("OP09-009",
    {"on_play": {"steps": [{"action": "ko", "count": 1, "power_lte": 6000, "target": "opp_character"}]}},
    "certo")

add("OP09-011",
    {"activate_main": {"costs": [{"type": "rest_self"}], "conditions": {"leader_type": "red-haired pirates"}, "steps": [{"action": "buff_power", "amount": 2000, "target": "opp_character", "duration": "this_turn"}]}},
    "palpite", "terceira carta com buff em character do oponente -- comecando a parecer padrao real, nao erro. Mesma duvida do OP09-001/003")

add("OP09-012",
    {"passive": {"steps": [{"action": "substitute_ko", "filter_name": "bonk punch", "cost": {"action": "trash_self"}}]}},
    "certo", "substitute_ko mas o alvo protegido e OUTRO character nomeado, nao 'this'. Confirma se substitute_ko aceita filter_name != self")

add("OP09-017",
    {"passive": {"don_requirement": 1, "conditions": {"leader_power_gte": 7000, "leader_type": "kid pirates"}, "steps": [{"action": "gain_rush"}]}},
    "certo")

add("OP09-021",
    {"activate_main": {"costs": [{"type": "rest_self_stage"}], "conditions": {"leader_type": "red-haired pirates"}, "steps": [{"action": "buff_power", "amount": 1000, "target": "opp_character", "duration": "this_turn"}]}},
    "palpite", "quarta ocorrencia do mesmo padrao 'buff power no character do oponente' -- definitivamente padrao real do jogo, nao erro meu")

add("OP09-033",
    {"on_play": {"conditions": {"own_rested_characters_gte": 2}, "steps": [{"action": "immune_to_opp_removal", "filter_type": ["odyssey", "straw hat crew"], "duration": "until_end_of_opp_next_turn"}]}},
    "certo", "reusa immune_to_opp_removal, mas com duracao temporaria em vez de permanente -- confirmar se action aceita campo duration")

add("OP09-058",
    {"main": {"steps": [{"action": "opp_choice_bounce", "cost_lte": 6, "chosen_by": "opponent"}]}, "trigger": {"steps": [{"action": "bounce", "count": 1, "cost_lte": 3}]}},
    "provavel", "opp_choice_bounce = oponente escolhe QUAL dos proprios characters volta pra mao (nao voce escolhe). Distinto de bounce normal onde voce escolhe o alvo")

add("OP09-073",
    {"when_attacking": {"costs": [{"type": "return_don", "count": "1_or_more", "chosen_by": "self"}], "steps": [{"action": "buff_power", "amount": 2000, "count": 2, "target": "opp_character", "duration": "this_turn"}]}},
    "provavel", "custo com quantidade variavel escolhida pelo proprio jogador ('1 or more') e novo -- diferente de count fixo. Quinta ocorrencia do padrao buff-oponente")

add("OP09-085",
    {"on_play": {"steps": [{"action": "play_from_trash", "count": 1, "filter_type": "thriller bark pirates", "cost_lte": 2, "rested": True}]}},
    "certo")

add("OP09-087",
    {"on_play": {"conditions": {"opp_hand_gte": 5}, "steps": [{"action": "opp_trash_from_hand", "count": 1, "chosen_by": "opponent"}]}},
    "certo", "reusa opp_trash_from_hand do lote 4")

add("OP09-097",
    {"counter": {"steps": [{"action": "negate_effect", "count": 1, "target": "opp_leader_or_character", "duration": "this_turn"}, {"action": "buff_power", "amount": 4000, "target": "opp_leader_or_character", "duration": "this_turn"}]}, "trigger": {"steps": [{"action": "negate_effect", "count": 1, "target": "opp_leader_or_character", "duration": "this_turn"}]}},
    "certo", "sexta ocorrencia do padrao buff-no-oponente -- aqui fica claro o motivo: negar efeito + dar power e um TRADE bom pra voce porque negar e mais valioso que o power dado")

add("OP09-098",
    {"main": {"conditions": {"leader_type": "blackbeard pirates"}, "steps": [{"action": "negate_effect", "count": 1, "target": "opp_character", "duration": "this_turn"}, {"action": "ko", "count": 1, "target": "opp_character", "conditions_target": {"cost_lte": 4}, "depends_on_previous": True}]}, "trigger": {"steps": [{"action": "negate_effect", "count": 1, "target": "opp_leader_or_character", "duration": "this_turn"}]}},
    "provavel", "'depends_on_previous' (segundo step so se aplica ao MESMO alvo do primeiro) e estrutura nova -- confirmar se e necessario ou se 'target' generico ja implica isso")

add("OP09-111",
    {"trigger": {"conditions": {"leader_type": "egghead", "opp_hand_gte": 6}, "steps": [{"action": "opp_trash_from_hand", "count": 2, "chosen_by": "opponent"}]}},
    "certo")


# CORRECAO CRITICA lote 5: as 6 cartas eram DEBUFF, nao buff -- erro de leitura de sinal
propostas["OP09-001"]["effects"] = {"opp_turn": {"once_per_turn": True, "trigger": "on_opp_attack_declared", "steps": [{"action": "debuff_power", "amount": 1000, "target": "opp_leader_or_character", "duration": "this_turn"}]}}
propostas["OP09-001"]["confidence"] = "certo"
propostas["OP09-001"]["notes"] = "CORRIGIDO: era debuff_power -1000, eu tinha lido como buff +1000"

propostas["OP09-003"]["effects"] = {"when_attacking": {"steps": [{"action": "debuff_power", "amount": 2000, "target": "opp_character", "duration": "this_turn"}]}}
propostas["OP09-003"]["confidence"] = "certo"
propostas["OP09-003"]["notes"] = "CORRIGIDO: era debuff_power -2000"

propostas["OP09-011"]["effects"] = {"activate_main": {"costs": [{"type": "rest_self"}], "conditions": {"leader_type": "red-haired pirates"}, "steps": [{"action": "debuff_power", "amount": 2000, "target": "opp_character", "duration": "this_turn"}]}}
propostas["OP09-011"]["confidence"] = "certo"
propostas["OP09-011"]["notes"] = "CORRIGIDO: era debuff_power -2000"

propostas["OP09-021"]["effects"] = {"activate_main": {"costs": [{"type": "rest_self_stage"}], "conditions": {"leader_type": "red-haired pirates"}, "steps": [{"action": "debuff_power", "amount": 1000, "target": "opp_character", "duration": "this_turn"}]}}
propostas["OP09-021"]["confidence"] = "certo"
propostas["OP09-021"]["notes"] = "CORRIGIDO: era debuff_power -1000"

propostas["OP09-073"]["effects"] = {"when_attacking": {"costs": [{"type": "return_don", "count": "1_or_more", "chosen_by": "self"}], "steps": [{"action": "debuff_power", "amount": 2000, "count": 2, "target": "opp_character", "duration": "this_turn"}]}}
propostas["OP09-073"]["confidence"] = "certo"
propostas["OP09-073"]["notes"] = "CORRIGIDO: era debuff_power -2000 em ate 2 characters"

propostas["OP09-097"]["effects"] = {"counter": {"steps": [{"action": "negate_effect", "count": 1, "target": "opp_leader_or_character"}, {"action": "debuff_power", "amount": 4000, "target": "same_as_negated", "duration": "this_turn"}]}, "trigger": {"source": "life", "steps": [{"action": "negate_effect", "count": 1, "target": "opp_leader_or_character", "duration": "this_turn"}]}}
propostas["OP09-097"]["confidence"] = "certo"
propostas["OP09-097"]["notes"] = "CORRIGIDO: era debuff -4000 no MESMO alvo que teve efeito negado (same_as_negated, novo campo similar a same_name_as_cost_target). Trigger marcado source=life pois usuario indicou 'vindo da vida'"

# ===== LOTE 6 (93-110) =====

add("OP10-033",
    {"on_play": {"conditions": {"own_rested_characters_gte": 2, "filter_type_condition": "odyssey"}, "steps": [{"action": "lock_opp_don_refresh", "count": 1}]}},
    "certo", "reusa lock_opp_don_refresh agora implementado")

add("OP10-043",
    {"on_play": {"costs": [{"type": "rest_named_or_type", "filter_type": "dressrosa", "card_kind": ["leader", "stage"]}], "steps": [{"action": "gain_banish", "count": 1, "filter_name": "monkey.d.luffy", "duration": "this_turn"}]}},
    "palpite", "custo 'rest 1 of your Dressrosa type Leader OR Stage' e estrutura nova -- rest_named_or_type cobre escolha entre 2 TIPOS de card (Leader ou Stage), nao 2 alvos especificos como o choice anterior")

add("OP10-046",
    {"on_play": {"steps": [{"action": "bounce", "count": 1, "cost_lte": 5}]}},
    "certo")

add("OP10-049",
    {"passive": {"steps": [{"action": "substitute_removal", "filter_cost_lte": 7, "exclude": "sabo", "cost": {"action": "bounce_self"}}]}},
    "certo", "reusa substitute_removal -- custo e bounce do proprio (acao nova 'bounce_self' como tipo de custo)")

add("OP10-066",
    {"opp_turn": {"once_per_turn": True, "costs": [{"type": "rest_don", "count": 2}], "steps": [{"action": "rest_opp_character", "count": 1, "cost_lte": 4}]}},
    "certo")

add("OP10-074",
    {"passive": {"once_per_turn": True, "steps": [{"action": "substitute_ko", "cost": {"action": "rest_own_don", "count": 2, "active_only": True}}]}},
    "certo", "reusa substitute_ko -- novo tipo de custo 'rest_own_don' (distinto de rest_don que e custo de ATIVAR, aqui e custo de SUBSTITUICAO)")

add("OP10-085",
    {"passive": {"don_requirement": 1, "conditions": {"trash_gte": 8}, "steps": [{"action": "gain_rush"}]}},
    "certo")

add("OP10-093",
    {"activate_main": {"costs": [{"type": "trash_self"}], "steps": [{"action": "buff_cost", "amount": 3, "count": 1, "target": "own_character", "filter_color": "black", "duration": "until_opp_turn_end"}]}},
    "certo", "buff_cost (aumentar custo) em character PROPRIO -- mesma mecanica negativa-intencional vista antes em OP08-088")

add("OP10-096",
    {"main": {"steps": [{"action": "ko", "count": 1, "target": "opp_character", "filter_type": "the seven warlords of the sea", "cost_lte": 8}]}, "trigger": {"steps": [{"action": "ko", "count": 1, "target": "opp_character", "filter_type": "the seven warlords of the sea", "cost_lte": 4}]}},
    "certo")

add("OP11-006",
    {"when_attacking": {"don_requirement": 1, "steps": [{"action": "debuff_power", "amount": 5000, "target": "opp_character", "filter_attribute": "special", "duration": "this_turn"}]}},
    "certo", "filtro por ATRIBUTO (Special), nao type -- novo campo filter_attribute")

add("OP11-009",
    {"when_attacking": {"don_requirement": 2, "steps": [{"action": "debuff_power", "amount": 2000, "target": "opp_character", "duration": "until_opp_turn_end"}]}},
    "certo")

add("OP11-025",
    {"opp_turn": {"once_per_turn": True, "costs": [{"type": "rest_don", "count": 1}, {"type": "rest_self"}], "steps": [{"action": "buff_power", "amount": 1000, "target": "leader_or_character", "duration": "battle_only"}]}},
    "certo")

add("OP11-027",
    {"passive": {"conditions": {"leader_is": "shirahoshi"}, "steps": [{"action": "gain_attack_active"}]}},
    "certo", "reusa gain_attack_active, sem filtro de tipo (afeta o proprio character)")

add("OP11-034",
    {"activate_main": {"costs": [{"type": "rest_self"}], "conditions": {"leader_type": ["fish-man", "merfolk"]}, "steps": [{"action": "lock_opp_character_attack", "count": 1, "cost_lte": 3, "duration": "until_end_of_opp_next_turn"}]}},
    "certo", "reusa lock_opp_character_attack")

add("OP11-040",
    {"your_turn": {"trigger_timing": "start_of_turn", "conditions": {"don_field_gte": 8}, "steps": [{"action": "look_top_deck", "count": 5, "reveal_filter": "straw hat crew", "add_to_hand": True}, {"action": "deck_top_or_bottom_rest"}]}},
    "palpite", "trigger_timing='start_of_turn' e novo -- texto diz explicitamente 'can be activated at the start of your turn', distinto de your_turn generico (que e o turno todo). deck_top_or_bottom_rest e variante nova de deck_bottom_rest (pode escolher topo OU fundo)")

add("OP11-042",
    {"on_play": {"costs": [{"type": "trash_from_hand", "filter_type": "firetank pirates", "count": 1}], "steps": [{"action": "gain_rush"}]}},
    "certo")

add("OP11-050",
    {"when_attacking": {"costs": [{"type": "trash_from_hand", "filter_type": "firetank pirates", "count": 1}], "steps": [{"action": "choice", "options": [
        {"action": "bounce", "count": 1, "cost_lte": 1},
        {"action": "deck_bottom_rest", "count": 1, "cost_lte": 1, "target": "opp_character"}
    ]}]}},
    "certo")

add("OP11-077",
    {"your_turn": {"once_per_turn": True, "trigger": "on_own_don_returned_to_deck", "steps": [{"action": "buff_cost", "amount": 2, "target": "own_character", "filter_type": "big mom pirates", "duration": "until_opp_turn_end"}]}},
    "palpite", "trigger novo 'on_own_don_returned_to_deck' -- dispara quando VOCE retorna seu proprio DON ao deck (acao que outras cartas fazem como custo). Sinaliza reacao a um evento de jogo especifico")


# ===== LOTE 7 (111-130) =====

add("OP11-091",
    {"on_play": {"steps": [{"action": "deck_bottom_rest", "count": 3, "source": "opp_trash", "filter_type": "event", "order": "any"}]}},
    "certo", "reusa deck_bottom_rest com source=opp_trash, filtrado so Events")

add("OP12-007",
    {"on_play": {"steps": [{"action": "gain_rush", "filter_type": "roger pirates", "exclude": "shanks"}]}},
    "certo")

add("OP12-022",
    {"activate_main": {"costs": [{"type": "rest_self"}], "steps": [{"action": "lock_opp_character_refresh", "count": 1, "cost_lte": 5, "target": "rested_only"}]}},
    "certo")

add("OP12-040",
    {"passive": {"trigger": "on_trash_from_hand_by_own_navy_effect", "steps": [{"action": "draw_equal_to_trashed"}]}},
    "palpite", "trigger muito especifico -- 'quando um card e trashado da MAO pelo efeito de um card SEU do tipo Navy' (nao qualquer trash). draw_equal_to_trashed e action nova (quantidade variavel = quantidade trashada)")

add("OP12-048",
    {"opp_turn": {"steps": [{"action": "substitute_removal", "filter_color": "blue", "filter_type": "navy", "cost": {"action": "rest_self_and_trash_hand", "trash_count": 1}}]}},
    "certo", "reusa substitute_removal -- custo composto novo (rest self E trash 1 da mao, ambos no mesmo custo)")

add("OP12-054",
    {"on_play": {"conditions": {"leader_type": "the seven warlords of the sea"}, "steps": [{"action": "bounce", "count": 1, "cost_lte": 1, "exclude": "self"}]}},
    "certo", "exclude='self' significa nao pode escolher a si mesmo -- variante do campo exclude (antes era nome de carta, aqui e 'self')")

add("OP12-070",
    {"passive": {"steps": [{"action": "buff_power_per_count_in_trash", "filter_type": "event", "count_per": 5, "amount_per": 1000, "target": "self"}]}, "passive_2": {"steps": [{"action": "substitute_removal", "cost": {"action": "return_don", "count": 1}}]}},
    "palpite", "buff_power_per_count_in_trash e generalizacao de buff_power_per_trash (do lote 2) mas com DIVISOR (cada 5 cards = +1000, nao cada 1 card). Preciso unificar essas duas actions parecidas -- revisar nome")

add("OP12-072",
    {"passive": {"trigger": "on_own_don_returned_to_deck", "conditions": {"leader_is": "sanji"}, "steps": [{"action": "gain_rush"}]}},
    "certo", "reusa on_own_don_returned_to_deck do lote 6")

add("OP12-081",
    {"passive": {"trigger": "on_leader_attack_opp_leader", "conditions": {"own_characters_cost_gte_8_count_gte": 2}, "steps": [{"action": "draw", "count": 1}]}, "passive_2": {"once_per_turn": True, "trigger": "on_opp_play_character_cost_gte_8_or_from_effect", "steps": [{"action": "opp_add_from_life_to_hand", "count": 1}]}},
    "palpite", "dois triggers MUITO especificos e raros: 'when this Leader attacks opponent's Leader' (distinto de when_attacking generico, que cobre attacks a qualquer alvo) e 'when opponent plays a Character cost>=8 OU via efeito'. Action 'opp_add_from_life_to_hand' tambem nova -- oponente adiciona carta da PROPRIA vida pra propria mao (parece desvantagem question able, conferir leitura)")

add("OP12-085",
    {"passive": {"conditions": {"leader_type": "revolutionary army"}, "steps": [{"action": "buff_cost", "amount": 3, "target": "self"}]}, "when_attacking": {"conditions": {"leader_type": "revolutionary army", "opp_hand_gte": 5}, "steps": [{"action": "opp_trash_from_hand", "count": 1, "chosen_by": "opponent"}]}},
    "certo", "reusa opp_trash_from_hand")

add("OP12-093",
    {"passive": {"conditions": {"leader_type": "revolutionary army"}, "steps": [{"action": "buff_cost", "amount": 4, "target": "self"}]}},
    "certo")

add("OP13-001",
    {"opp_turn": {"don_requirement": 1, "trigger": "on_opp_attack_declared", "conditions": {"own_active_don_lte": 5}, "steps": [{"action": "buff_power_per_don_rested", "max_count": "any", "amount_per": 2000, "target": "leader_or_character", "filter_type": "straw hat crew", "duration": "battle_only"}]}},
    "palpite", "buff_power_per_don_rested e mecanica nova -- jogador escolhe QUANTOS DON restar (custo variavel auto-escolhido), ganha poder proporcional. Parecido com buff_power_per_trash mas o 'recurso gasto' e DON, nao cards do trash")

add("OP13-003",
    {"passive": {"conditions": {"any_don_on_field": True}, "steps": [{"action": "redirect_don_phase_to_leader", "count": 1}]}},
    "palpite", "mecanica unica: durante a fase de DON, 1 dos DON que seriam dados a qualquer character vai direto pro Leader. Action nova bem especifica")


# ===== LOTE 8 (123-145) =====

add("OP13-004",
    {"passive": {"conditions": {"life_gte": 4}, "steps": [{"action": "buff_power", "amount": 1000, "target": "leader"}]}, "passive_2": {"don_requirement": 1, "conditions": {"own_character_cost_gte_8": True}, "steps": [{"action": "buff_power", "amount": 1000, "target": "leader"}, {"action": "buff_power", "amount": 1000, "target": "all_allies"}]}},
    "certo", "dois passivos independentes -- segundo afeta leader E todos characters simultaneamente")

add("OP13-007",
    {"activate_main": {"costs": [{"type": "transfer_own_don", "count": 1}, {"type": "trash_self"}], "steps": [{"action": "debuff_power", "amount": 3000, "target": "opp_character", "duration": "this_turn"}]}},
    "certo", "custo composto: mover 1 DON ativo (de qualquer character pra outro, incluindo si mesmo) + trashar a si mesmo")

add("OP13-008",
    {"passive": {"steps": [{"action": "substitute_ko", "filter_type": "revolutionary army", "cost": {"action": "trash_self"}}]}},
    "certo", "reusa substitute_ko com filtro de tipo (nao 'this character' generico)")

add("OP13-017",
    {"passive": {"once_per_turn": True, "steps": [{"action": "substitute_removal", "filter_type": "revolutionary army", "cost": {"action": "buff_power_self", "amount": 2000}}]}},
    "palpite", "substitute_removal com custo 'ganhar +2000 power' (nao trashar nem rest) -- buff_power_self como TIPO DE CUSTO e novo, distinto de debuff_power_self que ja existe")

add("OP13-028",
    {"on_play": {"steps": [{"action": "set_don_active", "target": "all_own_don"}, {"action": "lock_self_play_from_hand", "duration": "this_turn"}]}},
    "palpite", "lock_self_play_from_hand e action nova -- efeito NEGATIVO auto-imposto (nao pode jogar cards da mao este turno), trade-off pelo set_don_active em massa")

add("OP13-032",
    {"on_play": {"steps": [{"action": "lock_opp_character_attack", "count": 1, "cost_lte": 8, "via_rest_lock": True, "duration": "until_end_of_opp_next_end_phase"}]}},
    "palpite", "'cannot be rested' e mecanica DIFERENTE de lock_opp_character_attack (que e sobre atacar) -- aqui e impedir o character de ficar RESTED por qualquer efeito, nova action 'lock_opp_cannot_be_rested'")

add("OP13-033",
    {"on_ko": {"steps": [{"action": "rest_opp_character_or_don", "count": 2}]}},
    "palpite", "'rest up to 2 of your opponent's cards' (generico, sem dizer character ou don) -- reusa rest_opp_character_or_don do lote 1 (EB03-012), mas la era choice explicito, aqui e ambiguo sobre quantidade por tipo")

add("OP13-047",
    {"passive": {"steps": [{"action": "substitute_ko", "filter_type": "whitebeard pirates", "cost": {"action": "trash_self"}}]}},
    "certo", "reusa substitute_ko + filter_type, igual ao OP13-008")

add("OP13-059",
    {"main": {"costs": [{"type": "bounce_self_other", "count": 1}], "steps": [{"action": "bounce", "count": 1, "cost_lte": 6}]}},
    "certo", "reusa bounce_self_other do lote 5 (OP08-047)")

add("OP13-060",
    {"passive": {"steps": [{"action": "substitute_ko", "filter_type": "roger pirates", "cost": {"action": "trash_self"}}]}},
    "certo", "terceira ocorrencia do mesmo padrao substitute_ko + filter_type")

add("OP13-078",
    {"passive": {"once_per_turn": True, "trigger": "on_character_removed_by_opp_effect", "conditions": {"filter_type": "roger pirates"}, "steps": [{"action": "add_don", "count": 1, "rested": True}]}},
    "palpite", "trigger 'on_character_removed_by_opp_effect' (quando MEU character e removido pelo OPONENTE) e o INVERSO do on_character_removed_by_my_effect que ja temos -- par simetrico, faz sentido ter os dois")

add("OP14-004",
    {"passive": {"conditions": {"self_power_gte": 5000}, "steps": [{"action": "gain_rush"}]}},
    "certo")

add("OP14-006",
    {"when_attacking": {"conditions": {"self_power_gte": 5000}, "steps": [{"action": "debuff_power", "amount": 2000, "target": "opp_character", "duration": "this_turn"}]}},
    "certo")

add("OP14-016",
    {"opp_turn": {"once_per_turn": True, "steps": [{"action": "substitute_removal", "filter_type": "supernovas", "cost": {"action": "buff_power_self_leader", "amount": 2000}}]}, "when_attacking": {"don_requirement": 1, "steps": [{"action": "debuff_power", "amount": 2000, "target": "opp_character", "duration": "this_turn"}]}},
    "palpite", "custo 'buff_power_self_leader' (dar power ao proprio LIDER, nao ao character substituido) e variante do buff_power_self do OP13-017 -- preciso confirmar se e o mesmo conceito com alvo diferente ou action nova")

add("OP14-035",
    {"your_turn": {"trigger": "on_self_becomes_rested", "steps": [{"action": "lock_opp_character_refresh", "count": 1, "cost_lte": 4}]}},
    "palpite", "trigger 'on_self_becomes_rested' e novo -- dispara quando ESTE character fica rested (por atacar, bloquear, ou efeito), nao e on_play nem when_attacking")

add("OP14-056",
    {"passive": {"steps": [{"action": "cannot_attack"}]}, "passive_2": {"trigger": "on_any_trash_from_hand_by_effect", "steps": [{"action": "negate_effect", "target": "self", "duration": "this_turn"}]}},
    "palpite", "reusa cannot_attack do lote 3. Segundo trigger 'on_any_trash_from_hand_by_effect' (quando QUALQUER card e trashado da mao por um efeito, de qualquer jogador) e bem generico -- nega o PROPRIO efeito desta carta como penalidade")

add("OP14-065",
    {"on_ko": {"steps": [{"action": "return_opp_don", "count": 1}]}},
    "palpite", "return_opp_don e action nova -- forca o OPONENTE a devolver 1 DON do campo dele pro deck de DON dele (diferente de lock_opp_don que so impede ficar ativo, aqui remove de vez)")

add("OP14-082",
    {"on_ko": {"steps": [{"action": "buff_cost", "amount": 4, "target": "all_allies", "filter_type": "thriller bark pirates", "duration": "until_end_of_opp_next_end_phase"}]}},
    "certo")

add("OP14-083",
    {"activate_main": {"costs": [{"type": "trash_self"}], "steps": [{"action": "debuff_power", "amount": 3000, "target": "opp_character", "conditions_target": {"cost_eq": 0}, "duration": "this_turn"}]}},
    "certo")

add("OP14-084",
    {"on_play": {"conditions": {"leader_type": "baroque works"}, "steps": [{"action": "play_from_trash", "count": 1, "filter_type": "baroque works", "cost_lte": 4}, {"action": "play_from_trash", "count": 1, "filter_type": "baroque works", "cost_eq": 1}]}},
    "certo", "dois play_from_trash com filtros de custo diferentes (lte 4 e eq 1 exato)")

add("OP14-086",
    {"passive": {"conditions": {"trash_gte": 7}, "steps": [{"action": "buff_power", "amount": 1000, "target": "self"}, {"action": "buff_cost", "amount": 2, "target": "all_allies", "filter_type": "baroque works"}]}},
    "certo")

add("OP14-102",
    {"trigger": {"steps": [{"action": "play_from_trash", "count": 1, "filter_type": "thriller bark pirates", "cost_lte": 4, "rested": True}]}},
    "certo")


# correcao OP13-017 apos esclarecimento do usuario (era -2000, nao +2000)
propostas["OP13-017"]["effects"] = {"passive": {"once_per_turn": True, "steps": [{"action": "substitute_removal", "filter_type": "revolutionary army", "cost": {"action": "debuff_power_self", "amount": 2000}}]}}
propostas["OP13-017"]["confidence"] = "certo"
propostas["OP13-017"]["notes"] = "CORRIGIDO: custo e debuff_power_self -2000, nao buff. Reusa debuff_power_self ja existente, sem necessidade de action nova"

# correcao OP14-016 confirmada por imagem (X.Drake, OP14-016): -2000 no Leader, debuff
propostas["OP14-016"]["effects"] = {"opp_turn": {"once_per_turn": True, "steps": [{"action": "substitute_removal", "filter_type": "supernovas", "cost": {"action": "debuff_power_self_leader", "amount": 2000}}]}, "when_attacking": {"don_requirement": 1, "steps": [{"action": "debuff_power", "amount": 2000, "target": "opp_character", "duration": "this_turn"}]}}
propostas["OP14-016"]["confidence"] = "certo"
propostas["OP14-016"]["notes"] = "CORRIGIDO via imagem real (X.Drake): -2000 debuff no leader, nao buff. Regra: custo de substitute_ko/substitute_removal com power e SEMPRE debuff no alvo do custo, mesmo sendo proprio -- e sacrificio, nao bonus. Prioridade sobre a regra geral opponent=debuff/your=buff"

# correcao OP13-032 confirmada pelo usuario
propostas["OP13-032"]["effects"] = {"on_play": {"steps": [{"action": "lock_opp_cannot_be_rested", "count": 1, "cost_lte": 8, "duration": "until_end_of_opp_next_end_phase"}]}}
propostas["OP13-032"]["confidence"] = "certo"

# ===== LOTE 9 (146-165) =====

add("OP14-111",
    {"on_play": {"steps": [{"action": "lock_opp_character_attack", "count": 1, "cost_lte": 6, "duration": "until_end_of_opp_next_end_phase"}]}, "on_ko": {"steps": [{"action": "lock_opp_character_attack", "count": 1, "cost_lte": 6, "duration": "until_end_of_opp_next_end_phase"}]}, "trigger": {"steps": [{"action": "play_from_trash", "count": 1, "filter_type": "thriller bark pirates", "cost_lte": 4, "rested": True}]}},
    "certo", "padrao TAG1/TAG2 (on_play/on_ko) deveria duplicar automaticamente -- confirmar apos rodar no parser real")

add("OP15-006",
    {"passive": {"conditions": {"trash_gte": 4, "filter_type_condition": "event"}, "steps": [{"action": "buff_power", "amount": 2000, "target": "self"}]}},
    "certo")

add("OP15-009",
    {"passive": {"conditions": {"self_power_base_lte": 7000}, "steps": [{"action": "substitute_removal", "cost": {"action": "debuff_power_self_leader", "amount": 2000}}]}},
    "certo", "reusa substitute_removal + debuff_power_self_leader, ja implementados")

add("OP15-014",
    {"passive": {"steps": [{"action": "substitute_ko", "cost": {"action": "trash_from_hand", "filter_type": ["event"], "count": 1}}]}, "on_play": {"steps": [{"action": "activate_event_from_hand", "filter_type": "dressrosa", "cost_lte": 3}]}},
    "palpite", "activate_event_from_hand e action nova -- ativa o efeito de um Event da MAO sem joga-lo de fato (diferente de play_card)")

add("OP15-029",
    {"on_play": {"steps": [{"action": "lock_opp_cannot_be_rested", "count": 1, "cost_lte": 5, "duration": "until_end_of_opp_next_end_phase"}]}},
    "certo", "reusa lock_opp_cannot_be_rested do lote 8")

add("OP15-031",
    {"on_play": {"steps": [{"action": "ko", "count": 1, "target": "opp_character", "rested_only": True, "conditions_target": {"cost_eq_don_given": True}}]}},
    "palpite", "condicao 'cost equal to DON!! given' e comparacao dinamica nova -- custo do character == quantidade de DON anexados a ele, nao um numero fixo")

add("OP15-035",
    {"passive": {"conditions": {"self_power_base_lte": 7000}, "steps": [{"action": "substitute_removal", "cost": {"action": "rest_own_cards", "count": 2}}]}},
    "palpite", "custo 'rest 2 of your cards' (generico, qualquer card seu, nao so DON nem so o character) e novo -- distinto de rest_self e rest_own_don")

add("OP15-050",
    {"passive": {"conditions": {"have_named": "kelly funk"}, "steps": [{"action": "buff_power", "amount": 3000, "target": "self"}]}},
    "certo")

add("OP15-059",
    {"opp_turn": {"costs": [{"type": "rest_self"}], "steps": [{"action": "choice", "decided_by": "opponent", "options": [
        {"action": "opp_may_return_own_don", "count": 1},
        {"action": "debuff_power", "amount": 2000, "target": "opp_leader_or_character", "duration": "this_turn"}
    ]}]}},
    "certo", "reusa estrutura choice decided_by=opponent do OP05-099 -- mas aqui se oponente NAO retornar don, voce aplica debuff (nao buff como eu li errado antes)")

add("OP15-069",
    {"passive": {"conditions": {"self_power_base_lte": 7000}, "steps": [{"action": "substitute_removal", "cost": {"action": "return_own_don", "count": 1}}]}},
    "certo", "reusa substitute_removal + return_own_don, ja implementados")

add("OP15-072",
    {"activate_main": {"don_requirement": 2, "costs": [{"type": "rest_self"}], "conditions": {"have_named": ["kotori", "satori"]}, "steps": [{"action": "debuff_power", "amount": 3000, "target": "opp_character", "duration": "this_turn"}]}},
    "certo")

add("OP15-086",
    {"on_play": {"conditions": {"leader_type": "straw hat crew"}, "steps": [{"action": "play_from_trash", "count": 1, "filter_type": "straw hat crew", "cost_lte": 7, "gains_rush_this_play": True}]}},
    "provavel", "campo 'gains_rush_this_play' (o character jogado via este efeito ganha Rush so nesse turno) e especifico do play_from_trash, diferente de gain_rush solto")

add("OP15-090",
    {"passive": {"conditions": {"self_power_base_lte": 7000}, "steps": [{"action": "substitute_removal", "cost": {"action": "trash_from_hand", "count": 1}}]}},
    "certo", "quarta ocorrencia do padrao substitute_removal com power_base_lte 7000 -- claramente um arquetipo de cartas com a mesma clausula condicional, custos diferentes")

add("OP15-092",
    {"passive": {"steps": [
        {"action": "set_power", "amount": 9000, "conditions": {"trash_gte": 10}, "target": "self", "base_value": True},
        {"action": "buff_cost", "amount": 10, "conditions": {"trash_gte": 10}, "target": "self"},
        {"action": "set_power", "amount": 7000, "conditions": {"trash_gte": 20}, "target": "leader", "base_value": True, "trigger": "opp_turn"},
        {"action": "buff_power", "amount": 1000, "conditions": {"trash_gte": 30}, "target": "self"}
    ]}},
    "palpite", "estrutura de bullet-list com 3 thresholds independentes e ACUMULATIVOS (nao mutuamente exclusivos -- se tem 30+, TODOS os 3 efeitos se aplicam). Reusa set_power (base_value) do lote 1")

add("OP15-093",
    {"activate_main": {"costs": [{"type": "trash_self"}], "conditions": {"trash_gte": 15}, "steps": [{"action": "gain_rush", "filter_name": "monkey.d.luffy", "extra_attribute": "slash"}]}},
    "certo", "campo extra_attribute novo -- da tambem o atributo Slash, alem do Rush")

add("OP16-014",
    {"passive": {"steps": [{"action": "substitute_removal", "cost": {"action": "self_ko"}}]}, "on_ko": {"steps": [{"action": "play_from_trash", "filter_self": True, "power_eq": 8000, "cost": {"action": "trash_from_hand", "filter_power_eq": 8000, "count": 1}}]}},
    "palpite", "custo 'self_ko' (KO a si mesmo como substituicao de OUTRA remocao) e ironico mas faz sentido -- character troca uma remocao por KO controlado. play_from_trash com 'filter_self' (jogar A SI MESMO de volta do trash) e padrao novo")

add("OP16-015",
    {"passive": {"conditions": {"leader_name_includes": "ace", "don_field_gte": 6}, "steps": [{"action": "buff_cost_discount_hand", "amount": 2, "target": "self"}]}, "opp_turn": {"steps": [{"action": "set_power", "amount": 7000, "target": "leader_and_self", "base_value": True, "duration": "this_turn", "cost": {"action": "trash_from_hand", "filter_power_eq": 8000, "count": 1}}]}},
    "palpite", "set_power em DOIS alvos simultaneos (leader E self) com MESMO valor -- campo target composto novo")

add("OP16-018",
    {"passive": {"once_per_turn": True, "steps": [{"action": "substitute_ko", "filter_type": "red-haired pirates", "cost": {"action": "trash_from_hand", "filter_power_gte": 6000, "count": 1}}]}},
    "certo", "reusa substitute_ko + filter_type, com custo filtrado por power minimo (filter_power_gte e novo nesse contexto de custo)")

add("OP16-027",
    {"passive": {"don_requirement": 1, "steps": [{"action": "buff_power", "amount": 2000, "target": "self"}]}},
    "certo")

add("OP16-030",
    {"on_play": {"steps": [{"action": "lock_opp_character_refresh", "count": 1}]}}, 
    "certo", "reusa lock_opp_character_refresh -- segundo bloco [End of Your Turn] sera tratado separado pois e efeito completamente distinto")


# correcao OP15-031 confirmada por imagem (Purinpurin)
propostas["OP15-031"]["effects"] = {"on_play": {"steps": [{"action": "ko", "count": 1, "target": "opp_character", "rested_only": True, "conditions_target": {"cost_eq_don_given": True}}]}}
propostas["OP15-031"]["confidence"] = "certo"

# ===== LOTE 10 (166-189) =====

add("OP16-047",
    {"activate_main": {"costs": [{"type": "rest_self"}], "conditions": {"opp_hand_gte": 8}, "steps": [{"action": "deck_bottom_rest", "count": 2, "source": "opp_hand", "chosen_by": "opponent", "order": "any"}]}},
    "certo", "reusa source=opp_hand do lote 4")

add("OP16-074",
    {"on_play": {"conditions": {"leader_type": "impel down"}, "steps": [{"action": "return_opp_don", "count": 1}]}, "on_ko": {"steps": [{"action": "return_opp_don", "count": 4}]}},
    "certo", "reusa return_opp_don do lote 8")

add("OP16-079",
    {"passive": {"trigger": "on_own_character_played_from_trash", "conditions": {"filter_type": "land of wano"}, "steps": [{"action": "gain_rush"}]}},
    "palpite", "trigger 'on_own_character_played_from_trash' e novo -- dispara quando QUALQUER character desse tipo e jogado do trash (por qualquer efeito seu), nao e o proprio efeito de jogar")

add("OP16-080",
    {"opp_turn": {"steps": [{"action": "buff_cost", "amount": 1, "target": "all_allies"}]}, "opp_turn_attack": {"once_per_turn": True, "costs": [{"type": "trash_from_hand", "filter_has_trigger": True, "count": 1}], "steps": [{"action": "redirect_attack_target", "target": "leader_or_filter", "filter_type": "blackbeard pirates"}]}},
    "palpite", "redirect_attack_target (mudar o alvo de um ataque em andamento para o Leader ou um character especifico seu) e mecanica nova de redirecionamento -- trigger 'on_opp_attack_declared' generico nao cobre, criei opp_turn_attack especifico")

add("OP16-081",
    {"activate_main": {"costs": [{"type": "rest_self"}], "conditions": {"own_character_cost_gte_8": True}, "steps": [{"action": "debuff_power", "amount": 2000, "target": "opp_character", "duration": "this_turn"}]}},
    "certo")

add("OP16-084",
    {"activate_main": {"costs": [{"type": "trash_self", "cost_gte": 20}], "conditions": {"don_field_gte": 9}, "steps": [{"action": "play_from_trash", "count": 1, "filter_name": "kouzuki momonosuke", "cost_eq": 9}]}},
    "certo", "custo com filtro proprio (trashar a SI MESMO, que tem custo>=20) -- cost_gte dentro do custo trash_self e novo mas direto")

add("OP16-105",
    {"trigger": {"conditions": {"life_lte": 1}, "steps": [{"action": "play_from_trash", "count": 1, "filter_name": "absalom", "cost_lte": 4}, {"action": "play_from_trash", "count": 1, "filter_name": "dr. hogback", "cost_lte": 4}, {"action": "play_from_trash", "count": 1, "filter_name": "perona", "cost_lte": 4}]}},
    "certo", "tres play_from_trash com filtro de nome especifico cada, mesma condicao")

add("OP16-115",
    {"main": {"conditions": {"leader_type": "blackbeard pirates"}, "steps": [{"action": "add_from_trash", "count": 1, "has_trigger": True, "exclude": "black vortex"}]}, "trigger": {"steps": [{"action": "negate_effect", "count": 1, "target": "opp_leader_or_character", "duration": "this_turn"}]}},
    "certo", "reusa negate_effect; add_from_trash com has_trigger (novo campo, simetrico ao has_trigger do play_from_trash)")

add("P-002",
    {"main": {"steps": [{"action": "mulligan_hand_equal"}]}},
    "certo", "reusa mulligan_hand_equal do lote 3 -- segunda ocorrencia confirma mecanica generica real")

add("P-008",
    {"activate_main": {"costs": [{"type": "rest_self"}], "steps": [{"action": "rest_opp_character", "count": 1, "cost_lte": 2}]}},
    "certo")

add("P-009",
    {"on_play": {"conditions": {"opp_hand_gte": 6}, "steps": [{"action": "opp_add_from_life_to_hand", "count": 1}]}},
    "certo", "reusa opp_add_from_life_to_hand do lote 7 -- segunda ocorrencia confirma a leitura (efeito aparentemente generoso ao oponente, mas reduz a vida dele)")

add("P-043",
    {"on_play": {"steps": [{"action": "bounce", "count": 1, "cost_lte": 3}]}},
    "certo")

add("P-044",
    {"passive": {"don_requirement": 1, "conditions": {"hand_lte": 4}, "steps": [{"action": "buff_power", "amount": 2000, "target": "self"}]}},
    "certo")

add("P-056",
    {"on_play": {"costs": [{"type": "rest_don", "count": 2}], "steps": [{"action": "bounce", "count": 1, "cost_lte": 5}]}},
    "certo", "simbolo de circulo com numero (➁) e equivalente a custo de DON entre parenteses, ja coberto pelo padrao 1b")

add("P-057",
    {"main": {"conditions": {"leader_is": "uta"}, "steps": [{"action": "lock_opp_character_refresh", "count": 2, "cost_lte": 4, "target": "rested_only"}]}},
    "certo")

add("P-060",
    {"main": {"costs": [{"type": "rest_named", "filter_name": "uta", "count": 1}], "steps": [{"action": "rest_opp_don", "count": 2}]}},
    "certo", "custo 'rest 1 of your [Uta] cards' e variante de rest_named ja usado no lote 4")

add("P-071",
    {"on_ko": {"steps": [{"action": "add_self_from_trash_to_hand"}]}},
    "certo", "action especifica 'adicionar a SI MESMO do trash para a mao' -- distinto de play_from_trash (nao joga, so recupera pra mao)")

add("P-076",
    {"activate_main": {"once_per_turn": True, "costs": [{"type": "trash_from_hand", "filter_type": "navy", "count": 1}], "steps": [{"action": "debuff_cost", "amount": 1, "target": "opp_character"}]}},
    "certo")

add("P-078",
    {"passive": {"conditions": {"own_rested_characters_gte": 2, "filter_type_condition": "odyssey"}, "steps": [{"action": "buff_power", "amount": 1000, "target": "self"}]}},
    "certo")

add("PRB01-001",
    {"activate_main": {"once_per_turn": True, "steps": [{"action": "gain_rush", "count": 1, "cost_lte": 8, "conditions_target": {"no_on_play_effect": True}}]}},
    "certo", "condicao no alvo 'sem efeito On Play' e filtro estrutural, nao de tipo/custo -- campo conditions_target.no_on_play_effect")

add("PRB02-005",
    {"on_play": {"conditions": {"leader_multicolor": True, "opp_don_field_lte": 7}, "steps": [{"action": "lock_opp_don_active_at_next_main", "count": 1}]}},
    "palpite", "lock_opp_don_active_at_next_main e mecanica MUITO especifica -- DON fica ativo mas trava especificamente no inicio da Main Phase do oponente, nao no Refresh generico como lock_opp_don_refresh")

add("PRB02-017",
    {"passive": {"once_per_turn": True, "costs": [{"type": "trash_from_hand", "filter_has_trigger": True, "count": 1}], "steps": [{"action": "lock_opp_character_attack", "count": 1, "exclude": "monkey.d.luffy", "duration": "until_end_of_opp_next_end_phase", "includes_leader": True}]}, "trigger": {"steps": [{"action": "ko", "count": 1, "target": "opp_character", "cost_lte": 4}]}},
    "certo", "lock_opp_character_attack agora com 'includes_leader' (afeta tambem o Leader rested do oponente, nao so characters) -- campo novo simples")


# ===== LOTE 11 (188-209, ultimo lote) =====

add("ST01-001",
    {"activate_main": {"once_per_turn": True, "steps": [{"action": "give_don", "count": 1, "target": "leader_or_character"}]}},
    "certo")

add("ST01-013",
    {"passive": {"don_requirement": 1, "steps": [{"action": "buff_power", "amount": 1000, "target": "self"}]}},
    "certo")

add("ST02-003",
    {"passive": {"don_requirement": 1, "conditions": {"own_characters_gte": 3}, "steps": [{"action": "buff_power", "amount": 2000, "target": "self"}]}},
    "certo")

add("ST02-008",
    {"when_attacking": {"don_requirement": 1, "steps": [{"action": "rest_opp_don", "count": 1}]}},
    "certo")

add("ST03-009",
    {"on_play": {"steps": [{"action": "bounce", "count": 1, "cost_lte": 7}]}},
    "certo")

add("ST03-014",
    {"on_play": {"steps": [{"action": "bounce", "count": 1, "cost_lte": 3}]}},
    "certo")

add("ST08-013",
    {"passive": {"don_requirement": 1, "trigger": "on_end_of_battle_vs_opp_character", "steps": [{"action": "choice", "options": [
        {"action": "ko", "count": 1, "target": "opp_character", "filter_self": "battled_character"},
        {"action": "ko", "count": 0}
    ]}, {"action": "self_ko", "conditions": {"previous_choice_taken": True}}]}},
    "palpite", "trigger 'on_end_of_battle_vs_opp_character' e custo-efeito condicional onde se voce KO o oponente, voce TAMBEM se autoKO (trade obrigatorio). Estrutura de dependencia entre dois KOs e nova, precisa confirmar modelagem")

add("ST12-012",
    {"activate_main": {"steps": [{"action": "bounce_self"}]}},
    "certo", "reusa bounce_self como action de efeito direto, nao so como custo")

add("ST13-011",
    {"on_play": {"conditions": {"life_lte": 2}, "steps": [{"action": "gain_rush"}]}},
    "certo")

add("ST14-001",
    {"passive": {"don_requirement": 1, "steps": [{"action": "buff_cost", "amount": 1, "target": "all_allies"}]}, "passive_2": {"don_requirement": 1, "conditions": {"own_character_cost_gte_8": True}, "steps": [{"action": "buff_power", "amount": 1000, "target": "leader"}]}},
    "certo")

add("ST14-004",
    {"activate_main": {"once_per_turn": True, "steps": [{"action": "buff_cost", "amount": 2, "target": "own_character", "filter_color": "black", "filter_type": "straw hat crew", "duration": "until_end_of_opp_next_turn"}]}},
    "certo")

add("ST14-011",
    {"activate_main": {"costs": [{"type": "rest_self"}], "steps": [{"action": "buff_cost", "amount": 2, "target": "own_character", "filter_color": "black", "filter_type": "straw hat crew", "duration": "until_end_of_opp_next_turn"}]}},
    "certo", "mesma mecanica do ST14-004 mas custo e rest_self em vez de once_per_turn")

add("ST14-012",
    {"passive": {"conditions": {"own_character_cost_gte_10": True}, "steps": [{"action": "gain_rush"}]}},
    "certo")

add("ST15-001",
    {"when_attacking": {"conditions": {"leader_is": "edward.newgate"}, "steps": [{"action": "lock_self_life_add"}]}},
    "palpite", "lock_self_life_add e efeito NEGATIVO auto-imposto -- nao pode adicionar Life cards a mao usando proprios efeitos, este turno. Restricao temporaria sobre o proprio jogador")

add("ST16-003",
    {"passive": {"conditions": {"leader_type": "film", "own_rested_cards_gte": 6}, "steps": [{"action": "buff_power", "amount": 2000, "target": "self"}]}},
    "certo")

add("ST16-005",
    {"passive": {"conditions": {"have_named_rested": "uta"}, "steps": [{"action": "buff_power", "amount": 1000, "target": "self"}]}},
    "provavel", "condicao especifica 'tem [Uta] E ela esta RESTED' (nao so possuir) -- campo have_named_rested distinto de have_named simples")

add("ST17-002",
    {"on_play": {"costs": [{"type": "bounce_self_other", "count": 1}], "conditions": {"leader_type": "the seven warlords of the sea"}, "steps": [{"action": "bounce", "count": 1, "cost_lte": 4}]}},
    "certo", "reusa bounce_self_other do lote 5")

add("ST19-001",
    {"on_play": {"costs": [{"type": "trash_from_hand", "filter_color": "black", "filter_type": "navy", "count": 1}], "steps": [{"action": "lock_opp_character_attack", "count": 2, "cost_lte": 4, "duration": "until_end_of_opp_next_turn"}]}},
    "certo")

add("ST19-003",
    {"on_play": {"conditions": {"leader_is": "smoker"}, "steps": [{"action": "buff_cost", "amount": 4, "target": "opp_character", "duration": "this_turn"}]}}, 
    "certo", "buff_cost no OPONENTE (aumentar custo, dificultando manter em campo ou reciclar) -- distinto de debuff_cost; ja temos buff_cost generico, so o target opp e novo pra essa action")

add("ST26-001",
    {"passive": {"conditions": {"have_named_power_gte": {"names": ["san-gorou", "sanji"], "power": 7000}}, "steps": [{"action": "buff_cost_discount_hand", "amount": 5, "target": "self"}]}, "on_play": {"steps": [{"action": "bounce", "count": 99, "filter_name": ["san-gorou", "sanji"], "target": "own_character"}]}},
    "palpite", "have_named_power_gte com LISTA de nomes (qualquer um dos dois) e nova combinacao. on_play bounce em TODOS os proprios characters de nomes especificos (nao oponente) e padrao raro -- 'return ALL of your [X] and [Y] Characters'")

add("ST30-009",
    {"passive": {"conditions": {"self_power_base_eq": 6000}, "steps": [{"action": "substitute_removal", "cost": {"action": "trash_self"}, "extra_steps": [{"action": "draw", "count": 1}]}]}},
    "certo", "reusa substitute_removal com extra_steps -- condicao e EQ exato (6000), nao lte como os outros casos vistos")

add("ST30-014",
    {"activate_main": {"costs": [{"type": "rest_self"}], "steps": [{"action": "transfer_don", "count": 2, "target": "own_character", "filter_power_base_eq": 6000, "distribution": "free", "per_target_max": 2}]}},
    "certo", "reusa transfer_don com distribution free -- ate 2 characters, cada um recebendo ate 2 don")


# ===== Cartas que ficaram de fora dos lotes (fechamento das 209) =====

add("OP07-062",
    {"on_play": {"conditions": {"don_field_lte_opp": True}, "steps": [{"action": "bounce", "count": 1, "cost_eq": 1, "filter_type": "the vinsmoke family", "target": "own_character"}]}},
    "certo", "bounce em PROPRIO character (nao oponente) -- target own_character, cost exato 1")

add("OP08-092",
    {"on_play": {"steps": [{"action": "play_from_trash", "count": 1, "filter_name": "ulti", "cost_lte": 4}]}},
    "certo")

add("OP08-093",
    {"passive": {"don_requirement": 1, "steps": [{"action": "buff_cost", "amount": 2, "target": "self"}]}},
    "certo")

add("OP10-009",
    {"on_play": {"conditions": {"leader_type": "punk hazard"}, "steps": [{"action": "debuff_power", "amount": 3000, "target": "opp_character", "duration": "this_turn"}]}},
    "certo")

add("OP10-015",
    {"on_play": {"steps": [{"action": "debuff_power", "amount": 1000, "target": "opp_character", "duration": "this_turn"}]}},
    "certo")

add("OP10-032",
    {"passive": {"conditions": {"filter_color": "green", "exclude": "tashigi"}, "steps": [{"action": "substitute_removal", "cost": {"action": "rest_self"}}]}},
    "certo", "reusa substitute_removal + rest_self, com condicao de COR (nao type) e exclude")


# CORRECAO: 'give opponent cost N' sem sinal = SEMPRE debuff_cost (reduz),
# confirmado pelo usuario -- prepara kill por filtro de custo baixo
propostas["EB02-046"] = {"effects": {"on_play": {"steps": [{"action": "look_top_deck", "count": 2, "destination": "trash"}, {"action": "debuff_cost", "amount": 1, "target": "opp_character", "duration": "this_turn"}]}}, "confidence": "certo", "notes": "CORRIGIDO: debuff_cost, nao buff"}
propostas["EB02-051"] = {"effects": {"main": {"steps": [{"action": "choice", "options": [
    {"action": "ko", "count": 1, "target": "opp_character", "cost_lte": 2},
    {"action": "debuff_cost", "amount": 4, "target": "opp_character", "duration": "this_turn"}
]}]}}, "confidence": "certo", "notes": "CORRIGIDO: debuff_cost"}
propostas["EB04-017"] = {"effects": {"your_turn": {"conditions": {"own_characters_gte": 3, "filter_type_condition": "minks"}, "steps": [{"action": "debuff_cost", "amount": 1, "target": "all_opp_characters"}]}, "on_play": {"conditions": {"leader_type": "minks"}, "steps": [{"action": "play_card", "count": 1, "filter_type": "minks", "cost_lte": 5}]}}, "confidence": "certo", "notes": "CORRIGIDO: debuff_cost em todos os opp characters"}
propostas["OP08-057"] = {"effects": {"activate_main": {"once_per_turn": True, "costs": [{"type": "rest_don", "count": 2}], "steps": [{"action": "choice", "options": [
    {"action": "draw", "count": 1, "conditions": {"hand_lte": 5}},
    {"action": "debuff_cost", "amount": 2, "target": "opp_character", "duration": "this_turn"}
]}]}}, "confidence": "certo", "notes": "CORRIGIDO: debuff_cost"}
propostas["OP08-082"] = {"effects": {"activate_main": {"costs": [{"type": "rest_don", "count": 1}, {"type": "rest_self", "optional": True}], "steps": [{"action": "debuff_cost", "amount": 2, "target": "opp_character", "duration": "this_turn"}]}}, "confidence": "certo", "notes": "CORRIGIDO: debuff_cost"}
propostas["OP08-083"] = {"effects": {"your_turn": {"don_requirement": 1, "steps": [{"action": "debuff_cost", "amount": 1, "target": "all_opp_characters"}]}}, "confidence": "certo", "notes": "CORRIGIDO: debuff_cost"}
propostas["OP08-087"] = {"effects": {"activate_main": {"once_per_turn": True, "steps": [{"action": "debuff_cost", "amount": 1, "target": "opp_character", "duration": "this_turn"}]}, "passive": {"steps": [{"action": "keyword_blocker"}]}}, "confidence": "certo", "notes": "CORRIGIDO: debuff_cost"}
propostas["OP08-097"] = {"effects": {"main": {"conditions": {"leader_type": "animal kingdom pirates"}, "steps": [{"action": "debuff_cost", "amount": 2, "target": "opp_character", "duration": "this_turn"}, {"action": "ko", "count": 1, "target": "opp_character", "cost_eq": 0}]}, "trigger": {"steps": [{"action": "ko", "count": 1, "target": "opp_character", "cost_lte": 3}]}}, "confidence": "certo", "notes": "CORRIGIDO: debuff_cost prepara o KO seguinte, confirmado pelo usuario"}
propostas["OP09-083"] = {"effects": {"activate_main": {"costs": [{"type": "rest_self"}], "conditions": {"leader_type": "blackbeard pirates"}, "steps": [{"action": "debuff_cost", "amount": 3, "target": "opp_character", "duration": "this_turn"}]}, "on_ko": {"steps": [{"action": "draw", "count": 1}]}}, "confidence": "certo", "notes": "CORRIGIDO: debuff_cost"}
propostas["OP12-090"] = {"effects": {"when_attacking": {"costs": [{"type": "trash_from_deck_top", "count": 2}], "steps": [{"action": "debuff_cost", "amount": 2, "target": "opp_character", "duration": "this_turn"}]}}, "confidence": "certo", "notes": "CORRIGIDO: debuff_cost"}
propostas["OP16-089"] = {"effects": {"passive": {"steps": [{"action": "gain_attack_active"}]}, "on_play": {"steps": [{"action": "draw", "count": 2, "then_trash": 2}, {"action": "debuff_cost", "amount": 4, "target": "opp_character", "duration": "this_turn"}]}}, "confidence": "certo", "notes": "CORRIGIDO: debuff_cost"}
propostas["ST19-003"] = {"effects": {"on_play": {"conditions": {"leader_is": "smoker"}, "steps": [{"action": "debuff_cost", "amount": 4, "target": "opp_character", "duration": "this_turn"}]}, "activate_main": {"once_per_turn": True, "conditions": {"self_played_this_turn": True}, "steps": [{"action": "ko", "count": 1, "target": "opp_character", "cost_eq": 0}]}}, "confidence": "certo", "notes": "CORRIGIDO: debuff_cost. Usuario confirmou: activate_main so funciona no MESMO turno em que foi jogada (self_played_this_turn), nao once_per_turn generico recorrente"}
propostas["ST19-005"] = {"effects": {"passive": {"steps": [{"action": "keyword_blocker"}]}, "activate_main": {"once_per_turn": True, "costs": [{"type": "deck_bottom_rest_from_trash", "count": 1}], "steps": [{"action": "debuff_cost", "amount": 1, "target": "opp_character", "duration": "this_turn"}]}}, "confidence": "certo", "notes": "CORRIGIDO: debuff_cost"}

# nota removida: OP14-083 era falso positivo do regex de busca de cost
# (na verdade e debuff de POWER em character de custo 0, ja coberto antes)