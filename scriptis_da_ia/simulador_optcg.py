"""
OPTCG Game State Engine v2.0
Simulador de partidas com cartas REAIS para coletar dados e treinar IA

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
    has_on_play_ko: bool = False    # remove character ao entrar
    has_bounce: bool = False        # retorna carta à mão
    has_rest_effect: bool = False   # descansa character inimigo
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
        """Valor da carta no board para avaliação"""
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
        """Ameaça que esta carta representa para o oponente"""
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
    life: List[Card] = field(default_factory=list)
    don_deck: int = 10
    don_available: int = 0
    trash: List[Card] = field(default_factory=list)
    turn: int = 0
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
        """Ajuste de counter estimado por cor (doc IA)"""
        bonuses = {'Blue': 2000, 'Yellow': 1000, 'Green': 1000,
                   'Black': 1000, 'Purple': 500, 'Red': -1000}
        return bonuses.get(self.leader.color, 0)

    def estimated_counter(self) -> int:
        """Estimativa de counter disponível (doc IA: cartas × 1000 + ajuste cor)"""
        base = len(self.hand) * 1000
        return max(0, base + self.color_counter_bonus())


# ══════════════════════════════════════════════════════════════════════════════
# CARREGAMENTO DE DADOS REAIS
# ══════════════════════════════════════════════════════════════════════════════

def parse_card_effects(text: str, counter_amount: str) -> dict:
    """
    Lê o texto do efeito real da carta e extrai keywords.
    Baseado nas regras oficiais v1.11 + Comprehensive Rules v1.2.0
    """
    t = (text or '').lower()
    c_val = 0
    try:
        c_str = str(counter_amount or '').replace('.0', '')
        if c_str.isdigit():
            c_val = int(c_str)
    except:
        pass

    return {
        'has_rush':          '[rush]' in t,
        'has_blocker':       '[blocker]' in t,
        'has_double_attack': '[double attack]' in t,
        'has_banish':        '[banish]' in t,
        'has_trigger':       '[trigger]' in t,
        'has_unblockable':   '[unblockable]' in t,
        'has_on_play_ko':    ('on play' in t and ('k.o.' in t or 'trash' in t)),
        'has_bounce':        ('return' in t and 'hand' in t),
        'has_rest_effect':   ('rest' in t and ('opponent' in t or 'your opponent' in t)),
        'is_searcher':       ('look at' in t or 'search your deck' in t or 'add up to' in t),
        'draw_power':        (t.count('draw 1') + t.count('draw 2') * 2 +
                              t.count('draw 3') * 3 + t.count('draw a card')),
        'counter':           c_val,
    }


def load_cards_db(csv_path='cards_rows.csv') -> dict:
    """Carrega banco de cartas com efeitos reais"""
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
                **effects,
            }
        print(f'  Banco de cartas: {len(db)} cartas com efeitos reais')
    except Exception as e:
        print(f'  Erro ao carregar cards_rows.csv: {e}')
    return db


def build_real_deck(deck_name: str, deck_url: str, df_raw: pd.DataFrame,
                    cards_db: dict) -> Optional[tuple]:
    """
    Constrói um deck real a partir do decklists_raw.csv
    Retorna (leader_card, list_of_cards) ou None se falhar
    """
    rows = df_raw[df_raw['deck_url'] == deck_url]
    if rows.empty:
        return None

    leader = None
    cards = []

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
            draw_power=data.get('draw_power', 0),
        )

        if card.card_type == 'LEADER':
            leader = card
        else:
            for _ in range(qty):
                cards.append(deepcopy(card))

    if leader is None:
        # Tenta inferir leader pelo nome do deck
        leader = Card(code='UNK', name=deck_name, card_type='LEADER',
                      color='', power=5000, life=5)

    return leader, cards


# ══════════════════════════════════════════════════════════════════════════════
# MOTOR DE DECISÃO (baseado no documento de IA)
# ══════════════════════════════════════════════════════════════════════════════

class DecisionEngine:
    """
    Sistema de decisão baseado no documento ONE PIECE TCG AI Player Documentation.
    Implementa: prioridade de análise, sistema de pontuação, perfis de cor,
    estimativa de counter adversário, planejamento de turnos.
    """

    # Perfis de cor (doc IA)
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
        """
        Define postura atual (doc IA: agressiva/defensiva/controle/desenvolvimento)
        """
        my_life = self.me.life_count()
        opp_life = self.opp.life_count()
        my_board = self.me.board_score()
        opp_board = self.opp.board_score()

        if opp_life <= 1:
            return 'AGGRESSIVE'
        if my_life <= 1:
            return 'DEFENSIVE'
        if opp_board > my_board * 1.5:
            return 'CONTROL'
        if self.me.turn <= 3:
            return 'DEVELOP'
        return 'MIDRANGE'

    def can_lethal(self) -> bool:
        """Verifica se existe sequência letal disponível"""
        if self.opp.life_count() > 0:
            return False
        active = self.me.active_chars()
        return len(active) > 0

    def probable_lethal_next_turn(self) -> bool:
        """Estima se oponente pode ganhar no próximo turno (doc IA)"""
        opp_attackers = len(self.opp.active_chars()) + 1  # +1 pelo leader
        return self.opp.life_count() == 0 and opp_attackers > 0

    def score_card_to_play(self, card: Card) -> float:
        """
        Sistema de pontuação de jogadas (doc IA)
        Baixar Character base: +100
        """
        s = 100.0
        posture = self.posture()
        opp_life = self.opp.life_count()
        my_life = self.me.life_count()

        # Pontuação por keywords
        if card.has_blocker:       s += 50
        if card.has_rush:          s += 100
        if card.draw_power > 0:    s += 80
        if card.is_searcher:       s += 80
        if card.has_on_play_ko:    s += 120
        if card.has_bounce:        s += 80
        if card.has_rest_effect:   s += 60
        if card.has_double_attack: s += 60

        # Ajuste por postura
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

        # Ajuste por situação
        if my_life <= 2 and card.has_blocker:   s += 200
        if opp_life <= 2 and card.has_rush:     s += 300
        if opp_life <= 1 and card.has_rush:     s += 500

        # Custo-benefício
        if card.cost == 0:  s += 30
        if card.cost <= 2:  s += 20

        return s

    def choose_card_to_play(self) -> Optional[Card]:
        """Escolhe melhor carta para jogar"""
        playable = [c for c in self.me.hand
                    if c.card_type in ('CHARACTER', 'EVENT', 'STAGE')
                    and c.cost <= self.me.don_available]
        if not playable:
            return None
        return max(playable, key=self.score_card_to_play)

    def score_attack_target(self, attacker: Card, target_type: str,
                             target: Optional[Card]) -> float:
        """
        Sistema de pontuação de ataques (doc IA)
        """
        s = 0.0
        opp_life = self.opp.life_count()
        atk_power = attacker.effective_power(True)

        if target_type == 'leader':
            # Ataque ao leader
            s = 100
            if opp_life == 1: s = 500
            if opp_life == 0: s = 10000  # LETAL
            defend = self.opp.leader.power
            est_counter = self.opp.estimated_counter()
            if atk_power < defend + est_counter:
                s -= 50  # ataque provável de não passar

        elif target_type == 'character' and target:
            # Ataque a character (doc IA: prioridade por tipo)
            if target.cost <= 3:   s = 50
            elif target.cost <= 6: s = 120
            else:                  s = 200

            if target.has_blocker:          s += 250
            if target.has_rush:             s += 300
            if target.draw_power > 0:       s += 400
            if target.has_on_play_ko:       s += 350
            if target.has_double_attack:    s += 200
            if target.has_rest_effect:      s += 150

            # Verifica se o ataque passa
            if atk_power < target.power:
                s = -100  # não vai passar

        return s

    def choose_attack(self) -> Optional[tuple]:
        """
        Escolhe melhor atacante e alvo.
        Retorna (attacker, target_type, target) ou None
        """
        available = self.me.active_chars()
        if not available:
            return None

        best_score = -999
        best_action = None

        for attacker in available:
            # Opção 1: atacar leader
            s = self.score_attack_target(attacker, 'leader', None)
            if s > best_score:
                best_score = s
                best_action = (attacker, 'leader', None)

            # Opção 2: atacar characters descansados
            for target in self.opp.rested_chars():
                s = self.score_attack_target(attacker, 'character', target)
                if s > best_score:
                    best_score = s
                    best_action = (attacker, 'character', target)

        return best_action if best_score > -50 else None

    def should_use_counter(self, atk_power: int, def_power: int) -> bool:
        """
        Decide se usa counter (doc IA: usa quando vida <= 2 ou ataque grande)
        """
        my_life = self.me.life_count()
        counter_avail = self.me.counter_in_hand()
        if counter_avail == 0:
            return False
        if atk_power < def_power:
            return False
        # Doc IA: preservar counter é valioso (-150 se ficar sem counter)
        if my_life <= 1:
            return True
        if my_life <= 2:
            return atk_power - def_power >= 0
        if my_life <= 4:
            return atk_power - def_power >= 2000
        return False

    def use_counter(self, needed: int) -> int:
        """Usa counter da mão para defender"""
        counters = sorted(
            [c for c in self.me.hand if c.counter > 0],
            key=lambda c: c.counter
        )
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
        """
        Decide se usa blocker (doc IA: usa para proteger quando vida baixa)
        """
        my_life = self.me.life_count()
        if my_life > 3:
            return None  # vida alta, não precisa
        blockers = self.me.blockers_active()
        if not blockers:
            return None
        # Usa o blocker de menor valor (preserva os melhores)
        return min(blockers, key=lambda c: c.board_value())


# ══════════════════════════════════════════════════════════════════════════════
# SIMULADOR DE PARTIDA
# ══════════════════════════════════════════════════════════════════════════════

class OPTCGMatch:
    """
    Simula uma partida completa de OPTCG com cartas reais.
    Implementa todas as fases e mecânicas das regras oficiais.
    """

    MAX_TURNS = 25

    def __init__(self, deck_a: tuple, deck_b: tuple):
        leader_a, cards_a = deck_a
        leader_b, cards_b = deck_b

        self.state_a = GameState(
            leader=deepcopy(leader_a),
            deck=[deepcopy(c) for c in cards_a]
        )
        self.state_b = GameState(
            leader=deepcopy(leader_b),
            deck=[deepcopy(c) for c in cards_b]
        )

        # Decide quem vai primeiro
        if random.random() < 0.5:
            self.state_a.is_first = True
            self.state_b.is_first = False
        else:
            self.state_a.is_first = False
            self.state_b.is_first = True

    def setup(self):
        """Setup inicial — regras 5-2"""
        for p in [self.state_a, self.state_b]:
            random.shuffle(p.deck)
            # Compra 5 cartas
            p.hand = [p.deck.pop() for _ in range(min(5, len(p.deck)))]
            # Mulligan simples: refaz se não tiver jogada no T1
            if self._should_mulligan(p):
                p.deck.extend(p.hand)
                random.shuffle(p.deck)
                p.hand = [p.deck.pop() for _ in range(min(5, len(p.deck)))]
            # Coloca life cards
            life_count = p.leader.life if p.leader.life > 0 else 5
            p.life = [p.deck.pop() for _ in range(min(life_count, len(p.deck)))]

    def _should_mulligan(self, p: GameState) -> bool:
        """Mulligan: refaz se não tiver nenhuma carta de custo <= 2 (doc IA)"""
        playable_t1 = [c for c in p.hand if c.cost <= 2 and c.card_type != 'LEADER']
        return len(playable_t1) == 0

    # ── Fases ──────────────────────────────────────────────────────────────

    def refresh_phase(self, p: GameState):
        """Refresh Phase — regra 6-2"""
        p.don_available += sum(c.don_attached for c in p.field_chars)
        p.don_available += p.leader.don_attached
        for c in p.field_chars:
            c.don_attached = 0
            c.rested = False
            c.just_played = False
        p.leader.don_attached = 0

    def draw_phase(self, p: GameState):
        """Draw Phase — regra 6-3 (1º jogador não compra no T1)"""
        if p.turn == 1 and p.is_first:
            return
        if p.deck:
            p.hand.append(p.deck.pop())

    def don_phase(self, p: GameState):
        """DON!! Phase — regra 6-4"""
        if p.turn == 1 and p.is_first:
            gain = 1
        else:
            gain = min(2, p.don_deck)
        p.don_deck -= gain
        p.don_available += gain

    def main_phase(self, p: GameState, opp: GameState) -> bool:
        """
        Main Phase — regra 6-5
        Retorna True se o jogo acabou.
        """
        engine = DecisionEngine(p, opp)
        actions_taken = 0
        max_actions = 15

        while actions_taken < max_actions:
            # Prioridade 1: LETAL (doc IA: +10000)
            if engine.can_lethal():
                action = engine.choose_attack()
                if action:
                    attacker, ttype, target = action
                    if self._execute_attack(attacker, ttype, target, p, opp, engine):
                        return True

            # Prioridade 2: Evitar derrota (doc IA: +9000)
            if engine.probable_lethal_next_turn():
                # Joga blocker ou defensor
                best = engine.choose_card_to_play()
                if best and best.has_blocker:
                    self._play_card(best, p)
                    actions_taken += 1
                    continue

            # Prioridade 3: Jogar cartas
            card = engine.choose_card_to_play()
            if card:
                self._play_card(card, p)
                actions_taken += 1
                continue

            # Prioridade 4: Atacar
            action = engine.choose_attack()
            if action and p.turn > 1:
                attacker, ttype, target = action
                if self._execute_attack(attacker, ttype, target, p, opp, engine):
                    return True
                actions_taken += 1
                continue

            break  # Sem mais ações úteis

        # Remove flag just_played
        for c in p.field_chars:
            c.just_played = False

        return False

    def _play_card(self, card: Card, p: GameState):
        """Joga uma carta — regra 6-5-3"""
        p.hand.remove(card)
        p.don_available -= card.cost
        p.chars_played += 1

        if card.card_type == 'CHARACTER':
            # Campo cheio: remove o de menor valor
            if len(p.field_chars) >= 5:
                worst = min(p.field_chars, key=lambda c: c.board_value())
                p.field_chars.remove(worst)
                p.trash.append(worst)

            card.rested = False
            card.just_played = True
            p.field_chars.append(card)

            # On Play: draw
            for _ in range(card.draw_power):
                if p.deck:
                    p.hand.append(p.deck.pop())

            # On Play: searcher (simplificado: compra 1)
            if card.is_searcher and p.deck:
                p.hand.append(p.deck.pop())
                p.searchers_used += 1

    def _execute_attack(self, attacker: Card, target_type: str,
                         target: Optional[Card], p: GameState,
                         opp: GameState, engine: DecisionEngine) -> bool:
        """
        Executa um ataque completo.
        Retorna True se o jogo acabou.
        Implementa: Attack → Block → Counter → Damage (regras 7-1)
        """
        # Attack Step — descansa o atacante
        attacker.rested = True
        atk_power = attacker.effective_power(True)

        # Efeitos When Attacking (simplificado: Double Attack)
        damage = 2 if attacker.has_double_attack else 1

        # Block Step — oponente pode usar blocker
        opp_engine = DecisionEngine(opp, p)
        blocker = opp_engine.should_use_blocker(atk_power)
        if blocker and not attacker.has_unblockable:
            target_type = 'character'
            target = blocker
            blocker.rested = True

        # Counter Step — oponente pode usar counter
        if target_type == 'leader':
            defend_power = opp.leader.power
        elif target and target in opp.field_chars:
            defend_power = target.power
        else:
            return False

        if opp_engine.should_use_counter(atk_power, defend_power):
            needed = atk_power - defend_power + 1
            added = opp_engine.use_counter(needed)
            defend_power += added

        # Damage Step — regra 7-1-4
        if atk_power >= defend_power:
            if target_type == 'leader':
                # Dano ao leader
                for _ in range(damage):
                    if not opp.life:
                        # Oponente tem 0 vidas → próximo dano = vitória
                        p.dmg_dealt += 1
                        return True
                    life_card = opp.life.pop()
                    p.dmg_dealt += 1
                    # Verifica trigger
                    if life_card.has_trigger:
                        # Oponente escolhe ativar (simplificado: sempre ativa)
                        opp.hand.append(life_card)
                        opp.triggers_activated += 1
                    else:
                        opp.hand.append(life_card)
            elif target_type == 'character' and target and target in opp.field_chars:
                # K.O. do character
                opp.field_chars.remove(target)
                opp.trash.append(target)

        return False

    def end_phase(self, p: GameState):
        """End Phase — regra 6-6"""
        pass  # Efeitos End of Turn seriam processados aqui

    # ── Partida completa ────────────────────────────────────────────────────

    def play_turn(self, p: GameState, opp: GameState) -> Optional[str]:
        """
        Executa um turno completo.
        Retorna 'A', 'B' ou None.
        """
        p.turn += 1
        self.refresh_phase(p)
        self.draw_phase(p)
        self.don_phase(p)

        if self.main_phase(p, opp):
            return 'A' if p is self.state_a else 'B'

        # Verifica derrota por deck vazio
        if not p.deck:
            return 'B' if p is self.state_a else 'A'
        if not opp.deck:
            return 'A' if p is self.state_a else 'B'

        self.end_phase(p)
        return None

    def simulate(self) -> dict:
        """
        Simula a partida completa.
        Retorna dict com resultado e estatísticas.
        """
        self.setup()
        winner = None
        total_turns = 0

        for turn_num in range(self.MAX_TURNS * 2):
            # Alterna turno
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
            'winner':     winner,
            'turns':      total_turns,
            'dmg_a':      self.state_a.dmg_dealt,
            'dmg_b':      self.state_b.dmg_dealt,
            'life_a':     self.state_a.life_count(),
            'life_b':     self.state_b.life_count(),
            'counters_a': self.state_a.counters_used,
            'counters_b': self.state_b.counters_used,
            'searchers_a':self.state_a.searchers_used,
            'searchers_b':self.state_b.searchers_used,
            'triggers_a': self.state_a.triggers_activated,
            'triggers_b': self.state_b.triggers_activated,
        }


# ══════════════════════════════════════════════════════════════════════════════
# PIPELINE DE SIMULAÇÃO
# ══════════════════════════════════════════════════════════════════════════════

def simular_matchup(deck_a: tuple, deck_b: tuple, n: int = 100) -> dict:
    """Simula N partidas entre dois decks e retorna estatísticas"""
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
        'wins_a':      wins_a,
        'wins_b':      wins_b,
        'draws':       draws,
        'winrate_a':   round(wins_a / total * 100, 1) if total > 0 else 50.0,
        'winrate_b':   round(wins_b / total * 100, 1) if total > 0 else 50.0,
        'avg_turns':   round(avg_turns, 1),
        'counters_pg_a':  round(counters_a  / total, 1) if total > 0 else 0,
        'counters_pg_b':  round(counters_b  / total, 1) if total > 0 else 0,
        'searchers_pg_a': round(searchers_a / total, 1) if total > 0 else 0,
        'searchers_pg_b': round(searchers_b / total, 1) if total > 0 else 0,
        'triggers_pg_a':  round(triggers_a  / total, 1) if total > 0 else 0,
        'triggers_pg_b':  round(triggers_b  / total, 1) if total > 0 else 0,
    }


def main():
    print('=' * 60)
    print('OPTCG Game State Engine v2.0')
    print('Simulador com cartas REAIS')
    print('=' * 60)

    # ── Carrega dados ─────────────────────────────────────────────────────
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

    # ── Constrói decks reais ──────────────────────────────────────────────
    print('\n[1/3] Construindo decks reais...')
    decks = {}
    urls_by_name = df_raw.groupby('deck_url')['deck_name'].first().to_dict()

    for url, name in urls_by_name.items():
        result = build_real_deck(name, url, df_raw, cards_db)
        if result:
            leader, cards = result
            if len(cards) >= 40:  # só decks com pelo menos 40 cartas
                decks[url] = {
                    'name':   name,
                    'url':    url,
                    'leader': leader,
                    'cards':  cards,
                    'deck':   result,
                }

    print(f'  Decks construídos: {len(decks)}')

    # Ordena por placing para pegar os top 5
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

    print(f'  Top 5 para matchups: {[decks[u]["name"][:30] for u in top5_urls]}')

    # ── Simula matchups ───────────────────────────────────────────────────
    print('\n[2/3] Simulando partidas (cada deck vs top 5)...')
    resultados = []

    deck_urls = list(decks.keys())
    total = len(deck_urls)

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

        sim_wr = round(sum(winrates) / len(winrates), 1)
        avg_turns = round(sum(avg_turns_list) / len(avg_turns_list), 1)

        # Busca features do deck
        feat_row = df_feat[df_feat['url'] == url_a]
        placing = int(feat_row['placing'].values[0]) if len(feat_row) > 0 else 99
        perf_score = float(feat_row['performance_score'].values[0]) if len(feat_row) > 0 else 50.0
        leader_wr = float(feat_row['leader_winrate'].values[0]) if len(feat_row) > 0 else 0.0

        # Score final: 40% colocação + 30% winrate leader + 30% simulação
        final_score = round(
            perf_score * 0.40 +
            leader_wr  * 0.30 +
            sim_wr     * 0.30, 1
        )

        resultados.append({
            'deck_name':      deck_a_info['name'],
            'deck_url':       url_a,
            'leader':         deck_a_info['leader'].code,
            'placing':        placing,
            'performance_score': perf_score,
            'leader_winrate': leader_wr,
            'sim_winrate':    sim_wr,
            'avg_turns':      avg_turns,
            'counters_pg':    round(sum(counters_list)  / len(counters_list),  1),
            'searchers_pg':   round(sum(searchers_list) / len(searchers_list), 1),
            'triggers_pg':    round(sum(triggers_list)  / len(triggers_list),  1),
            'final_score':    final_score,
        })

        print(f'  [{i+1}/{total}] {deck_a_info["name"][:40]:<40} wr={sim_wr}% turns={avg_turns}')

    # ── Salva resultados ──────────────────────────────────────────────────
    print('\n[3/3] Salvando resultados...')
    df_res = pd.DataFrame(resultados)
    df_res.to_csv('resultados_simulacao.csv', index=False, encoding='utf-8')
    print(f'✅ resultados_simulacao.csv — {len(resultados)} decks')

    # Atualiza modelo
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
    print('Próximos passos:')
    print('1. python treinar_modelo.py')
    print('2. move modelo_optcg.json ..\\public\\modelo_optcg.json')


if __name__ == '__main__':
    main()