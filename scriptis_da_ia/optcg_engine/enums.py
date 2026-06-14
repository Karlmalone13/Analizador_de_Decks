"""
optcg_engine/enums.py
=====================
Todos os enums do simulador OPTCG, extraídos diretamente do
Assembly-CSharp.dll v1.40a via dnSpy.

Ordem de definição reflete os valores inteiros originais do C#
para garantir compatibilidade com dados serializados pelo jogo.
"""

from enum import Enum, IntEnum


# ---------------------------------------------------------------------------
# CardType  (Token: 0x0200006C)
# ---------------------------------------------------------------------------
class CardType(IntEnum):
    LEADER    = 0
    CHARACTER = 1
    EVENT     = 2
    STAGE     = 3


# ---------------------------------------------------------------------------
# CardColor  (Token: 0x0200006F)
# ---------------------------------------------------------------------------
class CardColor(IntEnum):
    RED    = 0
    GREEN  = 1
    BLUE   = 2
    PURPLE = 3
    BLACK  = 4
    YELLOW = 5


# ---------------------------------------------------------------------------
# StrikeType  (Token: 0x0200006D)
# ---------------------------------------------------------------------------
class StrikeType(IntEnum):
    STRIKE  = 0   # Soco / Punch
    SLASH   = 1   # Espada / Sword
    RANGED  = 2   # Distância / Gun / Ranged
    SPECIAL = 3   # Especial / Devil Fruit / Special
    WISDOM  = 4   # Sabedoria / Wisdom
    NONE    = 5


