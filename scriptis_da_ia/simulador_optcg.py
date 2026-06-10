"""
OPTCG Game State Engine v2.1
Simulador de partidas com cartas REAIS para coletar dados e treinar IA

Correções v2.1:
  - DON acumula corretamente entre turnos
  - Sem ataques no T1 e T2 (primeiro turno de cada jogador)
  - Leader ataca corretamente
  - Validador de decks (50 cartas, max 4 cópias, cores corretas)
  - Stage inicial detectado por efeito "at the start of the game"
  - Searcher mostra cartas buscadas

Fontes:
  - decklists_raw.csv  — listas reais de torneio
  - cards_rows.csv     — banco completo com efeitos reais das cartas
  - features.csv       — features agregadas dos decks

Uso:
    python simulador_optcg.py

Saída:
    resultados_simulacao.csv  — winrates e estatísticas por deck
    modelo_optcg.json         — modelo atualizado
"""

import random
import json
import os
import pandas as pd
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from copy import deepcopy

# ══════════════════════════════════════════════════════════════════════════════
# ESTRUTURAS DE DADOS
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class Card:
    code: str
    name: str
    card_type: str       # LEADER, CHARACTER, EVENT, STAGE
    color: str
    cost: int = 0
    power: int = 0
    counter: int = 0
    life: int = 0
    # Keywords
    has_rush: bool = False
    has_blocker: bool = False
    has_double_attack: bool = False
    has_banish: bool = False
    has_trigger: bool = False
    has_unblockable: bool = False
    # Efeitos
    draw_power: int = 0
    is_searcher: bool = False
    has_on_play_ko: bool = False
    has_bounce: bool = False
    has_rest_effect: bool = False
    has_start_of_game: bool = False  # efeito "At the start of the game"
    # Efeitos com condição e custo secundário
    draw_then_trash: int = 0         # draw X then trash Y → valor = Y
    draw_condition: str = ''         # condição ex: 'life<=3', 'always'
    has_power_minus: bool = False    # reduz poder de character inimigo
    trash_opp_char: bool = False     # coloca/elimina character inimigo
    card_text: str = ''              # texto original do efeito
    # Estado em jogo
    rested: bool = False
    just_played: bool = False
    don_attached: int = 0

    def effective_power(self, your_turn: bool = True) -> int:
        base = self.power
        if your_turn:
            base += self.don_attached * 1000
        return base

    def board_value(self) -> int:
        v = self.power // 1000
        if self.has_rush:          v += 4
        if self.has_blocker:       v += 3
        if self.has_on_play_ko:    v += 5
        if self.draw_power > 0:    v += 4
        if self.is_searcher:       v += 4
        if self.has_double_attack: v += 3
        if self.has_banish:        v += 2
        if self.has_bounce:        v += 3
        if self.has_rest_effect:   v += 3
        return v

    def threat_value(self) -> int:
        v = self.board_value()
        if self.has_rush:          v += 2
        if self.has_double_attack: v += 3
        if self.has_unblockable:   v += 4
        return v


@dataclass
class GameState:
    leader: Card
    deck: List[Card] = field(default_factory=list)
    hand: List[Card] = field(default_factory=list)
    field_chars: List[Card] = field(default_factory=list)
    field_stage: Optional[Card] = None   # Stage em campo (max 1)
    life: List[Card] = field(default_factory=list)
    don_deck: int = 10
    don_available: int = 0   # DON ativos no cost area
    don_rested: int = 0      # DON descansados (usados para pagar cartas)
    trash: List[Card] = field(default_factory=list)
    turn: int = 0
    global_turn: int = 0  # turno global da partida (1=primeiro turno de qualquer jogador)
    is_first: bool = True
    # Estatísticas
    dmg_dealt: int = 0
    chars_played: int = 0
    counters_used: int = 0
    searchers_used: int = 0
    triggers_activated: int = 0

    def life_count(self) -> int:
        return len(self.life)

    def active_chars(self) -> List[Card]:
        return [c for c in self.field_chars if not c.rested and not c.just_played]

    def rested_chars(self) -> List[Card]:
        return [c for c in self.field_chars if c.rested]

    def counter_in_hand(self) -> int:
        return sum(c.counter for c in self.hand if c.counter > 0)

    def blockers_active(self) -> List[Card]:
        return [c for c in self.field_chars if c.has_blocker and not c.rested]

    def board_score(self) -> int:
        return sum(c.board_value() for c in self.field_chars)

    def color_counter_bonus(self) -> int:
        bonuses = {'Blue': 2000, 'Yellow': 1000, 'Green': 1000,
                   'Black': 1000, 'Purple': 500, 'Red': -1000}
        return bonuses.get(self.leader.color, 0)

    def estimated_counter(self) -> int:
        base = len(self.hand) * 1000
        return max(0, base + self.color_counter_bonus())

    def can_attack_this_turn(self) -> bool:
        """
        Regra correta: nenhum jogador ataca no seu PRIMEIRO turno.
        1º jogador: não ataca no turno 1 (global_turn=1)
        2º jogador: não ataca no turno 2 (global_turn=2)
        """
        if self.is_first:
            return self.turn > 1   # 1º jogador ataca a partir do 2º turno dele
        else:
            return self.turn > 1   # 2º jogador ataca a partir do 2º turno dele


