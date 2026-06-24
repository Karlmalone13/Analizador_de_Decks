"""
optcg_engine/decision_engine.py
================================
Motor de simulação OPTCG — sistema unificado.

Baseado nas 34k linhas do Assembly-CSharp.dll v1.40a.

Estrutura:
    Card          — carta (estado em jogo)
    GameState     — estado de um jogador
    EffectExecutor — executa efeitos do card_effects_db.json (único ponto)
    DecisionEngine — IA de decisão situacional
    OPTCGMatch    — motor de partida (fases, combate, turnos)
    simular_matchup — pipeline de N partidas

Fluxo de efeitos (baseado no DoV3ActionStep das 34k linhas):
    _play_card() → EffectExecutor.execute(card, trigger='on_play', p, opp)
    _execute_attack() → EffectExecutor.execute(card, trigger='when_attacking', p, opp)
    on_ko → EffectExecutor.execute(card, trigger='on_ko', p, opp)
    your_turn → EffectExecutor.apply_your_turn_buffs(p, opp)
"""

import re
import json
import os
import random
import pandas as pd
from dataclasses import dataclass, field
from typing import List, Optional
from copy import deepcopy


# ===========================================================================
# Carrega o banco de efeitos
# ===========================================================================

_DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'card_effects_db.json')
_EFFECTS_DB: dict = {}

def _load_effects_db():
    global _EFFECTS_DB
    if _EFFECTS_DB:
        return
    try:
        with open(_DB_PATH, 'r', encoding='utf-8') as f:
            _EFFECTS_DB = json.load(f)
    except FileNotFoundError:
        pass

_load_effects_db()


def get_card_effects(code: str) -> dict:
    """Retorna os efeitos de uma carta pelo código."""
    return _EFFECTS_DB.get(code, {}).get('effects', {})


# ===========================================================================
# Estruturas de dados
# ===========================================================================

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
    sub_types: str = ''
    attribute: str = ''  # Slash, Special, Strike, Wisdom, Ranged (pode ser combinado, ex: "Slash Special")
    card_text: str = ''
    # Keywords (do banco ou detectadas)
    has_rush: bool = False
    has_rush_character: bool = False  # [Rush: Character] -- so pode atacar Characters no turno em que entra, NUNCA o Leader (mecanica distinta de has_rush)
    has_blocker: bool = False
    has_double_attack: bool = False
    has_banish: bool = False
    has_trigger: bool = False
    has_unblockable: bool = False
    # Campos de compatibilidade com o replay
    is_searcher: bool = False
    draw_power: int = 0
    draw_then_trash: int = 0
    draw_condition: str = 'always'
    has_on_play_ko: bool = False
    has_bounce: bool = False
    don_cond_keywords: dict = None  # {keyword: don_req} — keywords ganhas com [DON!! ×N]
    has_rest_effect: bool = False
    has_start_of_game: bool = False
    has_power_minus: bool = False
    trash_opp_char: bool = False
    # Estado em jogo
    rested: bool = False
    just_played: bool = False
    rush_character_only_this_turn: bool = False  # True so na janela em que Rush: Character libera o ataque (reseta junto com just_played)
    don_attached: int = 0
    cannot_attack_until: str = ''   # '', 'opp_turn_end', 'opp_end_phase', 'my_next_turn_start' -- trava de ataque (lock_opp_character_attack)
    cannot_be_rested_until: str = ''  # mesma semantica de duracao, para lock_opp_cannot_be_rested (mecanica DISTINTA de cannot_attack)
    # Buffs temporários (resetados a cada turno)
    power_buff: int = 0
    cost_buff: int = 0       # resetado no fim do turno do oponente (duration until_opp_turn_end)
    cost_buff_permanent: int = 0  # nunca resetado (duration permanent, ex: leader_type condicional)

    def effective_cost(self) -> int:
        return max(0, self.cost + self.cost_buff + self.cost_buff_permanent)

    def _kw_active(self, kw: str, native: bool) -> bool:
        """Keyword ativa se nativa OU condicional a [DON!! ×N] com DON suficiente."""
        if native:
            return True
        cond = self.don_cond_keywords or {}
        req = cond.get(kw)
        if req is not None:
            return getattr(self, 'don_attached', 0) >= req
        return False

    def is_blocker(self) -> bool:
        return self._kw_active('blocker', self.has_blocker)

    def is_double_attack(self) -> bool:
        return self._kw_active('double_attack', self.has_double_attack)

    def is_rush(self) -> bool:
        return self._kw_active('rush', self.has_rush)

    def is_rush_character(self) -> bool:
        return self._kw_active('rush_character', self.has_rush_character)

    def is_banish(self) -> bool:
        return self._kw_active('banish', self.has_banish)

    def effective_power(self, your_turn: bool = True) -> int:
        return self.power + self.power_buff + (self.don_attached * 1000 if your_turn else 0)

    def board_value(self) -> int:
        v = self.power // 1000
        if self.has_rush:          v += 4
        if self.has_blocker:       v += 3
        if self.has_double_attack: v += 3
        if self.has_banish:        v += 2
        if self.has_unblockable:   v += 4
        if self.has_trigger:       v += 2
        return v


@dataclass
class GameState:
    leader: Card
    deck: List[Card] = field(default_factory=list)
    hand: List[Card] = field(default_factory=list)
    field_chars: List[Card] = field(default_factory=list)
    field_stage: Optional[Card] = None
    life: List[Card] = field(default_factory=list)
    don_deck: int = 10
    don_available: int = 0
    don_rested: int = 0
    trash: List[Card] = field(default_factory=list)
    turn: int = 0
    global_turn: int = 0
    is_first: bool = True
    # Estatísticas
    dmg_dealt: int = 0
    chars_played: int = 0
    counters_used: int = 0
    searchers_used: int = 0
    triggers_activated: int = 0
    full_deck_census: dict = None
    # ids (id(card), nao codigo -- pode haver copias da mesma carta na mao
    # com status de revelacao diferente) das instancias de Card atualmente
    # na mao que foram expostas ao oponente por um efeito de busca com
    # 'reveal' (confirmado pela regra oficial: o padrao "look at N; reveal
    # up to 1 [filtro] and add to hand" expoe a carta especifica escolhida,
    # mesmo sendo o texto mais comum do jogo -- distinto de dano normal na
    # vida, que NUNCA revela, e de busca sem a palavra 'reveal', que tambem
    # nao revela). Removido do set quando a carta sai da mao (jogada,
    # trashada, etc) -- usado pelo OpponentModel para saber quais cartas
    # specificas o oponente certamente tem, em vez de sortear via Monte Carlo.
    revealed_to_opponent: set = field(default_factory=set)

    def known_hand_cards(self) -> List['Card']:
        """
        Subconjunto de `self.hand` que é conhecido pelo oponente (cartas
        reveladas por efeito de busca e que ainda estão na mão). Filtra de
        forma lazy contra `self.hand` em vez de exigir limpeza manual de
        `revealed_to_opponent` em cada um dos pontos do engine onde uma
        carta sai da mão (jogada, trashada, etc) -- mais seguro do que
        arriscar esquecer algum desses pontos e deixar um id() órfão
        apontando para memória já realocada para outra carta.
        """
        ids_na_mao = {id(c) for c in self.hand}
        # remove ids que não correspondem a nenhuma carta atual na mão
        # (carta já saiu -- ex: jogada, trashada). Faz isso aqui (lazy)
        # em vez de em cada ponto de remoção da mão.
        self.revealed_to_opponent &= ids_na_mao
        return [c for c in self.hand if id(c) in self.revealed_to_opponent]

    def life_count(self) -> int:
        return len(self.life)

    def active_chars(self) -> List[Card]:
        return [c for c in self.field_chars if not c.rested and not c.just_played]

    def rested_chars(self) -> List[Card]:
        return [c for c in self.field_chars if c.rested]

    def counter_in_hand(self) -> int:
        return sum(c.counter for c in self.hand if c.counter > 0)

    def blockers_active(self) -> List[Card]:
        return [c for c in self.field_chars if c.is_blocker() and not c.rested and not c.cannot_be_rested_until]

    def board_score(self) -> int:
        return sum(c.board_value() for c in self.field_chars)

    def estimated_counter(self) -> int:
        return len(self.hand) * 1000

    def can_attack_this_turn(self) -> bool:
        return self.turn > 1

    def don_on_field(self) -> int:
        return self.don_available + self.don_rested


def is_attack_locked_self(card: 'Card', owner: 'GameState', opp: 'GameState') -> bool:
    """
    True se `card` esta travada para atacar por um efeito PASSIVO PROPRIO
    (cannot_attack_self / cannot_attack_self_unless /
    cannot_attack_own_characters_by_cost), distinto de cannot_attack_until
    (que e trava posta por OUTRA carta via lock_opp_character_attack e ja
    e checada separadamente nos mesmos 6 pontos). Centraliza a logica aqui
    em vez de duplicar em GameAnalyzer/OPTCGMatch -- ambas as classes tem
    acesso a um GameState do dono e um do oponente em todo ponto que
    precisa decidir "esta carta pode atacar?".

    Condicoes suportadas (mesmo vocabulario de _check_conditions, mas
    replicado aqui de forma minima -- so os campos que cannot_attack_self_*
    de fato usa no banco hoje: board_has_power_gte,
    opp_chars_power_gte_count). Se 'conditions' nao foi reconhecida pelo
    parser (campo legado 'condition_text' presente em vez de 'conditions'),
    trata como travado SEMPRE -- mais seguro assumir o lock ativo do que
    liberar o ataque sem confirmar a condicao real.
    """
    effects = get_card_effects(card.code)
    passive = effects.get('passive', {})
    for step in passive.get('steps', []):
        action = step.get('action')
        if action == 'cannot_attack_self':
            return True
        if action == 'cannot_attack_self_unless':
            if 'condition_text' in step and 'conditions' not in step:
                return True  # condicao nao estruturada -- trava por seguranca
            conds = step.get('conditions', {})
            if 'board_has_power_gte' in conds:
                todos = list(owner.field_chars) + list(opp.field_chars)
                if not todos or max(c.effective_power(True) for c in todos) < conds['board_has_power_gte']:
                    return True  # condicao NAO satisfeita -> travada
            if 'opp_chars_power_gte_count' in conds:
                spec = conds['opp_chars_power_gte_count']
                n = sum(1 for c in opp.field_chars if c.effective_power(False) >= spec['power_gte'])
                if n < spec['count']:
                    return True
            # alguma condicao reconhecida e satisfeita (ou nenhuma condicao
            # suportada presente, caso futuro) -- nao trava.
    # mass_lock_conditional e um efeito de OUTRA carta no board (ex: P-084)
    # que trava `card` por filtro de custo -- precisa varrer todo o board
    # do dono (characters + leader) procurando alguma fonte com esse
    # trigger ativo, e nao apenas os efeitos da propria `card` sendo
    # avaliada (P-084 trava as OUTRAS cartas custo 3/4, nao trava P-084
    # nela mesma via este trigger -- P-084 se trava via cannot_attack_self
    # incondicional, ja checado acima).
    fontes_mass_lock = list(owner.field_chars) + [owner.leader]
    for fonte in fontes_mass_lock:
        fonte_effects = get_card_effects(fonte.code)
        mass_lock = fonte_effects.get('mass_lock_conditional')
        if not mass_lock:
            continue
        conds = mass_lock.get('conditions', {})
        leader_is = conds.get('leader_is', '').lower()
        if leader_is and leader_is not in owner.leader.name.lower():
            continue
        costs_alvo = set()
        for s in mass_lock.get('steps', []):
            if s.get('action') == 'cannot_attack_own_characters_by_cost':
                costs_alvo.update(s.get('costs', []))
        if card.cost in costs_alvo:
            return True
    return False


# ===========================================================================
# EffectExecutor — único ponto de execução de efeitos
# Baseado no DoV3ActionStep das 34k linhas
# ===========================================================================

