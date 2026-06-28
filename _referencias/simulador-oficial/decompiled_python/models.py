"""
optcg_engine/models.py
======================
Estruturas de dados do simulador OPTCG.

Fontes:
  - CardDefinition  → classe C# Token 0x02000073
  - LiveCard        → struct C# (campos de CardLogicScript.myCard)
  - PlayerState     → classe C# (campos de GameplayLogicScript.Lps_Players)
  - GameState       → estado completo de uma partida

Todas as decisões de design (nomes, tipos, valores padrão) foram
extraídas diretamente do Assembly-CSharp.dll v1.40a via dnSpy.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .enums import (
    CardType, CardColor, StrikeType, CardCategory, RemovalEffect
)

# Evita importação circular — action_system importa models,
# mas models só precisa dos tipos para type hints
if TYPE_CHECKING:
    from .action_system import ActV3Base, CardAction


# ===========================================================================
# Structs auxiliares (extraídos do C#)
# ===========================================================================

@dataclass
class CategoryCount:
    """
    Struct CategoryCount (Token 0x02000063).
    Usado em condições de ActV3Proc e ActV3StepDetails.
    Ex: 'precisa de pelo menos 2 personagens StrawHatCrew no campo'
    """
    category: CardCategory = CardCategory.NONE
    count: int = 0


@dataclass
class StringCount:
    """
    Struct StringCount (Token 0x02000064).
    Usado em NamesWithBasePowerInYourDeploy, NamesWithExactBasePowerInYourDeploy, etc.
    Ex: 'Luffy com base power exatamente 5000'
    """
    string: str = ""
    count: int = 0


# ===========================================================================
# CardDefinition
# ===========================================================================

@dataclass
class CardDefinition:
    """
    Classe CardDefinition (Token 0x02000073).
    Define os atributos ESTÁTICOS de uma carta — o que está impresso nela.
    Imutável durante o jogo; LiveCard guarda o estado dinâmico.

    Mapeamento C# → Python:
        cardID              → card_id
        cardType            → card_type
        characterName       → character_name
        strikeType          → strike_type
        cardLife            → card_life        (só Leaders)
        cardPower           → card_power
        cardCounter         → card_counter     (0, 1000, 2000)
        cardCost            → card_cost
        cardCategories      → card_categories
        cardColors          → card_colors
        extraNames          → extra_names      (nomes alternativos)
        extraStrikeTypes    → extra_strike_types
        blockNumberOverride → block_number_override
        cardActions         → card_actions     (sistema legado)
        actionV3s           → action_v3s       (sistema V3 — principal)
    """

    # ── Identidade ──────────────────────────────────────────────────────────
    card_id: str = ""                          # ex: "OP01-001"
    character_name: str = ""                   # ex: "Monkey D. Luffy"
    extra_names: list[str] = field(default_factory=list)

    # ── Tipo ────────────────────────────────────────────────────────────────
    card_type: CardType = CardType.CHARACTER
    strike_type: StrikeType = StrikeType.NONE
    extra_strike_types: list[StrikeType] = field(default_factory=list)

    # ── Stats base ──────────────────────────────────────────────────────────
    card_life: int = 0                         # só Leaders usam (4 ou 5)
    card_power: int = 0                        # ex: 5000, 6000, 9000
    card_counter: int = 0                      # 0, 1000 ou 2000
    card_cost: int = 0

    # ── Afiliações ──────────────────────────────────────────────────────────
    card_categories: list[CardCategory] = field(default_factory=list)
    card_colors: list[CardColor] = field(default_factory=list)

    # ── Número de bloco ─────────────────────────────────────────────────────
    block_number_override: int = 0

    # ── Sistemas de ação ────────────────────────────────────────────────────
    # Importação adiada para evitar circular import
    card_actions: list = field(default_factory=list)   # List[CardAction] legado
    action_v3s: list = field(default_factory=list)     # List[ActV3Base] principal

    # ── Helpers ─────────────────────────────────────────────────────────────

    def has_color(self, color: CardColor) -> bool:
        return color in self.card_colors

    def has_category(self, category: CardCategory) -> bool:
        return category in self.card_categories

    def has_name(self, name: str, exact: bool = True) -> bool:
        if exact:
            return (self.character_name == name or name in self.extra_names)
        return (name in self.character_name or
                any(name in n for n in self.extra_names))

    def is_multi_color(self) -> bool:
        return len(self.card_colors) > 1

    def __repr__(self) -> str:
        return f"CardDefinition({self.card_id!r}, {self.character_name!r})"


# ===========================================================================
# LiveCard
# ===========================================================================

@dataclass
class LiveCard:
    """
    Estado DINÂMICO de uma carta em jogo.
    Extraído dos campos de CardLogicScript.myCard no Assembly-CSharp.dll.

    Cada instância corresponde a uma carta física no tabuleiro.
    O deck_unique_id é o identificador global único:
        Jogador 0: positivo  (líder=1, deck=(i+1)*10, don=(i+10000))
        Jogador 1: negativo  (líder=-1, deck=-(i+1)*10, don=-(i+10000))
        0 = null / não encontrado
    """

    # ── Definição base (imutável) ───────────────────────────────────────────
    card_def: CardDefinition = field(default_factory=CardDefinition)
    deck_unique_id: int = 0

    # ── Power / combat ──────────────────────────────────────────────────────
    card_power: int = 0                        # buff permanente (+X power)
    card_combat_power: int = 0                 # buff de combate (counter/blocker)
    card_combat_base_power: int = 0            # modifica o BASE power no combate
    card_base_power_change: int = 0            # altera base power permanentemente
    card_base_power_change_to_start: int = 0   # expira no início do próximo turno
    card_base_power_change_to_opp_end: int = 0 # expira no fim do turno do oponente
    card_power_to_start: int = 0               # expira início do próximo turno
    card_power_to_owners_turn_end: int = 0     # expira fim do turno do dono
    card_power_to_opp_turn_end: int = 0        # expira fim do turno do oponente
    card_temp_combat_power: int = 0            # temporário de combate
    i_cost_change: int = 0                     # alteração de custo permanente
    i_cost_change_to_opp_end: int = 0          # expira fim do turno do oponente
    i_max_don: int = 0                         # override do máximo de don (ex: 0=usa default 10)

    # ── Estado físico ───────────────────────────────────────────────────────
    b_tapped: bool = False                     # repousado / tapped
    b_face_up: bool = False                    # virado para cima (vida revelada)
    b_forced_face_up: bool = False             # forçado face-up por efeito
    b_summon_sick: bool = True                 # recém jogado — não pode atacar
    b_first_turn: bool = True                  # primeiro turno em campo
    b_last_tapped_state: bool = False          # estado antes de ser removido

    # ── Batalha / turno ─────────────────────────────────────────────────────
    b_has_battled_character: bool = False      # batalhou contra personagem neste turno
    b_opp_character_kod: bool = False          # um personagem oponente foi KO'd neste turno
    b_opponent_lost_life: bool = False         # oponente perdeu vida neste turno

    # ── Keywords permanentes ────────────────────────────────────────────────
    b_blocker: bool = False
    b_double_attack: bool = False
    b_banish: bool = False
    b_rush_characters: bool = False            # personagens do campo ganham Rush
    b_unblockable: bool = False
    b_can_attack_active: bool = False          # pode atacar cartas ativas

    # ── Keywords temporárias (duram até fim de fase/turno) ──────────────────
    b_temp_banish: bool = False                # Banish temporário (combate)
    b_temp_double_attack: bool = False         # Double Attack temporário
    b_blocker_to_opp_turn_end: bool = False    # Blocker até fim do turno do oponente
    b_lose_blocker: bool = False               # PERDE Blocker (override)

    # ── Restrições ──────────────────────────────────────────────────────────
    b_cant_attack: bool = False
    b_cant_rest: bool = False                  # não pode ser repousado
    b_cant_draw_via_effects: bool = False      # não pode comprar por efeitos
    b_cant_play_any_from_hand: bool = False    # não pode jogar cartas da mão
    b_cant_play_any_characters_to_field: bool = False
    i_cant_attack_cost_x_or_less: int = 0     # não pode atacar personagens com custo <= X
    i_cant_play_original_cost_or_more: int = 0 # não pode jogar cartas com custo base >= X
    b_skip_next_active: bool = False           # pula o destap no próximo turno (freeze)

    # ── Imunidades ──────────────────────────────────────────────────────────
    b_immune: bool = False                     # imune a TUDO (efeitos + combate)
    b_combat_immune: bool = False              # imune a combate
    b_combat_immune_to_start: bool = False     # imune a combate até início do próximo turno
    b_combat_immune_to_end: bool = False       # imune a combate até fim deste turno
    b_effect_immune: bool = False              # imune a efeitos não-combate
    b_my_chars_immune: bool = False            # TODOS os meus personagens ficam imunes

    # ── Silêncio ────────────────────────────────────────────────────────────
    b_silenced: bool = False                   # silenciado (até fim de turno)
    b_silenced_to_owners_end: bool = False     # silenciado até fim do turno do dono
    b_roger_silence: bool = False              # silêncio especial do Roger

    # ── Efeitos de campo ────────────────────────────────────────────────────
    b_my_field_unblockable: bool = False       # meu campo todo fica unblockable
    b_field_cant_attack_leader: bool = False   # campo oponente não pode atacar líder
    b_my_don_cant_activate_via_characters: bool = False
    b_no_draw_from_life_to_start: bool = False # não compra de vida até início do turno
    b_no_on_play_to_turn_end: bool = False     # oponente não usa OnPlay até fim do turno

    # ── Efeitos especiais de líder ───────────────────────────────────────────
    b_kinemon_leader_effect: bool = False      # Kinemon: WanoCountry -1 custo
    b_rosinante_leader_effect: bool = False    # Rosinate: Trafalgar Law -2 custo
    b_usopp_cost_change: bool = False          # Usopp leader: +1 custo na carta

    # ── Flags de turno / estado ─────────────────────────────────────────────
    b_take_another_turn: bool = False          # ganha turno extra
    b_turn_end_eq_don: bool = False            # iguala don no fim de turno
    b_activate_film_at_end: bool = False       # ativa personagens Film no fim de turno

    # ── Contadores ──────────────────────────────────────────────────────────
    i_confusion: int = 0                       # confusion stacks
    i_turn_end_active_don: int = 0             # don ativo ganho no fim de turno
    i_turn_end_gain_active_don: int = 0
    i_turn_end_heal: int = 0                   # vida ganha no fim de turno
    i_turn_end_trash_film: int = 0             # personagens Film descartados no fim de turno
    i_hand_ui_order: int = 0                   # ordem na mão (UI)

    # ── Ações ───────────────────────────────────────────────────────────────
    lb_actions_used: list[bool] = field(default_factory=list)
    # List[ActV3Base] — ações concedidas por efeitos (temp=True)
    l_granted_actions: list = field(default_factory=list)
    l_extra_strike_types: list[StrikeType] = field(default_factory=list)

    # ── Filas de fim/início de turno ─────────────────────────────────────────
    # Cada tuple é (deck_unique_id_do_ator, action_idx)
    t_end_of_turn_actions: list[tuple[int, int]] = field(default_factory=list)
    t_start_of_main_phase_actions: list[tuple[int, int]] = field(default_factory=list)

    # ── Don equipado ────────────────────────────────────────────────────────
    # Lista de LiveCard (don tokens) equipados a esta carta
    attached_don: list[LiveCard] = field(default_factory=list)

    # ── Helpers ─────────────────────────────────────────────────────────────

    @property
    def is_silenced(self) -> bool:
        return self.b_silenced or self.b_silenced_to_owners_end or self.b_roger_silence

    @property
    def is_immune_to_all(self) -> bool:
        """bMyCharsImmune (Character) OU bImmune — ordem exata do CardIsImmuneToAll."""
        return self.b_immune or (
            self.b_my_chars_immune and
            self.card_def.card_type == CardType.CHARACTER
        )

    @property
    def attached_don_count(self) -> int:
        return len(self.attached_don)

    def reset_combat_power(self) -> None:
        """Zera campos de combate — chamado por ResetCombatPower()."""
        self.card_combat_power = 0
        self.card_combat_base_power = 0
        self.card_temp_combat_power = 0
        self.b_temp_banish = False
        self.b_temp_double_attack = False

    def __repr__(self) -> str:
        return (f"LiveCard({self.card_def.card_id!r}, "
                f"id={self.deck_unique_id}, "
                f"tapped={self.b_tapped})")


# ===========================================================================
# PlayerState
# ===========================================================================

@dataclass
class PlayerState:
    """
    Estado de um jogador durante a partida.
    Mapeamento direto da classe PlayerState do C#.

    Zonas do jogo (todas são listas de LiveCard):
        deck          → Lgo_MyDeck
        don_deck      → Lgo_MyDonDeck
        leader        → Lgo_MyLeader      (sempre 1 carta)
        stage         → Lgo_MyStage       (0 ou 1 carta)
        life_deck     → Lgo_MyLifeDeck    (topo = [-1])
        don_cost_area → Lgo_MyDonCostArea (don disponíveis/repousados)
        trash         → Lgo_MyTrash
        hand          → Lgo_MyHand
        deploy        → Lgo_MyDeploy      (personagens em campo, máx 5)
    """

    player_name: str = ""
    player_id: int = 0                         # 0 ou 1

    # ── Zonas ───────────────────────────────────────────────────────────────
    deck: list[LiveCard] = field(default_factory=list)
    don_deck: list[LiveCard] = field(default_factory=list)
    leader: list[LiveCard] = field(default_factory=list)
    stage: list[LiveCard] = field(default_factory=list)
    life_deck: list[LiveCard] = field(default_factory=list)
    don_cost_area: list[LiveCard] = field(default_factory=list)
    trash: list[LiveCard] = field(default_factory=list)
    hand: list[LiveCard] = field(default_factory=list)
    deploy: list[LiveCard] = field(default_factory=list)

    # ── Rastreadores ────────────────────────────────────────────────────────
    # iHighestEventPlayed — custo do evento mais caro ativado (para condições
    # como ActivatedEventXOrMore no ActV3StepDetails)
    i_highest_event_played: int = 0

    # ── Helpers ─────────────────────────────────────────────────────────────

    def max_don(self) -> int:
        """
        Retorna o máximo de don deste jogador.
        Verifica se o líder tem um passive DonDeckOverride (ex: líderes especiais).
        Padrão = 10.
        """
        if self.leader:
            for action in self.leader[0].l_granted_actions:
                if (getattr(action, 'proc', None) and
                        action.proc.passive and
                        action.steps and
                        getattr(action.steps[0].effect, 'don_deck_override', 0) != 0):
                    return action.steps[0].effect.don_deck_override
            for action in self.leader[0].card_def.action_v3s:
                if (getattr(action, 'proc', None) and
                        action.proc.passive and
                        action.steps and
                        getattr(action.steps[0].effect, 'don_deck_override', 0) != 0):
                    return action.steps[0].effect.don_deck_override
        return 10

    def don_on_field(self) -> int:
        """
        Don em jogo = max_don - don restante no deck de don.
        Equivale a DonOnField() do C#.
        """
        return self.max_don() - len(self.don_deck)

    def available_don(self) -> int:
        """
        Don ativo (não repousado) disponível para gastar.
        Equivale a AvailableDon() / FirstAvailableDon() do C#.
        """
        return sum(1 for d in self.don_cost_area if not d.b_tapped)

    def rested_don(self) -> int:
        """Don repousado (tapped) no cost area."""
        return sum(1 for d in self.don_cost_area if d.b_tapped)

    def get_leader(self) -> LiveCard | None:
        return self.leader[0] if self.leader else None

    def get_stage(self) -> LiveCard | None:
        return self.stage[0] if self.stage else None

    def life_count(self) -> int:
        return len(self.life_deck)

    def hand_count(self) -> int:
        return len(self.hand)

    def deploy_count(self) -> int:
        return len(self.deploy)

    def deck_count(self) -> int:
        return len(self.deck)

    def trash_count(self) -> int:
        return len(self.trash)

    def field_is_full(self) -> bool:
        """Campo cheio = 5 personagens."""
        return len(self.deploy) >= 5

    def find_card_by_id(self, deck_unique_id: int) -> LiveCard | None:
        """
        Busca uma carta em todas as zonas pelo deck_unique_id.
        Replica FindCardByUniqueDeckID do C# para um único jogador.
        """
        # Líder e don do líder
        if self.leader:
            ldr = self.leader[0]
            if ldr.deck_unique_id == deck_unique_id:
                return ldr
            for don in ldr.attached_don:
                if don.deck_unique_id == deck_unique_id:
                    return don

        # Deploy e don equipado
        for card in self.deploy:
            if card.deck_unique_id == deck_unique_id:
                return card
            for don in card.attached_don:
                if don.deck_unique_id == deck_unique_id:
                    return don

        # Outras zonas
        for zone in (self.hand, self.stage, self.trash,
                     self.life_deck, self.deck, self.don_cost_area):
            for card in zone:
                if card.deck_unique_id == deck_unique_id:
                    return card

        return None

    def __repr__(self) -> str:
        return (f"PlayerState({self.player_name!r}, "
                f"hand={len(self.hand)}, "
                f"deploy={len(self.deploy)}, "
                f"life={len(self.life_deck)}, "
                f"don={self.don_on_field()})")


# ===========================================================================
# GameState
# ===========================================================================

@dataclass
class GameState:
    """
    Estado completo de uma partida.
    Combina GameStateVars (gsv_CurrentGame) e a lista de jogadores
    (Lps_Players) do GameplayLogicScript.
    """

    players: list[PlayerState] = field(default_factory=list)

    # gsv_CurrentGame equivalents
    player_turn: int = 0            # iPlayerTurn — quem está com o turno
    player_action: int = 0          # iPlayerAction — quem está resolvendo ações
    player_goes_first: int = 0      # iPlayerGoesFirst
    turn_number: int = 1            # iTurnNumber (global)
    player_turn_number: int = 1     # iPlayerTurnNumber (por jogador)
    action_choices_stack: int = 0   # iActionChoicesStack

    # ── Helpers ─────────────────────────────────────────────────────────────

    def current_player(self) -> PlayerState | None:
        if self.players and 0 <= self.player_turn < len(self.players):
            return self.players[self.player_turn]
        return None

    def opponent_player(self) -> PlayerState | None:
        opp = 1 - self.player_turn
        if self.players and 0 <= opp < len(self.players):
            return self.players[opp]
        return None

    def find_card_by_id(self, deck_unique_id: int) -> LiveCard | None:
        """
        Busca global em ambos os jogadores.
        Replica FindCardByUniqueDeckID do GameplayLogicScript.
        IDs positivos = player 0, negativos = player 1.
        """
        if deck_unique_id == 0:
            return None
        owner_idx = 0 if deck_unique_id > 0 else 1
        if owner_idx < len(self.players):
            return self.players[owner_idx].find_card_by_id(deck_unique_id)
        return None

    def find_card_owner(self, card: LiveCard) -> PlayerState | None:
        """Retorna o PlayerState dono da carta."""
        for ps in self.players:
            if ps.find_card_by_id(card.deck_unique_id) is not None:
                return ps
        return None

    def __repr__(self) -> str:
        return (f"GameState(turn={self.turn_number}, "
                f"active={self.player_turn}, "
                f"players={len(self.players)})")