# ══════════════════════════════════════════════════════════════════════════════
# CARREGAMENTO DE DADOS REAIS
# ══════════════════════════════════════════════════════════════════════════════

def parse_card_effects(text: str, counter_amount: str) -> dict:
    t = (text or '').lower()
    c_val = 0
    try:
        c_str = str(counter_amount or '').replace('.0', '')
        if c_str.isdigit():
            c_val = int(c_str)
    except:
        pass

    # Detecta draw_power (compras sem custo secundário)
    raw_draw = (t.count('draw 1') + t.count('draw 2') * 2 +
                t.count('draw 3') * 3 + t.count('draw a card'))

    # Detecta "draw X and/then trash Y" — efeito com custo secundário
    import re
    draw_trash = 0
    draw_condition = 'always'
    m = re.search(r'draw\s+(\d)\s+cards?\s+and\s+trash\s+(\d)', t)
    if not m:
        m = re.search(r'draw\s+(\d)\s+cards?.*?trash\s+(\d)\s+card', t)
    if m:
        draw_amt  = int(m.group(1))
        trash_amt = int(m.group(2))
        draw_trash = trash_amt
        raw_draw = draw_amt  # draw correto
        # Detecta condição
        if 'if you have' in t and 'life' in t:
            lm = re.search(r'if you have\s+(\d+)\s+or less life', t)
            if lm:
                draw_condition = f'life<={lm.group(1)}'
        else:
            draw_condition = 'always'

    return {
        'has_rush':            '[rush]' in t,
        'has_blocker':         '[blocker]' in t,
        'has_double_attack':   '[double attack]' in t,
        'has_banish':          '[banish]' in t,
        'has_trigger':         '[trigger]' in t,
        'has_unblockable':     '[unblockable]' in t,
        'has_on_play_ko':      ('on play' in t and ('k.o.' in t or 'trash' in t) and 'draw' not in t),
        'has_bounce':          ('return' in t and 'hand' in t),
        'has_rest_effect':     ('rest' in t and ('opponent' in t or 'your opponent' in t)),
        'is_searcher':         ('look at' in t or 'search your deck' in t or 'add up to' in t),
        'has_start_of_game':   'at the start of the game' in t,
        'has_power_minus':     ('-' in t and 'power' in t and 'opponent' in t),
        'trash_opp_char':      ('opponent' in t and ('trash' in t or 'k.o.' in t) and 'on play' in t),
        'draw_power':          raw_draw,
        'draw_then_trash':     draw_trash,
        'draw_condition':      draw_condition,
        'counter':             c_val,
    }


def load_cards_db(csv_path='cards_rows.csv') -> dict:
    db = {}
    try:
        df = pd.read_csv(csv_path)
        df['card_cost']      = pd.to_numeric(df['card_cost'],  errors='coerce').fillna(0).astype(int)
        df['card_power']     = pd.to_numeric(df['card_power'], errors='coerce').fillna(0).astype(int)
        df['life']           = pd.to_numeric(df['life'],        errors='coerce').fillna(0).astype(int)
        df['card_set_id']    = df['card_set_id'].fillna('').astype(str)
        df['card_name']      = df['card_name'].fillna('').astype(str)
        df['card_color']     = df['card_color'].fillna('').astype(str)
        df['card_type']      = df['card_type'].fillna('').astype(str)
        df['card_text']      = df['card_text'].fillna('').astype(str)
        df['counter_amount'] = df['counter_amount'].fillna('').astype(str)

        for _, row in df.iterrows():
            code = row['card_set_id'].split('_')[0]
            if not code or code == 'nan':
                continue
            effects = parse_card_effects(row['card_text'], row['counter_amount'])
            db[code] = {
                'name':    row['card_name'],
                'color':   row['card_color'],
                'type':    row['card_type'].upper(),
                'cost':    int(row['card_cost']),
                'power':   int(row['card_power']),
                'life':    int(row['life']) if row['life'] > 0 else 0,
                'text':    row['card_text'],
                **effects,
            }
        print(f'  Banco de cartas: {len(db)} cartas com efeitos reais')
    except Exception as e:
        print(f'  Erro ao carregar cards_rows.csv: {e}')
    return db


# ══════════════════════════════════════════════════════════════════════════════
# VALIDADOR DE DECKS
# ══════════════════════════════════════════════════════════════════════════════

def validar_deck(leader: Card, cards: List[Card], cards_db: dict) -> tuple:
    """
    Valida o deck conforme as regras oficiais.
    Retorna (valido: bool, erros: list[str])
    """
    erros = []

    # 1. Total de cartas = 50
    if len(cards) != 50:
        erros.append(f'Total de cartas: {len(cards)} (deve ser 50)')

    # 2. Máximo 4 cópias por card_code
    from collections import Counter
    contagem = Counter(c.code for c in cards)
    for code, qty in contagem.items():
        if qty > 4:
            name = cards_db.get(code, {}).get('name', code)
            erros.append(f'Mais de 4 cópias: {name} ({code}) — {qty} cópias')

    # 3. Cores corretas conforme leader
    leader_colors = set(leader.color.replace('/', ' ').split())
    for c in cards:
        card_colors = set(c.color.replace('/', ' ').split())
        if card_colors and not card_colors.intersection(leader_colors):
            # Ignora cartas sem cor definida
            if c.color and c.color != 'nan':
                erros.append(f'Cor incompatível: {c.name} ({c.color}) — leader é {leader.color}')
                break  # reporta só o primeiro para não poluir

    valido = len(erros) == 0
    return valido, erros