class EffectExecutor:
    """
    Executa efeitos de cartas conforme o banco card_effects_db.json.
    Cada 'action' corresponde a um efeito do DoV3ActionStep das 34k linhas.
    """

    def __init__(self, me: GameState, opp: GameState):
        self.me = me
        self.opp = opp
        self._once_used: set = set()  # (card_code, trigger)

    def reset_once_per_turn(self):
        self._once_used.clear()

    def execute(self, card: Card, trigger: str, verbose: bool = False) -> list:
        """
        Executa todos os efeitos de um trigger para uma carta.
        Retorna lista de logs para o replay.
        """
        effects = get_card_effects(card.code)
        if trigger not in effects:
            return []

        ef_data = effects[trigger]

        # Once per turn
        key = (card.code, trigger)
        if ef_data.get('once_per_turn') and key in self._once_used:
            return []

        # Verifica condições
        if not self._check_conditions(ef_data.get('conditions', {}), card):
            return []

        # [DON!! ×N]: o efeito só ativa se a carta tem N DON anexados.
        # Sem isso, a IA executaria o efeito de graça (vantagem ilegal).
        don_req = ef_data.get('don_requirement', 0)
        if don_req and getattr(card, 'don_attached', 0) < don_req:
            return []

        # Paga custos
        if not self._pay_costs(ef_data.get('costs', []), card):
            return []

        # Executa steps. Os logs do CUSTO (pago acima) vêm primeiro, para o
        # replay mostrar o que foi pago antes do benefício.
        logs = list(getattr(self, '_cost_logs', []))
        for step in ef_data.get('steps', []):
            log = self._execute_step(step, card)
            if log:
                logs.append(log)

        if ef_data.get('once_per_turn'):
            self._once_used.add(key)

        return logs

    def try_substitute(self, card: Card, removal_kind: str, verbose: bool = False) -> str | None:
        """
        Verifica se `card` (do lado self.me) tem substitute_ko (removal_kind
        == 'ko') ou substitute_removal (removal_kind in ('ko','bounce',
        'deck_bottom') -- substitute_removal cobre QUALQUER remocao, nao so
        K.O.) ativo, e se sim tenta pagar o custo da substituicao.
        Retorna uma string de log se substituiu (e quem chamou NAO deve
        prosseguir com a remocao real), ou None se nao ha substituto
        aplicavel/pagavel (remocao segue normalmente).
        """
        effects = get_card_effects(card.code)
        block = effects.get('passive', {})
        if not block:
            return None

        for step in block.get('steps', []):
            action = step.get('action')
            aplica = (action == 'substitute_ko' and removal_kind == 'ko') or action == 'substitute_removal'
            if not aplica:
                continue

            # Once per turn (mesma chave de controle que efeitos normais)
            key = (card.code, 'passive_substitute')
            if block.get('once_per_turn') and key in self._once_used:
                continue

            # Filtro de alvo: self_type (sub_types) ou self_name (nome
            # proprio) -- quando presentes, restringem quais cards desse
            # arquetipo podem usar o substituto.
            conds = dict(block.get('conditions', {}))
            if not self._check_conditions(conds, card):
                continue
            filter_type = step.get('filter_type', '')
            if filter_type and filter_type.lower() not in card.sub_types.lower():
                continue
            filter_name = step.get('filter_name', '')
            if filter_name and filter_name.lower() not in card.name.lower():
                continue

            cost = step.get('cost', {})
            log = self._pay_substitute_cost(cost, card)
            if log is None:
                continue  # não conseguiu pagar -- tenta o próximo step (raro) ou desiste

            if block.get('once_per_turn'):
                self._once_used.add(key)
            return log

        return None

    def _pay_substitute_cost(self, cost: dict, card: Card) -> str | None:
        """Paga o custo de uma substituicao de K.O./remocao. Retorna log de
        sucesso, ou None se nao pode pagar (substituicao nao ocorre)."""
        ctype = cost.get('action')
        me = self.me

        if ctype == 'trash_self':
            if card not in me.field_chars:
                return None
            me.field_chars.remove(card)
            me.trash.append(card)
            return f'{card.name[:18]} evitou K.O./remoção trashando a si mesmo'

        if ctype == 'rest_don':
            count = cost.get('count', 1)
            if me.don_available < count:
                return None
            me.don_available -= count
            me.don_rested += count
            return f'{card.name[:18]} evitou K.O./remoção restando {count} DON'

        if ctype in ('return_own_don', 'don_minus'):
            count = cost.get('count', 1)
            if not self._return_don_to_deck(count):
                return None
            return f'{card.name[:18]} evitou K.O./remoção devolvendo {count} DON ao deck'

        if ctype == 'trash_from_hand':
            count = cost.get('count', 1)
            filter_type = cost.get('filter_type')
            power_gte = cost.get('power_gte')
            candidatos = list(me.hand)
            if filter_type:
                tipos_lower = [t.lower() for t in filter_type]
                candidatos = [c for c in candidatos
                              if any(t in c.sub_types.lower() or t in c.card_type.lower() for t in tipos_lower)]
            if power_gte is not None:
                candidatos = [c for c in candidatos if c.power >= power_gte]
            if len(candidatos) < count:
                return None
            trashed = []
            for _ in range(count):
                worst = min(candidatos, key=lambda c: c.board_value())
                me.hand.remove(worst)
                me.trash.append(worst)
                candidatos.remove(worst)
                trashed.append(worst.name[:15])
            return f'{card.name[:18]} evitou K.O./remoção trashando da mão: {", ".join(trashed)}'

        if ctype == 'debuff_power_self':
            amount = cost.get('amount', 0)
            card.power_buff -= amount
            return f'{card.name[:18]} evitou K.O./remoção perdendo {amount} de power'

        if ctype == 'debuff_power_self_leader':
            amount = cost.get('amount', 0)
            me.leader.power_buff -= amount
            return f'{card.name[:18]} evitou K.O./remoção (Leader perdeu {amount} de power)'

        if ctype == 'rest_self':
            if card.rested:
                return None
            card.rested = True
            return f'{card.name[:18]} evitou K.O./remoção restando-se'

        if ctype == 'bounce_self':
            if card not in me.field_chars:
                return None
            me.field_chars.remove(card)
            card.rested = False
            card.don_attached = 0
            me.hand.append(card)
            return f'{card.name[:18]} evitou K.O./remoção voltando para a mão'

        return None

    def apply_your_turn_buffs(self) -> list:
        """
        Aplica buffs passivos [Your Turn] de todas as cartas em campo.
        Baseado no CardV3PassiveFieldBuffs das 34k linhas.
        Inclui stages, líderes e personagens.
        """
        logs = []
        sources = self.me.field_chars + [self.me.leader]
        if self.me.field_stage:
            sources.append(self.me.field_stage)
        # Reset buffs temporários antes de aplicar novos
        for c in self.me.field_chars + [self.me.leader]:
            c.power_buff = 0
            c.cost_buff = 0

        for source in sources:
            effects = get_card_effects(source.code)
            for trigger in ('your_turn', 'passive'):
                if trigger not in effects:
                    continue
                ef_data = effects[trigger]
                if not self._check_conditions(ef_data.get('conditions', {}), source):
                    continue
                # LACUNA CONHECIDA: cartas com 'Choose one: • opcao A • opcao
                # B' tem ef_data['choice'] = [[steps_opcao_A], [steps_opcao_B]]
                # em vez de ef_data['steps'] (ver gerar_effects_db.py,
                # parse_block). O .get('steps', []) abaixo retorna [] para
                # essas cartas -- nenhuma opcao e executada (neutro, nao
                # quebra), mas tambem nenhum efeito real acontece. Decidir
                # qual opcao escolher e avaliacao de jogo (Opponent Reading /
                # Play Scoring), nao um parsing determinístico -- pendente.
                #
                # LACUNA CONHECIDA #2: cartas com 'Apply each of the
                # following effects based on N' (efeitos COEXISTENTES, nao
                # exclusivos como choice) tem ef_data['conditional_stack'] =
                # [{conditions, steps}, ...] em vez de ef_data['steps'].
                # Carta unica confirmada (OP15-092) -- mesma neutralidade:
                # nao quebra, mas nenhum item do stack e avaliado/executado
                # ainda. Pendente: iterar o stack, checar conditions de cada
                # item via _check_conditions, executar os steps dos que
                # passarem (sem early-return -- sao cumulativos, nao 'escolha
                # 1 e para').
                for step in ef_data.get('steps', []):
                    log = self._execute_step(step, source)
                    if log:
                        logs.append(log)

        return logs

    def reset_your_turn_buffs(self):
        """Reseta buffs temporários ao fim do turno."""
        for card in self.me.field_chars + [self.me.leader]:
            card.power_buff = 0
            card.cost_buff = 0

    # ── Verificação de condições ─────────────────────────────────────────────

    def _check_conditions(self, conds: dict, card: Card) -> bool:
        me = self.me
        opp = self.opp

        if not conds:
            return True

        if 'life_lte' in conds and me.life_count() > conds['life_lte']:
            return False
        if 'life_gte' in conds and me.life_count() < conds['life_gte']:
            return False
        if 'trash_gte' in conds and len(me.trash) < conds['trash_gte']:
            return False
        if 'don_gte' in conds and me.don_available < conds['don_gte']:
            return False
        if 'don_on_field_gte' in conds and me.don_on_field() < conds['don_on_field_gte']:
            return False
        if 'chars_gte' in conds:
            cost_filter = conds.get('chars_gte_cost_filter')
            if cost_filter is not None:
                contagem = sum(1 for c in me.field_chars if c.cost >= cost_filter)
            else:
                contagem = len(me.field_chars)
            if contagem < conds['chars_gte']:
                return False
        if 'hand_lte' in conds and len(me.hand) > conds['hand_lte']:
            return False
        if 'hand_gte' in conds and len(me.hand) < conds['hand_gte']:
            return False
        if 'leader_is' in conds:
            if conds['leader_is'].lower() not in me.leader.name.lower():
                return False
        if 'leader_type_includes' in conds:
            if conds['leader_type_includes'].lower() not in me.leader.sub_types.lower():
                return False
        if conds.get('leader_multicolor'):
            colors = set(me.leader.color.replace('/', ' ').split())
            if len(colors) < 2:
                return False
        if 'other_char_power_gte' in conds:
            outros = [c for c in me.field_chars if c is not card]
            if not outros or max(c.effective_power(True) for c in outros) < conds['other_char_power_gte']:
                return False
        if 'other_char_cost_gte' in conds:
            outros = [c for c in me.field_chars if c is not card]
            if not outros or max(c.cost for c in outros) < conds['other_char_cost_gte']:
                return False
        if 'self_power_gte' in conds and card.effective_power(True) < conds['self_power_gte']:
            return False
        if 'leader_power_gte' in conds and me.leader.effective_power(True) < conds['leader_power_gte']:
            return False
        if 'leader_power_lte' in conds and me.leader.effective_power(True) > conds['leader_power_lte']:
            return False
        if 'events_in_trash_gte' in conds:
            n_events = sum(1 for c in me.trash if c.card_type.lower() == 'event')
            if n_events < conds['events_in_trash_gte']:
                return False
        if 'board_has_cost' in conds or 'board_has_cost_gte' in conds:
            # condicao de existencia: QUALQUER Character no jogo (os dois
            # campos) com custo == N exato ou >= M.
            todos = list(me.field_chars) + list(opp.field_chars)
            exatos = set(conds.get('board_has_cost', []))
            gte = conds.get('board_has_cost_gte')
            existe = any(
                c.cost in exatos or (gte is not None and c.cost >= gte)
                for c in todos)
            if not existe:
                return False
        if 'opp_char_power_gte' in conds:
            if not opp.field_chars or max(c.effective_power(False) for c in opp.field_chars) < conds['opp_char_power_gte']:
                return False
        if 'board_has_power_gte' in conds:
            # condicao de existencia generica: QUALQUER Character no jogo
            # (os dois campos) com power >= N. Mesma semantica de
            # board_has_cost, mas para power -- usada por
            # cannot_attack_self_unless (ex: EB04-051).
            todos = list(me.field_chars) + list(opp.field_chars)
            if not todos or max(c.effective_power(True) for c in todos) < conds['board_has_power_gte']:
                return False
        if 'opp_chars_power_gte_count' in conds:
            # CONTAGEM (nao existencia): precisa de >= count Characters
            # distintos no campo do OPONENTE, cada um com power >= power_gte
            # -- usada por cannot_attack_self_unless (ex: EB04-005) e por
            # efeitos condicionais a board do oponente (ex: OP09-005).
            spec = conds['opp_chars_power_gte_count']
            n = sum(1 for c in opp.field_chars if c.effective_power(False) >= spec['power_gte'])
            if n < spec['count']:
                return False
        if 'self_type' in conds and conds['self_type'] not in card.sub_types.lower():
            return False

        return True

    # ── Pagamento de custos ──────────────────────────────────────────────────

    def _pay_costs(self, costs: list, card: Card) -> bool:
        """Verifica e paga custos. Retorna False se não pode pagar.
        Registra o que foi pago em self._cost_logs (para o replay mostrar)."""
        self._cost_logs = []
        for cost in costs:
            ctype = cost['type']
            if ctype == 'rest_self':
                if card.rested:
                    return False
                card.rested = True
                self._cost_logs.append(f'custo: restou {card.name[:18]}')
            elif ctype == 'rest_self_and_leader_or_stage':
                # Custo composto: a propria carta E um Leader/Stage com
                # filtro de tipo, AMBOS precisam estar disponiveis (nao
                # rested) antes de pagar qualquer um -- pagamento parcial
                # deixaria o jogo em estado inconsistente (carta restada
                # sem o efeito ter sido de fato pago).
                if card.rested:
                    return False
                filter_type = cost.get('filter_type', '').lower()
                candidato = None
                if filter_type in self.me.leader.sub_types.lower() and not self.me.leader.rested:
                    candidato = self.me.leader
                elif (self.me.field_stage and filter_type in self.me.field_stage.sub_types.lower()
                      and not self.me.field_stage.rested):
                    candidato = self.me.field_stage
                if candidato is None:
                    return False
                card.rested = True
                candidato.rested = True
                self._cost_logs.append(
                    f'custo: restou {card.name[:15]} e {candidato.name[:15]}')
            elif ctype == 'rest_don':
                count = cost.get('count', 1)
                if self.me.don_available < count:
                    return False
                self.me.don_available -= count
                self.me.don_rested += count
                self._cost_logs.append(f'custo: restou {count} DON')
            elif ctype == 'trash_from_hand':
                count = cost.get('count', 1)
                if len(self.me.hand) < count:
                    return False
                trashed = []
                for _ in range(count):
                    worst = self._choose_to_trash(self.me.hand)
                    if worst:
                        self.me.hand.remove(worst)
                        self.me.trash.append(worst)
                        trashed.append(worst.name[:15])
                if trashed:
                    self._cost_logs.append(f'custo: trashou da mão: {", ".join(trashed)}')
            elif ctype == 'trash_self':
                if card in self.me.field_chars:
                    self.me.field_chars.remove(card)
                    self.me.trash.append(card)
                    self._cost_logs.append(f'custo: trashou {card.name[:18]} (ele mesmo)')
            elif ctype == 'don_minus':
                count = cost.get('count', 1)
                if not self._return_don_to_deck(count):
                    return False
                self._cost_logs.append(f'custo: devolveu {count} DON ao deck')
            elif ctype == 'ko_own_character':
                # Custo de K.O. de um Character PROPRIO (distinto de trash_self:
                # o alvo e OUTRO Character do jogador). K.O. != Trash -- precisa
                # disparar o [On K.O.] do Character escolhido. Ex: OP14-079
                # Crocodile (K.O. um Baroque Works), OP05-087 Hakuba.
                count = cost.get('count', 1)
                filter_type = cost.get('filter_type', '').lower()
                candidatos = [
                    c for c in self.me.field_chars
                    if c is not card
                    and (not filter_type or filter_type in c.sub_types.lower())
                ]
                if len(candidatos) < count:
                    return False
                koados = []
                for _ in range(count):
                    if not candidatos:
                        break
                    # escolhe o de menor valor de board (sacrifica o menos util),
                    # reaproveitando a heuristica de _choose_to_trash.
                    alvo = min(candidatos, key=lambda c: c.board_value())
                    candidatos.remove(alvo)
                    self.me.field_chars.remove(alvo)
                    self.me.trash.append(alvo)
                    koados.append(alvo.name[:15])
                    # dispara [On K.O.] do Character K.O.ado (regra K.O. != Trash)
                    self.execute(alvo, 'on_ko')
                if koados:
                    self._cost_logs.append(f'custo: K.O. próprio: {", ".join(koados)}')
        return True

    def _return_don_to_deck(self, count: int) -> bool:
        """
        Paga um custo DON!! −X: devolve X DON do campo para o deck de DON.
        Preferência (regra do usuário): devolve primeiro o DON "sem trabalho" —
        anexado a quem JÁ atacou (restado) ou ao líder que já atacou, depois DON
        restado no banco. Evita DON ativo e DON anexado a quem ainda vai agir.
        Retorna False se não há DON suficiente devolvível.
        """
        me = self.me
        devolvidos = 0

        # Fonte 1: DON anexado a personagens que JÁ atacaram (restados)
        for c in me.field_chars:
            while c.don_attached > 0 and c.rested and devolvidos < count:
                c.don_attached -= 1
                me.don_deck += 1
                devolvidos += 1

        # Fonte 2: DON anexado ao líder se já atacou (restado)
        while me.leader.don_attached > 0 and me.leader.rested and devolvidos < count:
            me.leader.don_attached -= 1
            me.don_deck += 1
            devolvidos += 1

        # Fonte 3: DON restado no banco (gasto, parado)
        while me.don_rested > 0 and devolvidos < count:
            me.don_rested -= 1
            me.don_deck += 1
            devolvidos += 1

        # Fonte 4 (último caso): DON anexado a quem ainda NÃO atacou / DON ativo
        # — só se for inevitável. Preferimos NÃO chegar aqui (o planner deve
        # ordenar para atacar antes). Mas se o custo é obrigatório, paga.
        if devolvidos < count:
            for c in me.field_chars:
                while c.don_attached > 0 and devolvidos < count:
                    c.don_attached -= 1
                    me.don_deck += 1
                    devolvidos += 1
            while me.leader.don_attached > 0 and devolvidos < count:
                me.leader.don_attached -= 1
                me.don_deck += 1
                devolvidos += 1
            while me.don_available > 0 and devolvidos < count:
                me.don_available -= 1
                me.don_deck += 1
                devolvidos += 1

        return devolvidos >= count

    # ── Execução de steps individuais ────────────────────────────────────────

    def _execute_step(self, step: dict, card: Card) -> str:
        action = step.get('action', '')
        me = self.me
        opp = self.opp

        # Condicao PROPRIA do step (distinta da condicao global do entry,
        # ja checada em _execute_trigger antes de chamar qualquer step).
        # Existe para separar "[A incondicional]. Then, if [cond], [B]" --
        # a condicao do "Then, if" deve bloquear SO o step B, nao o A que
        # vem antes dela no texto. Sem isto, qualquer condicao so podia
        # valer pro bloco inteiro (todos os steps), causando scope leakage
        # (confirmado em ST14-001/ST14-008 e ~44 outras cartas, 23/06).
        step_conds = step.get('conditions')
        if step_conds and not self._check_conditions(step_conds, card):
            return ''

        # ── Busca (StartTopDeck + AddToHand + FinalizeTopDeck) ────────────────
        if action == 'look_top_deck':
            # Apenas marca quantas cartas serão vistas — próximo step faz a seleção
            return ''

        if action == 'add_to_hand':
            if not me.deck:
                return ''
            # Número de cartas a olhar (do step anterior look_top_deck)
            # Busca o look_top_deck no mesmo bloco de efeitos
            effects = get_card_effects(card.code)
            look_count = 5  # padrão
            for trigger, ef in effects.items():
                for s in ef.get('steps', []):
                    if s.get('action') == 'look_top_deck':
                        look_count = s.get('count', 5)
                        break

            look = min(look_count, len(me.deck))
            candidates = me.deck[-look:]

            # Filtra por tipo se especificado
            filter_type = step.get('filter_type', '')
            exclude = step.get('exclude', [])
            cost_lte = step.get('cost_lte', 99)
            power_lte = step.get('power_lte', 999999)

            filtered = []
            for c in candidates:
                if filter_type:
                    ft = filter_type.lower()
                    match = (ft in c.sub_types.lower() or
                             ft in c.name.lower() or
                             ft in c.card_type.lower() or
                             ft in c.card_text.lower())
                    if not match:
                        continue
                if any(ex.lower() in c.name.lower() for ex in exclude):
                    continue
                if c.cost > cost_lte:
                    continue
                if c.power > power_lte:
                    continue
                filtered.append(c)

            count = step.get('count', 1)
            taken = []
            for _ in range(min(count, len(filtered))):
                best = max(filtered, key=lambda x: x.board_value()) if filtered else None
                if best:
                    taken.append(best)
                    filtered.remove(best)

            for c in taken:
                if c in me.deck:
                    me.deck.remove(c)
                me.hand.append(c)
                if step.get('revealed_to_opponent') is True:
                    me.revealed_to_opponent.add(id(c))

            # Resto permanece no deck (será tratado pelo próximo step)
            me.searchers_used += 1
            names = ', '.join(c.name[:15] for c in taken)
            if names:
                return f'olhou {look} do topo -> pegou: {names}'
            else:
                return f'olhou {look} do topo -> nada para pegar'

        if action == 'trash_rest':
            # Cartas que foram vistas mas não pegas vão ao trash
            # Identifica quais cartas do topo foram vistas
            effects = get_card_effects(card.code)
            look_count = 5
            for trigger, ef in effects.items():
                for s in ef.get('steps', []):
                    if s.get('action') == 'look_top_deck':
                        look_count = s.get('count', 5)
                        break
            # As cartas não tomadas ficam no topo do deck
            # Quantas foram tomadas: count do add_to_hand
            taken_count = 1
            for trigger, ef in effects.items():
                for s in ef.get('steps', []):
                    if s.get('action') == 'add_to_hand':
                        taken_count = s.get('count', 1)
                        break
            # O resto = look_count - taken = vão ao trash
            rest_count = max(0, look_count - taken_count)
            trashed = []
            for _ in range(min(rest_count, len(me.deck))):
                if me.deck:
                    c = me.deck.pop()
                    me.trash.append(c)
                    trashed.append(c.name[:12])
            return f'trash resto: {", ".join(trashed)}' if trashed else ''

        if action == 'deck_bottom_rest':
            # Resto vai ao fundo do deck (já está no topo, move para o fundo)
            effects = get_card_effects(card.code)
            look_count = 5
            taken_count = 1
            for trigger, ef in effects.items():
                for s in ef.get('steps', []):
                    if s.get('action') == 'look_top_deck':
                        look_count = s.get('count', 5)
                    if s.get('action') == 'add_to_hand':
                        taken_count = s.get('count', 1)
            rest_count = max(0, look_count - taken_count)
            moved = []
            for _ in range(min(rest_count, len(me.deck))):
                if me.deck:
                    c = me.deck.pop()  # tira do topo
                    me.deck.insert(0, c)  # coloca no fundo
                    moved.append(c)
            return f'{len(moved)} carta(s) no fundo do deck' if moved else ''

        if action == 'activate_main_effect':
            # Trigger que ativa o efeito Main da carta
            return self.execute(card, 'main')[0] if self.execute(card, 'main') else ''

        # ── Draw ──────────────────────────────────────────────────────────────
        if action == 'draw':
            count = step.get('count', 1)
            drawn = []
            for _ in range(count):
                if me.deck:
                    c = me.deck.pop()
                    me.hand.append(c)
                    drawn.append(c.name[:12])
            # then_trash após draw
            then_trash = step.get('then_trash', 0)
            trashed_after = []
            for _ in range(then_trash):
                worst = self._choose_to_trash(me.hand)
                if worst:
                    me.hand.remove(worst)
                    me.trash.append(worst)
                    trashed_after.append(worst.name[:12])
            if not drawn:
                return ''
            msg = f'comprou: {", ".join(drawn)}'
            if trashed_after:
                msg += f' (e trashou: {", ".join(trashed_after)})'
            return msg

        # ── KO ───────────────────────────────────────────────────────────────
        if action in ('ko', 'trash_character'):
            # 'trash_character' usa a MESMA mecanica de remocao de campo que
            # 'ko' (vai para o trash do dono). A diferenca de regra real do
            # jogo -- K.O. dispara o gatilho [On K.O.] do alvo, Trash de
            # personagem NAO dispara -- ainda nao tem efeito aqui porque o
            # engine hoje so dispara on_ko por morte em BATALHA (ver
            # _resolve_battle), nunca por efeito de carta de nenhum dos dois
            # tipos. Quando essa cascata for implementada para efeitos de
            # carta, ela deve checar `action == 'ko'` antes de disparar.
            count = step.get('count', 1)
            target_type = step.get('target', 'opp_character')
            cost_lte = step.get('cost_lte')
            cost_eq = step.get('cost_eq')
            power_lte = step.get('power_lte')
            filter_type = step.get('filter_type', '').lower()
            rested_only = step.get('rested_only', False)

            if target_type == 'opp_stage':
                if opp.field_stage and (cost_lte is None or opp.field_stage.cost <= cost_lte):
                    ko_name = opp.field_stage.name[:20]
                    opp.trash.append(opp.field_stage)
                    opp.field_stage = None
                    return f'KO stage: {ko_name}'
                return ''

            def elegivel(c):
                if cost_lte is not None and c.cost > cost_lte:
                    return False
                if cost_eq is not None and c.cost != cost_eq:
                    return False
                if power_lte is not None and c.power > power_lte:
                    return False
                if rested_only and not c.rested:
                    return False
                if filter_type and filter_type not in c.sub_types.lower() and filter_type not in c.card_type.lower():
                    return False
                return True

            # KO personagem(s) -- opp_character (so do oponente) ou
            # all_character (ambos os lados, ex: board wipe simetrico).
            if target_type == 'all_character':
                pools = [(opp, [c for c in opp.field_chars if elegivel(c)]),
                         (me, [c for c in me.field_chars if elegivel(c)])]
            else:
                pools = [(opp, [c for c in opp.field_chars if elegivel(c)])]

            koed = []
            sub_logs = []
            for owner, candidates in pools:
                for _ in range(min(count, len(candidates))):
                    target = max(candidates, key=lambda x: x.board_value())
                    # Antes de remover de fato, verifica se o ALVO tem
                    # substitute_ko/substitute_removal ativo -- e um efeito
                    # passivo do proprio target, avaliado do ponto de vista
                    # do SEU dono (quem paga o custo da substituicao).
                    ee_target = EffectExecutor(owner, me if owner is opp else opp)
                    sub_log = ee_target.try_substitute(target, 'ko' if action == 'ko' else 'removal')
                    if sub_log:
                        sub_logs.append(sub_log)
                        candidates.remove(target)
                        continue
                    owner.field_chars.remove(target)
                    owner.trash.append(target)
                    candidates.remove(target)
                    koed.append(target.name[:15])
            label = 'KO' if action == 'ko' else 'Trash'
            partes = []
            if koed:
                partes.append(f'{label}: {", ".join(koed)}')
            partes.extend(sub_logs)
            return ' | '.join(partes)

        # ── Bounce ───────────────────────────────────────────────────────────
        if action == 'bounce':
            count = step.get('count', 1)
            cost_lte = step.get('cost_lte', 99)

            candidates = [c for c in opp.field_chars if c.cost <= cost_lte]
            bounced = []
            for _ in range(min(count, len(candidates))):
                target = max(candidates, key=lambda x: x.board_value())
                opp.field_chars.remove(target)
                opp.hand.append(target)
                target.rested = False
                target.don_attached = 0
                candidates.remove(target)
                bounced.append(target.name[:15])
            return f'bounce: {", ".join(bounced)}' if bounced else ''

        # ── Restar oponente ───────────────────────────────────────────────────
        if action == 'rest_opp_character':
            count = step.get('count', 1)
            cost_lte = step.get('cost_lte', 99)

            candidates = [c for c in opp.field_chars
                          if not c.rested and c.cost <= cost_lte and not c.cannot_be_rested_until]
            rested = []
            for _ in range(min(count, len(candidates))):
                target = max(candidates, key=lambda x: x.board_value())
                target.rested = True
                candidates.remove(target)
                rested.append(target.name[:15])
            return f'restou: {", ".join(rested)}' if rested else ''

        # ── Trava de ataque / trava de rest ─────────────────────────────────────
        # Mecanicas DISTINTAS apesar de compartilharem estrutura de
        # implementacao: lock_opp_character_attack impede ATACAR;
        # lock_opp_cannot_be_rested impede o character de ficar RESTED por
        # qualquer meio (atacar, bloquear, ou efeito). Nunca tratar como
        # sinonimos -- confirmado por Arthur.
        if action in ('lock_opp_character_attack', 'lock_opp_cannot_be_rested'):
            count = step.get('count', 1)
            cost_lte = step.get('cost_lte')
            exclude = step.get('exclude', '').lower()
            DUR_MAP = {
                'until_opp_turn_end': 'opp_turn_end',
                'until_opp_end_phase': 'opp_end_phase',
                'until_my_next_turn_start': 'my_next_turn_start',
            }
            dur = DUR_MAP.get(step.get('duration', 'until_opp_turn_end'), 'opp_turn_end')

            candidates = [c for c in opp.field_chars
                          if (cost_lte is None or c.cost <= cost_lte)
                          and (not exclude or exclude not in c.name.lower())]

            locked = []
            for _ in range(min(count, len(candidates))):
                target = max(candidates, key=lambda x: x.board_value())
                if action == 'lock_opp_character_attack':
                    target.cannot_attack_until = dur
                else:
                    target.cannot_be_rested_until = dur
                candidates.remove(target)
                locked.append(target.name[:15])
            verbo = 'atacar' if action == 'lock_opp_character_attack' else 'ficar rested'
            return f'travou (não pode {verbo}): {", ".join(locked)}' if locked else ''

        # ── Trava de ataque condicional a pagamento ─────────────────────────────
        # DISTINTA de lock_opp_character_attack: aqui o character do oponente
        # PODE atacar, mas o oponente paga um custo (ex: trash N cards) a cada
        # ataque enquanto a trava estiver ativa. Decidir se "vale a pena pagar"
        # e uma decisao de Opponent Reading (fase ainda pausada/pendente no
        # TODO.md), nao um efeito imediato deterministico. Por ora o step e
        # apenas reconhecido (nao falha, nao e ignorado silenciosamente) mas
        # NAO trava nem cobra nada -- nunca reaproveitar cannot_attack_until
        # aqui, pois isso mentiria sobre a mecanica (carta unica no banco ate
        # esta auditoria: OP08-043 Edward.Newgate).
        if action == 'lock_opp_attack_unless_pays':
            return '(lock_opp_attack_unless_pays: nao implementado -- pendente fase Opponent Reading)'

        # ── Trava de Refresh Phase (nao fica ativo no proximo refresh) ─────────
        # lock_opp_character_refresh / lock_opp_don_refresh: trava o character
        # ou DON do OPONENTE de virar active na proxima Refresh Phase dele.
        # lock_self_character_refresh: trava o PROPRIO character (geralmente
        # custo de um efeito forte do jogador) -- alvo OPOSTO dos dois
        # anteriores, nunca tratar como sinonimo. As 3 ainda nao tem logica de
        # refresh implementada no engine (refresh_phase nao consome esses
        # campos hoje); reconhecidas aqui para nao falhar silenciosamente,
        # mas pendente de implementacao real.
        if action in ('lock_opp_character_refresh', 'lock_opp_don_refresh', 'lock_self_character_refresh'):
            return f'({action}: nao implementado -- pendente logica de Refresh Phase)'

        # ── Substituicao de power base (set_base_power) ─────────────────────────
        # Mecanica DISTINTA de buff_power/debuff_power: 'base power becomes N'
        # substitui o valor (ignora buffs aditivos anteriores aplicados sobre a
        # base), nao soma. Implementar corretamente exige alterar
        # effective_power() para usar um override em vez de self.power -- isso
        # afeta TODO calculo de ataque/bloqueio existente, entao a mudanca fica
        # pendente para uma sessao dedicada em vez de uma alteracao isolada e
        # nao calibrada aqui. target pode ser 'leader', 'self',
        # 'own_character', ou 'leader_or_own_character' (alvo ambiguo,
        # escolha do jogador entre Leader OU Character -- tambem pendente).
        # 8 cards no banco (ex: OP15-092 Monkey.D.Luffy, EB04-003/004).
        if action == 'set_base_power':
            return '(set_base_power: nao implementado -- pendente alteracao calibrada de effective_power)'

        # ── Self-lock de ataque (incondicional / condicional / em massa) ────────
        # Implementar de verdade exige adicionar um campo booleano novo na
        # classe Card e inclui-lo em TODOS os pontos que ja checam
        # 'not c.cannot_attack_until' como filtro de "pode atacar" (6 pontos
        # neste arquivo: my_attack_power, _count_available_attacks,
        # planejamento de ataques, refresh, etc.) -- mudanca de escopo maior
        # que uma alteracao isolada aqui justificaria. Reconhecidas sem
        # travar nada ainda (cannot_attack_self: 3 cards; unless: 2 cards;
        # mass-lock condicional: 1 carta -- P-084).
        if action in ('cannot_attack_self', 'cannot_attack_self_unless', 'cannot_attack_own_characters_by_cost'):
            return f'({action}: nao implementado -- pendente integracao nos pontos de checagem de ataque)'

        # ── Power buff ────────────────────────────────────────────────────────
        if action == 'buff_power':
            amount = step.get('amount', 0)
            target = step.get('target', 'self')
            duration = step.get('duration', 'this_turn')

            if target == 'self':
                card.power_buff += amount
            elif target == 'leader':
                me.leader.power_buff += amount
            elif target == 'leader_or_character':
                # IA escolhe o mais forte
                best = max(me.field_chars + [me.leader],
                           key=lambda c: c.effective_power(True)) if me.field_chars else me.leader
                best.power_buff += amount
            elif target in ('all_allies', 'all_allies_and_leader'):
                for c in me.field_chars:
                    c.power_buff += amount
                if target == 'all_allies_and_leader':
                    me.leader.power_buff += amount
            return f'+{amount} power em {target}'

        # ── Cost buff/debuff (buff_cost / debuff_cost) ──────────────────────────
        # NOTA DE LIMITACAO: assim como buff_power, o sistema geral de turnos
        # ainda nao distingue 'until_opp_turn_end' de 'this_turn' -- ambos sao
        # resetados no mesmo ciclo (apply_your_turn_buffs/reset_your_turn_buffs).
        # duration='permanent' (ex: condicionado a leader_type, sem prazo) usa
        # cost_buff_permanent, que nunca e resetado por esses dois pontos.
        if action in ('buff_cost', 'debuff_cost'):
            amount = step.get('amount', 0)
            if action == 'debuff_cost':
                amount = -amount
            target = step.get('target', 'self')
            duration = step.get('duration', 'this_turn')
            count = step.get('count', 1)
            filter_type = step.get('filter_type', '').lower()
            color = step.get('color', '').lower()
            cost_gte = step.get('cost_gte')

            campo_alvo = me if target in ('self', 'own_character') else opp
            if target == 'self':
                candidatos = [card]
            else:
                candidatos = list(campo_alvo.field_chars)
                if filter_type:
                    candidatos = [c for c in candidatos if filter_type in c.sub_types.lower()]
                if color:
                    candidatos = [c for c in candidatos if color in c.color.lower()]
                if cost_gte is not None:
                    candidatos = [c for c in candidatos if c.cost >= cost_gte]

            afetados = []
            for c in candidatos[:count]:
                if duration == 'permanent':
                    c.cost_buff_permanent += amount
                else:
                    c.cost_buff += amount
                afetados.append(c.name[:15])
            sinal = '+' if amount >= 0 else ''
            return f'{sinal}{amount} cost em {", ".join(afetados)}' if afetados else ''

        # ── Give DON ──────────────────────────────────────────────────────────
        if action == 'give_don':
            count = step.get('count', 1)
            rested = step.get('rested', False)
            # Dá DON ao personagem mais forte ativo
            targets = [c for c in me.field_chars if not c.rested] + [me.leader]
            if targets:
                best = max(targets, key=lambda c: c.effective_power(True))
                best.don_attached += count
                # Debita do banco de DON real (don_rested + don_available),
                # nunca de uma fonte gratuita externa -- ambos os tipos vêm
                # do mesmo banco do jogador.
                if rested:
                    # "give up to N RESTED DON" -- exige especificamente DON
                    # rested do banco. Se não houver o suficiente, usa o que
                    # tiver (parcial) -- a IA não inventa DON.
                    do_rested = min(count, me.don_rested)
                    me.don_rested -= do_rested
                else:
                    # "give up to N DON" (sem qualificador) -- a IA escolhe.
                    # Prioriza DON rested primeiro (preserva don_available
                    # ativo para outras jogadas no mesmo turno); se não
                    # houver rested suficiente, completa com don_available.
                    do_rested = min(count, me.don_rested)
                    me.don_rested -= do_rested
                    restante = count - do_rested
                    if restante > 0:
                        do_available = min(restante, me.don_available)
                        me.don_available -= do_available
            return f'+{count} DON'

        # ── Give DON ao oponente (controle/setup) ───────────────────────────────
        # Mecanica distinta de give_don: o DON sai do BANCO DO OPONENTE (nao do
        # meu), e e anexado a um Character do OPONENTE. Geralmente usado para
        # travar o refresh dele depois (ex: combinado com lock_opp_don /
        # lock_opp_character_refresh), nao para dar vantagem ao oponente.
        if action == 'give_don_opp':
            count = step.get('count', 1)
            rested = step.get('rested', False)

            targets_opp = [c for c in opp.field_chars] + [opp.leader]
            if targets_opp:
                best = max(targets_opp, key=lambda c: c.effective_power(True))
                best.don_attached += count
                if rested:
                    do_rested = min(count, opp.don_rested)
                    opp.don_rested -= do_rested
                else:
                    # sem qualificador / "from cost area" -- usa o banco
                    # ativo do oponente primeiro (e o DON que ele "gastou"
                    # no turno, fica no cost area), completando com rested
                    # se nao houver ativo suficiente.
                    do_available = min(count, opp.don_available)
                    opp.don_available -= do_available
                    restante = count - do_available
                    if restante > 0:
                        do_rested = min(restante, opp.don_rested)
                        opp.don_rested -= do_rested
            return f'deu {count} DON ao character do oponente'

        # ── Play from trash ───────────────────────────────────────────────────
        if action == 'play_from_trash':
            filter_type = step.get('filter_type', '').lower()
            filter_name = step.get('filter_name', '').lower()
            cost_lte = step.get('cost_lte')
            cost_eq = step.get('cost_eq')
            power_eq = step.get('power_eq')
            power_lte = step.get('power_lte')
            count = step.get('count', 1)
            enters_rested = step.get('rested', False)
            distinct_names = step.get('distinct_names', False)

            # filter_self: recupera a SI MESMO do trash (ex: substituicao de
            # remocao por auto-K.O. seguida de replay). Nao usa o pool geral
            # de candidatos, e sim a propria carta que acabou de ir ao trash.
            if step.get('filter_self'):
                self_card = next((c for c in me.trash if c.code == card.code), None)
                if self_card:
                    me.trash.remove(self_card)
                    self_card.rested = enters_rested
                    if self_card.card_type == 'STAGE':
                        if me.field_stage:
                            me.trash.append(me.field_stage)
                        me.field_stage = self_card
                    else:
                        self_card.just_played = not (self_card.has_rush or self_card.is_rush_character())
                        self_card.rush_character_only_this_turn = self_card.is_rush_character() and not self_card.is_rush()
                        me.field_chars.append(self_card)
                    return f'jogou do trash (self): {self_card.name[:15]}'
                return ''

            candidates = []
            for c in me.trash:
                if cost_lte is not None and c.cost > cost_lte:
                    continue
                if cost_eq is not None and c.cost != cost_eq:
                    continue
                if power_eq is not None and c.power != power_eq:
                    continue
                if power_lte is not None and c.power > power_lte:
                    continue
                if filter_type:
                    match = (filter_type in c.sub_types.lower() or
                             filter_type in c.name.lower() or
                             filter_type in c.card_type.lower())
                    if not match:
                        continue
                if filter_name and filter_name not in c.name.lower():
                    continue
                candidates.append(c)

            played = []
            played_names_lower = set()
            for _ in range(min(count, len(candidates))):
                pool = candidates
                if distinct_names:
                    pool = [c for c in candidates if c.name.lower() not in played_names_lower]
                if not pool:
                    break
                if any(c.card_type == 'STAGE' for c in pool):
                    best = max((c for c in pool if c.card_type == 'STAGE'), key=lambda x: x.cost)
                else:
                    best = max(pool, key=lambda x: x.board_value())

                me.trash.remove(best)
                best.rested = enters_rested
                if best.card_type == 'STAGE':
                    if me.field_stage:
                        me.trash.append(me.field_stage)
                    me.field_stage = best
                else:
                    if len(me.field_chars) >= 5:
                        worst = min(me.field_chars, key=lambda x: x.board_value())
                        me.field_chars.remove(worst)
                        me.trash.append(worst)
                    best.just_played = not (best.has_rush or best.is_rush_character())
                    best.rush_character_only_this_turn = best.is_rush_character() and not best.is_rush()
                    me.field_chars.append(best)

                played.append(best.name[:15])
                played_names_lower.add(best.name.lower())
                candidates.remove(best)

            return f'jogou do trash: {", ".join(played)}' if played else ''

        # ── Play from deck ────────────────────────────────────────────────────
        if action == 'play_from_deck':
            filter_type = step.get('filter_type', '').lower()
            cost_lte = step.get('cost_lte', 99)
            color = step.get('color', '')
            count = step.get('count', 1)

            # Se precedido de 'look_top_deck' (padrao "look at N cards from
            # the top of your deck; play up to 1 [filtro]"), restringe a
            # busca as N cartas do topo, igual a add_to_hand -- sem isto, a
            # IA "veria" o deck inteiro para escolher a melhor carta, o que
            # nao e a regra real (so as N cartas reveladas pelo look estao
            # disponiveis) e tambem nao embaralharia o deck no final (regra
            # de "look E play" deixa o resto no topo/fundo conforme o texto,
            # nao embaralha -- distinto do "play a card from anywhere in
            # your deck", que de fato revela o deck inteiro e embaralha).
            effects = get_card_effects(card.code)
            look_count = None
            for trigger, ef in effects.items():
                for s in ef.get('steps', []):
                    if s.get('action') == 'look_top_deck':
                        look_count = s.get('count')
                        break
                if look_count:
                    break

            if look_count:
                look = min(look_count, len(me.deck))
                pool = me.deck[-look:]
            else:
                pool = me.deck

            candidates = []
            for c in pool:
                if c.cost > cost_lte:
                    continue
                if color and color.lower() not in c.color.lower():
                    continue
                if filter_type:
                    match = (filter_type in c.sub_types.lower() or
                             filter_type in c.name.lower())
                    if not match:
                        continue
                candidates.append(c)

            played = []
            for _ in range(min(count, len(candidates))):
                best = max(candidates, key=lambda x: x.board_value())
                me.deck.remove(best)
                if len(me.field_chars) >= 5:
                    worst = min(me.field_chars, key=lambda x: x.board_value())
                    me.field_chars.remove(worst)
                    me.trash.append(worst)
                best.just_played = not (best.has_rush or best.is_rush_character())
                best.rush_character_only_this_turn = best.is_rush_character() and not best.is_rush()
                me.field_chars.append(best)
                candidates.remove(best)
                played.append(best.name[:15])

            if not look_count:
                # so embaralha quando a busca expos o deck inteiro -- o
                # padrao "look at N; play" deixa o resto das N cartas vistas
                # para o step seguinte (trash_rest/deck_bottom_rest/etc)
                # tratar, sem tocar no resto do deck.
                random.shuffle(me.deck)
            return f'jogou do deck: {", ".join(played)}' if played else ''

        # ── Trash from hand ───────────────────────────────────────────────────
        if action == 'trash_from_hand':
            count = step.get('count', 1)
            trashed = []
            for _ in range(min(count, len(me.hand))):
                worst = self._choose_to_trash(me.hand)
                if worst:
                    me.hand.remove(worst)
                    me.trash.append(worst)
                    trashed.append(worst.name[:12])
            return f'descartou da mão: {", ".join(trashed)}' if trashed else ''

        # ── Trash from hand FORCADO no oponente (disrupcao de mao) ──────────────
        # Distinto de trash_from_hand: alvo e a mao do OPONENTE, nao a minha.
        # E um efeito DETERMINISTICO (sempre acontece, sem "se o oponente
        # quiser") -- a unica decisao real e QUAL carta ele descarta, e isso
        # reaproveita a mesma heuristica de _choose_to_trash (menor valor de
        # board) aplicada na mao dele. Simplificacao assumida: nao modela
        # blefe/retencao estrategica do oponente, so "descarta o que tem
        # menos valor para o lado que esta descartando" -- aproximacao
        # razoavel e nao tendenciosa para nenhum dos lados, mas e uma
        # simplificacao real, nao a decisao otima do oponente.
        if action == 'opp_trash_from_hand':
            count = step.get('count', 1)
            trashed = []
            for _ in range(min(count, len(opp.hand))):
                worst = self._choose_to_trash(opp.hand)
                if worst:
                    opp.hand.remove(worst)
                    opp.trash.append(worst)
                    trashed.append(worst.name[:12])
            return f'oponente descartou: {", ".join(trashed)}' if trashed else ''

        # ── Heal ─────────────────────────────────────────────────────────────
        if action == 'heal':
            count = step.get('count', 1)
            for _ in range(min(count, len(me.deck))):
                c = me.deck.pop(0)
                me.life.append(c)
            return f'+{count} vida(s)'

        # ── Add from trash ────────────────────────────────────────────────────
        if action == 'add_from_trash':
            filter_name = step.get('filter_name', '').lower()
            count = step.get('count', 1)
            found = [c for c in me.trash
                     if filter_name in c.name.lower() or filter_name in c.code.lower()]
            added = []
            for c in found[:count]:
                me.trash.remove(c)
                me.hand.append(c)
                added.append(c.name[:15])
            return f'recuperou do trash: {", ".join(added)}' if added else ''

        # ── Keywords ──────────────────────────────────────────────────────────
        if action == 'gain_rush':
            card.has_rush = True
            return 'ganhou Rush'
        if action == 'gain_rush_character':
            card.has_rush_character = True
            # Se o character ja esta em campo (efeito concedido mid-jogo, nao
            # no momento em que entrou), a restricao de alvo so importa se
            # ele ainda nao atacou neste turno -- aproxima usando just_played
            # como sinal de 'ainda no turno em que pode usar a permissao'.
            # Quando concedido no proprio turno em que e jogado (ex:
            # EB04-007 via Activate:Main apos o On Play), marca a janela.
            card.rush_character_only_this_turn = not card.has_rush
            return 'ganhou Rush: Character'
        if action == 'gain_blocker':
            card.has_blocker = True
            return 'ganhou Blocker'
        if action == 'gain_double_attack':
            card.has_double_attack = True
            return 'ganhou Double Attack'
        if action == 'gain_banish':
            card.has_banish = True
            return 'ganhou Banish'
        if action == 'gain_unblockable':
            card.has_unblockable = True
            return 'ganhou Unblockable'

        # Keywords passivas (apenas registra, já vem do banco)
        if action in ('keyword_blocker', 'keyword_rush', 'keyword_double_attack',
                      'keyword_banish', 'keyword_trigger', 'keyword_unblockable'):
            return ''

        return ''

    # ── Helpers de IA ────────────────────────────────────────────────────────

    def _choose_to_trash(self, hand: list) -> Optional[Card]:
        """Escolhe a carta de menor valor para descartar."""
        if not hand:
            return None
        # Descarta eventos sem trigger primeiro, depois por menor custo
        events = [c for c in hand if c.card_type == 'EVENT' and not c.has_trigger]
        if events:
            return min(events, key=lambda c: c.cost)
        return min(hand, key=lambda c: c.board_value())


