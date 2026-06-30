"""
OPTCG Match Replay v2.1
Replay visual de uma partida para validar o simulador.

Correções:
  - Mostra lista completa de cada deck (código, nome, quantidade)
  - Validador de decks antes de começar
  - DON acumula corretamente
  - Sem ataques no T1 e T2 (primeiro turno de cada jogador)
  - Searcher mostra cartas buscadas
  - Stage inicial em campo

Uso:
    python replay_optcg.py
"""

import random
import os
import pandas as pd
from collections import Counter
from copy import deepcopy
from optcg_engine.decision_engine import (
    load_cards_db, build_real_deck, validar_deck,
    Card, GameState, DecisionEngine, EffectExecutor, OPTCGMatch
)

# ── Cores terminal ─────────────────────────────────────────────────────────────
class C:
    RED    = '\033[91m'
    GREEN  = '\033[92m'
    YELLOW = '\033[93m'
    BLUE   = '\033[94m'
    PURPLE = '\033[95m'
    CYAN   = '\033[96m'
    GRAY   = '\033[90m'
    BOLD   = '\033[1m'
    RESET  = '\033[0m'

def sep(char='─', n=65): print(C.GRAY + char * n + C.RESET)

def don_bar(available: int, total_in_play: int = 10) -> str:
    """Renderiza barra visual dos DON em campo."""
    # DON ativos = available, DON restados = total_in_play - available - don_deck
    ativos = '■' * available
    vazios = '□' * max(0, total_in_play - available)
    return f'{C.YELLOW}{ativos}{C.GRAY}{vazios}{C.RESET}'

def print_field(p: 'GameState', col: str, name: str):
    """Renderiza o campo completo em ASCII."""
    W = 65
    vida_str = C.RED + '♥ ' * p.life_count() + C.RESET

    print(f'{col}┌{"─" * W}┐{C.RESET}')

    # Character area
    if p.field_chars:
        chars_line = '  '.join([
            f'{"[REST]" if c.rested else "[ATIV]"}'
            f'{c.name[:12]}({c.power})'
            f'{"[B]" if c.has_blocker else ""}'
            for c in p.field_chars
        ])
        print(f'{col}│{C.RESET} CHARACTER: {chars_line[:W-13]:<{W-13}}{col}│{C.RESET}')
    else:
        print(f'{col}│{C.RESET} CHARACTER: {C.GRAY}(vazio){C.RESET:<{W-19}}{col}│{C.RESET}')

    print(f'{col}│{"─" * W}│{C.RESET}')

    # Leader + Stage + Vida
    leader_str = f'LEADER: {p.leader.name[:18]}({p.leader.power})'
    stage_str  = f'STAGE: {p.field_stage.name[:15]}' if p.field_stage else 'STAGE: ---'
    mid_line   = f'{leader_str}  {stage_str}'
    print(f'{col}│{C.RESET} {mid_line:<{W-1}}{col}│{C.RESET}')
    print(f'{col}│{C.RESET} VIDA: {vida_str:<{W-8}}{col}│{C.RESET}')

    print(f'{col}│{"─" * W}│{C.RESET}')

    # DON area
    don_total_em_campo = 10 - p.don_deck
    don_rest = don_total_em_campo - p.don_available
    don_vis  = (C.YELLOW + '■' * p.don_available +
                C.GRAY   + '□' * max(0, don_rest) + C.RESET)
    don_line = f'DON em campo: {don_vis}  Ativos: {C.YELLOW}{p.don_available}{C.RESET}  Restados: {C.GRAY}{don_rest}{C.RESET}'
    print(f'{col}│{C.RESET} {don_line}')
    print(f'{col}│{C.RESET} Mão: {len(p.hand)} cartas  Deck: {len(p.deck)} cartas  Trash: {len(p.trash)}')
    # Cartas da mão (para auditoria): nome, custo e função
    if p.hand:
        for c in p.hand:
            kws = []
            if getattr(c, 'is_searcher', False):    kws.append('Search')
            if getattr(c, 'has_blocker', False):    kws.append('Blocker')
            if getattr(c, 'has_rush', False):       kws.append('Rush')
            if c.card_type == 'EVENT':              kws.append('Event')
            if c.card_type == 'STAGE':              kws.append('Stage')
            kw_str = f' [{", ".join(kws)}]' if kws else ''
            print(f'{col}│{C.RESET}   • {c.name[:32]:<32} (c{c.cost}){kw_str}')
    print(f'{col}└{"─" * W}┘{C.RESET}')