# ---------------------------------------------------------------------------
# CardCategory  (Token: 0x0200006E)  — 165 categorias, ordem original
# ---------------------------------------------------------------------------
class CardCategory(IntEnum):
    STRAW_HAT_CREW                  = 0
    CAPTAIN                         = 1
    FISH_MAN                        = 2
    SUPER_ROOKIE                    = 3
    ANIMAL                          = 4
    FOUR_EMPERORS                   = 5
    ANIMAL_KINGDOM_PIRATES          = 6
    ALABASTA_KINGDOM                = 7
    SUPERNOVAS                      = 8
    KID_PIRATES                     = 9
    DONQUIXOTE_PIRATES              = 10
    HEART_PIRATES                   = 11
    REVOLUTIONARY_ARMY              = 12
    NAVY                            = 13
    IMPEL_DOWN                      = 14
    WHITEBEARD_PIRATES              = 15
    SEVEN_WARLORDS_OF_THE_SEA       = 16
    BAROQUE_WORKS                   = 17
    THRILLER_BARK_PIRATES           = 18
    ELEVEN_SUPERNOVAS               = 19
    STRAW_HAT_GRAND_FLEET           = 20
    BIG_MOM_PIRATES                 = 21
    WANO_COUNTRY                    = 22
    EAST_BLUE                       = 23
    KUJA_PIRATES                    = 24
    NEW_FISH_MAN_PIRATES            = 25
    FISH_MAN_ISLAND                 = 26
    MINK_TRIBE                      = 27
    KOZUKI_CLAN                     = 28
    CP9                             = 29
    CP0                             = 30
    GERMA_66                        = 31
    VINSMOKE_FAMILY                 = 32
    SUN_PIRATES                     = 33
    LONG_ARM_TRIBE                  = 34
    LONG_LEG_TRIBE                  = 35
    THREE_EYE_TRIBE                 = 36
    GIANT                           = 37
    SKY_ISLAND                      = 38
    DRUM_ISLAND                     = 39
    DRUM_ISLAND_KINGDOM             = 40
    TORINO_KINGDOM                  = 41
    BIRKA                           = 42
    BOIN_ARCHIPELAGO                = 43
    SABAODY_ARCHIPELAGO             = 44
    MARINEFORD                      = 45
    PIRATES                         = 46
    CRIMINAL                        = 47
    BOUNTY_HUNTER                   = 48
    DOCTOR                          = 49
    EXPLORER                        = 50
    ASSASSIN                        = 51
    NINJA                           = 52
    SAMURAI                         = 53
    SWORDSMAN                       = 54
    SNIPER                          = 55
    COOK                            = 56
    NAVIGATOR                       = 57
    MUSICIAN                        = 58
    ARCHAEOLOGIST                   = 59
    SHIPWRIGHT                      = 60
    THIEF                           = 61
    FIGHTER                         = 62
    SCIENTIST                       = 63
    REBEL_ARMY                      = 64
    CELESTIAL_DRAGON                = 65
    GILD_TESORO_ENTERTAINMENT       = 66
    FILM                            = 67
    HAPPOU_NAVY                     = 68
    YONKO                           = 69  # (Four Emperors alias)
    WHITEBEARD_ALLIANCE             = 70
    ROGER_PIRATES                   = 71
    ROCKS_PIRATES                   = 72
    SPACE_PIRATES                   = 73
    BUGGY_PIRATES                   = 74
    FOXY_PIRATES                    = 75
    ARLONG_PIRATES                  = 76
    KRIEG_PIRATES                   = 77
    RED_HAIR_PIRATES                = 78
    HAWKINS_PIRATES                 = 79
    ON_AIR_PIRATES                  = 80
    BONNEY_PIRATES                  = 81
    FALLEN_MONK_PIRATES             = 82
    BEAUTIFUL_PIRATES               = 83
    FIRE_TANK_PIRATES               = 84
    SPADE_PIRATES                   = 85
    NEW_GIANT_PIRATES               = 86
    CROSS_GUILD                     = 87
    BEASTS_PIRATES                  = 88
    GODS_KNIGHTS                    = 89
    GIANT_WARRIOR_PIRATES           = 90
    GOLDEN_LION_PIRATES             = 91
    NAVY_ADMIRALS                   = 92
    WORLD_GOVERNMENT                = 93
    RYUGU_KINGDOM                   = 94
    DRESSROSA                       = 95
    WHOLE_CAKE_ISLAND               = 96
    PUNK_HAZARD                     = 97
    WEATHER_SCIENCE_TEAM            = 98   # (Weatheria etc.)
    TONTATTA_TRIBE                  = 99
    KOZUKI_NINE_RED_SCABBARDS       = 100
    SLAVE                           = 101
    SHANDORA                        = 102
    BIRKANS                         = 103
    SHANDIAN                        = 104
    GALLEY_LA_COMPANY               = 105
    WATER_SEVEN                     = 106
    GARP_FAMILY                     = 107
    AMAZON_LILY                     = 108
    RACE_ANIMAL                     = 109   # (Zoan users etc.)
    INTELLIGENCE_AGENCY             = 110   # (CP agents)
    CORRIDA_COLOSSEUM               = 111
    DADAN_FAMILY                    = 112
    NEWKAMA                         = 113
    NAVY_HQ                         = 114
    ENIES_LOBBY                     = 115
    BIOLOGICAL_WEAPON               = 116   # (SMILE / Gifters)
    STRAW_HAT_FLEET_MEMBER          = 117
    KUROZUMI_CLAN                   = 118
    GERMA_KINGDOM                   = 119
    CAESAR_CLOWN_CREW               = 120
    WHITEBEARD_COMMANDERS           = 121
    CARIBOU_PIRATES                 = 122
    BROWNBEARD_CREW                 = 123
    CIPHER_POL                      = 124
    TWIN_CAPES_LIGHTHOUSE           = 125
    BARATIE                         = 126
    FOOSHA_VILLAGE                  = 127
    SYRUP_VILLAGE                   = 128
    COCOYASHI_VILLAGE               = 129
    GECKO_PIRATES                   = 130
    RUMBAR_PIRATES                  = 131
    ROCKETMAN                       = 132
    THRILLER_BARK                   = 133
    IMPEL_DOWN_LEVEL_6              = 134
    USOPP_PIRATES                   = 135
    BELLAMY_PIRATES                 = 136
    ONCE_PIECE_FILM                 = 137   # Film characters
    GORGON_SISTERS                  = 138
    TRIBE                           = 139
    COMMANDER                       = 140
    NONE                            = 141
    # Extras adicionados em sets posteriores
    SERAPHIM                        = 142
    NAVY_RANK_CAPTAIN               = 143
    EGGHEAD                         = 144
    VEGAPUNK                        = 145
    YORK_SATELLITE                  = 146   # Satellites
    GIANT_WARRIOR                   = 147
    BLACKBEARD_PIRATES              = 148
    LUFFY_PIRATES                   = 149
    LOKI_PIRATES                    = 150
    ELBAPH                          = 151
    LULUSIA_KINGDOM                 = 152
    CITIZEN                         = 153
    NAVY_VICE_ADMIRAL               = 154
    NAVY_CAPTAIN                    = 155
    NAVY_REAR_ADMIRAL               = 156
    NAVY_ENSIGN                     = 157
    NAVY_COMMANDER                  = 158
    NAVY_LIEUTENANT                 = 159
    NAVY_PETTY_OFFICER              = 160
    NAVY_SEAMAN                     = 161
    NEW_WORLD                       = 162
    DARK_KING                       = 163
    IMU_SAMA                        = 164