# ===========================================================================
# Carregamento de dados
# ===========================================================================

def parse_card_effects_basic(text: str, counter_amount: str) -> dict:
    """Parser básico de keywords para cartas sem entrada no banco."""
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
        'counter':           c_val,
    }


def load_cards_db(csv_path: str = 'cards_rows.csv') -> dict:
    db = {}
    try:
        df = pd.read_csv(csv_path)
        for col in ['card_cost', 'card_power', 'life']:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
        for col in ['card_set_id', 'card_name', 'card_color', 'card_type',
                    'card_text', 'counter_amount', 'sub_types']:
            df[col] = df[col].fillna('').astype(str)

        for _, row in df.iterrows():
            code = row['card_set_id'].split('_')[0]
            if not code or code == 'nan':
                continue
            kws = parse_card_effects_basic(row['card_text'], row['counter_amount'])
            db[code] = {
                'name':      row['card_name'],
                'color':     row['card_color'],
                'type':      row['card_type'].upper(),
                'cost':      int(row['card_cost']),
                'power':     int(row['card_power']),
                'life':      int(row['life']),
                'text':      row['card_text'],
                'sub_types': row['sub_types'],
                **kws,
            }
        print(f'  Banco de cartas: {len(db)} cartas carregadas')
    except Exception as e:
        print(f'  Erro ao carregar {csv_path}: {e}')
    return db