def print_deck_list(name: str, leader: Card, cards: list, col: str):
    """Mostra a lista completa do deck com código, nome e quantidade."""
    sep('═')
    print(f'{col}{C.BOLD}📋 DECKLIST — {name}{C.RESET}')
    sep('─')
    print(f'  Leader: {C.CYAN}{leader.name}{C.RESET} ({leader.code}) | Life: {leader.life} | Power: {leader.power}')
    sep('─')

    # Agrupa por código
    from collections import Counter
    counter = Counter()
    card_map = {}
    for c in cards:
        counter[c.code] += 1
        card_map[c.code] = c

    # Ordena por custo
    sorted_codes = sorted(counter.keys(), key=lambda code: card_map[code].cost)

    print(f'  {"Código":<15} {"Nome":<35} {"Qtd":>4}  {"Custo":>5}  {"Tipo"}')
    sep('─')
    for code in sorted_codes:
        c = card_map[code]
        qty = counter[code]
        kws = []
        if c.has_rush:          kws.append('Rush')
        if c.has_blocker:       kws.append('Blocker')
        if c.has_double_attack: kws.append('DA')
        if c.is_searcher:       kws.append('Search')
        if c.has_trigger:       kws.append('Trigger')
        kw_str = f' [{",".join(kws)}]' if kws else ''
        print(f'  {code:<15} {c.name[:35]:<35} {qty:>4}x  {c.cost:>5}  {c.card_type}{kw_str}')

    total = sum(counter.values())
    print(f'\n  Total: {total} cartas')

def print_state(label: str, p: GameState, opp: GameState, col: str):
    life_str = C.RED + '♥ ' * p.life_count() + C.RESET + f'({p.life_count()})'
    print(f'\n{col}{C.BOLD}{label}{C.RESET}')
    print(f'  Leader: {C.CYAN}{p.leader.name[:25]}{C.RESET} | '
          f'Life: {life_str} | '
          f'Mão: {len(p.hand)} | '
          f'DON: {C.YELLOW}{p.don_available}{C.RESET} ativos | '
          f'Deck: {len(p.deck)}')

    if p.field_stage:
        print(f'  Stage: {C.PURPLE}{p.field_stage.name[:30]}{C.RESET}')

    if p.field_chars:
        for c in p.field_chars:
            state_str = C.GRAY + '[REST]' + C.RESET if c.rested else C.GREEN + '[ATIVO]' + C.RESET
            kws = []
            if c.has_blocker:       kws.append('B')
            if c.has_rush:          kws.append('R')
            if c.has_double_attack: kws.append('DA')
            kw = f'[{",".join(kws)}]' if kws else ''
            print(f'    {state_str} {c.name[:25]:<25} {c.power:>6}pwr  custo {c.cost}  {kw}')
    else:
        print(f'  Campo: {C.GRAY}vazio{C.RESET}')

    opp_life = C.RED + '♥ ' * opp.life_count() + C.RESET + f'({opp.life_count()})'
    print(f'  Oponente: vida {opp_life} | mão {len(opp.hand)} cartas')