def build_real_deck(deck_name: str, deck_url: str, df_raw: pd.DataFrame,
                    cards_db: dict) -> Optional[tuple]:
    """
    Constrói um deck real a partir do decklists_raw.csv.
    Retorna (leader_card, list_of_cards, start_of_game_stage) ou None
    """
    rows = df_raw[df_raw['deck_url'] == deck_url]
    if rows.empty:
        return None

    leader = None
    cards = []
    start_stage = None  # Stage que vai a campo no início do jogo

    for _, row in rows.iterrows():
        code = str(row['card_code'])
        qty  = int(row['qty'])
        data = cards_db.get(code, {})

        card = Card(
            code=code,
            name=data.get('name', code),
            card_type=data.get('type', 'CHARACTER'),
            color=data.get('color', ''),
            cost=data.get('cost', 0),
            power=data.get('power', 0),
            counter=data.get('counter', 0),
            life=data.get('life', 0),
            has_rush=data.get('has_rush', False),
            has_blocker=data.get('has_blocker', False),
            has_double_attack=data.get('has_double_attack', False),
            has_banish=data.get('has_banish', False),
            has_trigger=data.get('has_trigger', False),
            has_unblockable=data.get('has_unblockable', False),
            has_on_play_ko=data.get('has_on_play_ko', False),
            has_bounce=data.get('has_bounce', False),
            has_rest_effect=data.get('has_rest_effect', False),
            is_searcher=data.get('is_searcher', False),
            has_start_of_game=data.get('has_start_of_game', False),
            has_power_minus=data.get('has_power_minus', False),
            trash_opp_char=data.get('trash_opp_char', False),
            draw_power=data.get('draw_power', 0),
            draw_then_trash=data.get('draw_then_trash', 0),
            draw_condition=data.get('draw_condition', 'always'),
            card_text=data.get('text', ''),
        )

        if card.card_type == 'LEADER':
            leader = card
            # Leader com "at the start of the game" coloca stage
            if card.has_start_of_game:
                # Busca stage no deck para colocar em campo
                pass
        else:
            for _ in range(qty):
                c = deepcopy(card)
                cards.append(c)
                # Stage com "at the start of the game" — vai a campo automaticamente
                if c.card_type == 'STAGE' and c.has_start_of_game and start_stage is None:
                    start_stage = deepcopy(card)

    if leader is None:
        leader = Card(code='UNK', name=deck_name, card_type='LEADER',
                      color='', power=5000, life=5)

    return leader, cards, start_stage


# ══════════════════════════════════════════════════════════════════════════════
# MOTOR DE DECISÃO
# ══════════════════════════════════════════════════════════════════════════════

