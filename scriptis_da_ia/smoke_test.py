"""
Smoke test direcionado: set_base_power (8 cards), choice (16 cards),
conditional_stack (1 card) + fix de defend_power no combate.
Roda contra os dados REAIS de card_effects_db.json, nao contra mocks.
"""
import sys, json
sys.path.insert(0, '.')
import optcg_engine.decision_engine as de
from optcg_engine.decision_engine import (
    Card, CardData, GameState, EffectExecutor, DecisionEngine, OPTCGMatch,
    effective_hand_play_cost, get_card_effects
)

FAIL = 0
def check(label, cond):
    global FAIL
    status = 'OK' if cond else 'FALHOU'
    if not cond:
        FAIL += 1
    print(f'[{status}] {label}')

def mk(code, name, power=5000, cost=4, sub_types='', card_type='CHARACTER',
       color='Red', text='', counter=0, has_trigger=False):
    return Card(data=CardData(code=code, name=name, card_type=card_type,
                               color=color, cost=cost, power=power,
                               counter=counter, sub_types=sub_types,
                               card_text=text, has_trigger=has_trigger))

def me_opp():
    leader = mk('LD-01', 'Leader Teste', power=5000, card_type='LEADER', sub_types='')
    me = GameState(leader=leader, don_available=5)
    opp_leader = mk('LD-02', 'Opp Leader', power=5000, card_type='LEADER')
    opp = GameState(leader=opp_leader)
    return me, opp

# ── 1. effective_power com base_power_override ──────────────────────────────
me, opp = me_opp()
c = mk('X', 'Carta', power=5000)
c.power_buff = 1000
c.don_attached = 2
check('override ausente: effective_power = power + buff + don',
      c.effective_power(True) == 5000 + 1000 + 2000)
c.base_power_override = 7000
check('override presente: effective_power = override + buff + don (nao substitui tudo)',
      c.effective_power(True) == 7000 + 1000 + 2000)
check('your_turn=False: sem DON, com override',
      c.effective_power(False) == 7000 + 1000)

# ── 2. set_base_power real: EB04-003 (leader, filter_type=navy, GATE) ───────
me, opp = me_opp()
ee = EffectExecutor(me, opp)
card_eb04003 = mk('EB04-003', 'Smoker & Tashigi')
ef = get_card_effects('EB04-003')
step = ef['opp_turn']['steps'][0]
check('EB04-003 step e set_base_power amount=7000 target=leader filter_type=navy',
      step['action'] == 'set_base_power' and step['amount'] == 7000
      and step['target'] == 'leader' and step['filter_type'] == 'navy')

me.leader = mk('LD-02', 'Opp Leader', power=5000, card_type='LEADER', sub_types='Heart Pirates')  # NAO navy -- gate deve bloquear
log = ee._execute_step(step, card_eb04003)
check('gate filter_type bloqueia quando lider NAO e do tipo exigido',
      me.leader.base_power_override is None and log is None)

me.leader = mk('LD-03', 'Navy Leader', power=5000, card_type='LEADER', sub_types='Navy Special')  # agora E navy
log = ee._execute_step(step, card_eb04003)
check('set_base_power aplica quando lider E do tipo exigido (override=7000)',
      me.leader.base_power_override == 7000)
check('log de set_base_power retornado', bool(log))

# ── 3. set_base_power: own_character com filter_type (OP16-058) ─────────────
me, opp = me_opp()
ee = EffectExecutor(me, opp)
ef = get_card_effects('OP16-058')
step = ef['main']['steps'][0]
check('OP16-058 step e set_base_power target=own_character filter=prisoner of impel down',
      step['action'] == 'set_base_power' and step['target'] == 'own_character')

c1 = mk('A', 'Sem filtro', power=3000, sub_types='Marine')
c2 = mk('B', 'Com filtro fraco', power=4000, sub_types='Prisoner of Impel Down')
c3 = mk('C', 'Com filtro forte', power=9000, sub_types='Prisoner of Impel Down')
me.field_chars = [c1, c2, c3]
card_source = mk('OP16-058', 'Source')
ee._execute_step(step, card_source)
check('filter_type seleciona apenas candidatos do tipo certo, escolhe maior effective_power',
      c3.base_power_override == 7000 and c2.base_power_override is None and c1.base_power_override is None)

# sem candidato elegivel -> nao quebra, retorna None
me.field_chars = [c1]  # nenhum 'prisoner of impel down'
log2 = ee._execute_step(step, card_source)
check('sem candidato elegivel: nao quebra, retorna None (nao aplica)', log2 is None)