class ReplayMatch:
    MAX_TURNS = 15

    def __init__(self, deck_a: tuple, deck_b: tuple,
                 name_a='Jogador A', name_b='Jogador B'):
        leader_a, cards_a, stage_a = deck_a if len(deck_a) == 3 else (*deck_a, None)
        leader_b, cards_b, stage_b = deck_b if len(deck_b) == 3 else (*deck_b, None)

        self.state_a = GameState(leader=deepcopy(leader_a),
                                  deck=[deepcopy(c) for c in cards_a])
        self.state_b = GameState(leader=deepcopy(leader_b),
                                  deck=[deepcopy(c) for c in cards_b])
        self.stage_a = deepcopy(stage_a)
        self.stage_b = deepcopy(stage_b)
        self.name_a = name_a
        self.name_b = name_b
        self.global_turn = 0

        # Opponent Reading (Monte Carlo) exige model_for_a/model_for_b em
        # main_phase. Construímos AQUI, neste exato ponto -- deck completo,
        # ANTES do setup() tirar a mão de abertura -- pela mesma regra do
        # OPTCGMatch.__init__ real: cada lado modela o deck COMPLETO do
        # adversário (list(state_b.deck) / list(state_a.deck)), nunca uma
        # reconstrução parcial feita depois que cartas já saíram pra mão.
        from optcg_engine.decision_engine import OpponentModel
        self.model_for_a = OpponentModel(full_decklist=list(self.state_b.deck))
        self.model_for_b = OpponentModel(full_decklist=list(self.state_a.deck))

        if random.random() < 0.5:
            self.state_a.is_first = True
            self.state_b.is_first = False
        else:
            self.state_a.is_first = False
            self.state_b.is_first = True

    def col(self, p): return C.BLUE if p is self.state_a else C.RED
    def name(self, p): return self.name_a if p is self.state_a else self.name_b

    def _get_engine_match(self) -> 'OPTCGMatch':
        """
        Retorna o OPTCGMatch interno usado para delegar fases/main_phase ao
        ENGINE (fonte única), criando-o uma vez se necessário.

        Não chamamos OPTCGMatch.__init__ porque ele criaria state_a/state_b
        NOVOS via deepcopy dos decks originais -- desconectados do estado que
        este replay já vem evoluindo turno a turno. Em vez disso, via
        __new__, montamos um OPTCGMatch que aponta para os MESMOS objetos
        state_a/state_b/model_for_a/model_for_b do ReplayMatch (estes últimos
        já construídos no __init__, com o deck completo, igual ao
        OPTCGMatch.__init__ real faz) -- main_phase passou a exigir
        model_for_a/model_for_b (Opponent Reading) e antes desta correção
        isso quebrava com AttributeError.
        """
        if not hasattr(self, '_engine_match'):
            self._engine_match = OPTCGMatch.__new__(OPTCGMatch)
            self._engine_match.global_turn = 0
            self._engine_match.state_a = self.state_a
            self._engine_match.state_b = self.state_b
            self._engine_match.model_for_a = self.model_for_a
            self._engine_match.model_for_b = self.model_for_b
            # replay_log e _name_a/_name_b: necessarios para _log_event
            self._engine_match.replay_log = None
            self._engine_match._name_a = getattr(self, 'name_a', 'A')
            self._engine_match._name_b = getattr(self, 'name_b', 'B')
        return self._engine_match

    def setup(self):
        sep('═')
        print(f'{C.BOLD}🏴‍☠️  OPTCG MATCH REPLAY v2.1{C.RESET}')
        sep('═')

        for p, stage, col, nm in [
            (self.state_a, self.stage_a, C.BLUE,  self.name_a),
            (self.state_b, self.stage_b, C.RED,   self.name_b),
        ]:
            random.shuffle(p.deck)
            # Censo do deck COMPLETO (50 cartas) — antes de separar mão/vida.
            # Serve ao perfil do deck (aggressive/control/midrange).
            from optcg_engine.deck_census import deck_census
            p.full_deck_census = deck_census(list(p.deck))
            p.hand = [p.deck.pop() for _ in range(min(5, len(p.deck)))]
            # Decisão de mulligan via ENGINE (fonte única), com motivo
            deve_trocar, motivo = self._get_engine_match()._mulligan_decision(
                p.hand, deck=p.hand + p.deck)
            if deve_trocar:
                print(f'{col}{nm}: fez Mulligan — {motivo}{C.RESET}')
                p.deck.extend(p.hand)
                random.shuffle(p.deck)
                p.hand = [p.deck.pop() for _ in range(min(5, len(p.deck)))]
            else:
                print(f'{col}{nm}: manteve a mão — {motivo}{C.RESET}')
            life_n = p.leader.life if p.leader.life > 0 else 5
            p.life = [p.deck.pop() for _ in range(min(life_n, len(p.deck)))]

            # Stage inicial: usa a mesma regra do motor principal.
            if stage and not p.leader.has_start_of_game:
                p.field_stage = stage
            else:
                opp_state = self.state_b if p is self.state_a else self.state_a
                self._get_engine_match()._place_start_stage(p, opp_state)
            if p.field_stage:
                print(f'{col}{nm}: Stage inicial → {p.field_stage.name}{C.RESET}')

            print(f'{col}{nm}{C.RESET}: {len(p.hand)} cartas, {p.life_count()} vidas, {len(p.deck)} no deck')

        first_name = self.name_a if self.state_a.is_first else self.name_b
        print(f'\n{C.YELLOW}⚡ {first_name} vai primeiro!{C.RESET}')

    def play_turn(self, p, opp):
        self.global_turn += 1
        p.turn += 1
        col = self.col(p)

        sep()
        print(f'{col}{C.BOLD}TURNO {self.global_turn} '
              f'(T{p.turn} de {self.name(p).upper()}){C.RESET}')
        sep()

        # Fases de início: delegadas ao ENGINE (fonte única), com verbose
        engine_match = self._get_engine_match()
        engine_match.refresh_phase(p)
        engine_match.draw_phase(p, verbose=True)
        engine_match.don_phase(p, verbose=True)
        print_field(p, col, self.name(p))

        # Perfil do deck + fase da partida + postura (para auditoria)
        from optcg_engine.decision_engine import DecisionEngine
        eng = DecisionEngine(p, opp)
        prof = eng.analyzer.deck_profile_type()
        fase = eng.analyzer.game_phase()
        post = eng.posture()
        prio = eng.analyzer.analysis_priority()
        print(f'  {C.GRAY}[perfil: {prof} │ fase: {fase} │ postura: {post} │ prioridade: {prio}]{C.RESET}')

        # LÓGICA delegada ao ENGINE (fonte única).
        won = self._get_engine_match().main_phase(p, opp, verbose=True)
        if won:
            return 'A' if p is self.state_a else 'B'
        if not p.deck:
            return 'B' if p is self.state_a else 'A'
        if not opp.deck:
            return 'A' if p is self.state_a else 'B'
        return None

    def run(self):
        self.setup()
        winner = None

        for turn_num in range(self.MAX_TURNS * 2):
            if turn_num % 2 == 0:
                p   = self.state_a if self.state_a.is_first else self.state_b
                opp = self.state_b if self.state_a.is_first else self.state_a
            else:
                p   = self.state_b if self.state_a.is_first else self.state_a
                opp = self.state_a if self.state_a.is_first else self.state_b

            result = self.play_turn(p, opp)
            if result:
                winner = result
                break

        sep('═')
        if winner == 'A':
            print(f'{C.GREEN}{C.BOLD}🏆 VENCEDOR: {self.name_a}!{C.RESET}')
        elif winner == 'B':
            print(f'{C.GREEN}{C.BOLD}🏆 VENCEDOR: {self.name_b}!{C.RESET}')
        else:
            print(f'{C.YELLOW}{C.BOLD}⏰ EMPATE — limite de turnos{C.RESET}')

        sep()
        print(f'Turnos: {self.global_turn}')
        print(f'{self.name_a}: {self.state_a.dmg_dealt} danos, '
              f'{self.state_a.counters_used} counter, '
              f'{self.state_a.searchers_used} searchers')
        print(f'{self.name_b}: {self.state_b.dmg_dealt} danos, '
              f'{self.state_b.counters_used} counter, '
              f'{self.state_b.searchers_used} searchers')
        sep('═')