class DecisionEngine:
    COLOR_PROFILES = {
        'Red':    {'aggro': 3, 'control': 0, 'tempo': 1},
        'Blue':   {'aggro': 1, 'control': 2, 'tempo': 3},
        'Green':  {'aggro': 1, 'control': 3, 'tempo': 2},
        'Black':  {'aggro': 1, 'control': 3, 'tempo': 1},
        'Yellow': {'aggro': 1, 'control': 2, 'tempo': 2},
        'Purple': {'aggro': 2, 'control': 1, 'tempo': 3},
    }

    def __init__(self, me: GameState, opp: GameState):
        self.me = me
        self.opp = opp

    def posture(self) -> str:
        my_life = self.me.life_count()
        opp_life = self.opp.life_count()
        my_board = self.me.board_score()
        opp_board = self.opp.board_score()
        if opp_life <= 1:   return 'AGGRESSIVE'
        if my_life <= 1:    return 'DEFENSIVE'
        if opp_board > my_board * 1.5: return 'CONTROL'
        if self.me.turn <= 3:          return 'DEVELOP'
        return 'MIDRANGE'

    def can_lethal(self) -> bool:
        if self.opp.life_count() > 0:
            return False
        active = self.me.active_chars()
        leader_active = not getattr(self.me.leader, 'rested', False)
        return len(active) > 0 or leader_active

    def score_card_to_play(self, card: Card) -> float:
        s = 100.0
        posture = self.posture()
        opp_life = self.opp.life_count()
        my_life = self.me.life_count()

        if card.has_blocker:       s += 50
        if card.has_rush:          s += 100
        if card.draw_power > 0:    s += 80
        if card.is_searcher:       s += 80
        if card.has_on_play_ko:    s += 120
        if card.has_bounce:        s += 80
        if card.has_rest_effect:   s += 60
        if card.has_double_attack: s += 60

        if posture == 'AGGRESSIVE':
            if card.has_rush:          s += 200
            if card.has_double_attack: s += 150
            if card.has_unblockable:   s += 100
        elif posture == 'DEFENSIVE':
            if card.has_blocker:       s += 200
            if card.counter > 0:       s += 100
        elif posture == 'CONTROL':
            if card.has_on_play_ko:    s += 150
            if card.has_bounce:        s += 100
        elif posture == 'DEVELOP':
            if card.is_searcher:       s += 100
            if card.draw_power > 0:    s += 80

        if my_life <= 2 and card.has_blocker:   s += 200
        if opp_life <= 2 and card.has_rush:     s += 300
        if opp_life <= 1 and card.has_rush:     s += 500
        if card.cost == 0:  s += 30
        if card.cost <= 2:  s += 20

        return s

    def don_futuro(self, turnos: int = 2) -> int:
        """Estima DON disponível nos próximos N turnos"""
        return min(10, self.me.don_available + turnos * 2)

    def avaliar_carta_situacional(self, card: Card) -> float:
        """
        Valor situacional de uma carta considerando:
        - Estado atual da partida (vida, board, DON)
        - Planejamento 2-3 turnos à frente
        - Postura atual
        Usado em: search (maior valor), trash (menor valor), play (maior valor)
        """
        s = 0.0
        posture    = self.posture()
        my_life    = self.me.life_count()
        opp_life   = self.opp.life_count()
        my_board   = self.me.board_score()
        opp_board  = self.opp.board_score()
        don_now    = self.me.don_available
        don_t2     = self.don_futuro(2)
        don_t3     = self.don_futuro(3)

        # ── Jogabilidade futura ────────────────────────────────────────────
        # Carta jogável agora vale mais
        if card.cost <= don_now:    s += 40
        elif card.cost <= don_t2:   s += 20
        elif card.cost <= don_t3:   s += 10
        else:                       s -= 10  # não consegue jogar em breve

        # ── Valor base por poder ───────────────────────────────────────────
        s += card.power / 1000 * 5

        # ── Keywords ofensivas ─────────────────────────────────────────────
        if card.has_rush:
            rush_val = 30
            if opp_life <= 2: rush_val += 40  # mais valioso para fechar
            if opp_life == 0: rush_val += 100 # letal
            s += rush_val

        if card.has_double_attack:
            s += 25
            if opp_life <= 2: s += 30

        if card.has_unblockable:
            s += 20
            if opp_life <= 2: s += 25

        if card.has_banish:
            s += 15

        # ── Keywords defensivas ────────────────────────────────────────────
        if card.has_blocker:
            block_val = 20
            if my_life <= 2: block_val += 60   # urgente quando vida baixa
            if my_life == 1: block_val += 80
            if opp_board > my_board: block_val += 30  # adversário com board forte
            s += block_val

        if card.counter > 0:
            counter_val = card.counter / 1000 * 15
            if my_life <= 2: counter_val *= 2.0  # counters valem mais com vida baixa
            if my_life <= 1: counter_val *= 3.0
            # Penaliza se já tem muitos counters na mão
            counters_em_mao = sum(1 for c in self.me.hand if c.counter > 0 and c is not card)
            if counters_em_mao >= 3: counter_val *= 0.5
            s += counter_val

        if card.has_trigger:
            s += 10

        # ── Vantagem de cartas ─────────────────────────────────────────────
        if card.draw_power > 0:
            draw_val = card.draw_power * 20
            # Draw vale mais quando mão está pequena
            if len(self.me.hand) <= 3: draw_val += 20
            s += draw_val

        if card.draw_then_trash > 0:
            # draw_then_trash: compra X, descarta Y — valor líquido
            cond = card.draw_condition
            cond_ok = True
            if 'life<=' in cond:
                limit = int(cond.split('<=')[1])
                cond_ok = my_life <= limit
            if cond_ok:
                s += card.draw_power * 15 - card.draw_then_trash * 5
            else:
                s -= 20  # condição não satisfeita, carta inútil agora

        if card.is_searcher:
            search_val = 25
            # Searcher vale mais cedo (mais turnos para usar o que buscar)
            if self.me.turn <= 3: search_val += 15
            s += search_val

        # ── Remoção ────────────────────────────────────────────────────────
        if card.has_on_play_ko or card.trash_opp_char:
            remove_val = 30
            if opp_board > my_board: remove_val += 20
            s += remove_val

        if card.has_bounce:
            s += 20
            if opp_board > my_board: s += 15

        if card.has_rest_effect:
            s += 15

        if card.has_power_minus:
            s += 15
            if opp_board > my_board: s += 10

        # ── Ajuste por postura ─────────────────────────────────────────────
        if posture == 'AGGRESSIVE':
            if card.has_rush:          s += 30
            if card.has_double_attack: s += 20
            if card.counter > 0:       s -= 10  # menos defensivo em modo agressivo
        elif posture == 'DEFENSIVE':
            if card.has_blocker:       s += 40
            if card.counter > 0:       s += 20
            if card.has_rush:          s -= 10
        elif posture == 'CONTROL':
            if card.has_on_play_ko:    s += 25
            if card.has_bounce:        s += 15
        elif posture == 'DEVELOP':
            if card.is_searcher:       s += 20
            if card.draw_power > 0:    s += 15

        return s

    def choose_card_to_play(self) -> Optional[Card]:
        playable = [c for c in self.me.hand
                    if c.card_type in ('CHARACTER', 'EVENT', 'STAGE')
                    and c.cost <= self.me.don_available]
        if not playable:
            return None
        return max(playable, key=self.avaliar_carta_situacional)

    def choose_card_to_trash(self, hand: list) -> Optional[Card]:
        """Escolhe a carta de menor valor situacional para descartar"""
        if not hand:
            return None
        return min(hand, key=self.avaliar_carta_situacional)

    def choose_card_to_search(self, candidates: list) -> Optional[Card]:
        """Escolhe a carta de maior valor situacional para buscar"""
        if not candidates:
            return None
        return max(candidates, key=self.avaliar_carta_situacional)

    def score_attack_target(self, attacker: Card, target_type: str,
                             target: Optional[Card]) -> float:
        s = 0.0
        opp_life = self.opp.life_count()
        atk_power = attacker.effective_power(True)

        if target_type == 'leader':
            s = 100
            if opp_life == 1: s = 500
            if opp_life == 0: s = 10000
            defend = self.opp.leader.power
            est_counter = self.opp.estimated_counter()
            if atk_power < defend + est_counter:
                s -= 50
        elif target_type == 'character' and target:
            if target.cost <= 3:   s = 50
            elif target.cost <= 6: s = 120
            else:                  s = 200
            if target.has_blocker:       s += 250
            if target.has_rush:          s += 300
            if target.draw_power > 0:    s += 400
            if target.has_on_play_ko:    s += 350
            if target.has_double_attack: s += 200
            if target.has_rest_effect:   s += 150
            if atk_power < target.power:
                s = -100

        return s

    def should_use_counter(self, atk_power: int, def_power: int) -> bool:
        my_life = self.me.life_count()
        counter_avail = self.me.counter_in_hand()
        if counter_avail == 0 or atk_power < def_power:
            return False
        if my_life <= 1: return True
        if my_life <= 2: return atk_power - def_power >= 0
        if my_life <= 4: return atk_power - def_power >= 2000
        return False

    def use_counter(self, needed: int) -> int:
        counters = sorted([c for c in self.me.hand if c.counter > 0],
                          key=lambda c: c.counter)
        total = 0
        for c in counters:
            if total >= needed:
                break
            self.me.hand.remove(c)
            self.me.trash.append(c)
            total += c.counter
            self.me.counters_used += c.counter
        return total

    def should_use_blocker(self, attacker_power: int) -> Optional[Card]:
        my_life = self.me.life_count()
        if my_life > 3:
            return None
        blockers = self.me.blockers_active()
        if not blockers:
            return None
        return min(blockers, key=lambda c: c.board_value())


