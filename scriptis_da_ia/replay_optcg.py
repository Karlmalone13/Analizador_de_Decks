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
from simulador_optcg import (
    load_cards_db, build_real_deck, validar_deck,
    Card, GameState, DecisionEngine
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

        if random.random() < 0.5:
            self.state_a.is_first = True
            self.state_b.is_first = False
        else:
            self.state_a.is_first = False
            self.state_b.is_first = True

    def col(self, p): return C.BLUE if p is self.state_a else C.RED
    def name(self, p): return self.name_a if p is self.state_a else self.name_b

    def setup(self):
        sep('═')
        print(f'{C.BOLD}🏴‍☠️  OPTCG MATCH REPLAY v2.1{C.RESET}')
        sep('═')

        for p, stage, col, nm in [
            (self.state_a, self.stage_a, C.BLUE,  self.name_a),
            (self.state_b, self.stage_b, C.RED,   self.name_b),
        ]:
            random.shuffle(p.deck)
            p.hand = [p.deck.pop() for _ in range(min(5, len(p.deck)))]
            if self._mulligan(p):
                print(f'{col}{nm}: fez Mulligan!{C.RESET}')
                p.deck.extend(p.hand)
                random.shuffle(p.deck)
                p.hand = [p.deck.pop() for _ in range(min(5, len(p.deck)))]
            life_n = p.leader.life if p.leader.life > 0 else 5
            p.life = [p.deck.pop() for _ in range(min(life_n, len(p.deck)))]
            if stage:
                p.field_stage = stage
                print(f'{col}{nm}: Stage inicial → {stage.name}{C.RESET}')
            print(f'{col}{nm}{C.RESET}: {len(p.hand)} cartas, {p.life_count()} vidas, {len(p.deck)} no deck')

        first_name = self.name_a if self.state_a.is_first else self.name_b
        print(f'\n{C.YELLOW}⚡ {first_name} vai primeiro!{C.RESET}')

    def _mulligan(self, p):
        return len([c for c in p.hand if c.cost <= 2 and c.card_type != 'LEADER']) == 0

    def refresh(self, p):
        don_from_cards = sum(c.don_attached for c in p.field_chars) + p.leader.don_attached
        for c in p.field_chars:
            c.don_attached = 0
            c.rested = False
            c.just_played = False
        p.leader.don_attached = 0
        p.leader.rested = False
        # Todos os DON restados viram ativos no refresh
        p.don_available += p.don_rested + don_from_cards
        p.don_rested = 0

    def draw(self, p):
        if p.turn == 1 and p.is_first:
            return
        if p.deck:
            drawn = p.deck.pop()
            p.hand.append(drawn)
            print(f'  {C.GRAY}Comprou: {drawn.name[:30]}{C.RESET}')

    def don(self, p):
        if p.turn == 1 and p.is_first:
            gain = min(1, p.don_deck)
        else:
            gain = min(2, p.don_deck)
        p.don_deck -= gain
        p.don_available += gain
        print(f'  {C.YELLOW}DON!! +{gain} rampados │ '
              f'{p.don_available} ativos │ '
              f'{p.don_rested} restados{C.RESET}')

    def choose_card(self, p, opp):
        engine = DecisionEngine(p, opp)
        return engine.choose_card_to_play()

    def play_card(self, card, p):
        col = self.col(p)
        p.hand.remove(card)
        p.don_rested += card.cost
        p.don_available -= card.cost
        p.chars_played += 1

        kws = []
        if card.has_rush:          kws.append('Rush')
        if card.has_blocker:       kws.append('Blocker')
        if card.has_double_attack: kws.append('Double Atk')
        if card.is_searcher:       kws.append('Searcher')
        if card.has_trigger:       kws.append('Trigger')
        kw_str = f' [{", ".join(kws)}]' if kws else ''

        don_spent = f'gastou {card.cost} DON' if card.cost > 0 else 'grátis'
        print(f'  {col}▶ {don_spent} → Joga: {card.name[:28]}{C.RESET}'
              f' ({card.power}pwr){kw_str}')
        if card.cost > 0:
            print(f'    {C.YELLOW}DON restantes: {p.don_available} ativos{C.RESET}')

        if card.card_type == 'CHARACTER':
            if len(p.field_chars) >= 5:
                worst = min(p.field_chars, key=lambda c: c.power)
                p.field_chars.remove(worst)
                p.trash.append(worst)
                print(f'    {C.GRAY}Campo cheio — descartou {worst.name[:25]}{C.RESET}')

            card.rested = False
            card.just_played = not card.has_rush
            p.field_chars.append(card)

            for _ in range(card.draw_power):
                if p.deck:
                    d = p.deck.pop()
                    p.hand.append(d)
                    print(f'    {C.GRAY}Draw → {d.name[:25]}{C.RESET}')

            if card.is_searcher and p.deck:
                look = min(5, len(p.deck))
                candidates = p.deck[-look:]
                useful = [c for c in candidates
                          if c.cost >= 2 or c.has_blocker or c.has_rush or c.draw_power > 0]
                best = max(useful if useful else candidates, key=lambda c: c.board_value())
                p.deck.remove(best)
                p.hand.append(best)
                p.searchers_used += 1
                kws_s = []
                if best.has_rush:          kws_s.append('Rush')
                if best.has_blocker:       kws_s.append('Blocker')
                if best.has_double_attack: kws_s.append('DA')
                kw_s = f' [{", ".join(kws_s)}]' if kws_s else ''
                print(f'    {C.CYAN}Searcher → olhou {look} cartas, '
                      f'pegou: {best.name[:28]} (custo {best.cost}, {best.power}pwr){kw_s}{C.RESET}')
            elif card.is_searcher and not p.deck:
                print(f'    {C.GRAY}Searcher → deck vazio, nada buscado{C.RESET}')

        elif card.card_type == 'STAGE':
            if p.field_stage:
                p.trash.append(p.field_stage)
                print(f'    {C.GRAY}Stage anterior descartado{C.RESET}')
            p.field_stage = card
            print(f'    {C.PURPLE}Stage em campo: {card.name[:30]}{C.RESET}')

    def execute_attack(self, attacker, target_type, target, p, opp):
        col_p = self.col(p)
        col_o = self.col(opp)

        if attacker is p.leader:
            p.leader.rested = True
        else:
            attacker.rested = True

        atk_power = attacker.effective_power(True)
        damage = 2 if attacker.has_double_attack else 1

        tgt_name = (f'Leader {opp.leader.name[:15]}'
                    if target_type == 'leader'
                    else (target.name[:20] if target else '?'))
        defend_power = (opp.leader.power
                        if target_type == 'leader'
                        else (target.power if target else 0))

        print(f'\n  {col_p}⚔  {attacker.name[:25]} ({atk_power}pwr) '
              f'ataca {tgt_name} ({defend_power}pwr){C.RESET}')

        # Block step
        opp_engine = DecisionEngine(opp, p)
        blocker = opp_engine.should_use_blocker(atk_power)
        if blocker and not attacker.has_unblockable:
            blocker.rested = True
            target_type = 'character'
            target = blocker
            defend_power = blocker.power
            print(f'    {col_o}🛡  Blocker! {blocker.name[:25]} intercepta ({defend_power}pwr){C.RESET}')

        # Counter step
        if opp_engine.should_use_counter(atk_power, defend_power):
            needed = atk_power - defend_power + 1
            counters_av = sorted([c for c in opp.hand if c.counter > 0],
                                  key=lambda c: c.counter)
            total_used = 0
            used_names = []
            for c in counters_av:
                if total_used >= needed:
                    break
                opp.hand.remove(c)
                opp.trash.append(c)
                total_used += c.counter
                opp.counters_used += c.counter
                used_names.append(f'{c.name[:15]}(+{c.counter})')
            defend_power += total_used
            print(f'    {col_o}🛡  Counter! {" + ".join(used_names)} → poder total {defend_power}{C.RESET}')

        # Damage step
        if atk_power >= defend_power:
            if target_type == 'leader':
                for d in range(damage):
                    if not opp.life:
                        p.dmg_dealt += 1
                        print(f'  {C.YELLOW}{C.BOLD}💀 {self.name(opp)} sem vidas — DERROTA!{C.RESET}')
                        return True
                    life_card = opp.life.pop()
                    p.dmg_dealt += 1
                    trigger_str = ''
                    if life_card.has_trigger:
                        opp.triggers_activated += 1
                        opp.hand.append(life_card)
                        trigger_str = f' {C.YELLOW}[TRIGGER: {life_card.name[:20]}]{C.RESET}'
                    else:
                        opp.hand.append(life_card)
                    print(f'    {C.RED}💥 DANO! {self.name(opp)} vida: {opp.life_count()}{trigger_str}{C.RESET}')
                if not opp.life:
                    print(f'    {C.YELLOW}⚠  0 vidas — próximo ataque é LETAL!{C.RESET}')
            elif target_type == 'character' and target and target in opp.field_chars:
                opp.field_chars.remove(target)
                opp.trash.append(target)
                print(f'    {C.GREEN}💀 {target.name[:25]} foi KO!{C.RESET}')
        else:
            print(f'    {C.GRAY}✗ Ataque bloqueado ({atk_power} < {defend_power}){C.RESET}')

        return False

    def play_turn(self, p, opp):
        self.global_turn += 1
        p.turn += 1
        col = self.col(p)

        sep()
        print(f'{col}{C.BOLD}TURNO {self.global_turn} '
              f'(T{p.turn} de {self.name(p).upper()}){C.RESET}')
        sep()

        self.refresh(p)
        self.draw(p)
        self.don(p)
        print_field(p, col, self.name(p))

        # Main phase: jogar cartas
        print(f'\n{C.BOLD}── Jogando cartas ──{C.RESET}')
        plays = 0
        while plays < 8:
            card = self.choose_card(p, opp)
            if card:
                self.play_card(card, p)
                plays += 1
            else:
                if plays == 0:
                    print(f'  {C.GRAY}Nenhuma carta jogável{C.RESET}')
                break

        # Ataques
        print(f'\n{C.BOLD}── Ataques ──{C.RESET}')
        if not p.can_attack_this_turn():
            print(f'  {C.GRAY}Primeiro turno — sem ataques (regra oficial){C.RESET}')
        else:
            attackers = [c for c in p.field_chars
                         if not c.rested and not c.just_played]
            if not p.leader.rested:
                attackers.append(p.leader)

            if not attackers:
                print(f'  {C.GRAY}Nenhum atacante disponível{C.RESET}')

            for attacker in list(attackers):
                if attacker.rested:
                    continue
                engine = DecisionEngine(p, opp)

                best_score = -999
                best_action = None

                s = engine.score_attack_target(attacker, 'leader', None)
                if s > best_score:
                    best_score = s
                    best_action = (attacker, 'leader', None)

                for t in opp.rested_chars():
                    s = engine.score_attack_target(attacker, 'character', t)
                    if s > best_score:
                        best_score = s
                        best_action = (attacker, 'character', t)

                if best_action and best_score > -50:
                    a, ttype, tgt = best_action
                    if self.execute_attack(a, ttype, tgt, p, opp):
                        return 'A' if p is self.state_a else 'B'

                    if not opp.life:
                        remaining = [c for c in p.field_chars
                                     if not c.rested and not c.just_played
                                     and c is not a]
                        if not p.leader.rested and p.leader is not a:
                            remaining.append(p.leader)
                        for fin in remaining:
                            if self.execute_attack(fin, 'leader', None, p, opp):
                                return 'A' if p is self.state_a else 'B'

        for c in p.field_chars:
            c.just_played = False

        if not p.deck:
            print(f'{C.RED}Deck de {self.name(p)} vazio!{C.RESET}')
            return 'B' if p is self.state_a else 'A'
        if not opp.deck:
            print(f'{C.RED}Deck de {self.name(opp)} vazio!{C.RESET}')
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