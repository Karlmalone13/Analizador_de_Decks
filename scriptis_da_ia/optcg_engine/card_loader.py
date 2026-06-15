"""
optcg_engine/card_loader.py
============================
Carrega o cards_rows.csv do Supabase e converte para CardDefinition.

Detecta keywords diretamente do texto da carta (card_text) e monta
ActV3Base simplificados para cada efeito, compatíveis com o engine.

Uso:
    from optcg_engine.card_loader import CardLoader

    loader = CardLoader('cards_rows.csv')
    card_def = loader.get('OP01-001')  # CardDefinition completo
    deck_config = loader.build_deck_config(deck_json, name='Meu Deck')
"""

from __future__ import annotations
import re
import pandas as pd
from typing import Optional

from .models import CardDefinition
from .enums import (
    CardType, CardColor, StrikeType, CardCategory
)
from .action_system import (
    ActV3Base, ActV3Proc, ActV3Step, ActV3StepDetails,
    ActV3Target, ActV3Effect
)


# ===========================================================================
# Mapeamentos de texto → enums
# ===========================================================================

COLOR_MAP = {
    'red':    CardColor.RED,
    'green':  CardColor.GREEN,
    'blue':   CardColor.BLUE,
    'purple': CardColor.PURPLE,
    'black':  CardColor.BLACK,
    'yellow': CardColor.YELLOW,
}

TYPE_MAP = {
    'leader':    CardType.LEADER,
    'character': CardType.CHARACTER,
    'event':     CardType.EVENT,
    'stage':     CardType.STAGE,
    'don!!':     CardType.CHARACTER,  # don token
}

STRIKE_MAP = {
    'slash':   StrikeType.SLASH,
    'strike':  StrikeType.STRIKE,
    'ranged':  StrikeType.RANGED,
    'special': StrikeType.SPECIAL,
    'wisdom':  StrikeType.WISDOM,
}