# ══════════════════════════════════════════════════════════════════════════════
# SIMULADOR DE PARTIDA
# ══════════════════════════════════════════════════════════════════════════════

class OPTCGMatch:
    MAX_TURNS = 15  # Limite realista — partidas terminam em 8-15 turnos

    def __init__(self, deck_a: tuple, deck_b: tuple):
        # deck_a e deck_b = (leader, cards, start_stage)
        leader_a, cards_a, stage_a = deck_a if len(deck_a) == 3 else (*deck_a, None)
        leader_b, cards_b, stage_b = deck_b if len(deck_b) == 3 else (*deck_b, None)

        self.state_a = GameState(
            leader=deepcopy(leader_a),
            deck=[deepcopy(c) for c in cards_a]
        )
        self.state_b = GameState(
            leader=deepcopy(leader_b),
            deck=[deepcopy(c) for c in cards_b]
        )
        self.start_stage_a = deepcopy(stage_a) if stage_a else None
        self.start_stage_b = deepcopy(stage_b) if stage_b else None

        if random.random() < 0.5:
            self.state_a.is_first = True
            self.state_b.is_first = False
        else:
            self.state_a.is_first = False
            self.state_b.is_first = True

        self.global_turn = 0  # conta turnos totais da partida

    def setup(self):
        """Setup inicial — regras 5-2"""
        for p, stage in [(self.state_a, self.start_stage_a),
                          (self.state_b, self.start_stage_b)]:
            random.shuffle(p.deck)
            p.hand = [p.deck.pop() for _ in range(min(5, len(p.deck)))]
            if self._should_mulligan(p):
                p.deck.extend(p.hand)
                random.shuffle(p.deck)
                p.hand = [p.deck.pop() for _ in range(min(5, len(p.deck)))]
            life_count = p.leader.life if p.leader.life > 0 else 5
            p.life = [p.deck.pop() for _ in range(min(life_count, len(p.deck)))]
            # Coloca stage inicial em campo (ex: Imu)
            if stage:
                p.field_stage = stage

    def _should_mulligan(self, p: GameState) -> bool:
        return len([c for c in p.hand
                    if c.cost <= 2 and c.card_type != 'LEADER']) == 0

    # ── Fases ──────────────────────────────────────────────────────────────

    def refresh_phase(self, p: GameState):
        """Refresh Phase — regra 6-2
        Todos os DON no cost area viram ativos.
        DON dado a cartas volta ao cost area.
        """
        # Retorna DON dado a cartas ao cost area
        don_from_cards = sum(c.don_attached for c in p.field_chars) + p.leader.don_attached
        for c in p.field_chars:
            c.don_attached = 0
            c.rested = False
            c.just_played = False
        p.leader.don_attached = 0
        p.leader.rested = False
        # Todos os DON descansados viram ativos (refresh)
        p.don_available += p.don_rested + don_from_cards
        p.don_rested = 0

    def draw_phase(self, p: GameState):
        """Draw Phase — regra 6-3
        1º jogador NÃO compra no primeiro turno.
        """
        if p.turn == 1 and p.is_first:
            return
        if p.deck:
            p.hand.append(p.deck.pop())

    def don_phase(self, p: GameState):
        """DON!! Phase — regra 6-4
        Regra correta de DON:
        - T1 do 1º jogador: +1 DON
        - Todos os outros turnos: +2 DON (até esgotar o DON!! deck de 10)
        DON acumula no cost area entre turnos!
        """
        if p.turn == 1 and p.is_first:
            gain = min(1, p.don_deck)
        else:
            gain = min(2, p.don_deck)
        p.don_deck -= gain
        p.don_available += gain

    def main_phase(self, p: GameState, opp: GameState) -> bool:
        """Main Phase — regra 6-5
        Ordem: jogar cartas → atacar com TODOS os atacantes
        """
        engine = DecisionEngine(p, opp)

        # ── Jogar cartas ──────────────────────────────────────────────────
        plays = 0
        while plays < 8:
            card = engine.choose_card_to_play()
            if card:
                self._play_card(card, p)
                plays += 1
            else:
                break

        # ── Atacar ────────────────────────────────────────────────────────
        if p.can_attack_this_turn():
            # Coleta todos os atacantes
            attackers = [c for c in p.field_chars
                         if not c.rested and not c.just_played]
            if not p.leader.rested:
                attackers.append(p.leader)

            for attacker in list(attackers):
                if attacker.rested:
                    continue  # pode ter descansado em blocker
                engine2 = DecisionEngine(p, opp)

                best_score = -999
                best_action = None

                s = engine2.score_attack_target(attacker, 'leader', None)
                if s > best_score:
                    best_score = s
                    best_action = (attacker, 'leader', None)

                for target in opp.rested_chars():
                    s = engine2.score_attack_target(attacker, 'character', target)
                    if s > best_score:
                        best_score = s
                        best_action = (attacker, 'character', target)

                if best_action and best_score > -50:
                    a, ttype, tgt = best_action
                    if self._execute_attack(a, ttype, tgt, p, opp, engine2):
                        return True

                    # Tenta letal imediato se vida chegou a 0
                    if not opp.life:
                        remaining = [c for c in p.field_chars
                                     if not c.rested and not c.just_played
                                     and c is not a]
                        if not p.leader.rested and p.leader is not a:
                            remaining.append(p.leader)
                        for finisher in remaining:
                            if self._execute_attack(finisher, 'leader', None,
                                                     p, opp, engine2):
                                return True

        for c in p.field_chars:
            c.just_played = False

        return False

    def _play_card(self, card: Card, p: GameState):
        """Joga uma carta — regra 6-5-3"""
        p.hand.remove(card)
        p.don_rested += card.cost   # DON gastos ficam descansados
        p.don_available -= card.cost
        p.chars_played += 1

        if card.card_type == 'CHARACTER':
            if len(p.field_chars) >= 5:
                worst = min(p.field_chars, key=lambda c: c.board_value())
                p.field_chars.remove(worst)
                p.trash.append(worst)
            card.rested = False
            card.just_played = not card.has_rush  # Rush pode atacar imediatamente
            p.field_chars.append(card)

            # Draw power com condição
            do_draw = True
            if card.draw_condition and card.draw_condition != 'always':
                if 'life<=' in card.draw_condition:
                    limit = int(card.draw_condition.split('<=')[1])
                    do_draw = p.life_count() <= limit

            if do_draw:
                for _ in range(card.draw_power):
                    if p.deck:
                        p.hand.append(p.deck.pop())

                # Se tem trash após draw, descarta a carta de menor valor situacional
                if card.draw_then_trash > 0 and len(p.hand) > 0:
                    engine_tmp = DecisionEngine(p, GameState(leader=p.leader))
                    for _ in range(card.draw_then_trash):
                        if p.hand:
                            worst = engine_tmp.choose_card_to_trash(p.hand)
                            if worst:
                                p.hand.remove(worst)
                                p.trash.append(worst)

            if card.is_searcher and p.deck:
                # Searcher: olha as 5 primeiras, usa avaliar_carta_situacional
                engine_tmp = DecisionEngine(p, GameState(leader=p.leader))
                look = min(5, len(p.deck))
                candidates = p.deck[-look:]
                if candidates:
                    best = engine_tmp.choose_card_to_search(candidates)
                    p.deck.remove(best)
                    p.hand.append(best)
                    p.searchers_used += 1

        elif card.card_type == 'STAGE':
            # Substitui stage existente
            if p.field_stage:
                p.trash.append(p.field_stage)
            p.field_stage = card

    def _execute_attack(self, attacker: Card, target_type: str,
                         target: Optional[Card], p: GameState,
                         opp: GameState, engine: DecisionEngine) -> bool:
        """Executa ataque completo: Attack → Block → Counter → Damage"""
        # Descansa atacante
        if attacker is p.leader:
            p.leader.rested = True
        else:
            attacker.rested = True

        atk_power = attacker.effective_power(True)
        damage = 2 if attacker.has_double_attack else 1

        # Block Step
        opp_engine = DecisionEngine(opp, p)
        blocker = opp_engine.should_use_blocker(atk_power)
        if blocker and not attacker.has_unblockable:
            target_type = 'character'
            target = blocker
            blocker.rested = True

        # Define poder de defesa
        if target_type == 'leader':
            defend_power = opp.leader.power
        elif target and target in opp.field_chars:
            defend_power = target.power
        else:
            return False

        # Counter Step
        if opp_engine.should_use_counter(atk_power, defend_power):
            needed = atk_power - defend_power + 1
            added = opp_engine.use_counter(needed)
            defend_power += added

        # Damage Step
        if atk_power >= defend_power:
            if target_type == 'leader':
                for _ in range(damage):
                    if not opp.life:
                        p.dmg_dealt += 1
                        return True
                    life_card = opp.life.pop()
                    p.dmg_dealt += 1
                    if life_card.has_trigger:
                        opp.hand.append(life_card)
                        opp.triggers_activated += 1
                    else:
                        opp.hand.append(life_card)
                if not opp.life:
                    return False  # vida chegou a 0, mas precisa de mais 1 ataque
            elif target_type == 'character' and target and target in opp.field_chars:
                opp.field_chars.remove(target)
                opp.trash.append(target)

        return False

    def end_phase(self, p: GameState):
        pass

    def play_turn(self, p: GameState, opp: GameState) -> Optional[str]:
        self.global_turn += 1
        p.turn += 1
        p.global_turn = self.global_turn

        self.refresh_phase(p)
        self.draw_phase(p)
        self.don_phase(p)

        if self.main_phase(p, opp):
            return 'A' if p is self.state_a else 'B'

        if not p.deck:
            return 'B' if p is self.state_a else 'A'
        if not opp.deck:
            return 'A' if p is self.state_a else 'B'

        self.end_phase(p)
        return None

    def simulate(self) -> dict:
        self.setup()
        winner = None
        total_turns = 0

        for turn_num in range(self.MAX_TURNS * 2):
            if turn_num % 2 == 0:
                p   = self.state_a if self.state_a.is_first else self.state_b
                opp = self.state_b if self.state_a.is_first else self.state_a
            else:
                p   = self.state_b if self.state_a.is_first else self.state_a
                opp = self.state_a if self.state_a.is_first else self.state_b

            result = self.play_turn(p, opp)
            total_turns += 1

            if result:
                winner = result
                break

        if not winner:
            winner = 'DRAW'

        return {
            'winner':      winner,
            'turns':       total_turns,
            'dmg_a':       self.state_a.dmg_dealt,
            'dmg_b':       self.state_b.dmg_dealt,
            'life_a':      self.state_a.life_count(),
            'life_b':      self.state_b.life_count(),
            'counters_a':  self.state_a.counters_used,
            'counters_b':  self.state_b.counters_used,
            'searchers_a': self.state_a.searchers_used,
            'searchers_b': self.state_b.searchers_used,
            'triggers_a':  self.state_a.triggers_activated,
            'triggers_b':  self.state_b.triggers_activated,
        }