def validar_deck(leader: Card, cards: list, cards_db: dict) -> tuple:
    from collections import Counter
    erros = []
    if len(cards) != 50:
        erros.append(f'Total: {len(cards)} (deve ser 50)')
    contagem = Counter(c.code for c in cards)
    for code, qty in contagem.items():
        if qty > 4:
            erros.append(f'{code}: {qty} copias (max 4)')
    return len(erros) == 0, erros


def _make_card(code: str, data: dict) -> Card:
    """Cria Card a partir do banco de dados, usando o effects_db para keywords."""
    effects = get_card_effects(code)

    # Keywords do banco ou do parse básico
    has_blocker      = data.get('has_blocker', False)
    has_rush         = data.get('has_rush', False)
    has_rush_character = data.get('has_rush_character', False)
    has_double_attack= data.get('has_double_attack', False)
    has_banish       = data.get('has_banish', False)
    has_trigger      = data.get('has_trigger', False)
    has_unblockable  = data.get('has_unblockable', False)

    # Enriquece com o banco de efeitos
    if 'passive' in effects:
        for step in effects['passive'].get('steps', []):
            a = step.get('action', '')
            if a == 'keyword_blocker':      has_blocker = True
            elif a == 'keyword_rush':       has_rush = True
            elif a == 'keyword_rush_character': has_rush_character = True
            elif a == 'keyword_double_attack': has_double_attack = True
            elif a == 'keyword_banish':     has_banish = True
            elif a == 'keyword_trigger':    has_trigger = True
            elif a == 'keyword_unblockable': has_unblockable = True

    # Keywords CONDICIONAIS a [DON!! ×N]: só valem com N DON anexados.
    # Guardadas em dict {keyword: don_req}; a Card decide na hora se está ativa.
    don_cond_keywords = {}
    if 'don_conditional_keywords' in effects:
        for step in effects['don_conditional_keywords'].get('steps', []):
            a = step.get('action', '')
            req = step.get('don_requirement', 1)
            kw = a.replace('keyword_', '')
            don_cond_keywords[kw] = req

    # Campos extras detectados pelo banco ou pelo texto
    t = data.get('text', '').lower()
    is_searcher   = ('look at' in t or 'search your deck' in t or 'add up to' in t)
    has_start_of_game = 'at the start of the game' in t
    has_on_play_ko = 'on play' in t and ('k.o.' in t or 'trash' in t) and 'draw' not in t
    has_bounce    = 'return' in t and 'hand' in t
    has_rest_effect = 'rest' in t and 'opponent' in t
    has_power_minus = '-' in t and 'power' in t and 'opponent' in t
    trash_opp_char = 'opponent' in t and ('trash' in t or 'k.o.' in t) and 'on play' in t

    import re as _re
    raw_draw = (t.count('draw 1') + t.count('draw 2') * 2 +
                t.count('draw 3') * 3 + t.count('draw a card'))
    draw_then_trash = 0
    draw_condition  = 'always'
    m = _re.search(r'draw\s+(\d)\s+cards?.*?trash\s+(\d)\s+card', t)
    if m:
        raw_draw = int(m.group(1))
        draw_then_trash = int(m.group(2))
        lm = _re.search(r'if you have\s+(\d+)\s+or less life', t)
        if lm:
            draw_condition = f'life<={lm.group(1)}'

    return Card(
        code=code,
        name=data.get('name', code),
        card_type=data.get('type', 'CHARACTER'),
        color=data.get('color', ''),
        cost=data.get('cost', 0),
        power=data.get('power', 0),
        counter=data.get('counter', 0),
        life=data.get('life', 0),
        sub_types=data.get('sub_types', ''),
        attribute=data.get('attribute', ''),
        card_text=data.get('text', ''),
        has_rush=has_rush,
        has_rush_character=has_rush_character,
        has_blocker=has_blocker,
        has_double_attack=has_double_attack,
        has_banish=has_banish,
        has_trigger=has_trigger,
        has_unblockable=has_unblockable,
        don_cond_keywords=don_cond_keywords,
        is_searcher=is_searcher,
        draw_power=raw_draw,
        draw_then_trash=draw_then_trash,
        draw_condition=draw_condition,
        has_on_play_ko=has_on_play_ko,
        has_bounce=has_bounce,
        has_rest_effect=has_rest_effect,
        has_start_of_game=has_start_of_game,
        has_power_minus=has_power_minus,
        trash_opp_char=trash_opp_char,
    )


def build_real_deck(deck_name: str, deck_url: str,
                    df_raw: pd.DataFrame, cards_db: dict) -> Optional[tuple]:
    rows = df_raw[df_raw['deck_url'] == deck_url]
    if rows.empty:
        return None

    leader = None
    cards  = []

    for _, row in rows.iterrows():
        code = str(row['card_code'])
        qty  = int(row['qty'])
        data = cards_db.get(code, {})
        if not data:
            continue

        card = _make_card(code, data)

        if card.card_type == 'LEADER':
            leader = card
        else:
            for _ in range(qty):
                cards.append(deepcopy(card))

    if leader is None:
        leader = Card(code='UNK', name=deck_name, card_type='LEADER',
                      color='', power=5000, life=5)

    return leader, cards, None  # start_stage detectada no setup


# ===========================================================================
# DecisionEngine — IA de decisão
# ===========================================================================


# ============================================================================
# NOVO DecisionEngine — Análise probabilística completa
# Substitui a classe DecisionEngine no decision_engine.py
# ============================================================================

class GameAnalyzer:
    """
    Analisador de estado do jogo — calcula probabilidades e avalia posições.
    Usado pelo DecisionEngine para tomar decisões informadas.
    """

    def __init__(self, me: 'GameState', opp: 'GameState'):
        self.me  = me
        self.opp = opp

    # ── Análise do deck (perfil early/mid/late) ──────────────────────────────

    def deck_profile(self) -> str:
        """
        Determina se o deck é early, mid ou late game
        baseado na curva de custo das cartas no campo e mão.
        """
        all_cards = self.me.field_chars + self.me.hand
        if not all_cards:
            return 'mid'
        avg_cost = sum(c.cost for c in all_cards) / len(all_cards)
        if avg_cost <= 2.5:   return 'early'
        elif avg_cost <= 5.0: return 'mid'
        else:                 return 'late'

    def game_phase(self) -> str:
        """
        FASE DA PARTIDA pelos DON na mesa (documento pág. 3):
        Early (0-4 DON), Mid (5-8), Late (9-10).
        É o MOMENTO da partida, não o tipo do deck.
        """
        don_total = self.me.don_available + self.me.don_rested
        if don_total <= 4:   return 'early'
        elif don_total <= 8: return 'mid'
        else:                return 'late'

    def deck_profile_type(self) -> str:
        """
        PERFIL do deck (aggressive/control/midrange) a partir do censo do deck
        completo. Diferente de deck_profile() (que é por curva de mão+campo).
        Usa o deck guardado em me.full_deck_census (setado no setup).
        """
        census = getattr(self.me, 'full_deck_census', None)
        if not census:
            return 'midrange'  # sem censo, neutro
        from optcg_engine.deck_census import deck_profile as classify
        return classify(census)['profile']

    # ── Potencial ofensivo ───────────────────────────────────────────────────

    def my_attack_power(self) -> int:
        """Poder total de ataque disponível (sem DON)."""
        total = self.me.leader.effective_power(True) if not self.me.leader.rested else 0
        for c in self.me.field_chars:
            if (not c.rested and not c.just_played and not c.cannot_attack_until
                    and not c.cannot_be_rested_until and not is_attack_locked_self(c, self.me, self.opp)):
                total += c.effective_power(True)
        return total

    def my_available_don(self) -> int:
        return self.me.don_available

    def max_don_boost(self) -> int:
        """Máximo de boost de poder com DON disponível."""
        return self.me.don_available * 1000

    # ── Potencial defensivo do oponente ──────────────────────────────────────

    def opp_counter_potential(self) -> int:
        """
        Potencial máximo de counter do oponente.
        Cada carta na mão pode ter counter de 1000 ou 2000.
        Estimativa: média de 1000 por carta na mão.
        """
        hand_size = len(self.opp.hand)
        # Estima baseado em proporção típica de counters em decks
        # ~40% das cartas têm counter 1000, ~20% têm counter 2000
        estimated_1k = int(hand_size * 0.4)
        estimated_2k = int(hand_size * 0.2)
        return estimated_1k * 1000 + estimated_2k * 2000

    def opp_counter_in_hand(self) -> int:
        """Counter real do oponente (se visível — normalmente 0 em simulação)."""
        return self.opp.counter_in_hand()

    def opp_has_active_don_for_events(self) -> bool:
        """Oponente tem DON para ativar eventos de defesa?"""
        return self.opp.don_available >= 1

    def opp_blocker_count(self) -> int:
        """Quantos blockers ativos o oponente tem."""
        return len(self.opp.blockers_active())

    def opp_attack_count(self) -> int:
        """Quantos personagens o oponente pode atacar no próximo turno."""
        count = sum(1 for c in self.opp.field_chars if not c.rested)
        if not self.opp.leader.rested:
            count += 1
        return count

    # ── Probabilidades de vida ───────────────────────────────────────────────

    def prob_trigger_in_opp_life(self) -> float:
        """
        Probabilidade de trigger na vida do oponente.
        Baseado na proporção típica de triggers em decks competitivos (~20-30%).
        """
        if self.opp.life_count() == 0:
            return 0.0
        # Estima ~25% de chance de trigger por carta de vida
        return min(0.25 * self.opp.life_count(), 0.85)

    def prob_counter_in_opp_life(self) -> float:
        """
        Probabilidade de counter (+1000 ou +2000) na vida do oponente.
        Estima ~35% das cartas têm counter em decks típicos.
        """
        if self.opp.life_count() == 0:
            return 0.0
        return min(0.35, 0.35 * self.opp.life_count())

    def prob_trigger_in_my_life(self) -> float:
        """Probabilidade de trigger na minha vida."""
        if self.me.life_count() == 0:
            return 0.0
        return min(0.25 * self.me.life_count(), 0.85)

    def prob_counter_in_my_life(self) -> float:
        """Probabilidade de counter na minha vida."""
        if self.me.life_count() == 0:
            return 0.0
        return min(0.35, 0.35 * self.me.life_count())

    # ── Análise de lethality ─────────────────────────────────────────────────

    def can_lethal_this_turn(self) -> bool:
        """
        Posso GARANTIR a vitória neste turno, mesmo no pior caso de defesa do
        oponente (ele escolhe livremente blocker/counter por ataque, na ordem
        que mais o favorece)?

        Antes, esta funcao so contava NUMERO de ataques >= vida+1, ignorando
        poder/blocker/counter -- superestimava lethal contra qualquer
        oponente com blocker ou counter na mao. Agora simula o pior caso real:
          1. Lista os poderes de ataque disponiveis (com DON ja anexado via
             effective_power); double attack conta como 2 hits do MESMO poder
             (e o MESMO ataque -- um unico Blocker ou Counter resolve os 2
             hits dele, nao 2 blockers/counters separados).
          2. Ataques [Unblockable] NUNCA podem ser bloqueados -- sempre vao
             direto pro Leader.
          3. Os blocker do oponente (N ativos) desviam ate N ataques
             BLOQUEAVEIS -- ele escolhe bloquear os de MAIOR poder primeiro
             (sao os mais caros/dificeis de cobrir so com counter), pior caso
             pra mim.
          4. O que sobra (nao bloqueado) precisa ser coberto por counter da
             MAO REAL do oponente (nao estimativa -- a simulacao conhece a
             mao do oponente do outro lado). Sobrevive ao ataque de poder P
             se consegue somar counter total >= P - leader_power + 1.
             Distribui os counters da mao greedy: cobre primeiro os ataques
             que precisam de MENOS counter (maximiza quantos ataques
             sobrevive com o estoque de counter que tem).
          5. Lethal garantido = mesmo nessa defesa otima do oponente, a vida
             dele chega a 0 E ainda resta pelo menos 1 hit que conecta
             (regra: receber dano com 0 vidas = derrota).
        """
        opp_life = self.opp.life_count()
        leader_power = self.opp.leader.effective_power(False)

        # Ataques disponiveis: (poder, eh_unblockable, hits) -- double attack
        # e 1 ataque so (1 blocker/counter resolve os 2 hits), mas conta 2
        # hits de dano se conectar.
        ataques = []
        if not self.me.leader.rested and not is_attack_locked_self(self.me.leader, self.me, self.opp):
            ataques.append((self.me.leader.effective_power(True), self.me.leader.has_unblockable, 1))
        for c in self.me.field_chars:
            if (not c.rested and not c.just_played and not c.cannot_attack_until
                    and not c.cannot_be_rested_until and not is_attack_locked_self(c, self.me, self.opp)):
                hits = 2 if c.is_double_attack() else 1
                ataques.append((c.effective_power(True), c.has_unblockable, hits))

        if not ataques:
            return False  # sem atacantes disponiveis, nunca fecha o jogo

        unblockable = [a for a in ataques if a[1]]
        bloqueaveis = sorted([a for a in ataques if not a[1]], key=lambda a: -a[0])  # maior poder primeiro

        n_blockers = len(self.opp.blockers_active())
        # Oponente bloqueia os N bloqueaveis de MAIOR poder (pior caso pra mim)
        bloqueados = bloqueaveis[:n_blockers]
        nao_bloqueados = bloqueaveis[n_blockers:]

        candidatos_dano = unblockable + nao_bloqueados  # estes podem conectar (sujeitos a counter)

        if not candidatos_dano:
            return False  # tudo que sobrou foi bloqueado, nada chega na vida/leader

        # Counters disponiveis na mao REAL do oponente (conhecida na simulacao,
        # nao estimada -- distinto de max_plausible_defense, usado quando a
        # mao do oponente NAO e observavel).
        counters_disponiveis = sorted(
            [c.counter for c in self.opp.hand if c.counter > 0]
        )

        # Greedy: cobre primeiro os ataques que precisam de MENOS counter
        # (maximiza quantos ataques o oponente sobrevive com o estoque que
        # tem) -- pior caso pra mim, melhor defesa pra ele.
        candidatos_dano_ordenados = sorted(candidatos_dano, key=lambda a: a[0])
        sobrou_counters = list(counters_disponiveis)
        conecta = []
        for power, is_unblockable, hits in candidatos_dano_ordenados:
            necessario = power - leader_power + 1
            # necessario = quanto de counter o oponente precisa somar para a
            # defesa (leader_power + counter) IGUALAR ou SUPERAR o ataque.
            # necessario <= 0 significa power < leader_power -- o ataque NAO
            # tem poder suficiente para conectar mesmo SEM nenhum counter
            # (regra do jogo: conecta apenas se atk_power >= defend_power) --
            # logo nao conecta, e nao consome counter nenhum do oponente.
            if necessario <= 0:
                continue  # nao conecta, counters do oponente ficam intactos
            # tenta cobrir 'necessario' somando counters disponiveis (do menor
            # pro maior, gastando o minimo de cartas possivel)
            soma = 0
            usados = []
            for ctr in sobrou_counters:
                if soma >= necessario:
                    break
                soma += ctr
                usados.append(ctr)
            if soma >= necessario:
                for u in usados:
                    sobrou_counters.remove(u)
                # sobreviveu -- nao conecta
            else:
                conecta.append((power, hits))  # nao deu pra cobrir -- conecta

        hits_que_conectam = sum(h for _, h in conecta)

        if opp_life > 0:
            return hits_que_conectam >= opp_life + 1
        else:
            return hits_que_conectam >= 1

    def _count_available_attacks(self) -> int:
        """Conta ataques disponíveis incluindo double attack."""
        count = 0
        if not self.me.leader.rested:
            count += 1
        for c in self.me.field_chars:
            if (not c.rested and not c.just_played and not c.cannot_attack_until
                    and not c.cannot_be_rested_until and not is_attack_locked_self(c, self.me, self.opp)):
                count += 2 if c.is_double_attack() else 1
        return count

    def opp_can_survive_lethal(self) -> float:
        """
        Probabilidade do oponente sobreviver a uma tentativa de letal.
        Considera: blockers, counters na mão, triggers na vida.
        """
        prob_survive = 0.0

        # Blockers podem desviar ataques
        if self.opp_blocker_count() > 0:
            prob_survive += 0.3

        # Counters na mão podem aumentar o poder de defesa
        if len(self.opp.hand) >= 3:
            prob_survive += 0.2

        # Triggers podem ativar efeitos de defesa
        prob_survive += self.prob_trigger_in_opp_life() * 0.3

        return min(prob_survive, 0.9)

    # ── Análise de defesa ────────────────────────────────────────────────────

    def opp_lethal_threat(self) -> float:
        """
        Probabilidade do oponente me finalizar no próximo turno.
        Considera atacantes, DON disponível, minha vida.
        """
        opp_attacks = self.opp_attack_count()
        my_life = self.me.life_count()
        my_blockers = len(self.me.blockers_active())
        my_counter  = self.me.counter_in_hand()

        if opp_attacks == 0:
            return 0.0

        # Oponente precisa de (my_life + 1) hits para me finalizar
        hits_needed = my_life + 1
        available_hits = opp_attacks

        if available_hits < hits_needed:
            return 0.0

        # Chance base
        prob = max(0.0, (available_hits - hits_needed + 1) / max(available_hits, 1))

        # Meus blockers reduzem a ameaça
        prob *= max(0.1, 1.0 - my_blockers * 0.2)

        # Meus counters reduzem a ameaça
        if my_counter >= 2000:
            prob *= 0.7
        elif my_counter >= 1000:
            prob *= 0.85

        return min(prob, 0.95)

    # ── Vale a pena salvar um personagem? ────────────────────────────────────

    def char_value_score(self, card: 'Card') -> float:
        """
        Valor de um personagem para a partida.
        Usado para decidir se vale gastar blocker/counter para salvar.
        """
        score = card.board_value() * 10.0

        effects = get_card_effects(card.code)

        # Tem efeito ativável que ainda não usou
        if 'activate_main' in effects:
            score += 20

        # Tem efeito de ataque
        if 'when_attacking' in effects:
            score += 15

        # É um blocker valioso
        if card.has_blocker and self.me.life_count() <= 2:
            score += 30

        # Tem double attack
        if card.has_double_attack:
            score += 20

        return score

    # ── Análise do campo ─────────────────────────────────────────────────────

    def field_advantage(self) -> float:
        """
        Vantagem de campo: positivo = eu estou na frente.
        Considera poder total, quantidade de cartas e efeitos.
        """
        my_score  = sum(c.board_value() for c in self.me.field_chars)
        opp_score = sum(c.board_value() for c in self.opp.field_chars)
        return my_score - opp_score

    def critical_threats(self) -> list:
        """
        Identifica AMEAÇAS CRÍTICAS no board do oponente (documento nível 3).
        Uma carta é ameaça crítica se:
        - poder alto (>= 6000), OU
        - tem efeito perigoso (gera vantagem recorrente, blocker que trava ataque),
        - (a ameaça de lethal é tratada à parte por opp_lethal_threat).
        Retorna a lista de cartas-ameaça, da mais perigosa para a menos.
        """
        ameacas = []
        for c in self.opp.field_chars:
            peso = 0
            if c.power >= 6000:           peso += 3
            elif c.power >= 5000:         peso += 1
            if c.has_blocker:             peso += 2   # trava meu ataque
            effects = get_card_effects(c.code)
            if 'activate_main' in effects: peso += 2   # vantagem recorrente
            if 'when_attacking' in effects: peso += 2
            if c.has_double_attack:       peso += 2
            if c.has_rush:                peso += 1
            if peso >= 3:
                ameacas.append((peso, c))
        ameacas.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in ameacas]

    def analysis_priority(self) -> str:
        """
        PRIORIDADE DE ANÁLISE (documento) — cascata de INCLINAÇÃO.
        Retorna o modo dominante deste momento. A ordem é respeitada (o nível
        mais alto satisfeito comanda), mas é inclinação, não bloqueio: o loop
        de pontuação ainda considera o contexto, com pesos ajustados por este modo.

        1. LETHAL      — posso vencer neste turno (sempre vence, topo)
        2. DEFENSIVE   — posso morrer no próximo turno (e não tenho lethal)
        3. REMOVE_THREAT — existe ameaça crítica no board
        4. DEVELOP     — posso/devo desenvolver board
        5. ATTACK      — atacar líder (padrão)
        """
        if self.can_lethal_this_turn():
            return 'LETHAL'
        if self.opp_lethal_threat() > 0.6:
            return 'DEFENSIVE'
        if self.critical_threats():
            return 'REMOVE_THREAT'
        # desenvolver cedo / sem pressão; senão, atacar
        don_total = self.me.don_available + self.me.don_rested
        if don_total <= 4 and self.me.hand:
            return 'DEVELOP'
        return 'ATTACK'

    def should_clear_field(self) -> bool:
        """
        Vale a pena limpar o campo do oponente?
        Sim se oponente tem cartas com efeitos importantes ou muitos atacantes.
        """
        opp_threats = 0
        for c in self.opp.field_chars:
            effects = get_card_effects(c.code)
            if any(t in effects for t in ('activate_main', 'when_attacking', 'on_ko')):
                opp_threats += 2
            else:
                opp_threats += 1
        return opp_threats >= 3 or self.opp_attack_count() >= 3