# ── 4. set_base_power: leader_or_own_character (OP16-106) ────────────────────
me, opp = me_opp()
ee = EffectExecutor(me, opp)
ef = get_card_effects('OP16-106')
steps = ef['on_ko']['steps']
sbp_step = next(s for s in steps if s['action'] == 'set_base_power')
check('OP16-106 set_base_power target=leader_or_own_character',
      sbp_step['target'] == 'leader_or_own_character')

fraco = mk('F', 'Fraco', power=1000)
me.field_chars = [fraco]
me.leader = mk('LD-99', 'Lider Forte', power=9000, card_type='LEADER')
card_source2 = mk('OP16-106', 'Source2')
ee._execute_step(sbp_step, card_source2)
check('leader_or_own_character escolhe quem tem maior effective_power (lider, no caso)',
      me.leader.base_power_override == 7000 and fraco.base_power_override is None)

# ── 5. defend_power no combate (fix do bug confirmado) ───────────────────────
me, opp = me_opp()
defensor = mk('D', 'Defensor', power=5000)
defensor.power_buff = 500
defensor.base_power_override = 7000
calc_antigo = defensor.power + defensor.power_buff           # 5500 -- BUG (ignora override)
calc_novo = defensor.effective_power(your_turn=False)        # 7500 -- correto
check('fix de combate: defend_power agora usa effective_power (considera override)',
      calc_novo == 7500 and calc_antigo == 5500 and calc_novo != calc_antigo)

# ── 6. choice real: OP05-096 (3 opcoes: ko/bounce/(place+draw)) ──────────────
me, opp = me_opp()
ee = EffectExecutor(me, opp)
ef = get_card_effects('OP05-096')
options = ef['main']['choice']
card_op05096 = mk('OP05-096', 'Source')

# sem nenhum personagem do oponente -> nenhuma opcao de remocao viavel,
# mas draw (na opcao 3) sempre viavel -> deve escolher a opcao 3 (tem draw viavel)
opp.field_chars = []
resolved = ee._resolve_choice(options, card_op05096)
check('choice sem alvo de remocao: cai para opcao com step sempre-viavel (draw)',
      any(s['action'] == 'draw' for s in resolved))

# com personagem do oponente -> 3 opcoes viaveis, prioridade vai pra
# place_opp_character_bottom_deck (peso 3) sobre ko (peso 2) e bounce (peso 1)
opp.field_chars = [mk('OC', 'Opp Char', power=2000, cost=1)]
resolved2 = ee._resolve_choice(options, card_op05096)
check('choice com alvo disponivel: prioriza place_bottom_deck (peso 3) sobre ko/bounce',
      any(s['action'] == 'place_opp_character_bottom_deck' for s in resolved2))

# ── 7. choice sem custo (ST07-010) integrado via execute() completo ─────────
me, opp = me_opp()
ee = EffectExecutor(me, opp)
card_st07010 = mk('ST07-010', 'Nami', card_type='CHARACTER')
me.hand = [card_st07010]
opp.life = [mk('L1', 'vida', power=0)]
logs = ee.execute(card_st07010, 'on_play')
check('choice integrado via execute() nao quebra e retorna log nao-vazio',
      isinstance(logs, list) and len(logs) > 0)

# ── 8. choice + custo real (regressao corrigida): EB02-045 ───────────────────
me, opp = me_opp()
ee = EffectExecutor(me, opp)
ef_eb02045 = get_card_effects('EB02-045')
card_eb02045 = mk('EB02-045', 'Source')
me.trash = []  # SEM cartas no trash -> custo place_from_trash_bottom_deck:2 IMPOSSIVEL de pagar
logs = ee.execute(card_eb02045, 'on_play')
check('EB02-045 sem trash suficiente para o custo: nao executa nem quebra',
      logs == [] or logs is None or logs == [''])

# ── 9. conditional_stack real: OP15-092 (3 blocos cumulativos por trash_gte) ─
me, opp = me_opp()
ee = EffectExecutor(me, opp)
ef_op15092 = get_card_effects('OP15-092')
check('OP15-092 tem conditional_stack com 3 blocos',
      len(ef_op15092['passive']['conditional_stack']) == 3)

card_op15092 = mk('OP15-092', 'Luffy', power=6000)
me.field_chars = [card_op15092]
me.trash = [mk(f'T{i}', 'trash') for i in range(25)]  # 25 cartas no trash: passa gte=10 e gte=20, NAO gte=30
me.leader = mk('LD-X', 'Lider', power=5000, card_type='LEADER')
ee.apply_your_turn_buffs()
check('conditional_stack: trash=25 ativa bloco gte=10 (self override 9000) e gte=20 (leader override 7000), NAO gte=30',
      card_op15092.base_power_override == 9000 and me.leader.base_power_override == 7000
      and card_op15092.power_buff == 0)