# ══════════════════════════════════════════════════════════════════════════════
# PIPELINE DE SIMULAÇÃO
# ══════════════════════════════════════════════════════════════════════════════

def simular_matchup(deck_a: tuple, deck_b: tuple, n: int = 100) -> dict:
    wins_a = wins_b = draws = 0
    total_turns = []
    counters_a = counters_b = 0
    searchers_a = searchers_b = 0
    triggers_a = triggers_b = 0

    for _ in range(n):
        match = OPTCGMatch(deck_a, deck_b)
        r = match.simulate()
        if r['winner'] == 'A':   wins_a += 1
        elif r['winner'] == 'B': wins_b += 1
        else:                    draws  += 1
        total_turns.append(r['turns'])
        counters_a  += r['counters_a']
        counters_b  += r['counters_b']
        searchers_a += r['searchers_a']
        searchers_b += r['searchers_b']
        triggers_a  += r['triggers_a']
        triggers_b  += r['triggers_b']

    total = wins_a + wins_b + draws
    avg_turns = sum(total_turns) / len(total_turns) if total_turns else 0

    return {
        'wins_a':         wins_a,
        'wins_b':         wins_b,
        'draws':          draws,
        'winrate_a':      round(wins_a / total * 100, 1) if total > 0 else 50.0,
        'winrate_b':      round(wins_b / total * 100, 1) if total > 0 else 50.0,
        'avg_turns':      round(avg_turns, 1),
        'counters_pg_a':  round(counters_a  / total, 1) if total > 0 else 0,
        'counters_pg_b':  round(counters_b  / total, 1) if total > 0 else 0,
        'searchers_pg_a': round(searchers_a / total, 1) if total > 0 else 0,
        'searchers_pg_b': round(searchers_b / total, 1) if total > 0 else 0,
        'triggers_pg_a':  round(triggers_a  / total, 1) if total > 0 else 0,
        'triggers_pg_b':  round(triggers_b  / total, 1) if total > 0 else 0,
    }