# Mapa de sub_types (texto) → CardCategory
# Cobre os principais tipos do jogo
SUBTYPE_MAP = {
    'straw hat crew':           CardCategory.STRAW_HAT_CREW,
    'four emperors':            CardCategory.FOUR_EMPERORS,
    'navy':                     CardCategory.NAVY,
    'revolutionary army':       CardCategory.REVOLUTIONARY_ARMY,
    'supernovas':               CardCategory.SUPERNOVAS,
    'worst generation':         CardCategory.SUPERNOVAS,
    'animal kingdom pirates':   CardCategory.ANIMAL_KINGDOM_PIRATES,
    'big mom pirates':          CardCategory.BIG_MOM_PIRATES,
    'heart pirates':            CardCategory.HEART_PIRATES,
    'kid pirates':              CardCategory.KID_PIRATES,
    'donquixote pirates':       CardCategory.DONQUIXOTE_PIRATES,
    'whitebeard pirates':       CardCategory.WHITEBEARD_PIRATES,
    'roger pirates':            CardCategory.ROGER_PIRATES,
    'beasts pirates':           CardCategory.BEASTS_PIRATES,
    'land of wano':             CardCategory.WANO_COUNTRY,
    'wano country':             CardCategory.WANO_COUNTRY,
    'alabasta':                 CardCategory.ALABASTA_KINGDOM,
    'east blue':                CardCategory.EAST_BLUE,
    'baroque works':            CardCategory.BAROQUE_WORKS,
    'cp9':                      CardCategory.CP9,
    'cp0':                      CardCategory.CP0,
    'impel down':               CardCategory.IMPEL_DOWN,
    'sky island':               CardCategory.SKY_ISLAND,
    'fish-man island':          CardCategory.FISH_MAN_ISLAND,
    'fish man island':          CardCategory.FISH_MAN_ISLAND,
    'mink tribe':               CardCategory.MINK_TRIBE,
    'kozuki clan':              CardCategory.KOZUKI_CLAN,
    'germa 66':                 CardCategory.GERMA_66,
    'vinsmoke family':          CardCategory.VINSMOKE_FAMILY,
    'sun pirates':              CardCategory.SUN_PIRATES,
    'kuja pirates':             CardCategory.KUJA_PIRATES,
    'thriller bark pirates':    CardCategory.THRILLER_BARK_PIRATES,
    'red hair pirates':         CardCategory.RED_HAIR_PIRATES,
    'blackbeard pirates':       CardCategory.BLACKBEARD_PIRATES,
    'cross guild':              CardCategory.CROSS_GUILD,
    'rocks pirates':            CardCategory.ROCKS_PIRATES,
    'egghead':                  CardCategory.EGGHEAD,
    'vegapunk':                 CardCategory.VEGAPUNK,
    'seraphim':                 CardCategory.SERAPHIM,
    'film':                     CardCategory.FILM,
    'doctor':                   CardCategory.DOCTOR,
    'swordsman':                CardCategory.SWORDSMAN,
    'sniper':                   CardCategory.SNIPER,
    'cook':                     CardCategory.COOK,
    'navigator':                CardCategory.NAVIGATOR,
    'musician':                 CardCategory.MUSICIAN,
    'archaeologist':            CardCategory.ARCHAEOLOGIST,
    'shipwright':               CardCategory.SHIPWRIGHT,
    'fighter':                  CardCategory.FIGHTER,
    'scientist':                CardCategory.SCIENTIST,
    'assassin':                 CardCategory.ASSASSIN,
    'ninja':                    CardCategory.NINJA,
    'samurai':                  CardCategory.SAMURAI,
    'captain':                  CardCategory.CAPTAIN,
    'pirate':                   CardCategory.PIRATES,
    'pirates':                  CardCategory.PIRATES,
    'bounty hunter':            CardCategory.BOUNTY_HUNTER,
    'criminal':                 CardCategory.CRIMINAL,
    'giant':                    CardCategory.GIANT,
    'animal':                   CardCategory.ANIMAL,
}


# ===========================================================================
# Parser de efeitos — lê card_text e monta ActV3Base
# ===========================================================================

def parse_colors(color_str: str) -> list[CardColor]:
    """Converte string de cor para lista de CardColor."""
    if not color_str or str(color_str) == 'nan':
        return []
    colors = []
    for part in re.split(r'[\s/]+', str(color_str)):
        c = COLOR_MAP.get(part.strip().lower())
        if c is not None:
            colors.append(c)
    return colors


def parse_subtypes(subtype_str: str) -> list[CardCategory]:
    """Converte sub_types para lista de CardCategory."""
    if not subtype_str or str(subtype_str) == 'nan':
        return []
    cats = []
    text = str(subtype_str).lower()
    for key, cat in SUBTYPE_MAP.items():
        if key in text and cat not in cats:
            cats.append(cat)
    return cats


def parse_strike(attr_str: str) -> StrikeType:
    """Converte attribute para StrikeType."""
    if not attr_str or str(attr_str) == 'nan':
        return StrikeType.NONE
    return STRIKE_MAP.get(str(attr_str).strip().lower(), StrikeType.NONE)


def make_passive_action(
    desc: str,
    effect: ActV3Effect,
    condition: ActV3Proc | None = None,
) -> ActV3Base:
    """Helper para criar ActV3Base passivo simples."""
    proc = condition or ActV3Proc(passive=True)
    proc.passive = True
    step = ActV3Step(
        internal_description=desc,
        details=ActV3StepDetails(),
        target=[],
        effect=effect,
    )
    return ActV3Base(
        internal_desc=desc,
        status_text=desc,
        proc=proc,
        steps=[step],
    )