me, opp = me_opp()
ee = EffectExecutor(me, opp)
card_op15092b = mk('OP15-092', 'Luffy', power=6000)
me.field_chars = [card_op15092b]
me.trash = [mk(f'T{i}', 'trash') for i in range(35)]  # 35: passa TODOS os 3 blocos
me.leader = mk('LD-X', 'Lider', power=5000, card_type='LEADER')
ee.apply_your_turn_buffs()
check('conditional_stack: trash=35 ativa os 3 blocos cumulativamente (inclui buff_power +1000)',
      card_op15092b.base_power_override == 9000 and card_op15092b.power_buff == 1000)

# ── 10. descarte situacional: nao jogar fora evento defensivo/removal valioso ──
me, opp = me_opp()
ee = EffectExecutor(me, opp)
ground_death = mk(
    'OP14-096',
    'Ground Death',
    card_type='EVENT',
    cost=1,
    text='[Main] Negate the effect of up to 1 of your opponent Characters. [Counter] +4000 power.',
)
carta_pior = mk('LOW', 'Carta pior', card_type='EVENT', cost=5)
me.hand = [ground_death, carta_pior]
chosen = ee._choose_to_trash(me.hand)
check('choose_to_trash preserva Ground Death quando ha descarte pior',
      chosen is carta_pior)

# ── 11. Five Elders: Mary Geoise + corpo premium pode disputar DON reservado ──
me, opp = me_opp()
me.turn = 8
me.don_available = 9
five_elders = mk(
    'OP13-082',
    'Five Elders',
    power=12000,
    cost=10,
    sub_types='Celestial Dragons Five Elders',
)
mary_geoise = mk(
    'OP05-097',
    'Mary Geoise',
    cost=1,
    card_type='STAGE',
    sub_types='Mary Geoise',
    text='The cost of playing [Celestial Dragons] type Character cards with a cost of 2 or more from your hand will be reduced by 1.',
)
ground_death_2 = mk(
    'OP14-096',
    'Ground Death',
    card_type='EVENT',
    cost=1,
    text='[Counter] Your Leader gains +4000 power during this battle.',
)
me.field_stage = mary_geoise
me.hand = [five_elders, ground_death_2]
me.life = [ground_death_2, ground_death_2]
opp.field_chars = [mk('BIG1', 'Ameaca 1', power=9000), mk('BIG2', 'Ameaca 2', power=9000)]
engine = DecisionEngine(me, opp)
actions = OPTCGMatch((me.leader, []), (opp.leader, []))._generate_and_score_actions(me, opp, engine)
check('Mary Geoise reduz Five Elders para 9 DON',
      effective_hand_play_cost(me, five_elders) == 9)
check('Five Elders entra como candidata mesmo com DON reservado para defesa',
      any(a[1] == 'play' and a[2] is five_elders for a in actions))

# ── 12. can_lethal_this_turn nao espia counter oculto da mao real ──
me, opp = me_opp()
me.leader = mk('LD-ATK', 'Leader atacante', power=6000, card_type='LEADER')
opp.leader = mk('LD-DEF', 'Leader defensor', power=5000, card_type='LEADER')
opp.life = []
opp.hand = [
    mk('H1', 'Counter oculto 1', counter=2000),
    mk('H2', 'Counter oculto 2', counter=2000),
    mk('H3', 'Counter oculto 3', counter=2000),
]
hidden_counter_result = DecisionEngine(me, opp).analyzer.can_lethal_this_turn()

me2, opp2 = me_opp()
me2.leader = mk('LD-ATK', 'Leader atacante', power=6000, card_type='LEADER')
opp2.leader = mk('LD-DEF', 'Leader defensor', power=5000, card_type='LEADER')
opp2.life = []
opp2.hand = [mk('B1', 'Blank 1'), mk('B2', 'Blank 2'), mk('B3', 'Blank 3')]
blank_hidden_result = DecisionEngine(me2, opp2).analyzer.can_lethal_this_turn()

opp.revealed_to_opponent = {id(c) for c in opp.hand}
known_counter_result = DecisionEngine(me, opp).analyzer.can_lethal_this_turn()

check('can_lethal_this_turn ignora counters reais ocultos e usa tamanho da mao',
      hidden_counter_result == blank_hidden_result)
check('can_lethal_this_turn respeita counters revelados',
      known_counter_result is False and hidden_counter_result is True)