class DecisionEngine:
    """
    Motor de decisão com análise probabilística completa.

    Toma decisões baseado em:
    - Perfil do deck (early/mid/late)
    - Análise de lethality (posso finalizar? oponente pode me finalizar?)
    - Distribuição ótima de DON
    - Ordem de ataque estratégica
    - Decisões de defesa (blocker vs counter)
    - Gerenciamento de mão e DON reservado
    """

    def __init__(self, me: 'GameState', opp: 'GameState'):
        self.me   = me
        self.opp  = opp
        self.analyzer = GameAnalyzer(me, opp)

    # ── Postura ──────────────────────────────────────────────────────────────

    def posture(self) -> str:
        """
        Postura do turno = PERFIL do deck (aggressive/control/midrange) +
        FASE da partida (early/mid/late pelos DON), conforme o documento.

        - Prioridades absolutas primeiro (lethal / evitar derrota).
        - Depois o PERFIL comanda:
          * aggressive: pressiona em todas as fases (busca dano cedo)
          * control: segue a fase (early desenvolve, mid controla, late finaliza)
          * midrange: equilíbrio pela fase
        """
        a = self.analyzer
        profile = a.deck_profile_type()   # aggressive / control / midrange
        phase   = a.game_phase()          # early / mid / late (pelos DON)
        my_life  = self.me.life_count()
        opp_life = self.opp.life_count()

        # ── Prioridades absolutas (independem de perfil/fase) ──
        if a.can_lethal_this_turn():
            return 'LETHAL'
        if a.opp_lethal_threat() > 0.6:
            return 'DEFENSIVE'

        # ── Perfil AGRESSIVO: pressiona em todas as fases ──
        # (deck de curva baixa com rush/buff ataca a vida desde cedo)
        if profile == 'aggressive':
            if my_life <= 1 and a.field_advantage() < 0:
                return 'DEFENSIVE'      # só recua se realmente prestes a morrer
            return 'AGGRESSIVE'

        # ── Perfil CONTROLE: segue o padrão das fases ──
        if profile == 'control':
            if phase == 'early':
                # desenvolver e preservar (board > dano)
                if opp_life <= 1: return 'AGGRESSIVE'
                return 'DEVELOP'
            if phase == 'mid':
                # disputar board, eliminar ameaças
                if my_life <= 1: return 'DEFENSIVE'
                if a.field_advantage() < -2: return 'CONTROL'
                if opp_life <= 2: return 'AGGRESSIVE'
                return 'CONTROL'
            # late: buscar letal / finalizar
            if my_life <= 2 and a.field_advantage() < 0: return 'DEFENSIVE'
            return 'AGGRESSIVE'

        # ── Perfil MIDRANGE: equilíbrio pela fase ──
        if opp_life <= 1:   return 'AGGRESSIVE'
        if my_life <= 1:    return 'DEFENSIVE'
        if phase == 'early':
            if a.field_advantage() < -2: return 'CONTROL'
            return 'DEVELOP'
        if phase == 'mid':
            if a.field_advantage() < -3: return 'CONTROL'
            if opp_life <= 2: return 'AGGRESSIVE'
            return 'MIDRANGE'
        # late
        return 'AGGRESSIVE'

    # ── Avaliação de cartas ──────────────────────────────────────────────────

    def avaliar_carta(self, card: 'Card') -> float:
        """Avalia o valor situacional de uma carta para jogar/guardar/descartar."""
        a       = self.analyzer
        posture = self.posture()
        s       = 0.0
        my_life  = self.me.life_count()
        opp_life = self.opp.life_count()
        don_now  = self.me.don_available

        # Jogabilidade imediata
        if card.cost <= don_now:       s += 40
        elif card.cost <= don_now + 2: s += 20
        else:                          s -= 15

        s += card.power / 1000 * 5

        # Keywords
        if card.has_rush:
            v = 30
            if opp_life <= 2: v += 50
            if opp_life == 0: v += 100
            s += v

        if card.has_double_attack:
            s += 25
            if opp_life <= 2: s += 35

        if card.has_unblockable:
            s += 20
            if opp_life <= 2: s += 30

        if card.has_banish:
            s += 15

        if card.has_blocker:
            v = 20
            if my_life <= 1:   v += 100
            elif my_life <= 2: v += 60
            elif my_life <= 3: v += 30
            if a.opp_attack_count() >= 3: v += 20
            s += v

        if card.counter > 0:
            v = card.counter / 1000 * 15
            if my_life <= 1: v *= 4.0
            elif my_life <= 2: v *= 2.5
            elif my_life <= 3: v *= 1.5
            # Penaliza se já tem muitos counters na mão
            counters_em_mao = sum(1 for c in self.me.hand
                                  if c.counter > 0 and c is not card)
            if counters_em_mao >= 4: v *= 0.4
            elif counters_em_mao >= 2: v *= 0.7
            s += v

        if card.has_trigger:
            s += 10

        # Efeitos do banco
        effects = get_card_effects(card.code)
        has_draw   = any('draw' in str(e) for e in effects.values())
        has_search = any('look_top_deck' in str(e) for e in effects.values())
        has_ko     = any('ko' in str(e) for e in effects.values())
        has_bounce = any('bounce' in str(e) for e in effects.values())
        has_rest   = any('rest_opp_character' in str(e) for e in effects.values())

        if has_draw:   s += 25 + (10 if len(self.me.hand) <= 3 else 0)
        if has_search: s += 30 + (15 if self.me.turn <= 3 else 0)
        if has_ko:
            s += 35
            if a.field_advantage() < 0: s += 25
        if has_bounce:
            s += 20
            if a.field_advantage() < 0: s += 15
        if has_rest:
            # Restar abre personagens para ataque
            if a.should_clear_field(): s += 20
            else: s += 10

        # Ajuste por postura
        if posture == 'LETHAL':
            if card.has_rush:          s += 50
            if card.has_double_attack: s += 40
            if card.has_unblockable:   s += 30
        elif posture == 'AGGRESSIVE':
            if card.has_rush:          s += 30
            if card.has_double_attack: s += 20
            if card.counter > 0:       s -= 10
        elif posture == 'DEFENSIVE':
            if card.has_blocker:       s += 50
            if card.counter > 0:       s += 25
            if card.has_rush:          s -= 15
        elif posture == 'CONTROL':
            if has_ko:     s += 30
            if has_bounce: s += 20
            if has_rest:   s += 15
        elif posture == 'DEVELOP':
            if has_search: s += 25
            if has_draw:   s += 20

        return s

    # ── Escolher carta para jogar ─────────────────────────────────────────────

    def _effect_conditions_met(self, card) -> bool:
        """
        Verifica se as condições do efeito principal da carta estão satisfeitas
        no estado ATUAL. Evita jogar carta cujo efeito condicional não vai ativar
        (ex: Otama com 'life_lte:3' jogada com 4 vidas).

        Retorna True se não há condições, ou se as condições batem.
        """
        effects = get_card_effects(card.code)
        # pega o gatilho principal (on_play / main / activate_main)
        main_trig = None
        for t in ('on_play', 'main', 'activate_main'):
            if t in effects:
                main_trig = effects[t]
                break
        if not main_trig:
            return True  # sem efeito principal — sem condição a checar

        conds = main_trig.get('conditions', {})
        if not conds:
            return True

        me = self.me
        my_life  = me.life_count()
        my_hand  = len(me.hand)
        my_don   = me.don_available
        my_trash = len(me.trash)
        my_chars = len(me.field_chars)
        leader_types = set(str(getattr(me.leader, 'sub_types', '')).lower().split())

        for k, v in conds.items():
            if k == 'life_lte'  and not (my_life  <= v): return False
            if k == 'life_gte'  and not (my_life  >= v): return False
            if k == 'hand_lte'  and not (my_hand  <= v): return False
            if k == 'hand_gte'  and not (my_hand  >= v): return False
            if k == 'don_gte'   and not (my_don   >= v): return False
            if k == 'don_on_field_gte' and not ((my_don + me.don_rested) >= v): return False
            if k == 'trash_gte' and not (my_trash >= v): return False
            if k == 'events_in_trash_gte':
                n_events = sum(1 for c in me.trash if c.card_type.lower() == 'event')
                if not (n_events >= v): return False
            if k == 'leader_power_lte':
                if not (me.leader.effective_power(True) <= v): return False
            if k in ('board_has_cost', 'board_has_cost_gte'):
                todos = list(me.field_chars) + list(self.opp.field_chars)
                exatos = set(conds.get('board_has_cost', []))
                gte = conds.get('board_has_cost_gte')
                if not any(c.cost in exatos or (gte is not None and c.cost >= gte)
                           for c in todos):
                    return False
            if k == 'chars_gte':
                cost_filter = conds.get('chars_gte_cost_filter')
                contagem = (sum(1 for c in me.field_chars if c.cost >= cost_filter)
                            if cost_filter is not None else my_chars)
                if not (contagem >= v): return False
            if k == 'leader_type':
                if str(v).lower() not in ' '.join(leader_types): return False
            if k == 'leader_is':
                if str(v).lower() not in str(getattr(me.leader, 'name', '')).lower(): return False
        return True

    def _can_play_card(self, card) -> bool:
        """Decide se uma carta é jogável agora (mesma regra do choose_card_to_play)."""
        if card.card_type not in ('CHARACTER', 'EVENT', 'STAGE'):
            return False
        don_reserve = self._don_reserve_for_defense()
        don_usable  = max(0, self.me.don_available - don_reserve)
        if card.cost > don_usable:
            return False
        if '[counter]' in card.card_text.lower() and card.card_type == 'EVENT':
            return False
        effects = get_card_effects(card.code)
        has_main = any(t in effects for t in ('on_play', 'main', 'activate_main'))
        if card.card_type == 'EVENT' and not has_main:
            return False
        if not self._effect_conditions_met(card):
            vale_pelo_corpo = (card.card_type == 'CHARACTER' and card.power >= 5000)
            if not vale_pelo_corpo:
                return False
        return True

    def choose_card_to_play(self) -> 'Optional[Card]':
        """
        Escolhe a melhor carta para jogar considerando:
        - DON que vai sobrar depois
        - Necessidade de reservar DON para defesa/efeitos
        - Se as condições do efeito da carta estão satisfeitas
        - Postura atual
        """
        a = self.analyzer

        # Quanto DON reservar para defesa
        don_reserve = self._don_reserve_for_defense()
        don_usable  = max(0, self.me.don_available - don_reserve)

        playable = []
        for c in self.me.hand:
            if c.card_type not in ('CHARACTER', 'EVENT', 'STAGE'):
                continue
            if c.cost > don_usable:
                continue
            # Não joga Counter como carta normal
            if '[counter]' in c.card_text.lower() and c.card_type == 'EVENT':
                continue
            # Eventos sem efeito main/on_play não devem ser jogados
            effects = get_card_effects(c.code)
            has_main = any(t in effects for t in ('on_play', 'main', 'activate_main'))
            if c.card_type == 'EVENT' and not has_main:
                continue
            # NÃO joga carta cujo efeito condicional não vai ativar.
            # Exceção: CHARACTER com poder relevante vale pelo corpo mesmo sem efeito.
            if not self._effect_conditions_met(c):
                vale_pelo_corpo = (c.card_type == 'CHARACTER' and c.power >= 5000)
                if not vale_pelo_corpo:
                    continue
            playable.append(c)

        if not playable:
            return None
        return max(playable, key=self.avaliar_carta)

    def _don_reserve_for_defense(self) -> int:
        """
        Quantos DON reservar para defesa no turno do oponente.
        Decisão baseada na ANÁLISE DE RISCO (regra do usuário):
        - Em PERIGO (pouca vida, ameaça alta, pouco counter na mão, ou tenho
          evento counter que preciso deixar DON em pé para usar) -> reserva mais.
        - SEGURO (muito counter na mão, blockers, vida alta, sem risco de perder
          no próximo turno) -> reserva pouco/nada, força ataque.
        """
        a = self.analyzer
        my_life = self.me.life_count()
        threat  = a.opp_lethal_threat()
        don_disp = self.me.don_available

        # Recursos defensivos que JÁ tenho na mão/campo
        counters_mao = sum(1 for c in self.me.hand if getattr(c, 'counter', 0) >= 1000)
        eventos_counter = sum(1 for c in self.me.hand
                              if c.card_type == 'EVENT' and '[counter]' in c.card_text.lower())
        blockers = len(self.me.blockers_active())

        # ── Estou SEGURO? muito counter + blocker + vida ok + sem ameaça ──
        seguro = (counters_mao >= 3 and my_life >= 3 and threat < 0.4) or \
                 (blockers >= 2 and my_life >= 4 and threat < 0.4)
        if seguro:
            return 0   # força ataque, não precisa guardar DON

        # ── Estou em PERIGO? reserva conforme a gravidade ──
        reserva = 0
        if threat > 0.7:        reserva = 3
        elif threat > 0.4:      reserva = 2
        elif my_life <= 2:      reserva = 2
        elif my_life <= 3:      reserva = 1

        # Tenho evento counter mas POUCO counter de mão? vale deixar DON p/ o evento
        if eventos_counter >= 1 and counters_mao <= 1 and my_life <= 3:
            reserva = max(reserva, 1)

        # Pouco counter na mão aumenta o risco de não conseguir defender
        if counters_mao == 0 and my_life <= 3:
            reserva = max(reserva, 1)

        return min(reserva, don_disp)

    # ── Distribuição de DON ───────────────────────────────────────────────────

    def plan_don_distribution(self, attackers: list) -> dict:
        """
        Planeja a distribuição ótima de DON entre os atacantes.

        Retorna dict: {card: don_amount}

        Lógica:
        1. Se pode finalizar — concentra DON no atacante mais forte
        2. Se deve limpar campo — distribui para atingir cartas inimigas
        3. Senão — distribui para maximizar dano na vida respeitando counters
        """
        a = self.analyzer
        don_available = self.me.don_available
        result = {id(att): 0 for att in attackers}
        _att_map = {id(att): att for att in attackers}

        if don_available <= 0 or not attackers:
            return result

        # Estima defesa do oponente
        opp_leader_power = self.opp.leader.power
        estimated_counter = a.opp_counter_potential()

        # ── Modo LETHAL: concentra no mais forte ─────────────────────────────
        if a.can_lethal_this_turn() or self.posture() == 'LETHAL':
            # Ordena: mais forte primeiro
            sorted_atk = sorted(attackers,
                                 key=lambda c: c.effective_power(True),
                                 reverse=True)
            # Concentra no atacante principal
            main_atk = sorted_atk[0]
            result[id(main_atk)] = don_available
            return result

        # ── Modo CLEAR FIELD: distribui para restar/destruir cartas ──────────
        if a.should_clear_field() and self.opp.rested_chars():
            targets = sorted(self.opp.rested_chars(),
                             key=lambda c: c.power)
            don_left = don_available
            for att in attackers:
                if don_left <= 0:
                    break
                # Quanto DON precisa para superar o alvo mais fraco?
                if targets:
                    target_power = targets[0].power
                    att_base = att.effective_power(True)
                    don_needed = max(0, (target_power - att_base + 1000) // 1000)
                    don_give   = min(don_needed, don_left)
                    result[id(att)] = don_give
                    don_left -= don_give
                    if don_give >= don_needed and targets:
                        targets.pop(0)
            return result

        # ── Modo NORMAL: distribui para superar defesa do líder ──────────────
        # Ordena atacantes: mais fraco primeiro (gasta counters do oponente)
        sorted_atk = sorted(attackers,
                             key=lambda c: c.effective_power(True))

        don_left = don_available
        # Distribui DON para o atacante mais forte superar a defesa estimada
        if sorted_atk:
            strong_atk = sorted_atk[-1]  # mais forte
            needed = max(0, (opp_leader_power + 1000 - strong_atk.effective_power(True)) // 1000)
            don_give = min(needed, don_left)
            result[id(strong_atk)] += don_give
            don_left -= don_give

        # DON restante vai para o segundo mais forte — SÓ se o ataque tiver
        # chance de passar. Não desperdiça DON num ataque que não supera a
        # defesa nem com o DON (ex: personagem 2000 + 2 DON = 4000 < líder 5000).
        if don_left > 0 and len(sorted_atk) >= 2:
            second_atk = sorted_atk[-2]
            second_power = second_atk.effective_power(True)
            # com o DON restante, esse ataque chega a quanto?
            reachable = second_power + don_left * 1000
            # alvo mínimo viável: superar o líder (ou um personagem restado fraco)
            min_target = opp_leader_power
            rested = self.opp.rested_chars()
            if rested:
                min_target = min(min_target, min(c.power for c in rested))
            # só anexa se o ataque puder ALCANÇAR o alvo (senão é desperdício)
            if reachable >= min_target:
                # anexa só o necessário para alcançar, não todo o resto
                needed2 = max(0, (min_target - second_power + 999) // 1000)
                result[id(second_atk)] += min(needed2, don_left)
            # se não alcança nem com tudo, não anexa (deixa DON livre)
        return result

    # ── Ordem e escolha de ataques ────────────────────────────────────────────

    def plan_attacks(self, attackers: list) -> list:
        """
        Planeja a ordem ótima de ataques.

        Retorna lista de (attacker, target_type, target) em ordem de execução.

        Lógica:
        1. Cartas com When Attacking têm prioridade
        2. Mais fraco primeiro (gasta counters/blockers do oponente)
        3. Mais forte por último (no alvo mais importante)
        4. Se pode finalizar, concentra todos no líder
        """
        a = self.analyzer
        plan = []

        if not attackers:
            return plan

        # Separa: cartas com when_attacking vs normais
        when_atk = []
        normal   = []
        for att in attackers:
            effects = get_card_effects(att.code)
            if 'when_attacking' in effects:
                when_atk.append(att)
            else:
                normal.append(att)

        # ── Modo LETHAL: todos atacam o líder (que tenham chance) ────────────
        if a.can_lethal_this_turn():
            # Mais fraco primeiro para gastar counters, mais forte por último
            all_atk = sorted(attackers, key=lambda c: c.effective_power(True))
            for att in all_atk:
                # mesmo no lethal, não inclui ataque que não passa nem ativa nada
                if self.score_attack_target(att, 'leader', None) > -500:
                    plan.append((att, 'leader', None))
            return plan

        # ── Modo CLEAR FIELD: ataca cartas restadas ──────────────────────────
        rested_targets = sorted(self.opp.rested_chars(),
                                key=lambda c: c.board_value(), reverse=True)

        if a.should_clear_field() and rested_targets:
            # When attacking primeiro
            for att in when_atk:
                if rested_targets:
                    plan.append((att, 'character', rested_targets[0]))
                    rested_targets = rested_targets[1:]
                else:
                    plan.append((att, 'leader', None))

            # Mais fracos atacam cartas restadas primeiro
            weak_first = sorted(normal, key=lambda c: c.effective_power(True))
            for att in weak_first:
                if rested_targets:
                    target = rested_targets[0]
                    if att.effective_power(True) >= target.power:
                        plan.append((att, 'character', target))
                        rested_targets = rested_targets[1:]
                    else:
                        plan.append((att, 'leader', None))
                else:
                    plan.append((att, 'leader', None))
            return plan

        # ── Modo NORMAL: mix de ataques ───────────────────────────────────────
        # When attacking primeiro (aproveitam o efeito)
        for att in when_atk:
            plan.append((att, 'leader', None))

        # Mais fracos atacam a vida primeiro (gastam counters do oponente)
        sorted_normal = sorted(normal, key=lambda c: c.effective_power(True))
        for att in sorted_normal:
            # Avalia se ataque na vida ou em personagem restado
            best_score = self.score_attack_target(att, 'leader', None)
            best_action = (att, 'leader', None)

            for t in self.opp.rested_chars():
                s = self.score_attack_target(att, 'character', t)
                if s > best_score:
                    best_score = s
                    best_action = (att, 'character', t)

            if best_score > -500:
                plan.append(best_action)

        return plan

    def _rest_activates_effect(self, card) -> bool:
        """
        Decide se restar este personagem (atacando) ativa um efeito útil,
        justificando o ataque mesmo sem chance de passar.

        Verdadeiro quando:
        - tem [When Attacking] (o ato de atacar dispara o efeito), OU
        - tem efeito [Your Turn]/[Opponent's Turn] que depende de estar restado
          (ex: Shanks — restado dá -1000 a todos os personagens do oponente).
        """
        effects = get_card_effects(card.code)
        if 'when_attacking' in effects:
            return True
        # efeitos que se beneficiam de estar restado
        txt = (card.card_text or '').lower()
        if ('when this character becomes rested' in txt or
                'if this character is rested' in txt or
                'while this character is rested' in txt):
            return True
        return False

    def score_attack_target(self, attacker: 'Card',
                             target_type: str,
                             target: 'Optional[Card]') -> float:
        """
        Pontua um alvo de ataque levando em conta múltiplos fatores.
        """
        a = self.analyzer
        s = 0.0
        opp_life  = self.opp.life_count()
        atk_power = attacker.effective_power(True)

        # Custo de restar um atacante que tem [Activate: Main] útil:
        # atacar com ele perde o efeito do turno. Desconta, salvo letal/ameaça grande.
        activate_cost = self._activate_main_value(attacker)

        if target_type == 'leader':
            atk_power = attacker.effective_power(True)
            don_disp  = self.me.don_available
            leader_power = self.opp.leader.power

            # REGRA DURA (validada com o usuário):
            # Ataque ao líder só vale se:
            #  (a) poder do atacante >= poder-base do líder (passa sem DON), OU
            #  (b) poder + DON disponível >= poder-base do líder (passa com DON), OU
            #  (c) restar o personagem ativa um efeito útil (When Attacking, ou
            #      efeito Your Turn/Opp Turn que depende de estar restado).
            passa_sem_don = atk_power >= leader_power
            passa_com_don = (atk_power + don_disp * 1000) >= leader_power
            vale_restar   = self._rest_activates_effect(attacker)

            if not (passa_sem_don or passa_com_don or vale_restar):
                return -999  # ataque inútil: não passa e não ativa nada — barra

            # Pontua os ataques válidos
            s = 100
            if opp_life == 1:  s = 500
            if opp_life == 0:  s = 10000

            # Bônus se restar ativa efeito (vale mesmo sem dano)
            if vale_restar and not passa_sem_don:
                s = max(s, 80)

            # Penaliza levemente se precisa de muito DON (mas ainda é válido)
            opp_defense = leader_power + a.opp_counter_potential()
            if atk_power < opp_defense and not passa_sem_don:
                s -= 10

            # Unblockable: o ataque não pode ser bloqueado. Vale mais quando o
            # oponente tem blockers (passa onde os outros seriam interceptados).
            if attacker.has_unblockable and self.opp.blockers_active():
                s += 40

            # Custo de perder o Activate Main: desconta, salvo se for letal
            if activate_cost > 0 and opp_life > 1:
                s -= activate_cost
            return s

        elif target_type == 'character' and target:
            don_disp = self.me.don_available
            # REGRA DURA (mesma do líder, validada com o usuário):
            # só ataca personagem se:
            #  (a) poder >= poder do alvo (mata sem DON), OU
            #  (b) poder + DON disponível >= poder do alvo (mata com DON), OU
            #  (c) restar o atacante ativa efeito útil.
            passa_sem_don = atk_power >= target.power
            passa_com_don = (atk_power + don_disp * 1000) >= target.power
            vale_restar   = self._rest_activates_effect(attacker)

            if not (passa_sem_don or passa_com_don or vale_restar):
                return -999   # não mata e não ativa nada — barra

            # Valor do alvo (quão importante é removê-lo)
            s = target.board_value() * 15

            # Alvo COM EFEITO vale matar mesmo com poder baixo/0 (regra do usuário)
            tgt_effects = get_card_effects(target.code)
            tem_efeito_alvo = any(t in tgt_effects for t in
                                  ('on_play', 'activate_main', 'when_attacking',
                                   'blocker', 'on_ko', 'your_turn', 'opp_turn'))
            if tem_efeito_alvo and target.power <= 2000:
                s += 50   # remover utilidade do oponente vale, apesar do poder baixo

            # Alvo cujo efeito AMEAÇA (pune no turno do oponente, ativa vantagem
            # recorrente, ou bloqueia): remover nega a ameaça futura. Vale mais.
            efeito_ameaca = any(t in tgt_effects for t in
                                ('opp_turn', 'activate_main', 'blocker'))
            if efeito_ameaca:
                s += 70   # negar ameaça futura do oponente

            # Prioriza ameaças (ordem de prioridade de alvos do documento)
            if target.has_double_attack:  s += 50
            if target.has_rush:           s += 40
            if target.has_blocker:        s += 60
            if 'when_attacking' in tgt_effects: s += 35
            if 'activate_main' in tgt_effects:  s += 25
            if 'on_ko' in tgt_effects:          s -= 20  # cuidado: ativa ao morrer

            # Bônus se restar ativa efeito (vale mesmo sem matar)
            if vale_restar and not passa_sem_don:
                s = max(s, 60)

            # Custo de perder o Activate Main do ATACANTE: só compensa se o alvo
            # é ameaça grande (poder alto, blocker, rush, gera vantagem).
            ameaca_grande = (target.power >= 5000 or target.has_blocker or
                             target.has_rush or target.has_double_attack)
            if activate_cost > 0 and not ameaca_grande:
                s -= activate_cost

            return s

        return s

    def _activate_main_value(self, card) -> float:
        """
        Valor do efeito [Activate: Main] de um personagem — o "custo" de restá-lo
        atacando (perde o efeito do turno). 0 se não tem efeito ativável OU se a
        condição do efeito NÃO está satisfeita agora (não há o que preservar:
        regra do usuário — se não pode ativar, ataca normalmente).
        """
        effects = get_card_effects(card.code)
        am = effects.get('activate_main')
        if not am:
            return 0.0
        # Se o efeito não pode ativar agora (condição não satisfeita), não há
        # nada a preservar — custo zero, a IA pode atacar com ela.
        if not self._effect_conditions_met(card):
            return 0.0
        # Respeita once_per_turn: se já usou, não há efeito a preservar neste turno
        if am.get('once_per_turn') and getattr(card, '_am_used_turn', -1) == self.me.turn:
            return 0.0
        steps = am.get('steps', [])
        actions = [s.get('action') for s in steps]
        if any(x in ('draw', 'look_top_deck', 'add_to_hand') for x in actions):
            return 70.0
        return 40.0

    # ── Decisões de defesa ────────────────────────────────────────────────────

    def should_use_blocker(self, attacker_power: int) -> 'Optional[Card]':
        """
        Decide se usa blocker e qual usar.

        Fatores:
        - Valor da minha vida (poucos = mais defensivo)
        - Probabilidade de trigger na vida
        - Valor do personagem que está sendo atacado vs valor do blocker
        """
        a = self.analyzer
        my_life = self.me.life_count()

        # Com muita vida, não usa blocker
        if my_life > 4:
            return None

        blockers = self.me.blockers_active()
        if not blockers:
            return None

        # Analisa se vale usar blocker
        # Quanto mais baixa a vida, mais agressivo na defesa
        use_threshold = {5: False, 4: False, 3: True, 2: True, 1: True}
        if not use_threshold.get(my_life, True):
            return None

        # Com 1-2 vidas, sempre usa blocker se tiver
        if my_life <= 2:
            return min(blockers, key=lambda c: a.char_value_score(c))

        # Com 3 vidas, usa se o atacante é forte
        if my_life == 3 and attacker_power >= self.me.leader.power:
            return min(blockers, key=lambda c: a.char_value_score(c))

        return None

    def should_use_counter(self, atk_power: int, def_power: int) -> bool:
        """
        Decide se usa counter considerando:
        - Vida atual
        - Quantidade de counters na mão
        - Probabilidade de precisar de counters no próximo ataque
        - DON ativo para ativar eventos
        """
        a = self.analyzer
        my_life       = self.me.life_count()
        counter_avail = self.me.counter_in_hand()

        if counter_avail == 0:
            return False
        if atk_power < def_power:
            return False  # defesa já suficiente

        needed = atk_power - def_power + 1

        # Com 1 vida — sempre usa counter se tiver
        if my_life <= 1:
            return counter_avail >= needed

        # Com 2 vidas — usa se tem counter suficiente
        if my_life <= 2:
            return counter_avail >= needed

        # Com 3 vidas — usa só se o ataque é sério
        if my_life <= 3:
            return counter_avail >= needed and needed <= 2000

        # Com 4+ vidas — conserva counters para situações críticas
        if my_life <= 4:
            return needed <= 1000 and counter_avail >= needed * 2

        return False

    def use_counter(self, needed: int) -> int:
        """
        Usa o mínimo de counter necessário.
        Prefere usar counters de menor valor primeiro para conservar os maiores.
        """
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

    # ── Helpers ───────────────────────────────────────────────────────────────

    def choose_to_trash(self, hand: list) -> 'Optional[Card]':
        """Escolhe a carta de menor valor situacional para descartar."""
        if not hand:
            return None
        return min(hand, key=self.avaliar_carta)



# ===========================================================================
# OPTCGMatch — motor de partida
# Baseado no fluxo de turno das 34k linhas
# ===========================================================================

class OPTCGMatch:
    MAX_TURNS = 15

    def __init__(self, deck_a: tuple, deck_b: tuple):
        leader_a, cards_a, stage_a = deck_a if len(deck_a) == 3 else (*deck_a, None)
        leader_b, cards_b, stage_b = deck_b if len(deck_b) == 3 else (*deck_b, None)

        self.state_a = GameState(leader=deepcopy(leader_a),
                                 deck=[deepcopy(c) for c in cards_a])
        self.state_b = GameState(leader=deepcopy(leader_b),
                                 deck=[deepcopy(c) for c in cards_b])

        if random.random() < 0.5:
            self.state_a.is_first = True
            self.state_b.is_first = False
        else:
            self.state_a.is_first = False
            self.state_b.is_first = True

        self.global_turn = 0

    def _distribute_don(self, p: GameState, engine: 'DecisionEngine'):
        """
        Distribui DON disponível antes dos ataques.
        Baseado no AttachDon das 34k linhas.
        IA: dá DON ao atacante mais forte que ainda não atacou.
        """
        if p.don_available <= 0:
            return

        opp = self.state_b if p is self.state_a else self.state_a

        # Candidatos: personagens ativos + líder
        candidates = [c for c in p.field_chars
                      if not c.rested and not c.just_played and not c.cannot_attack_until
                      and not c.cannot_be_rested_until and not is_attack_locked_self(c, p, opp)]
        if not p.leader.rested:
            candidates.append(p.leader)

        if not candidates:
            return

        # Distribui DON ao mais forte (maximiza poder de ataque)
        best = max(candidates, key=lambda c: c.effective_power(True))
        don_to_give = p.don_available
        best.don_attached += don_to_give
        p.don_available -= don_to_give

    # ── Setup (CheckStartOfGameActions das 34k linhas) ───────────────────────

    def _place_start_stage(self, p: GameState):
        """
        Detecta e coloca stage inicial em campo.
        Baseado em CheckStartOfGameActions (proc.StartOfGame) das 34k linhas.
        """
        if not p.leader.card_text:
            return

        t = p.leader.card_text.lower()
        if 'at the start of the game' not in t:
            return

        # Extrai tipo de stage mencionado
        m = re.search(r'start of the game[^.]*play.*?\[([^\]]+)\].*?stage', t)
        wanted = m.group(1).lower() if m else None

        candidates = [c for c in p.deck if c.card_type == 'STAGE'
                      and (not wanted or wanted in c.sub_types.lower()
                           or wanted in c.name.lower())]

        if candidates:
            # Prefere a de maior custo (The Empty Throne > Mary Geoise)
            best = max(candidates, key=lambda c: c.cost)
            p.deck.remove(best)
            p.field_stage = best

    def _mulligan_decision(self, hand, deck=None) -> tuple:
        """
        Decide mulligan seguindo o documento (pág. 2) e as regras do usuário.

        Avalia (contagem simples — sinais bons vs ruins):
        - Jogada para T1/T2/T3: consigo aproveitar o DON de cada turno com as
          cartas baratas da mão? (não é 1 carta — é gastar o DON do turno)
        - Trigger demais na mão: relativo a quantos o deck tem (triggers valem
          mais na vida; ter muitos na mão desperdiça)
        - Tem searcher (bom: busca peça)
        - Tem ramp de DON (bom: acelera)
        - Counter de menos (ruim: sem defesa)
        Se sinais ruins > bons -> mulligan.
        """
        from optcg_engine.deck_census import deck_census
        non_leader = [c for c in hand if c.card_type != 'LEADER']
        custos = sorted(c.cost for c in non_leader)

        bons, ruins, motivos = 0, 0, []

        # ── Jogada por turno: consigo gastar o DON do turno? ──
        # DON disponível no turno N (jogador 1): T1=1, T2=3, T3=5
        def aproveita_don(don_disp):
            # tenta somar custos de cartas (cada uma usada uma vez) até o DON
            restante = don_disp
            usadas = 0
            for c in custos:
                if c <= restante and c > 0:
                    restante -= c
                    usadas += 1
            return usadas > 0  # jogou pelo menos 1 carta aproveitando o turno

        t1 = aproveita_don(1)
        t2 = aproveita_don(3)
        t3 = aproveita_don(5)
        jogadas_cedo = sum([t1, t2, t3])
        if jogadas_cedo >= 2:
            bons += 1
            motivos.append(f'curva ok (T1:{"s" if t1 else "n"} T2:{"s" if t2 else "n"} T3:{"s" if t3 else "n"})')
        else:
            ruins += 1
            motivos.append('mao lenta (sem jogadas para os primeiros turnos)')

        # ── Tem searcher na mão? (bom) ──
        tem_searcher = any(getattr(c, 'is_searcher', False) or 'search' in c.card_text.lower()
                           for c in non_leader)
        if tem_searcher:
            bons += 1; motivos.append('tem searcher')

        # ── Tem ramp de DON? (bom) ──
        tem_ramp = any('don' in c.card_text.lower() and
                       ('add' in c.card_text.lower() or 'active' in c.card_text.lower())
                       for c in non_leader)
        if tem_ramp:
            bons += 1; motivos.append('tem ramp de DON')

        # ── Trigger demais na mão (relativo ao deck) ──
        if deck:
            census = deck_census(deck)
            trig_no_deck = max(1, census['trigger'])
            trig_na_mao = sum(1 for c in non_leader if getattr(c, 'has_trigger', False))
            # se metade ou mais dos triggers do deck estão na mão, é ruim
            if trig_na_mao >= 2 and trig_na_mao >= trig_no_deck * 0.5:
                ruins += 1
                motivos.append(f'trigger demais na mao ({trig_na_mao} de {trig_no_deck} do deck)')

        # ── Counter de menos na mão (ruim) ──
        counters_mao = sum(1 for c in non_leader if getattr(c, 'counter', 0) >= 1000)
        if counters_mao == 0:
            ruins += 1; motivos.append('sem counter na mao')

        deve_trocar = ruins > bons
        resumo = '; '.join(motivos)
        return deve_trocar, resumo

    def setup(self):
        """
        Setup inicial conforme sequência das 34k linhas:
        CheckStartOfGameActions → DrawCard(5) → OfferMulligan → StartGame
        """
        for p in [self.state_a, self.state_b]:
            random.shuffle(p.deck)
            p.hand = [p.deck.pop() for _ in range(min(5, len(p.deck)))]

            # Mulligan se mão sem cartas de custo <= 2
            if not any(c.cost <= 2 for c in p.hand if c.card_type != 'LEADER'):
                p.deck.extend(p.hand)
                random.shuffle(p.deck)
                p.hand = [p.deck.pop() for _ in range(min(5, len(p.deck)))]

            life_count = p.leader.life if p.leader.life > 0 else 5
            p.life = [p.deck.pop() for _ in range(min(life_count, len(p.deck)))]

            # Stage inicial (CheckStartOfGameActions)
            self._place_start_stage(p)

    # ── Fases do turno ───────────────────────────────────────────────────────

    def refresh_phase(self, p: GameState):
        """
        PlayerUntap das 34k linhas:
        - Retorna DON dado a cartas
        - Reseta rested/just_played/power_buff
        - Reseta once_per_turn
        - Reseta travas de ataque/rest (cannot_attack_until,
          cannot_be_rested_until) quando este jogador comeca seu turno.
          NOTA: o engine nao modela 'End Phase' como passo distinto do
          turno -- por isso 'until end of next turn' e 'until end of next
          End Phase' sao tratados de forma equivalente aqui (ambos resetam
          no refresh do jogador travado). A diferenca de granularidade
          entre os dois so importaria se algum efeito pudesse agir
          especificamente NA End Phase antes do refresh, o que o engine
          ainda nao simula.
        """
        don_from_cards = sum(c.don_attached for c in p.field_chars) + p.leader.don_attached
        for c in p.field_chars:
            c.don_attached = 0
            c.rested = False
            c.just_played = False
            c.power_buff = 0
            c.cost_buff = 0
            c.cannot_attack_until = ''
            c.cannot_be_rested_until = ''
        p.leader.don_attached = 0
        p.leader.rested = False
        p.leader.power_buff = 0
        p.leader.cost_buff = 0
        p.leader.cannot_attack_until = ''
        p.don_available += p.don_rested + don_from_cards
        p.don_rested = 0

    def draw_phase(self, p: GameState, verbose: bool = False):
        """PlayerDrawPhase — 1º jogador não compra no T1."""
        if p.turn == 1 and p.is_first:
            return
        if p.deck:
            drawn = p.deck.pop()
            p.hand.append(drawn)
            if verbose:
                print(f'  \033[90mComprou: {drawn.name[:30]}\033[0m')

    def don_phase(self, p: GameState, verbose: bool = False):
        """
        PlayerDonPhase:
        - T1 do 1º jogador: +1 DON
        - Outros turnos: +2 DON
        - Máximo 10 (limitado pelo don_deck)
        """
        gain = min(1 if (p.turn == 1 and p.is_first) else 2, p.don_deck)
        p.don_deck -= gain
        p.don_available += gain
        if verbose:
            print(f'  \033[93mDON!! +{gain} rampados │ '
                  f'{p.don_available} ativos │ '
                  f'{p.don_rested} restados\033[0m')

    def _activate_main_effects(self, p, opp, ee, verbose=False):
        """
        Ativa efeitos [Activate: Main] disponíveis (líder, Stage, personagens).
        A IA decide ativar quando o benefício é claro e o custo é pagável.
        Respeita 'once_per_turn'.
        """
        # Fontes de efeito ativável: líder, stage, e personagens em campo
        sources = []
        if p.leader:
            sources.append(p.leader)
        if p.field_stage:
            sources.append(p.field_stage)
        sources.extend(p.field_chars)

        for src in sources:
            effects = get_card_effects(src.code)
            am = effects.get('activate_main')
            if not am:
                continue
            # once per turn: marca em atributo dinâmico
            if am.get('once_per_turn'):
                used = getattr(src, '_am_used_turn', -1)
                if used == p.turn:
                    continue
            # Decide se vale ativar (benefício claro): draw/search/play sempre vale;
            # efeitos que precisam de alvo, só se houver alvo.
            if not self._should_activate_main(src, am, p, opp):
                continue
            # Marca uso e executa
            src._am_used_turn = p.turn
            if verbose:
                print(f'    ⚙ ativou [Activate:Main] de {src.name[:22]}')
            logs = ee.execute(src, 'activate_main')
            if verbose:
                for log in logs:
                    if log:
                        print(f'      ↳ {log}')

    def _should_activate_main(self, src, am, p, opp) -> bool:
        """
        Decide se vale ativar um efeito [Activate: Main] — GERAL, para qualquer
        carta (não só Imu). Considera o custo real (você paga para receber):
        - benefício de vantagem (draw/search) vale, SE o custo é pagável e compensa
        - efeito que precisa de alvo só vale se há alvo
        - se há custo de trash, só ativa com carta descartável (e que valha perder)
        """
        steps = am.get('steps', [])
        actions = [s.get('action') for s in steps]
        costs = am.get('costs', [])   # lista (corrigido: era 'cost' singular)

        # Verifica se o custo é PAGÁVEL
        for c in costs:
            ctype = c.get('type')
            cnt = c.get('count', 1)
            if ctype == 'trash_from_hand' and len(p.hand) < cnt:
                return False   # não tem carta para trashar
            if ctype == 'don_minus':
                don_total = p.don_available + p.don_rested + \
                            sum(x.don_attached for x in p.field_chars) + p.leader.don_attached
                if don_total < cnt:
                    return False

        tem_custo_trash = any(c.get('type') == 'trash_from_hand' for c in costs)

        # Efeitos de vantagem pura (draw, search) — valem se o custo compensa
        if any(a in ('draw', 'look_top_deck', 'add_to_hand') for a in actions):
            if tem_custo_trash:
                # só ativa se, após trashar, ainda sobra mão útil (não esvazia a mão
                # por 1 draw). Heurística: ter mais cartas que o custo + 1.
                cnt = next((c.get('count', 1) for c in costs
                            if c.get('type') == 'trash_from_hand'), 1)
                return len(p.hand) > cnt   # sobra ao menos 1 carta após o custo
            return True

        # Efeitos que afetam o oponente — só com alvo
        if any(a in ('rest_opp', 'ko_opp', 'debuff', 'debuff_power', 'bounce') for a in actions):
            return bool(opp.field_chars)

        # Efeitos de DON (ramp, reativar) — valem
        if any(a in ('add_don', 'set_don_active') for a in actions):
            return True

        return False

    def _score_play_action(self, card, engine) -> float:
        """
        Pontua JOGAR uma carta. Cartas cujo efeito HABILITA o ataque
        (On Play remoção, rush, buff, activate que ajuda) pontuam alto e saem
        ANTES dos ataques. Cartas só-desenvolvimento (blocker defensivo, vanilla)
        pontuam como dev e saem DEPOIS dos ataques (regra de ordem do usuário).
        """
        base = engine.avaliar_carta(card)
        effects = get_card_effects(card.code)

        # Carta que PRECISA entrar para ativar efeito que ajuda o ataque agora:
        # On Play de remoção/buff, rush. Bônus para sair antes do ataque.
        habilita_ataque = False
        if 'on_play' in effects:
            txt = (card.card_text or '').lower()
            if any(k in txt for k in ['k.o.', 'ko ', 'rest', 'give', '-', 'draw', 'play']):
                habilita_ataque = True
        if card.has_rush:
            habilita_ataque = True

        if habilita_ataque:
            base += 60   # prioriza sair antes dos ataques
        return base

    def _generate_and_score_actions(self, p, opp, engine):
        """
        Gera TODAS as ações possíveis no estado atual e as pontua.
        Retorna lista de (score, tipo, dados) ordenada por score desc.

        Ações: ('play', card) | ('activate', source) | ('attack', attacker, ttype, tgt)
        """
        actions = []
        a = engine.analyzer

        # PRIORIDADE DE ANÁLISE (cascata de inclinação): o modo dominante ajusta
        # os pesos das ações, respeitando a ordem do documento sem bloquear.
        priority = a.analysis_priority()
        threats = a.critical_threats() if priority == 'REMOVE_THREAT' else []

        # ── Ações de JOGAR carta ──
        for card in p.hand:
            if not engine._can_play_card(card):
                continue
            score = self._score_play_action(card, engine)
            # Inclinação: desenvolver ganha peso no modo DEVELOP; perde no LETHAL/DEFENSIVE
            if priority == 'DEVELOP':
                score += 40
            elif priority == 'LETHAL':
                score -= 60   # não desenvolve quando pode ganhar — ataca
            # Carta defensiva (blocker/counter) ganha peso no modo DEFENSIVE
            if priority == 'DEFENSIVE' and (card.has_blocker or card.counter > 0):
                score += 120
            actions.append((score, 'play', card, None, None))

        # ── Ações de ATACAR (com risco de trigger descontado) ──
        if p.can_attack_this_turn():
            attackers = [c for c in p.field_chars
                         if not c.rested and not c.just_played and not c.cannot_attack_until
                         and not c.cannot_be_rested_until and not is_attack_locked_self(c, p, opp)]
            if not p.leader.rested:
                attackers.append(p.leader)
            for att in attackers:
                # [Rush: Character] restringe o alvo a Characters do
                # oponente neste turno -- nao gera a opcao de atacar o Leader.
                pode_atacar_leader = not getattr(att, 'rush_character_only_this_turn', False)
                # alvo líder
                if pode_atacar_leader:
                    s_leader = engine.score_attack_target(att, 'leader', None)
                    if s_leader > -500:
                        s_leader -= self._trigger_risk_penalty(opp)   # desconto de trigger
                        # Banish: prioriza atacar a vida (nega trigger e remove a carta
                        # de vez). Inclinação forte, mas a ameaça crítica ainda vem antes.
                        if att.has_banish:
                            s_leader += 150
                        if priority == 'LETHAL':       s_leader += 500   # foco em fechar
                        elif priority == 'DEFENSIVE':  s_leader -= 80    # não exponha à toa
                        elif priority == 'REMOVE_THREAT': s_leader -= 100 # remova antes
                        actions.append((s_leader, 'attack', att, 'leader', None))
                # alvos personagem
                for tgt in opp.field_chars:
                    s_char = engine.score_attack_target(att, 'character', tgt)
                    if s_char > -500:
                        # Inclinação: remover a AMEAÇA CRÍTICA ganha prioridade alta
                        if tgt in threats:
                            s_char += 300   # acima de atacar o líder
                        actions.append((s_char, 'attack', att, 'character', tgt))

        # ── Ações de ANEXAR DON para ligar efeitos/keywords [DON!! ×N] ──
        actions.extend(self._generate_attach_don_actions(p, opp, engine))

        actions.sort(key=lambda x: x[0], reverse=True)
        return actions

    def _generate_attach_don_actions(self, p, opp, engine):
        """
        Gera ações de ANEXAR DON para ligar efeitos/keywords [DON!! ×N].
        Avalia cada personagem em campo que tem efeito condicional a DON e ainda
        não atingiu o requisito. Vale anexar se o efeito ligado compensa prender
        o DON (custo ~25/DON), modulado pelo estado (postura/prioridade).
        """
        DON_COST = 25
        acts = []
        if p.don_available <= 0:
            return acts
        priority = engine.analyzer.analysis_priority()

        for card in p.field_chars:
            effects = get_card_effects(card.code)
            # 1) keywords condicionais a DON (blocker/double_attack/rush/banish)
            cond_kw = getattr(card, 'don_cond_keywords', None) or {}
            for kw, req in cond_kw.items():
                falta = req - card.don_attached
                if falta <= 0 or falta > p.don_available:
                    continue
                valor = self._keyword_don_value(kw, card, p, opp, priority)
                score = valor - falta * DON_COST
                if score > 0:
                    acts.append((score, 'attach_don', card, falta, kw))

            # 2) gatilhos condicionais a DON (when_attacking/on_play/etc.)
            for trig, ef in effects.items():
                if not isinstance(ef, dict):
                    continue
                req = ef.get('don_requirement', 0)
                if not req or card.don_attached >= req:
                    continue
                falta = req - card.don_attached
                if falta > p.don_available:
                    continue
                # só vale ligar gatilho de ataque se o personagem vai atacar
                valor = self._trigger_don_value(trig, ef, card, p, opp, priority)
                score = valor - falta * DON_COST
                if score > 0:
                    acts.append((score, 'attach_don', card, falta, trig))
        return acts

    def _keyword_don_value(self, kw, card, p, opp, priority) -> float:
        """Valor de ligar uma keyword via DON, conforme o estado."""
        if kw == 'blocker':
            # defensivo: vale muito sob pressão / vida baixa
            base = 100
            if priority == 'DEFENSIVE': base += 80
            if p.life_count() <= 2:     base += 60
            return base
        if kw == 'double_attack':
            # ofensivo: vale se o oponente está em alcance de dano
            base = 80
            if opp.life_count() <= 3: base += 60
            if priority == 'LETHAL':  base += 150
            return base
        if kw == 'rush':
            return 90   # poder atacar já
        if kw == 'banish':
            return 70 + (40 if opp.life_count() <= 3 else 0)
        return 40

    def _trigger_don_value(self, trig, ef, card, p, opp, priority) -> float:
        """Valor de ligar um gatilho condicional a DON, pelo que o efeito faz."""
        steps = ef.get('steps', [])
        actions = [s.get('action') for s in steps]
        valor = 0
        if any(x in ('ko', 'rest_opp', 'debuff_power', 'bounce') for x in actions):
            valor = 120   # remoção/controle — vale
            if opp.field_chars: valor += 30
        elif any(x in ('draw', 'add_to_hand', 'look_top_deck') for x in actions):
            valor = 90    # vantagem de carta
        elif any('power' in str(x) for x in actions):
            valor = 60    # buff de poder
        else:
            valor = 40
        # gatilhos de ataque só valem se o personagem pode atacar
        if trig == 'when_attacking' and (card.rested or card.just_played):
            valor = 0
        return valor

    def _trigger_risk_penalty(self, opp) -> float:
        """
        Risco de trigger ao atacar (documento pág. 21): desconta, mas não proíbe.
        Mais vidas do oponente = mais chance de trigger. Amarelo = risco maior.
        """
        vidas = opp.life_count()
        if vidas == 0:
            return 0
        base = vidas * 8   # desconto suave por vida (trigger é risco, não veto)
        cor = (getattr(opp.leader, 'color', '') or '').lower()
        if 'yellow' in cor or 'amarelo' in cor:
            base *= 1.8
        return base

    def _evaluate_state(self, p, opp) -> float:
        """
        Avalia quão bom é um estado para 'p' (ao fim de uma sequência simulada).
        Combina: dano causado, vida própria, vantagem de board, recursos.
        Usado pelo Turn Planner para comparar linhas de jogo.
        """
        score = 0.0
        # Dano causado ao oponente (vidas tiradas) — peso alto
        score += p.dmg_dealt * 200
        score -= opp.life_count() * 150          # quanto menos vida o opp tem, melhor
        # Vitória/derrota
        if opp.life_count() <= 0 and p.dmg_dealt > 0:
            score += 10000
        # Board próprio vs oponente
        score += sum(c.board_value() for c in p.field_chars) * 10
        score -= sum(c.board_value() for c in opp.field_chars) * 8
        # Blockers do oponente vivos (ruim para mim)
        score -= len(opp.blockers_active()) * 30
        # Minha vida (defesa)
        score += p.life_count() * 40
        # Recursos: cartas na mão, DON ainda disponível (flexibilidade)
        score += len(p.hand) * 8
        score += p.don_available * 5
        return score

    def _apply_action(self, action, p, opp, ee, engine, verbose=False):
        """
        Executa UMA ação no estado dado (real ou cópia). Retorna True se venceu.
        Reúso entre o jogo real e a simulação do planner.
        """
        score, kind, obj, ttype, tgt = action

        if kind == 'play':
            self._play_card(obj, p, opp, ee, verbose=verbose)

        elif kind == 'attach_don':
            card, falta, what = obj, ttype, tgt
            anexar = min(falta, p.don_available)
            if anexar > 0:
                card.don_attached += anexar
                p.don_available -= anexar
                if verbose:
                    print(f'    ⚡ anexou {anexar} DON em {card.name[:20]} para ligar [{what}]')

        elif kind == 'attack':
            attacker = obj
            if attacker.rested:
                return False
            self._attach_don_for_attack(attacker, ttype, tgt, p, opp, engine, verbose)
            if verbose:
                tgt_name = 'Leader' if ttype == 'leader' else (tgt.name[:20] if tgt else '?')
                print(f'    {attacker.name[:20]} ({attacker.effective_power(True)}pwr) ataca {tgt_name}')
            if self._execute_attack(attacker, ttype, tgt, p, opp, engine, verbose=verbose):
                return True
        return False

    def _simulate_sequence(self, p, opp, first_action, max_steps=12):
        """
        Simula uma LINHA DE JOGO começando por first_action, numa CÓPIA do estado.
        Após a primeira ação, segue gulosamente (melhor ação a cada passo) até o
        fim do turno. Retorna o valor do estado final (para comparar linhas).
        """
        from copy import deepcopy
        p2 = deepcopy(p)
        opp2 = deepcopy(opp)
        eng2 = DecisionEngine(p2, opp2)
        ee2 = EffectExecutor(p2, opp2)

        # Mapeia a primeira ação para os objetos da cópia (por índice/identidade)
        first2 = self._remap_action(first_action, p, p2, opp, opp2)
        if first2 is None:
            return -1e9
        won = self._apply_action(first2, p2, opp2, ee2, eng2, verbose=False)
        if won:
            return 1e9   # essa linha vence

        # Continua gulosamente até o fim do turno
        for _ in range(max_steps):
            acts = self._generate_and_score_actions(p2, opp2, eng2)
            if not acts or acts[0][0] < 0:
                break
            if self._apply_action(acts[0], p2, opp2, ee2, eng2, verbose=False):
                return 1e9
        return self._evaluate_state(p2, opp2)

    def _remap_action(self, action, p, p2, opp, opp2):
        """Remapeia uma ação do estado real para os objetos da cópia (por índice)."""
        score, kind, obj, ttype, tgt = action
        try:
            if kind == 'play':
                idx = p.hand.index(obj)
                return (score, kind, p2.hand[idx], None, None)
            if kind == 'attach_don':
                idx = p.field_chars.index(obj) if obj in p.field_chars else None
                obj2 = p2.field_chars[idx] if idx is not None else (p2.leader if obj is p.leader else None)
                return (score, kind, obj2, ttype, tgt)
            if kind == 'attack':
                if obj is p.leader:
                    att2 = p2.leader
                else:
                    att2 = p2.field_chars[p.field_chars.index(obj)]
                if ttype == 'character' and tgt in opp.field_chars:
                    tgt2 = opp2.field_chars[opp.field_chars.index(tgt)]
                else:
                    tgt2 = None
                return (score, kind, att2, ttype, tgt2)
        except (ValueError, IndexError):
            return None
        return None

    def main_phase(self, p: GameState, opp: GameState, verbose: bool = False) -> bool:
        """
        Fase principal = LOOP DE PONTUAÇÃO DE JOGADAS (documento pág. 9).
        A cada passo: gera todas as ações possíveis, pontua, executa a melhor,
        reavalia o estado, repete. A ordem (jogar antes/depois de atacar) emerge
        das pontuações: cartas que habilitam ataque saem antes; desenvolvimento
        sai depois. Para quando nenhuma ação tem score acima do limiar.
        """
        engine = DecisionEngine(p, opp)
        ee     = EffectExecutor(p, opp)
        ee.apply_your_turn_buffs()

        if verbose:
            print('  -- Turno (Turn Planner: simula sequências) --')

        MAX_ACOES = 30
        TOP_K = 6        # simula só as K ações mais promissoras (custo controlado)
        n = 0

        while n < MAX_ACOES:
            n += 1
            self._activate_main_effects(p, opp, ee, verbose=verbose)

            actions = self._generate_and_score_actions(p, opp, engine)
            if not actions or actions[0][0] < 0:
                break

            # TURN PLANNER: para as TOP_K ações candidatas, simula a linha de jogo
            # resultante e escolhe a que leva ao MELHOR estado de fim de turno.
            # (Em vez de escolher gulosamente a de maior score imediato.)
            candidatas = actions[:TOP_K]
            melhor_acao = None
            melhor_valor = -1e18
            for cand in candidatas:
                valor = self._simulate_sequence(p, opp, cand)
                if valor > melhor_valor:
                    melhor_valor = valor
                    melhor_acao = cand

            if melhor_acao is None:
                break

            # Executa a primeira ação da melhor linha no estado REAL
            if self._apply_action(melhor_acao, p, opp, ee, engine, verbose=verbose):
                return True

        for c in p.field_chars:
            c.just_played = False
        return False

    def _attach_don_for_attack(self, attacker, ttype, tgt, p, opp, engine, verbose):
        """Anexa DON a este ataque, se ajudar a passar a defesa."""
        if p.don_available <= 0:
            return
        if ttype == 'leader':
            alvo_power = opp.leader.power
        else:
            alvo_power = tgt.power if tgt else 0
        atk = attacker.effective_power(True)
        # Considera o COUNTER provável do oponente (alinha com score_attack_target):
        # anexa DON para superar o alvo + counter estimado, não só o poder base.
        # Mas não exagera: limita o counter considerado ao que a mão dele comporta.
        counter_prov = engine.analyzer.opp_counter_potential() if ttype == 'leader' else 0
        alvo_total = alvo_power + counter_prov
        falta = alvo_total - atk
        if falta > 0:
            need = min(p.don_available, (falta + 999) // 1000)
            if need > 0:
                attacker.don_attached += need
                p.don_available -= need
                if verbose:
                    print(f'    anexou {need} DON em {attacker.name[:20]}')

    def _main_phase_OLD_fixed(self, p: GameState, opp: GameState, verbose: bool = False) -> bool:
        engine = DecisionEngine(p, opp)
        ee     = EffectExecutor(p, opp)

        # 1. Aplica buffs Your Turn (stage, personagens, líder)
        ee.apply_your_turn_buffs()

        # 2. Jogar cartas — engine reserva DON para defesa automaticamente
        if verbose:
            print('  -- Jogando cartas --')
        plays = 0
        while plays < 10:
            card = engine.choose_card_to_play()
            if card:
                self._play_card(card, p, opp, ee, verbose=verbose)
                plays += 1
            else:
                break
        if verbose and plays == 0:
            print('    (nenhuma carta jogada)')

        # 2b. Ativar efeitos [Activate: Main] (líder, Stage, personagens)
        self._activate_main_effects(p, opp, ee, verbose=verbose)

        # 3. Distribui DON entre os atacantes
        if p.can_attack_this_turn():
            attackers = [c for c in p.field_chars
                         if not c.rested and not c.just_played and not c.cannot_attack_until
                         and not c.cannot_be_rested_until and not is_attack_locked_self(c, p, opp)]
            if not p.leader.rested:
                attackers.append(p.leader)

            if attackers and p.don_available > 0:
                don_plan = engine.plan_don_distribution(attackers)
                for att in attackers:
                    don_amt = don_plan.get(id(att), 0)
                    if don_amt > 0 and p.don_available >= don_amt:
                        att.don_attached += don_amt
                        p.don_available  -= don_amt
                        p.don_rested     += don_amt
                        if verbose:
                            print(f'    anexou {don_amt} DON em {att.name[:20]}')

            # 4. Executa ataques na ordem planejada
            if verbose:
                print('  -- Ataques --')
            attack_plan = engine.plan_attacks(attackers)
            atacantes_usados = set()

            for attacker, ttype, tgt in attack_plan:
                if attacker.rested:
                    continue
                if id(attacker) in atacantes_usados:
                    continue
                atacantes_usados.add(id(attacker))

                if ttype == 'character':
                    if tgt not in opp.field_chars:
                        ttype, tgt = 'leader', None

                if verbose:
                    tgt_name = 'Leader' if ttype == 'leader' else (tgt.name[:20] if tgt else '?')
                    print(f'    {attacker.name[:20]} ({attacker.effective_power(True)}pwr) '
                          f'ataca {tgt_name}')

                if self._execute_attack(attacker, ttype, tgt, p, opp, engine, verbose=verbose):
                    return True

                if not opp.life:
                    remaining = [c for c in p.field_chars
                                 if not c.rested and not c.just_played and not c.cannot_attack_until
                                 and not c.cannot_be_rested_until and not is_attack_locked_self(c, p, opp)
                                 and id(c) not in atacantes_usados]
                    if not p.leader.rested and id(p.leader) not in atacantes_usados:
                        remaining.append(p.leader)
                    for fin in remaining:
                        if self._execute_attack(fin, 'leader', None, p, opp, engine, verbose=verbose):
                            return True

        for c in p.field_chars:
            c.just_played = False

        return False

    def _play_card(self, card: Card, p: GameState, opp: GameState,
                   ee: EffectExecutor, verbose: bool = False):
        """
        Joga uma carta.
        Efeitos executados APENAS via EffectExecutor — sem lógica duplicada.
        Com verbose=True, narra a jogada (para o replay). Silencioso por padrão
        (simulação em massa não passa verbose).
        """
        p.hand.remove(card)
        p.don_rested  += card.cost
        p.don_available -= card.cost

        if verbose:
            don_txt = f'gastou {card.cost} DON' if card.cost > 0 else 'grátis'
            print(f'  > {don_txt} -> Joga: {card.name[:30]} '
                  f'({card.effective_power(True)}pwr) [{card.card_type}]')
            # Texto do efeito da carta (cinza) — para auditoria sem decorar
            txt = (card.card_text or '').strip()
            if txt:
                # primeira frase/linha do efeito, até ~90 chars
                short = txt.replace('\n', ' ')[:90]
                print(f'    \033[90mefeito: {short}{"..." if len(txt) > 90 else ""}\033[0m')

        if card.card_type == 'CHARACTER':
            if len(p.field_chars) >= 5:
                worst = min(p.field_chars, key=lambda c: c.board_value())
                p.field_chars.remove(worst)
                p.trash.append(worst)
                if verbose:
                    print(f'    campo cheio -> descartou {worst.name[:25]}')
            card.rested = False
            card.just_played = not (card.has_rush or card.is_rush_character())
            card.rush_character_only_this_turn = card.is_rush_character() and not card.is_rush()
            p.field_chars.append(card)

        elif card.card_type == 'EVENT':
            p.trash.append(card)

        elif card.card_type == 'STAGE':
            if p.field_stage:
                p.trash.append(p.field_stage)
            p.field_stage = card

        # Executa efeito ao jogar a carta via EffectExecutor (único ponto).
        # Eventos e personagens podem ter o efeito em 'on_play' OU em 'main'
        # (cartas cujo texto começa com [Main]). Ao jogar, ambos disparam.
        logs = []
        logs += ee.execute(card, 'on_play')
        logs += ee.execute(card, 'main')
        if verbose:
            for log in logs:
                if log:
                    print(f'    ↳ [{card.name[:20]}] {log}')

    def _execute_attack(self, attacker: Card, target_type: str,
                        target: Optional[Card], p: GameState,
                        opp: GameState, engine: DecisionEngine,
                        verbose: bool = False) -> bool:
        """
        Sequência: tap atacante → blocker → counter → damage.
        Com verbose, narra blocker/counter/dano.
        """
        if attacker is p.leader:
            p.leader.rested = True
        else:
            attacker.rested = True

        # Executa efeito When Attacking
        ee = EffectExecutor(p, opp)
        wa_logs = ee.execute(attacker, 'when_attacking')
        if verbose:
            for log in wa_logs:
                if log:
                    print(f'      ↳ [when attacking] {log}')

        atk_power = attacker.effective_power(True)
        damage    = 2 if attacker.is_double_attack() else 1

        # Block step
        opp_engine = DecisionEngine(opp, p)
        blocker = opp_engine.should_use_blocker(atk_power)
        if blocker and not attacker.has_unblockable:
            target_type = 'character'
            target      = blocker
            blocker.rested = True
            if verbose:
                print(f'      🛡 Blocker! {blocker.name[:20]} intercepta')
            # [On Block]: efeito que dispara quando este personagem bloqueia.
            # Roda no contexto do oponente (dono do blocker).
            ob_effects = get_card_effects(blocker.code)
            if 'on_block' in ob_effects:
                ee_block = EffectExecutor(opp, p)
                ob_logs = ee_block.execute(blocker, 'on_block')
                if verbose:
                    for log in ob_logs:
                        if log:
                            print(f'      ⚡ [On Block] {log}')

        # Define poder de defesa
        if target_type == 'leader':
            defend_power = opp.leader.power + opp.leader.power_buff
        elif target and target in opp.field_chars:
            defend_power = target.power + target.power_buff
        else:
            return False

        # Counter step
        if opp_engine.should_use_counter(atk_power, defend_power):
            counter_add = opp_engine.use_counter(atk_power - defend_power + 1)
            defend_power += counter_add
            if verbose and counter_add > 0:
                print(f'      🛡 Counter! +{counter_add} -> defesa {defend_power}')

        # Damage step
        if atk_power >= defend_power:
            if target_type == 'leader':
                # Vitória só se o oponente JÁ estava com 0 vidas ANTES deste ataque.
                # (Receber dano com 0 vidas = derrota.)
                if not opp.life:
                    p.dmg_dealt += 1
                    return True  # vitória: dano com 0 vidas

                # Tira até 'damage' vidas, UMA por vez, resolvendo trigger de cada.
                # Se a vida acabar durante o double attack, PARA — o dano extra
                # não causa derrota (regra: só compra as vidas que tem).
                for _ in range(damage):
                    if not opp.life:
                        break   # acabou a vida durante este ataque — não é derrota
                    life_card = opp.life.pop()
                    p.dmg_dealt += 1
                    # Banish: a vida vai DIRETO para o trash, sem ir para a mão
                    # e sem direito a trigger (regra oficial).
                    if attacker.has_banish:
                        opp.trash.append(life_card)
                        if verbose:
                            print(f'      💥 DANO (BANISH)! vida -> trash: {opp.life_count()}')
                    else:
                        opp.hand.append(life_card)
                        if verbose:
                            print(f'      💥 DANO! vida do oponente: {opp.life_count()}')
                    if life_card.has_trigger and not attacker.has_banish:
                        opp.triggers_activated += 1
                        ee_opp = EffectExecutor(opp, p)
                        tg_logs = ee_opp.execute(life_card, 'trigger')
                        if verbose:
                            for log in tg_logs:
                                if log:
                                    print(f'      ⚡ [trigger] {log}')
                return False   # tirou vida(s), mas oponente não estava em 0 — sem derrota
            elif target_type == 'character' and target and target in opp.field_chars:
                ee_opp = EffectExecutor(opp, p)
                sub_log = ee_opp.try_substitute(target, 'ko')
                if sub_log:
                    if verbose:
                        print(f'      🔁 {sub_log}')
                    return False
                opp.field_chars.remove(target)
                opp.trash.append(target)
                if verbose:
                    print(f'      💀 {target.name[:20]} foi KO!')
                ko_logs = ee_opp.execute(target, 'on_ko')
                if verbose:
                    for log in ko_logs:
                        if log:
                            print(f'      ↳ [on KO] {log}')
        else:
            if verbose:
                print(f'      ✗ Ataque bloqueado ({atk_power} < {defend_power})')

        return False

    def play_turn(self, p: GameState, opp: GameState, verbose: bool = False) -> Optional[str]:
        self.global_turn += 1
        p.turn += 1
        p.global_turn = self.global_turn

        self.refresh_phase(p)
        self.draw_phase(p, verbose=verbose)
        self.don_phase(p, verbose=verbose)

        if self.main_phase(p, opp, verbose=verbose):
            return 'A' if p is self.state_a else 'B'
        if not p.deck:
            return 'B' if p is self.state_a else 'A'
        if not opp.deck:
            return 'A' if p is self.state_a else 'B'
        return None

    def simulate(self) -> dict:
        self.setup()
        winner = None
        total_turns = 0

        for turn_num in range(self.MAX_TURNS * 2):
            p   = (self.state_a if self.state_a.is_first else self.state_b) \
                  if turn_num % 2 == 0 \
                  else (self.state_b if self.state_a.is_first else self.state_a)
            opp = self.state_b if p is self.state_a else self.state_a

            result = self.play_turn(p, opp)
            total_turns += 1
            if result:
                winner = result
                break

        return {
            'winner':      winner or 'DRAW',
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


# ===========================================================================
# Pipeline de simulação
# ===========================================================================

def simular_matchup(deck_a: tuple, deck_b: tuple, n: int = 100) -> dict:
    wins_a = wins_b = draws = 0
    total_turns = []
    counters_a = counters_b = searchers_a = searchers_b = triggers_a = triggers_b = 0

    for _ in range(n):
        match = OPTCGMatch(deck_a, deck_b)
        r = match.simulate()
        if r['winner'] == 'A':   wins_a += 1
        elif r['winner'] == 'B': wins_b += 1
        else:                    draws  += 1
        total_turns.append(r['turns'])
        counters_a  += r['counters_a'];  counters_b  += r['counters_b']
        searchers_a += r['searchers_a']; searchers_b += r['searchers_b']
        triggers_a  += r['triggers_a'];  triggers_b  += r['triggers_b']

    total     = wins_a + wins_b + draws
    avg_turns = sum(total_turns) / len(total_turns) if total_turns else 0

    return {
        'wins_a': wins_a, 'wins_b': wins_b, 'draws': draws,
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