def make_trigger_action(
    desc: str,
    effect: ActV3Effect,
    trigger_type: str = 'on_play',
) -> ActV3Base:
    """Helper para criar ActV3Base com trigger."""
    proc = ActV3Proc()
    setattr(proc, trigger_type, True)
    step = ActV3Step(
        internal_description=desc,
        details=ActV3StepDetails(),
        target=[ActV3Target(
            deployed_character=True,
            enemy_only=True,
            auto_all_matching_targets=False,
        )],
        effect=effect,
    )
    return ActV3Base(
        internal_desc=desc,
        status_text=desc,
        proc=proc,
        steps=[step],
    )


def parse_card_text_to_actions(text: str, counter_str: str) -> list[ActV3Base]:
    """
    Lê o card_text e gera ActV3Base para cada efeito detectado.
    Cobre os efeitos mais comuns do jogo.
    """
    if not text or str(text) == 'nan':
        return []

    t = str(text).lower()
    actions = []

    # ── Keywords passivas (sempre ativas) ────────────────────────────────

    if '[rush]' in t:
        ef = ActV3Effect(gain_rush=True)
        actions.append(make_passive_action('Rush', ef))

    if '[blocker]' in t:
        ef = ActV3Effect(gain_blocker=True)
        actions.append(make_passive_action('Blocker', ef))

    if '[double attack]' in t:
        ef = ActV3Effect(gain_double_attack=True)
        actions.append(make_passive_action('Double Attack', ef))

    if '[banish]' in t:
        ef = ActV3Effect(gain_banish=True)
        actions.append(make_passive_action('Banish', ef))

    if '[unblockable]' in t:
        ef = ActV3Effect(gain_unblockable=True)
        actions.append(make_passive_action('Unblockable', ef))

    # ── Trigger ──────────────────────────────────────────────────────────

    if '[trigger]' in t:
        # Detecta o que o trigger faz
        ef = ActV3Effect()
        if 'draw' in t and 'trigger' in t:
            m = re.search(r'draw\s+(\d+)', t)
            ef.draw_cards = int(m.group(1)) if m else 1
        elif 'play' in t and 'trigger' in t:
            ef.deploy_character = True
        elif 'k.o.' in t or 'trash' in t:
            ef.ko_card = True
        else:
            ef.draw_cards = 1  # trigger genérico

        proc = ActV3Proc(trigger=True)
        step = ActV3Step(
            internal_description='Trigger',
            details=ActV3StepDetails(),
            target=[],
            effect=ef,
        )
        actions.append(ActV3Base(
            internal_desc='Trigger',
            status_text='Trigger',
            proc=proc,
            steps=[step],
        ))

    # ── Counter ───────────────────────────────────────────────────────────

    if '[counter]' in t:
        ef = ActV3Effect()
        # Detecta efeito adicional do counter
        if 'draw' in t:
            m = re.search(r'draw\s+(\d+)', t)
            ef.draw_cards = int(m.group(1)) if m else 1
        elif 'k.o.' in t or 'trash' in t:
            ef.ko_card = True
        elif 'return' in t and 'hand' in t:
            ef.send_to_hand = True

        proc = ActV3Proc(counter=True)
        step = ActV3Step(
            internal_description='Counter',
            details=ActV3StepDetails(),
            target=[],
            effect=ef,
        )
        actions.append(ActV3Base(
            internal_desc='Counter',
            status_text='Counter',
            proc=proc,
            steps=[step],
        ))

    # ── On Play ───────────────────────────────────────────────────────────

    if '[on play]' in t or 'on play' in t:
        ef = ActV3Effect()
        details = ActV3StepDetails()
        target = []

        # Draw
        m = re.search(r'draw\s+(\d+)', t)
        if m:
            ef.draw_cards = int(m.group(1))

        # Search
        if 'look at' in t or 'search your deck' in t or 'add up to' in t:
            ef.searching_deck = True
            ef.draw_cards = max(ef.draw_cards, 1)

        # KO / Trash de personagem inimigo
        if ('k.o.' in t or ('trash' in t and 'opponent' in t)) and 'on play' in t:
            ef.ko_card = True
            m_cost = re.search(r'cost\s+(\d+)\s+or less', t)
            if m_cost:
                ef.ko_if_cost_x_or_less = int(m_cost.group(1))
            target = [ActV3Target(
                deployed_character=True,
                enemy_only=True,
                cost_or_less=ef.ko_if_cost_x_or_less or 99,
            )]

        # Bounce (return to hand)
        if 'return' in t and 'hand' in t and 'on play' in t:
            ef.send_to_hand = True
            m_cost = re.search(r'cost\s+(\d+)\s+or less', t)
            if m_cost:
                ef.ko_if_cost_x_or_less = int(m_cost.group(1))
            target = [ActV3Target(
                deployed_character=True,
                enemy_only=True,
                cost_or_less=ef.ko_if_cost_x_or_less or 99,
            )]

        # Rest effect
        if 'rest' in t and 'opponent' in t and 'on play' in t:
            ef.rest = True
            target = [ActV3Target(
                deployed_character=True,
                enemy_only=True,
            )]

        # Power buff
        m_buff = re.search(r'\+(\d+)\s*power', t)
        if m_buff:
            ef.buff_power = int(m_buff.group(1))

        # Power debuff do oponente
        m_debuff = re.search(r'-(\d+)\s*power', t)
        if m_debuff and 'opponent' in t:
            ef.buff_other = -int(m_debuff.group(1))

        if ef.draw_cards or ef.ko_card or ef.send_to_hand or ef.rest or ef.buff_power or ef.searching_deck:
            proc = ActV3Proc(on_play=True)
            step = ActV3Step(
                internal_description='On Play',
                details=details,
                target=target,
                effect=ef,
            )
            actions.append(ActV3Base(
                internal_desc='On Play',
                status_text='On Play',
                proc=proc,
                steps=[step],
            ))

    # ── Activate: Main ────────────────────────────────────────────────────

    if 'activate:main' in t or 'activate: main' in t or '[activate:main]' in t:
        ef = ActV3Effect()
        once = '[once per turn]' in t

        # Don cost
        m_don = re.search(r'\[don!!\s*x\s*(\d+)\]', t)
        if m_don:
            ef.don_tap = int(m_don.group(1))

        # Draw
        m = re.search(r'draw\s+(\d+)', t)
        if m:
            ef.draw_cards = int(m.group(1))

        # Rest oponente
        if 'rest' in t and ('opponent' in t or "opponent's" in t):
            ef.rest = True

        # KO
        if 'k.o.' in t or ('trash' in t and 'character' in t):
            ef.ko_card = True

        # Power buff
        m_buff = re.search(r'\+(\d+)\s*power', t)
        if m_buff:
            ef.buff_power = int(m_buff.group(1))

        if ef.draw_cards or ef.rest or ef.ko_card or ef.buff_power:
            proc = ActV3Proc(activate_main=True, once_per_turn=once)
            step = ActV3Step(
                internal_description='Activate Main',
                details=ActV3StepDetails(),
                target=[ActV3Target(
                    deployed_character=True,
                    enemy_only=True,
                )] if (ef.rest or ef.ko_card) else [],
                effect=ef,
            )
            actions.append(ActV3Base(
                internal_desc='Activate Main',
                status_text='Activate Main',
                proc=proc,
                steps=[step],
            ))

    # ── On Attack ─────────────────────────────────────────────────────────

    if '[when attacking]' in t or 'when attacking' in t or '[on attack]' in t:
        ef = ActV3Effect()

        m_buff = re.search(r'\+(\d+)\s*power', t)
        if m_buff:
            ef.buff_power = int(m_buff.group(1))

        m = re.search(r'draw\s+(\d+)', t)
        if m:
            ef.draw_cards = int(m.group(1))

        if ef.buff_power or ef.draw_cards:
            proc = ActV3Proc(on_attack=True)
            step = ActV3Step(
                internal_description='On Attack',
                details=ActV3StepDetails(),
                target=[],
                effect=ef,
            )
            actions.append(ActV3Base(
                internal_desc='On Attack',
                proc=proc,
                steps=[step],
            ))

    # ── Passivos de power (DON!! x1, etc.) ───────────────────────────────

    m_don_buff = re.search(r'\[don!!\s*x(\d+)\].*?\+(\d+)\s*power', t)
    if m_don_buff:
        don_req = int(m_don_buff.group(1))
        power_buff = int(m_don_buff.group(2))
        ef = ActV3Effect(passive_power_change=power_buff)
        proc = ActV3Proc(passive=True, self_attached_don=don_req)
        actions.append(make_passive_action(
            f'DON x{don_req} +{power_buff}',
            ef, proc
        ))

    # ── At the start of the game ──────────────────────────────────────────

    if 'at the start of the game' in t:
        ef = ActV3Effect()
        proc = ActV3Proc(start_of_game=True, passive=False)
        step = ActV3Step(
            internal_description='Start of Game',
            details=ActV3StepDetails(),
            target=[],
            effect=ef,
        )
        actions.append(ActV3Base(
            internal_desc='Start of Game',
            proc=proc,
            steps=[step],
        ))

    return actions