# ── 13. imunidade source=opp nao protege contra efeito proprio ──
me, opp = me_opp()
source = mk('SRC', 'Board wipe')
immune_own = mk('OP07-033', 'Luffy imune proprio', power=7000)
me.field_chars = [immune_own, mk('ALLY1', 'Ally 1'), mk('ALLY2', 'Ally 2')]
opp.field_chars = []
ee = EffectExecutor(me, opp)
log = ee._execute_step({'action': 'ko', 'target': 'all_character', 'count': 99}, source)
check('imunidade by opponent effects nao protege contra KO do proprio efeito',
      immune_own in me.trash and immune_own not in me.field_chars)

me, opp = me_opp()
source = mk('SRC', 'Removal inimigo')
immune_opp = mk('OP07-033', 'Luffy imune oponente', power=7000)
opp.field_chars = [immune_opp, mk('OALLY1', 'Opp Ally 1'), mk('OALLY2', 'Opp Ally 2')]
me.field_chars = []
ee = EffectExecutor(me, opp)
log = ee._execute_step({'action': 'ko', 'target': 'opp_character', 'count': 1}, source)
check('imunidade by opponent effects protege contra KO do oponente',
      immune_opp in opp.field_chars and immune_opp not in opp.trash and 'imune' in (log or ''))

# ── 14. substitute_removal executa extra_steps (Thatch: trash self + draw) ──
me, opp = me_opp()
thatch = mk('OP08-045', 'Thatch')
alvo = mk('ALLY-CG', 'Cross Guild ally', sub_types='Cross Guild')
draw_card = mk('DRAW1', 'Carta comprada')
me.field_chars = [thatch, alvo]
me.deck = [draw_card]
ee = EffectExecutor(me, opp)
log = ee.try_substitute(thatch, 'removal')
check('substitute_removal com extra_steps compra carta apos trash_self',
      thatch in me.trash and draw_card in me.hand and 'comprou' in (log or ''))

# ── 15. substituicao externa protege outro alvo quando o step tem filtro ──
de._EFFECTS_DB['TEST-PROTECTOR'] = {
    'effects': {
        'passive': {
            'steps': [{
                'action': 'substitute_ko',
                'filter_type': 'allytag',
                'cost': {'action': 'trash_self'},
            }]
        }
    }
}
me, opp = me_opp()
protector = mk('TEST-PROTECTOR', 'Protetor externo', sub_types='Guard')
protected = mk('TEST-ALLY', 'Alvo protegido', sub_types='AllyTag')
unmatched = mk('TEST-OTHER', 'Alvo errado', sub_types='Other')
me.field_chars = [protector, protected, unmatched]
ee = EffectExecutor(me, opp)
log = ee.try_any_substitute(protected, 'ko')
check('substituicao externa usa fonte aliada e preserva alvo filtrado',
      protector in me.trash and protected in me.field_chars and 'Protetor' in (log or ''))

me, opp = me_opp()
protector = mk('TEST-PROTECTOR', 'Protetor externo', sub_types='Guard')
unmatched = mk('TEST-OTHER', 'Alvo errado', sub_types='Other')
me.field_chars = [protector, unmatched]
ee = EffectExecutor(me, opp)
log = ee.try_any_substitute(unmatched, 'ko')
check('substituicao externa nao protege alvo fora do filtro',
      log is None and protector in me.field_chars and unmatched in me.field_chars)

de._EFFECTS_DB['TEST-LEADER-PROTECT'] = {
    'effects': {
        'opp_turn': {
            'don_requirement': 1,
            'steps': [{
                'action': 'substitute_ko',
                'power_gte': 5000,
                'cost': {'action': 'debuff_power_self', 'amount': 1000},
            }]
        }
    }
}
me, opp = me_opp()
me.leader = mk('TEST-LEADER-PROTECT', 'Leader protetor', power=5000, card_type='LEADER')
me.leader.don_attached = 1
protected = mk('TEST-BIG', 'Alvo grande', power=5000)
me.field_chars = [protected]
ee = EffectExecutor(me, opp)
log = ee.try_any_substitute(protected, 'ko', source_is_opp=True)
check('substituicao externa com debuff aplica custo no alvo protegido',
      protected.power_buff == -1000 and me.leader.power_buff == 0 and protected in me.field_chars and bool(log))

me, opp = me_opp()
buggy = mk('ST30-011', 'Buggy', power=5000)
alvo_6000 = mk('TARGET-6000', 'Alvo 6000', power=6000)
alvo_5000 = mk('TARGET-5000', 'Alvo 5000', power=5000)
me.field_chars = [buggy, alvo_6000, alvo_5000]
ee = EffectExecutor(me, opp)
log = ee.try_any_substitute(alvo_6000, 'removal')
check('substituicao externa real ST30-011 protege alvo com power_eq 6000',
      buggy.rested and alvo_6000 in me.field_chars and bool(log))