# ---------------------------------------------------------------------------
# ActionChoice  (Token: 0x020000AD)
# Usado em ActivatedCardAction.eChoice — escolha do jogador mid-ação
# ---------------------------------------------------------------------------
class ActionChoice(IntEnum):
    NONE         = 0
    KO           = 1   # KO a carta alvo
    BOUNCE       = 2   # Retornar à mão
    TOP_LIFE     = 3   # Enviar ao topo da vida
    BOTTOM_LIFE  = 4   # Enviar ao fundo da vida
    DAMAGE       = 5   # Causar dano direto
    COST         = 6   # Relacionado a custo (ex: Perona)
    TRASH        = 7   # Descartar
    HIDE_LIFE    = 8   # Esconder cartas de vida (virar face down)
    ARRANGE_LIFE = 9   # Reorganizar a vida


# ---------------------------------------------------------------------------
# RemovalEffect  (Token: 0x020000AC)
# Rastreia COMO uma carta está sendo removida — usado pelo sistema de
# replacement effects (PreKO, PreBounce, PreAllyKO, etc.)
# ---------------------------------------------------------------------------
class RemovalEffect(IntEnum):
    NONE             = 0
    # Remoções próprias (da própria carta)
    KO               = 1
    REST             = 2
    BOTTOM_LIFE      = 3
    TOP_LIFE         = 4
    TRASH            = 5
    BOUNCE           = 6   # Retornar à mão
    DECK_BOTTOM      = 7
    # Remoções de aliado (triggered quando um aliado é removido)
    ALLY_KO          = 8
    ALLY_BOUNCE      = 9
    ALLY_BOTTOM_LIFE = 10
    ALLY_TOP_LIFE    = 11
    ALLY_TRASH       = 12
    ALLY_DECK_BOTTOM = 13