# ===========================================================================
# CardLoader
# ===========================================================================

class CardLoader:
    """
    Carrega o cards_rows.csv e converte para CardDefinition.

    Uso:
        loader = CardLoader('cards_rows.csv')
        cd = loader.get('OP01-001')
        deck = loader.build_deck_config(deck_json, name='Krieg')
    """

    def __init__(self, csv_path: str = 'cards_rows.csv'):
        self._db: dict[str, CardDefinition] = {}
        self._load(csv_path)

    def _load(self, csv_path: str) -> None:
        """Carrega e parseia o CSV."""
        try:
            df = pd.read_csv(csv_path)
        except FileNotFoundError:
            print(f"❌ {csv_path} não encontrado!")
            return

        # Normaliza tipos
        df['card_cost']      = pd.to_numeric(df['card_cost'],  errors='coerce').fillna(0).astype(int)
        df['card_power']     = pd.to_numeric(df['card_power'], errors='coerce').fillna(0).astype(int)
        df['life']           = pd.to_numeric(df['life'],       errors='coerce').fillna(0).astype(int)
        df['card_set_id']    = df['card_set_id'].fillna('').astype(str)
        df['card_name']      = df['card_name'].fillna('').astype(str)
        df['card_color']     = df['card_color'].fillna('').astype(str)
        df['card_type']      = df['card_type'].fillna('').astype(str)
        df['card_text']      = df['card_text'].fillna('').astype(str)
        df['counter_amount'] = df['counter_amount'].fillna('').astype(str)
        df['sub_types']      = df['sub_types'].fillna('').astype(str)
        df['attribute']      = df['attribute'].fillna('').astype(str)

        loaded = 0
        for _, row in df.iterrows():
            code = str(row['card_set_id']).split('_')[0].strip()
            if not code or code == 'nan':
                continue

            colors     = parse_colors(row['card_color'])
            categories = parse_subtypes(row['sub_types'])
            strike     = parse_strike(row['attribute'])
            card_type  = TYPE_MAP.get(str(row['card_type']).lower(), CardType.CHARACTER)

            # Counter
            counter_str = str(row['counter_amount']).replace('.0', '').strip()
            counter_val = int(counter_str) if counter_str.isdigit() else 0

            # Extra names (nomes alternativos no sub_types)
            extra_names = []
            if row['sub_types']:
                # Guarda sub_types como string para busca por nome
                extra_names = [p.strip() for p in str(row['sub_types']).split() if len(p) > 2]

            # Parseia efeitos → ActV3Base
            action_v3s = parse_card_text_to_actions(
                row['card_text'],
                row['counter_amount']
            )

            cd = CardDefinition(
                card_id=code,
                character_name=str(row['card_name']),
                extra_names=extra_names,
                card_type=card_type,
                strike_type=strike,
                card_life=int(row['life']),
                card_power=int(row['card_power']),
                card_counter=counter_val,
                card_cost=int(row['card_cost']),
                card_colors=colors,
                card_categories=categories,
                action_v3s=action_v3s,
            )

            self._db[code] = cd
            loaded += 1

        print(f"  CardLoader: {loaded} cartas carregadas")

    def get(self, card_id: str) -> Optional[CardDefinition]:
        """Retorna CardDefinition pelo ID (ex: 'OP01-001')."""
        code = str(card_id).split('_')[0].strip()
        return self._db.get(code)

    def all(self) -> dict[str, CardDefinition]:
        return self._db

    def build_deck_config(
        self,
        deck_json: dict,
        name: str = 'Deck',
    ):
        """
        Converte o JSON do deck (formato do Deck Builder) para DeckConfig.

        deck_json formato:
        {
            "leader": {"card_set_id": "OP15-001", ...},
            "cards": [{"card": {"card_set_id": "OP15-037", ...}, "quantity": 4}, ...]
        }
        """
        from .simulator import DeckConfig

        # Líder
        leader_data = deck_json.get('leader', {})
        leader_id = (leader_data.get('card_set_id') or
                     leader_data.get('id') or '').split('_')[0]
        leader_cd = self.get(leader_id)

        if not leader_cd:
            # Fallback: cria CardDefinition básico do JSON
            leader_cd = self._make_card_from_json(leader_data, CardType.LEADER)

        # Deck
        deck_cards = []
        missing = []
        for entry in deck_json.get('cards', []):
            card_data = entry.get('card') or entry
            quantity  = int(entry.get('quantity', 1))
            card_id   = (card_data.get('card_set_id') or
                         card_data.get('id') or '').split('_')[0]

            cd = self.get(card_id)
            if not cd:
                cd = self._make_card_from_json(card_data)
                missing.append(card_id)

            for _ in range(quantity):
                deck_cards.append(cd)

        if missing:
            print(f"  ⚠️  {len(missing)} cartas não encontradas no CSV: {missing[:5]}")

        return DeckConfig(leader=leader_cd, deck=deck_cards, name=name)

    def _make_card_from_json(
        self,
        card_data: dict,
        card_type: CardType | None = None,
    ) -> CardDefinition:
        """Cria CardDefinition básico a partir do JSON do Supabase."""
        code = (card_data.get('card_set_id') or
                card_data.get('id') or 'UNKNOWN').split('_')[0]

        ct = card_type or TYPE_MAP.get(
            str(card_data.get('card_type', '')).lower(),
            CardType.CHARACTER
        )
        colors = parse_colors(str(card_data.get('card_color', '')))
        cats   = parse_subtypes(str(card_data.get('sub_types', '')))

        try: cost = int(float(card_data.get('card_cost') or 0))
        except: cost = 0
        try: power = int(float(card_data.get('card_power') or 0))
        except: power = 0
        try: life = int(float(card_data.get('life') or 0))
        except: life = 0
        try:
            c = str(card_data.get('counter_amount') or '').replace('.0','')
            counter = int(c) if c.isdigit() else 0
        except: counter = 0

        action_v3s = parse_card_text_to_actions(
            str(card_data.get('card_text', '')),
            str(card_data.get('counter_amount', '')),
        )

        return CardDefinition(
            card_id=code,
            character_name=str(card_data.get('card_name', code)),
            card_type=ct,
            card_life=life,
            card_power=power,
            card_counter=counter,
            card_cost=cost,
            card_colors=colors,
            card_categories=cats,
            action_v3s=action_v3s,
        )