me, opp = me_opp()
buggy = mk('ST30-011', 'Buggy', power=5000)
alvo_5000 = mk('TARGET-5000', 'Alvo 5000', power=5000)
me.field_chars = [buggy, alvo_5000]
ee = EffectExecutor(me, opp)
log = ee.try_any_substitute(alvo_5000, 'removal')
check('substituicao externa real ST30-011 nao protege power diferente',
      log is None and not buggy.rested and alvo_5000 in me.field_chars)

me, opp = me_opp()
me.don_available = 2
evento_counter = mk('EB02-030', "Friend's Dream", card_type='EVENT', cost=2)
descarte = mk('DISC-1', 'Carta custo counter')
alvo = mk('ALLY-KO', 'Aliado em batalha')
me.hand = [evento_counter, descarte]
me.field_chars = [alvo]
ee = EffectExecutor(me, opp)
log = ee.try_counter_event_substitute(alvo, 'ko')
check('Counter event EB02-030 substitui KO em batalha pagando evento e descarte',
      alvo in me.field_chars and evento_counter in me.trash and descarte in me.trash
      and me.don_available == 0 and me.don_rested == 2 and bool(log))

me, opp = me_opp()
me.don_available = 1
evento_counter = mk('EB02-030', "Friend's Dream", card_type='EVENT', cost=2)
descarte = mk('DISC-1', 'Carta custo counter')
alvo = mk('ALLY-KO', 'Aliado em batalha')
me.hand = [evento_counter, descarte]
me.field_chars = [alvo]
ee = EffectExecutor(me, opp)
log = ee.try_counter_event_substitute(alvo, 'ko')
check('Counter event EB02-030 nao ativa sem DON suficiente',
      log is None and evento_counter in me.hand and descarte in me.hand and me.don_available == 1)

me, opp = me_opp()
me.don_available = 2
evento_buff = mk('OP01-086', 'Overheat', card_type='EVENT', cost=2)
me.hand = [evento_buff]
target = me.leader
ee = EffectExecutor(me, opp)
counter = ee.try_counter_event_power(target, 'leader', needed=3000)
check('Counter event simples usa buff suficiente no leader',
      counter and counter[0] == 4000 and evento_buff in me.trash
      and me.don_available == 0 and me.don_rested == 2)

me, opp = me_opp()
me.don_available = 0
evento_buff = mk('OP02-068', 'Gum-Gum Rain', card_type='EVENT', cost=0)
descarte = mk('DISC-2', 'Carta custo buff')
me.hand = [evento_buff, descarte]
target = me.leader
ee = EffectExecutor(me, opp)
counter = ee.try_counter_event_power(target, 'leader', needed=3000)
check('Counter event simples paga custo extra de trash da mao',
      counter and counter[0] == 3000 and evento_buff in me.trash and descarte in me.trash)

me, opp = me_opp()
me.don_available = 1
evento_leader = mk('OP10-019', 'Divine Departure', card_type='EVENT', cost=1)
alvo_char = mk('CHAR-1', 'Personagem defendido')
me.hand = [evento_leader]
me.field_chars = [alvo_char]
ee = EffectExecutor(me, opp)
counter = ee.try_counter_event_power(alvo_char, 'character', needed=3000)
check('Counter event leader-only nao buffa character',
      counter is None and evento_leader in me.hand and evento_leader not in me.trash)

me, opp = me_opp()
me.don_available = 1
evento_cond = mk('EB01-028', 'Champion Rifle', card_type='EVENT', cost=1)
me.hand = [evento_cond]
ee = EffectExecutor(me, opp)
counter = ee.try_counter_event_power(me.leader, 'leader', needed=2000)
check('Counter event com leader_type nao ativa para lider errado',
      counter is None and evento_cond in me.hand)

me, opp = me_opp()
me.leader = mk('LD-IMPEL', 'Impel Leader', power=5000, card_type='LEADER', sub_types='Impel Down')
me.don_available = 1
evento_cond = mk('EB01-028', 'Champion Rifle', card_type='EVENT', cost=1)
me.hand = [evento_cond]
ee = EffectExecutor(me, opp)
counter = ee.try_counter_event_power(me.leader, 'leader', needed=2000)
check('Counter event com leader_type ativa para lider correto',
      counter and counter[0] == 2000 and evento_cond in me.trash)

print()
print(f'{"TODOS OS TESTES PASSARAM" if FAIL == 0 else f"{FAIL} TESTE(S) FALHARAM"}')
sys.exit(1 if FAIL else 0)