def main():
    print('=' * 60)
    print('OPTCG Game State Engine v2.1')
    print('Simulador com cartas REAIS')
    print('=' * 60)

    cards_db = load_cards_db('cards_rows.csv')

    if not os.path.exists('decklists_raw.csv'):
        print('❌ decklists_raw.csv não encontrado!')
        return
    if not os.path.exists('features.csv'):
        print('❌ features.csv não encontrado!')
        return

    df_raw  = pd.read_csv('decklists_raw.csv')
    df_feat = pd.read_csv('features.csv')

    print(f'  Decklists: {len(df_raw)} linhas')
    print(f'  Decks com features: {len(df_feat)}')

    # ── Constrói e valida decks ───────────────────────────────────────────
    print('\n[1/3] Construindo e validando decks reais...')
    decks = {}
    invalidos = 0
    urls_by_name = df_raw.groupby('deck_url')['deck_name'].first().to_dict()

    for url, name in urls_by_name.items():
        result = build_real_deck(name, url, df_raw, cards_db)
        if not result:
            continue
        leader, cards, start_stage = result

        # Valida deck
        valido, erros = validar_deck(leader, cards, cards_db)
        if not valido:
            invalidos += 1
            continue  # pula deck inválido

        if len(cards) >= 40:
            decks[url] = {
                'name':   name,
                'url':    url,
                'leader': leader,
                'cards':  cards,
                'deck':   result,
            }

    print(f'  Decks válidos: {len(decks)} | Inválidos/ignorados: {invalidos}')

    # Top 5 por placing
    df_feat_sorted = df_feat.sort_values('placing')
    top5_urls = []
    for _, row in df_feat_sorted.iterrows():
        url = row.get('url', '')
        if url in decks and url not in top5_urls:
            top5_urls.append(url)
        if len(top5_urls) >= 5:
            break
    if len(top5_urls) < 5:
        top5_urls = list(decks.keys())[:5]

    print(f'  Top 5: {[decks[u]["name"][:25] for u in top5_urls]}')

    # ── Simula matchups ───────────────────────────────────────────────────
    print('\n[2/3] Simulando partidas (cada deck vs top 5)...')
    resultados = []
    deck_urls = list(decks.keys())

    for i, url_a in enumerate(deck_urls):
        deck_a_info = decks[url_a]
        deck_a = deck_a_info['deck']

        winrates = []
        avg_turns_list = []
        counters_list = []
        searchers_list = []
        triggers_list = []

        for url_b in top5_urls:
            if url_b == url_a:
                continue
            deck_b = decks[url_b]['deck']
            mr = simular_matchup(deck_a, deck_b, n=100)
            winrates.append(mr['winrate_a'])
            avg_turns_list.append(mr['avg_turns'])
            counters_list.append(mr['counters_pg_a'])
            searchers_list.append(mr['searchers_pg_a'])
            triggers_list.append(mr['triggers_pg_a'])

        if not winrates:
            continue

        sim_wr    = round(sum(winrates) / len(winrates), 1)
        avg_turns = round(sum(avg_turns_list) / len(avg_turns_list), 1)

        feat_row   = df_feat[df_feat['url'] == url_a]
        placing    = int(feat_row['placing'].values[0])    if len(feat_row) > 0 else 99
        perf_score = float(feat_row['performance_score'].values[0]) if len(feat_row) > 0 else 50.0
        leader_wr  = float(feat_row['leader_winrate'].values[0])    if len(feat_row) > 0 else 0.0

        final_score = round(
            perf_score * 0.40 +
            leader_wr  * 0.30 +
            sim_wr     * 0.30, 1
        )

        resultados.append({
            'deck_name':         deck_a_info['name'],
            'deck_url':          url_a,
            'leader':            deck_a_info['leader'].code,
            'placing':           placing,
            'performance_score': perf_score,
            'leader_winrate':    leader_wr,
            'sim_winrate':       sim_wr,
            'avg_turns':         avg_turns,
            'counters_pg':       round(sum(counters_list)  / len(counters_list),  1),
            'searchers_pg':      round(sum(searchers_list) / len(searchers_list), 1),
            'triggers_pg':       round(sum(triggers_list)  / len(triggers_list),  1),
            'final_score':       final_score,
        })

        print(f'  [{i+1}/{len(deck_urls)}] {deck_a_info["name"][:40]:<40} wr={sim_wr}% turns={avg_turns}')

    # ── Salva ─────────────────────────────────────────────────────────────
    print('\n[3/3] Salvando resultados...')
    df_res = pd.DataFrame(resultados)
    df_res.to_csv('resultados_simulacao.csv', index=False, encoding='utf-8')
    print(f'✅ resultados_simulacao.csv — {len(resultados)} decks')

    if os.path.exists('modelo_optcg.json'):
        with open('modelo_optcg.json', 'r', encoding='utf-8') as f:
            modelo = json.load(f)
        modelo['sim_results'] = resultados
        modelo['sim_thresholds'] = {
            'excelente': float(df_res['final_score'].quantile(0.75)),
            'bom':       float(df_res['final_score'].quantile(0.50)),
            'regular':   float(df_res['final_score'].quantile(0.25)),
        }
        with open('modelo_optcg.json', 'w', encoding='utf-8') as f:
            json.dump(modelo, f, ensure_ascii=False, indent=2)
        print('✅ modelo_optcg.json atualizado!')

    print('\nTop 10 por final_score:')
    print(df_res.nlargest(10, 'final_score')[
        ['deck_name', 'placing', 'sim_winrate', 'leader_winrate', 'avg_turns', 'final_score']
    ].to_string())

    print('\n✅ Simulação concluída!')
    print('1. python treinar_modelo.py')
    print('2. copy modelo_optcg.json ..\\public\\modelo_optcg.json')


if __name__ == '__main__':
    main()