def main():
    print('Carregando dados...')
    cards_db = load_cards_db('cards_rows.csv')

    if not os.path.exists('decklists_raw.csv'):
        print('❌ decklists_raw.csv não encontrado!')
        return

    df_raw  = pd.read_csv('decklists_raw.csv')
    df_feat = pd.read_csv('features.csv') if os.path.exists('features.csv') else pd.DataFrame()

    urls = df_raw.groupby('deck_url')['deck_name'].first()
    deck_list = []

    for url, name in urls.items():
        result = build_real_deck(name, url, df_raw, cards_db)
        if not result:
            continue
        leader, cards, start_stage = result
        valido, erros = validar_deck(leader, cards, cards_db)
        if not valido:
            continue
        if len(cards) >= 40:
            deck_list.append((name, url, (leader, cards, start_stage)))
        if len(deck_list) >= 20:
            break

    if len(deck_list) < 2:
        print('❌ Decks insuficientes!')
        return

    # Mostra decks disponíveis para escolher
    print(f'\nDecks disponíveis:')
    for i, (name, url, _) in enumerate(deck_list):
        print(f'  [{i}] {name}')

    try:
        idx_a = int(input('\nEscolha o índice do Deck A [0]: ') or 0)
        idx_b = int(input('Escolha o índice do Deck B [1]: ') or 1)
    except:
        idx_a, idx_b = 0, 1

    name_a, url_a, deck_a = deck_list[idx_a]
    name_b, url_b, deck_b = deck_list[idx_b]

    # Mostra decklists completas
    leader_a, cards_a, _ = deck_a
    leader_b, cards_b, _ = deck_b
    print_deck_list(name_a, leader_a, cards_a, C.BLUE)
    print_deck_list(name_b, leader_b, cards_b, C.RED)

    input('\nPressione Enter para iniciar o replay...')

    match = ReplayMatch(deck_a, deck_b, name_a[:25], name_b[:25])
    match.run()


if __name__ == '__main__':
    main()