# ---------------------------------------------------------------------------
# GameplayState  (Token: 0x020000A7)
# Máquina de estados do GameplayLogicScript
# ---------------------------------------------------------------------------
class GameplayState(IntEnum):
    # ── Setup ──────────────────────────────────────────────────────────────
    START_WAIT_ON_TURN_SELECTION      = 0
    START_WAIT_ON_TURN_ORDER          = 1
    START_WAIT_ON_DECK_FILL           = 2
    START_WAIT_ON_START_GAME_ACTION   = 3
    START_WAIT_ON_MULLIGAN_CHOICE     = 4
    START_WAIT_ON_OPPONENT_START      = 5

    # ── Início de turno ────────────────────────────────────────────────────
    PLAYER_TURN_START                 = 6
    PLAYER_TURN_START_WAIT            = 7
    PLAYER_TURN_UNTAP                 = 8   # destap don/cartas
    PLAYER_TURN_DRAW_CARD             = 9
    PLAYER_TURN_DRAW_CARD_WAIT        = 10
    PLAYER_TURN_DRAW_DON              = 11
    PLAYER_TURN_DRAW_DON_WAIT         = 12
    PLAYER_TURN_MAIN_WAIT             = 13  # aguarda fim de StartOfMainPhase
    PLAYER_TURN_ACTION                = 14  # fase principal ativa

    # ── Ações ──────────────────────────────────────────────────────────────
    ACTION_ATTACHING_DON              = 15
    ACTION_SELECTING_DEPLOY_SWAP      = 16

    # ── Combate ────────────────────────────────────────────────────────────
    ATTACK_SELECTING_TARGET           = 17
    ATTACK_HANDLING_CONFUSION         = 18
    ATTACK_WAIT_ON_COUNTERS           = 19
    ATTACK_WAIT_ON_BLOCKER            = 20
    ATTACK_BEFORE_BLOCKER             = 21

    # ── Pós-ataque ─────────────────────────────────────────────────────────
    POST_ATTACK_HIT_LEADER            = 22
    POST_ATTACK_HIT_LEADER_DOUBLE     = 23  # primeiro hit de double attack
    POST_ATTACK_KOD_CHARACTER         = 24

    # ── Vida / Trigger ─────────────────────────────────────────────────────
    LIFE_ACTIVATE_TRIGGER             = 25
    LIFE_DOUBLE_TRIGGERING            = 26  # segundo hit do double attack

    # ── UI / misc ──────────────────────────────────────────────────────────
    MAIN_MENU                         = 27
    LOBBY_HOSTING                     = 28
    LOBBY_JOINING                     = 29
    GAME_OVER                         = 30
    OPPONENT_TURN_ACTION              = 31
    TRASH_VIEWING_SELF                = 32
    TRASH_VIEWING_OPPONENT            = 33
    CONFIRM_REVEALED_CARD             = 34
    CONFIRM_REVEALED_CARD_OPP_TURN    = 35
    MULTIPLAYER_REMATCH               = 36
    MULTIPLAYER_REMATCH_READY         = 37
    OPPONENT_DISCONNECT               = 38
    OBSERVING                         = 39
    OBSERVING_COMBAT                  = 40

    # ── Fim de turno ───────────────────────────────────────────────────────
    ENDING_TURN                       = 41
    END_TURN_TRASHING_FILM            = 42  # descarta personagens Film
    END_TURN_EQUAL_DON                = 43  # ReturnDonToEqual

    # ── Save state ─────────────────────────────────────────────────────────
    SAVE_STATE_LOADING                = 44
    SAVE_STATE_TURN_START             = 45


# ---------------------------------------------------------------------------
# ReplaySyncZone  — códigos de zona para o sistema de replay (RZ1)
# Fonte: ReplaySync_TryGetZoneSlot (linhas 32677-32787 do GameplayLogicScript)
# ---------------------------------------------------------------------------
class ReplaySyncZone(IntEnum):
    DECK           = 0
    HAND           = 1
    DEPLOY         = 2   # campo (personagens jogados)
    LIFE           = 3
    DON_DECK       = 4
    DON_COST_AREA  = 5
    TRASH          = 6
    STAGE          = 7
    LEADER         = 8
    ATTACHED_DON   = 9   # don equipado a um personagem/líder


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def card_type_name(ct: CardType) -> str:
    return ct.name.title().replace("_", " ")


def colors_from_list(color_ints: list[int]) -> list[CardColor]:
    return [CardColor(c) for c in color_ints]


def categories_from_list(cat_ints: list[int]) -> list[CardCategory]:
    return [CardCategory(c) for c in cat_ints]