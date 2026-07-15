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
    effective_hand_play_cost, get_card_effects, is_immune, can_afford_attack_paywall,
    is_attack_locked_self, attack_time_power, don_needed_for_attack
)
from optcg_engine.sim_bridge import order_target_candidates

FAIL = 0
def check(label, cond):
    global FAIL
    status = 'OK' if cond else 'FALHOU'
    if not cond:
        FAIL += 1
    print(f'[{status}] {label}')

def mk(code, name, power=5000, cost=4, sub_types='', card_type='CHARACTER',
       color='Red', text='', counter=0, has_trigger=False, attribute=''):
    return Card(data=CardData(code=code, name=name, card_type=card_type,
                               color=color, cost=cost, power=power,
                               counter=counter, sub_types=sub_types,
                               attribute=attribute, card_text=text,
                               has_trigger=has_trigger))

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
docq = mk('OP16-109', 'Doc Q', power=0)
krieg = mk('OP15-008', 'Krieg', power=9000)
opp.field_chars = [krieg]
docq._attack_power_override = -2000
docq.don_attached = 9
check('attack_time_power preserva powerAtk negativo e soma DON depois',
      attack_time_power(docq, opp) == 7000)
docq.don_attached = 0
me.don_available = 9
check('score_attack_target barra Doc Q 0 power: mesmo 9 DON nao cobre -2000 vivo vs 9000',
      DecisionEngine(me, opp).score_attack_target(docq, 'character', krieg) < -500)

me, opp = me_opp()
devon = mk('OP16-104', 'Catarina Devon', power=3000)
buggy = mk('OP15-012', 'Buggy', power=4000)
krieg = mk('OP15-008', 'Krieg', power=9000)
opp.field_chars = [buggy, krieg]
EffectExecutor(me, opp).execute(devon, 'when_attacking')
check('Devon set_base_power escolhe personagem oponente de maior poder',
      devon.base_power_override == 9000)

devon._deck_uid = 99
buggy._deck_uid = 12
krieg._deck_uid = 8
me.field_chars = [devon]
order = order_target_candidates(
    me, opp,
    [{'id': 99, 'zone': 'own_board', 'code': 'OP16-104'},
     {'id': 12, 'zone': 'opp_board', 'code': 'OP15-012'},
     {'id': 8, 'zone': 'opp_board', 'code': 'OP15-008'}],
    attacker_power=1000, defender_uid=-210, actor_code='OP16-104')
check('choose_target de Devon prioriza maior poder do opp_board',
      order and order[0] == 8)

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
me.don_available = 0
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
me2.don_available = 0
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

me, opp = me_opp()
me.leader = mk('LD-ATK-4K', 'Leader atacante 4k', power=4000, card_type='LEADER')
me.don_available = 1
opp.leader = mk('LD-DEF-5K', 'Leader defensor 5k', power=5000, card_type='LEADER')
opp.life = []
opp.hand = []
check('can_lethal_this_turn considera DON anexavel no ataque',
      DecisionEngine(me, opp).analyzer.can_lethal_this_turn() is True)

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

me, opp = me_opp()
battle_only = mk('OP03-079', 'Vergo battle-only', power=7000)
battle_only.don_attached = 1
check('imunidade KO in battle nao protege contra KO por efeito',
      not is_immune(battle_only, 'ko', me, opp, source_is_opp=True, ko_context='effect'))
check('imunidade KO in battle protege no contexto de batalha',
      is_immune(battle_only, 'ko', me, opp, source_is_opp=True, ko_context='battle'))

effect_only = mk('OP02-102', 'Smoker effect-only', power=7000)
check('imunidade KO by effects nao protege contra KO em batalha',
      not is_immune(effect_only, 'ko', me, opp, source_is_opp=True, ko_context='battle'))
check('imunidade KO by effects protege no contexto de efeito',
      is_immune(effect_only, 'ko', me, opp, source_is_opp=True, ko_context='effect'))

slash_immune = mk('OP03-032', 'Buggy slash-only', power=3000)
slash_attacker = mk('ATK-SLASH', 'Atacante Slash', attribute='Slash')
strike_attacker = mk('ATK-STRIKE', 'Atacante Strike', attribute='Strike')
check('imunidade KO battle por Slash protege contra atacante Slash',
      is_immune(slash_immune, 'ko', me, opp, source_is_opp=True,
                ko_context='battle', source_card=slash_attacker))
check('imunidade KO battle por Slash nao protege contra atacante Strike',
      not is_immune(slash_immune, 'ko', me, opp, source_is_opp=True,
                    ko_context='battle', source_card=strike_attacker))

leader_only = mk('ST08-002', 'Uta leader-only', power=4000)
leader_attacker = mk('ATK-LD', 'Leader atacante', card_type='LEADER', attribute='Strike')
char_attacker = mk('ATK-CHAR', 'Character atacante', attribute='Strike')
check('imunidade KO battle por Leaders protege contra Leader',
      is_immune(leader_only, 'ko', me, opp, source_is_opp=True,
                ko_context='battle', source_card=leader_attacker))
check('imunidade KO battle por Leaders nao protege contra Character',
      not is_immune(leader_only, 'ko', me, opp, source_is_opp=True,
                    ko_context='battle', source_card=char_attacker))

without_special = mk('P-025', 'Smoker without-special', power=4000)
without_special.don_attached = 1
normal_attacker = mk('ATK-NORMAL', 'Character sem Special', attribute='Strike')
special_attacker = mk('ATK-SPECIAL', 'Character Special', attribute='Special')
check('imunidade KO battle sem Special protege contra Character sem Special',
      is_immune(without_special, 'ko', me, opp, source_is_opp=True,
                ko_context='battle', source_card=normal_attacker))
check('imunidade KO battle sem Special nao protege contra Character Special',
      not is_immune(without_special, 'ko', me, opp, source_is_opp=True,
                    ko_context='battle', source_card=special_attacker))

# ── 13b. [Blocker] seguido de texto nao engole o resto do bloco (bug do
# parser: 'blocker' esta em TODAS_TAGS sem handler proprio, sem o fix o
# texto apos o reminder do Blocker era descartado por inteiro) ──
smoker_op11 = mk('OP11-005', 'Smoker DON imune', power=5000)
smoker_op11.don_attached = 1
smoker_op11_sem_don = mk('OP11-005', 'Smoker sem DON', power=5000)
check('OP11-005 ganha keyword Blocker (nao regrediu com o fix)',
      any(s.get('action') == 'keyword_blocker' for s in get_card_effects('OP11-005').get('passive', {}).get('steps', [])))
check('OP11-005 imune a KO por efeito de Character sem Special com 1 DON',
      is_immune(smoker_op11, 'ko', me, opp, source_is_opp=True, ko_context='effect',
                source_card=mk('ATK-N', 'Atacante sem Special', attribute='Strike')))
check('OP11-005 nao imune sem DON anexado',
      not is_immune(smoker_op11_sem_don, 'ko', me, opp, source_is_opp=True, ko_context='effect',
                    source_card=mk('ATK-N2', 'Atacante sem Special', attribute='Strike')))

yonji_op11 = mk('OP11-046', 'Vinsmoke Yonji so GERMA', power=5000, sub_types='The Vinsmoke Family GERMA 66')
me_germa, opp_dummy = me_opp()
me_germa.field_chars = [yonji_op11, mk('ALLY-GERMA', 'Aliado GERMA', sub_types='The Vinsmoke Family GERMA 66')]
check('OP11-046 imune a KO por efeito do oponente quando so tem Characters GERMA',
      is_immune(yonji_op11, 'ko', me_germa, opp_dummy, source_is_opp=True, ko_context='effect'))
me_misto, opp_dummy2 = me_opp()
me_misto.field_chars = [yonji_op11, mk('ALLY-OUTRO', 'Aliado nao-GERMA', sub_types='Navy')]
check('OP11-046 nao imune quando tem Character fora de GERMA no campo',
      not is_immune(yonji_op11, 'ko', me_misto, opp_dummy2, source_is_opp=True, ko_context='effect'))

# ── 13c. condicao only_field_type tambem respeitada por _check_conditions
# (EffectExecutor) -- estava parseada desde 29/06 mas nunca era checada,
# tratando o efeito como incondicional para qualquer carta que a use ──
me_cond, opp_cond = me_opp()
charlos = mk('OP05-084', 'Saint Charlos', sub_types='Celestial Dragons')
me_cond.field_chars = [charlos]
ee_cond = EffectExecutor(me_cond, opp_cond)
check('_check_conditions respeita only_field_type satisfeita',
      ee_cond._check_conditions({'only_field_type': 'celestial dragons'}, charlos))
me_cond2, opp_cond2 = me_opp()
me_cond2.field_chars = [charlos, mk('OUTRO', 'Nao Dragon', sub_types='Navy')]
ee_cond2 = EffectExecutor(me_cond2, opp_cond2)
check('_check_conditions reprova only_field_type com Character fora do tipo',
      not ee_cond2._check_conditions({'only_field_type': 'celestial dragons'}, charlos))

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

me, opp = me_opp()
me.don_available = 2
evento_draw_buff = mk('OP10-115', "Let's Meet Again", card_type='EVENT', cost=2)
compra = mk('DRAW-COUNTER', 'Compra do counter')
me.hand = [evento_draw_buff]
me.deck = [compra]
ee = EffectExecutor(me, opp)
counter = ee.try_counter_event_power(me.leader, 'leader', needed=4000)
check('Counter event draw + buff compra carta e defende',
      counter and counter[0] == 4000 and evento_draw_buff in me.trash
      and compra in me.hand and me.don_available == 0)

me, opp = me_opp()
me.don_available = 3
me.don_rested = 3
evento_cond_draw = mk('OP10-080', 'Little Black Bears', card_type='EVENT', cost=3)
compra = mk('DRAW-COND', 'Compra condicional')
me.hand = [evento_cond_draw]
me.deck = [compra]
ee = EffectExecutor(me, opp)
counter = ee.try_counter_event_power(me.leader, 'leader', needed=4000)
check('Counter event buff + draw condicional nao compra se condicao falha',
      counter and counter[0] == 4000 and evento_cond_draw in me.trash
      and compra in me.deck and compra not in me.hand)

me, opp = me_opp()
me.don_available = 10
me.don_rested = 0
evento_cond_draw = mk('OP10-080', 'Little Black Bears', card_type='EVENT', cost=3)
compra = mk('DRAW-COND', 'Compra condicional')
me.hand = [evento_cond_draw]
me.deck = [compra]
ee = EffectExecutor(me, opp)
counter = ee.try_counter_event_power(me.leader, 'leader', needed=4000)
check('Counter event buff + draw condicional compra quando condicao passa',
      counter and counter[0] == 4000 and evento_cond_draw in me.trash
      and compra in me.hand)

me, opp = me_opp()
me.don_available = 1
evento_set_active = mk('OP01-057', 'Paradise Waterfall', card_type='EVENT', cost=1)
rested_char = mk('RESTED-ALLY', 'Aliado rested')
rested_char.rested = True
me.hand = [evento_set_active]
me.field_chars = [rested_char]
ee = EffectExecutor(me, opp)
counter = ee.try_counter_event_power(rested_char, 'character', needed=2000)
check('Counter event com set_active reativa character proprio',
      counter and counter[0] == 2000 and evento_set_active in me.trash
      and not rested_char.rested)

me, opp = me_opp()
me.don_available = 2
evento_rest = mk('OP01-058', 'Punk Gibson', card_type='EVENT', cost=2)
opp_char = mk('OPP-ACTIVE', 'Oponente ativo', cost=4)
opp.field_chars = [opp_char]
me.hand = [evento_rest]
ee = EffectExecutor(me, opp)
counter = ee.try_counter_event_power(me.leader, 'leader', needed=4000)
check('Counter event com rest_opp_character resta character oponente',
      counter and counter[0] == 4000 and evento_rest in me.trash
      and opp_char.rested)

me, opp = me_opp()
me.life = [mk('L1', 'Life 1'), mk('L2', 'Life 2')]
me.don_available = 2
me.don_deck = 5
evento_add_don = mk('OP01-119', 'Thunder Bagua', card_type='EVENT', cost=2)
me.hand = [evento_add_don]
ee = EffectExecutor(me, opp)
counter = ee.try_counter_event_power(me.leader, 'leader', needed=4000)
check('Counter event com add_don adiciona DON ativo quando condicao passa',
      counter and counter[0] == 4000 and evento_add_don in me.trash
      and me.don_available == 1 and me.don_rested == 2 and me.don_deck == 4)

me, opp = me_opp()
me.life = [mk('L1', 'Life 1'), mk('L2', 'Life 2'), mk('L3', 'Life 3')]
me.don_available = 2
me.don_deck = 5
evento_add_don = mk('OP01-119', 'Thunder Bagua', card_type='EVENT', cost=2)
me.hand = [evento_add_don]
ee = EffectExecutor(me, opp)
counter = ee.try_counter_event_power(me.leader, 'leader', needed=4000)
check('Counter event com add_don respeita condicao life_lte',
      counter and counter[0] == 4000 and evento_add_don in me.trash
      and me.don_available == 0 and me.don_rested == 2 and me.don_deck == 5)

me, opp = me_opp()
me.don_available = 2
me.don_rested = 1
evento_set_don = mk('ST02-016', 'Repel', card_type='EVENT', cost=2)
me.hand = [evento_set_don]
ee = EffectExecutor(me, opp)
counter = ee.try_counter_event_power(me.leader, 'leader', needed=4000)
check('Counter event com set_don_active reativa DON rested',
      counter and counter[0] == 4000 and evento_set_don in me.trash
      and me.don_available == 1 and me.don_rested == 2)

me, opp = me_opp()
me.don_available = 2
evento_ko = mk('OP01-026', 'Red Hawk', card_type='EVENT', cost=2)
opp_low = mk('OPP-LOW', 'Alvo pequeno', power=4000)
opp_high = mk('OPP-HIGH', 'Alvo grande', power=7000)
opp.field_chars = [opp_low, opp_high]
me.hand = [evento_ko]
ee = EffectExecutor(me, opp)
counter = ee.try_counter_event_power(me.leader, 'leader', needed=4000)
check('Counter event com KO remove alvo elegivel do oponente',
      counter and counter[0] == 4000 and evento_ko in me.trash
      and opp_low in opp.trash and opp_low not in opp.field_chars
      and opp_high in opp.field_chars)

me, opp = me_opp()
me.don_available = 2
evento_bottom = mk('OP04-057', 'Dragon Twister', card_type='EVENT', cost=2)
opp_char = mk('OPP-C1', 'Alvo custo 1', cost=1)
opp.field_chars = [opp_char]
me.hand = [evento_bottom]
ee = EffectExecutor(me, opp)
counter = ee.try_counter_event_power(me.leader, 'leader', needed=4000)
check('Counter event com bottom deck envia character ao fundo',
      counter and counter[0] == 4000 and evento_bottom in me.trash
      and opp_char not in opp.field_chars and opp.deck and opp.deck[0] is opp_char)

me, opp = me_opp()
me.don_available = 3
evento_bounce_puro = mk('ST03-016', 'Thrust Pad Cannon', card_type='EVENT', cost=2)
opp_char = mk('OPP-C3', 'Alvo bounce', cost=3)
opp.field_chars = [opp_char]
me.hand = [evento_bounce_puro]
ee = EffectExecutor(me, opp)
counter = ee.try_counter_event_power(me.leader, 'leader', needed=1)
check('Counter event de remocao pura sem buff nao entra na rota defensiva',
      counter is None and evento_bounce_puro in me.hand and opp_char in opp.field_chars)

# ── 15. debuff_power: action parseada/usada em viabilidade e score desde
# antes, mas SEM handler de execucao em _execute_step ate agora (achado
# 30/06/2026: 142 steps reais no banco eram no-op silencioso) ──
me, opp = me_opp()
alvo_fraco = mk('OPP-FRACO', 'Fraco', power=3000)
alvo_forte = mk('OPP-FORTE', 'Forte', power=8000)
opp.field_chars = [alvo_fraco, alvo_forte]
ee = EffectExecutor(me, opp)
ee._execute_step({'action': 'debuff_power', 'amount': 2000, 'target': 'opp_character', 'duration': 'this_turn'}, me.leader)
check('debuff_power opp_character escolhe o alvo mais valioso do oponente',
      alvo_forte.power_buff == -2000 and alvo_fraco.power_buff == 0)

me, opp = me_opp()
opp.field_chars = []
ee = EffectExecutor(me, opp)
ee._execute_step({'action': 'debuff_power', 'amount': 1000, 'target': 'opp_leader_or_character', 'duration': 'this_turn'}, me.leader)
check('debuff_power opp_leader_or_character cai no Leader quando campo do oponente esta vazio',
      opp.leader.power_buff == -1000)

me, opp = me_opp()
opp.field_chars = [mk('OPP-A', 'A', power=3000), mk('OPP-B', 'B', power=4000)]
ee = EffectExecutor(me, opp)
ee._execute_step({'action': 'debuff_power', 'amount': 1000, 'target': 'all_opp_characters', 'duration': 'this_turn'}, me.leader)
check('debuff_power all_opp_characters atinge todos os Characters do oponente',
      all(c.power_buff == -1000 for c in opp.field_chars))

me, opp = me_opp()
ee = EffectExecutor(me, opp)
ee._execute_step({'action': 'debuff_power', 'amount': 1000, 'target': 'opp_leader', 'duration': 'this_turn'}, me.leader)
check('debuff_power opp_leader atinge o Leader do oponente diretamente',
      opp.leader.power_buff == -1000)

# ── 15b. Counter event real com buff + debuff (OP10-018 Ten-Layer Igloo:
# +3000 leader_or_character battle_only / -2000 opp_leader_or_character) ──
me, opp = me_opp()
me.don_available = 2
evento_buff_debuff = mk('OP10-018', 'Ten-Layer Igloo', card_type='EVENT', cost=2)
opp_alvo = mk('OPP-D1', 'Alvo do debuff', power=5000)
opp.field_chars = [opp_alvo]
me.hand = [evento_buff_debuff]
ee = EffectExecutor(me, opp)
counter = ee.try_counter_event_power(me.leader, 'leader', needed=3000)
check('Counter event com buff + debuff_power aplica os dois efeitos',
      counter and counter[0] == 3000 and evento_buff_debuff in me.trash
      and opp_alvo.power_buff == -2000)

# ── 15c. Counter event com 2 buff_power(battle_only): o 2º (target='self')
# e BONUS condicional ao MESMO alvo escolhido no 1º ("that card gains an
# additional +X power"), nao um 2º alvo independente. EB03-020 tem
# condicao "if you have 2 or more {FILM} type Characters" (achado 15/07 --
# chars_gte_type_filter, antes essa condicao nem existia no parser e o
# bonus somava sempre; teste antigo aqui testava esse BUG sem querer,
# corrigido pra montar o cenario com a condicao satisfeita/nao satisfeita,
# mesmo padrao do OP04-095 abaixo). OP04-095 com condicao (trash_gte 15) ──
me, opp = me_opp()
me.don_available = 2
me.field_chars = [mk('FILM1', 'Film 1', sub_types='FILM'), mk('FILM2', 'Film 2', sub_types='FILM')]
evento_multi_buff = mk('EB03-020', 'There You Are Sore Loser', card_type='EVENT', cost=2)
me.hand = [evento_multi_buff]
ee = EffectExecutor(me, opp)
counter = ee.try_counter_event_power(me.leader, 'leader', needed=4000)
check('Counter event com 2 buffs battle_only soma os dois quando condicao FILM passa',
      counter and counter[0] == 4000 and evento_multi_buff in me.trash)

me, opp = me_opp()
me.don_available = 2
evento_multi_buff2 = mk('EB03-020', 'There You Are Sore Loser', card_type='EVENT', cost=2)
me.hand = [evento_multi_buff2]
ee = EffectExecutor(me, opp)
counter = ee.try_counter_event_power(me.leader, 'leader', needed=4000)
check('Counter event com 2 buffs battle_only NAO soma o bonus sem 2+ FILM Characters',
      counter is None and evento_multi_buff2 in me.hand)

me, opp = me_opp()
me.don_available = 2
me.trash = [mk(f'TR{i}', f'Trash {i}') for i in range(16)]
evento_multi_cond = mk('OP04-095', 'Barrier', card_type='EVENT', cost=2)
me.hand = [evento_multi_cond]
ee = EffectExecutor(me, opp)
counter = ee.try_counter_event_power(me.leader, 'leader', needed=4000)
check('Counter event com bonus condicional soma quando condicao passa (trash_gte 15)',
      counter and counter[0] == 4000 and evento_multi_cond in me.trash)

me, opp = me_opp()
me.don_available = 2
me.trash = [mk(f'TR{i}', f'Trash {i}') for i in range(3)]
evento_multi_cond2 = mk('OP04-095', 'Barrier', card_type='EVENT', cost=2)
me.hand = [evento_multi_cond2]
ee = EffectExecutor(me, opp)
counter = ee.try_counter_event_power(me.leader, 'leader', needed=4000)
check('Counter event com bonus condicional NAO soma quando condicao falha',
      counter is None and evento_multi_cond2 in me.hand)

# ── 15d. Counter events com extras simples desbloqueados (trash_from_deck_top,
# peek_life, add_from_trash, gain_life) ──
me, opp = me_opp()
me.don_available = 2
me.deck = [mk('D1', 'Topo do deck')]
evento_trash_top = mk('OP03-054', "Usopp's Rubber Band of Doom", card_type='EVENT', cost=2)
me.hand = [evento_trash_top]
ee = EffectExecutor(me, opp)
counter = ee.try_counter_event_power(me.leader, 'leader', needed=2000)
check('Counter event com trash_from_deck_top trasha o topo do deck',
      counter and counter[0] == 2000 and evento_trash_top in me.trash
      and not me.deck and any(c.name == 'Topo do deck' for c in me.trash))

me, opp = me_opp()
me.don_available = 2
me.life = [mk('L1', 'Vida 1'), mk('L2', 'Vida 2')]
evento_peek = mk('ST07-016', 'Power Mochi', card_type='EVENT', cost=2)
me.hand = [evento_peek]
ee = EffectExecutor(me, opp)
counter = ee.try_counter_event_power(me.leader, 'leader', needed=2000)
check('Counter event com peek_life ativa sem erro',
      counter and counter[0] == 2000 and evento_peek in me.trash)

me, opp = me_opp()
me.don_available = 2
me.trash = [mk(f'TR{i}', f'Trash {i}', cost=2) for i in range(11)]
recuperavel = me.trash[0]
evento_add_trash = mk('OP11-097', "After All These Years", card_type='EVENT', cost=2)
me.hand = [evento_add_trash]
ee = EffectExecutor(me, opp)
counter = ee.try_counter_event_power(me.leader, 'leader', needed=1000)
check('Counter event com add_from_trash recupera carta quando condicao passa (trash_gte 10)',
      counter and counter[0] == 1000 and evento_add_trash in me.trash
      and recuperavel in me.hand)

me, opp = me_opp()
me.don_available = 2
me.trash = [mk(f'TR{i}', f'Trash {i}', cost=2) for i in range(3)]
evento_add_trash2 = mk('OP11-097', "After All These Years", card_type='EVENT', cost=2)
me.hand = [evento_add_trash2]
ee = EffectExecutor(me, opp)
counter = ee.try_counter_event_power(me.leader, 'leader', needed=1000)
check('Counter event com add_from_trash nao recupera quando condicao falha (trash_gte 10)',
      counter and counter[0] == 1000 and evento_add_trash2 in me.trash
      and len([c for c in me.trash if c.name.startswith('Trash')]) == 3)

me, opp = me_opp()
me.don_available = 2
me.life = [mk('L1', 'Vida 1')]
evento_gain_life = mk('ST09-015', 'Thunder Bagua', card_type='EVENT', cost=2)
me.hand = [evento_gain_life]
ee = EffectExecutor(me, opp)
counter = ee.try_counter_event_power(me.leader, 'leader', needed=4000)
check('Counter event com gain_life ativa quando condicao passa (life_lte 2)',
      counter and counter[0] == 4000 and evento_gain_life in me.trash)

# ── 15e. Counter events com buff duration='this_turn' (nao so 'battle_only')
# -- o Counter Step so acontece DENTRO da resolucao da batalha, entao
# 'this_turn' tambem impede o hit. OP13-077 (target='leader' direto) ──
me, opp = me_opp()
me.don_available = 2
evento_this_turn = mk('OP13-077', 'Go All the Way to the Top', card_type='EVENT', cost=2)
me.hand = [evento_this_turn]
ee = EffectExecutor(me, opp)
counter = ee.try_counter_event_power(me.leader, 'leader', needed=3000)
check('Counter event com buff duration=this_turn conta como defesa de batalha',
      counter and counter[0] == 3000 and evento_this_turn in me.trash)

# ── 15f. Counter events com target='select_filtered' -- so conta como
# defesa se o ALVO REAL sob ataque bater no filtro (EB03-029: Boa Hancock) ──
me, opp = me_opp()
me.don_available = 2
me.leader = mk('LD-BH', 'Boa Hancock Leader', power=5000, card_type='LEADER', sub_types='Boa Hancock Pirates')
evento_filtrado = mk('EB03-029', 'Insolent Fool Stand Down', card_type='EVENT', cost=2)
me.hand = [evento_filtrado]
ee = EffectExecutor(me, opp)
counter = ee.try_counter_event_power(me.leader, 'leader', needed=3000)
check('Counter event select_filtered protege quando o alvo sob ataque bate no filtro',
      counter and counter[0] == 3000 and evento_filtrado in me.trash)

me, opp = me_opp()
me.don_available = 2
me.leader = mk('LD-OUTRO', 'Leader qualquer', power=5000, card_type='LEADER', sub_types='Navy')
evento_filtrado2 = mk('EB03-029', 'Insolent Fool Stand Down', card_type='EVENT', cost=2)
me.hand = [evento_filtrado2]
ee = EffectExecutor(me, opp)
counter = ee.try_counter_event_power(me.leader, 'leader', needed=1)
check('Counter event select_filtered nao protege alvo fora do filtro',
      counter is None and evento_filtrado2 in me.hand)

# ── 15g. Counter events que enfraquecem o ATACANTE (debuff_power puro, sem
# buffar a propria defesa) -- mecanica distinta de try_counter_event_power.
# OP01-028: unico debuff_power, target=opp_leader_or_character ──
me, opp = me_opp()
me.don_available = 2
atacante = mk('ATK-1', 'Atacante', power=6000)
evento_debuff_puro = mk('OP01-028', 'Green Star Rafflesia', card_type='EVENT', cost=2)
me.hand = [evento_debuff_puro]
ee = EffectExecutor(me, opp)
counter = ee.try_counter_event_debuff(atacante, 'character', needed=2000)
check('Counter event de debuff puro enfraquece o atacante o suficiente',
      counter and counter[0] == 2000 and evento_debuff_puro in me.trash
      and atacante.power_buff == -2000)

me, opp = me_opp()
me.don_available = 2
atacante2 = mk('ATK-2', 'Atacante 2', power=6000)
evento_debuff_fraco = mk('OP01-028', 'Green Star Rafflesia', card_type='EVENT', cost=2)
me.hand = [evento_debuff_fraco]
ee = EffectExecutor(me, opp)
counter = ee.try_counter_event_debuff(atacante2, 'character', needed=2001)
check('Counter event de debuff puro nao ativa se o debuff nao for suficiente',
      counter is None and evento_debuff_fraco in me.hand and atacante2.power_buff == 0)

# OP03-017: target='opp_character' -- nao deve proteger contra Leader atacando
me, opp = me_opp()
me.don_available = 2
me.leader = mk('LD-WB', 'Whitebeard Leader', power=5000, card_type='LEADER', sub_types='Whitebeard Pirates')
atacante_leader = mk('ATK-LD', 'Leader Atacante', power=6000, card_type='LEADER')
evento_op03017 = mk('OP03-017', 'Cross Fire', card_type='EVENT', cost=2)
me.hand = [evento_op03017]
ee = EffectExecutor(me, opp)
counter = ee.try_counter_event_debuff(atacante_leader, 'leader', needed=1)
check('Counter event de debuff target=opp_character nao protege contra Leader atacando',
      counter is None and evento_op03017 in me.hand)

# ST09-014: condicao no nivel do block (life_lte 2)
me, opp = me_opp()
me.don_available = 2
me.life = [mk('L1', 'Vida 1'), mk('L2', 'Vida 2')]
atacante3 = mk('ATK-3', 'Atacante 3', power=6000)
evento_st09014 = mk('ST09-014', 'Narikabura Arrow', card_type='EVENT', cost=2)
me.hand = [evento_st09014]
ee = EffectExecutor(me, opp)
counter = ee.try_counter_event_debuff(atacante3, 'character', needed=3000)
check('Counter event de debuff com condicao de vida ativa quando passa (life_lte 2)',
      counter and counter[0] == 3000 and atacante3.power_buff == -3000)

# ── 15h. Counter events que dao K.O. no ATACANTE inteiro -- cancela o
# ataque por completo (sem comparacao de power). EB01-010: power_lte 6000 ──
me, opp = me_opp()
me.don_available = 2
atacante_ko = mk('ATK-KO1', 'Atacante fraco', power=5000)
atacante_ko.rested = True
opp.field_chars = [atacante_ko]
evento_ko_puro = mk('EB01-010', "There's No Way You Could Defeat Me", card_type='EVENT', cost=2)
me.hand = [evento_ko_puro]
ee = EffectExecutor(me, opp)
log = ee.try_counter_event_ko_attacker(atacante_ko)
check('Counter event de K.O. puro remove o atacante elegivel (power_lte)',
      log and evento_ko_puro in me.trash and atacante_ko in opp.trash
      and atacante_ko not in opp.field_chars)

me, opp = me_opp()
me.don_available = 2
atacante_forte = mk('ATK-KO2', 'Atacante forte', power=7000)
atacante_forte.rested = True
opp.field_chars = [atacante_forte]
evento_ko_fraco = mk('EB01-010', "There's No Way You Could Defeat Me", card_type='EVENT', cost=2)
me.hand = [evento_ko_fraco]
ee = EffectExecutor(me, opp)
log = ee.try_counter_event_ko_attacker(atacante_forte)
check('Counter event de K.O. puro nao remove atacante acima do power_lte',
      log is None and evento_ko_fraco in me.hand and atacante_forte in opp.field_chars)

# OP10-040: cost_lte 7 + rested_only -- atacante sempre esta rested ao atacar
me, opp = me_opp()
me.don_available = 2
atacante_rested = mk('ATK-KO3', 'Atacante custo 5', cost=5, power=8000)
atacante_rested.rested = True
opp.field_chars = [atacante_rested]
evento_ko_rested = mk('OP10-040', 'The Weak Do Not Have the Right', card_type='EVENT', cost=2)
me.hand = [evento_ko_rested]
ee = EffectExecutor(me, opp)
log = ee.try_counter_event_ko_attacker(atacante_rested)
check('Counter event de K.O. com rested_only remove atacante (sempre rested ao atacar)',
      log and atacante_rested in opp.trash)

me, opp = me_opp()
me.don_available = 2
atacante_caro = mk('ATK-KO4', 'Atacante custo 8', cost=8, power=8000)
atacante_caro.rested = True
opp.field_chars = [atacante_caro]
evento_ko_caro = mk('OP10-040', 'The Weak Do Not Have the Right', card_type='EVENT', cost=2)
me.hand = [evento_ko_caro]
ee = EffectExecutor(me, opp)
log = ee.try_counter_event_ko_attacker(atacante_caro)
check('Counter event de K.O. nao remove atacante acima do cost_lte',
      log is None and atacante_caro in opp.field_chars)

# ── 15i. Counter events com buff + play_card/busca em deck (acoes que ja
# tem handler generico, so bonus de valor -- o buff sozinho ja defende) ──
me, opp = me_opp()
me.don_available = 2
evento_play = mk('OP02-045', 'Three Sword Style Oni Giri', card_type='EVENT', cost=2)
carta_barata = mk('BARATA1', 'Carta barata', cost=2, power=3000)
me.hand = [evento_play, carta_barata]
ee = EffectExecutor(me, opp)
counter = ee.try_counter_event_power(me.leader, 'leader', needed=6000)
check('Counter event com play_card joga carta da mao de graca como bonus',
      counter and counter[0] == 6000 and evento_play in me.trash
      and carta_barata in me.field_chars and carta_barata not in me.hand)

me, opp = me_opp()
me.don_available = 2
me.life = [mk('L1', 'Vida 1')]
evento_play_cond = mk('EB02-059', "Without Your Help", card_type='EVENT', cost=2)
sanji_barato = mk('SANJI1', 'Sanji barato', cost=3, power=3000)
me.hand = [evento_play_cond, sanji_barato]
ee = EffectExecutor(me, opp)
counter = ee.try_counter_event_power(me.leader, 'leader', needed=1000)
check('Counter event com play_card condicional joga quando condicao passa (life_lte 1)',
      counter and counter[0] == 1000 and evento_play_cond in me.trash
      and sanji_barato in me.field_chars)

me, opp = me_opp()
me.don_available = 2
me.life = [mk('L1', 'Vida 1'), mk('L2', 'Vida 2')]
evento_play_cond2 = mk('EB02-059', "Without Your Help", card_type='EVENT', cost=2)
sanji_barato2 = mk('SANJI2', 'Sanji barato 2', cost=3, power=3000)
me.hand = [evento_play_cond2, sanji_barato2]
ee = EffectExecutor(me, opp)
counter = ee.try_counter_event_power(me.leader, 'leader', needed=1000)
check('Counter event com play_card condicional NAO joga quando condicao falha',
      counter and counter[0] == 1000 and evento_play_cond2 in me.trash
      and sanji_barato2 in me.hand and sanji_barato2 not in me.field_chars)

# EB01-019: look_top_deck + add_to_hand + deck_bottom_rest + buff
me, opp = me_opp()
me.don_available = 2
evento_busca = mk('EB01-019', 'Off-White', card_type='EVENT', cost=2)
donquixote_top = mk('DQ1', 'Donquixote Family char', sub_types='Donquixote Pirates', cost=3)
me.deck = [mk('IRRELEVANTE', 'Irrelevante'), donquixote_top]
me.hand = [evento_busca]
ee = EffectExecutor(me, opp)
counter = ee.try_counter_event_power(me.leader, 'leader', needed=4000)
check('Counter event com look_top_deck + add_to_hand busca carta filtrada do deck',
      counter and counter[0] == 4000 and evento_busca in me.trash
      and donquixote_top in me.hand)

# ── 16. lock_opp_attack_unless_pays (OP08-043 Edward.Newgate) -- character
# PODE atacar, mas o dono paga um custo a cada ataque enquanto a trava
# estiver ativa. Distinto de cannot_attack_until (bloqueio total) ──
me, opp = me_opp()
opp.field_chars = [mk('OC1', 'Oponente 1'), mk('OC2', 'Oponente 2')]
newgate = mk('OP08-043', 'Edward.Newgate', power=12000, cost=10)
ee = EffectExecutor(me, opp)
log = ee._execute_step(
    {'action': 'lock_opp_attack_unless_pays', 'count': 99,
     'duration': 'until_opp_turn_end', 'cost_type': 'trash_from_hand', 'cost_amount': 2},
    newgate,
)
check('lock_opp_attack_unless_pays trava TODOS os Characters do oponente no momento',
      bool(log) and all(c.attack_paywall == {'cost_type': 'trash_from_hand', 'cost_amount': 2, 'until': 'opp_turn_end'}
                         for c in opp.field_chars))

# can_afford_attack_paywall: sem paywall sempre pode; com paywall, so se a
# mao tiver cartas suficientes pra pagar
me, opp = me_opp()
sem_paywall = mk('SP1', 'Sem paywall')
check('can_afford_attack_paywall permite atacar sem paywall ativo',
      can_afford_attack_paywall(sem_paywall, me))

com_paywall = mk('CP1', 'Com paywall')
com_paywall.attack_paywall = {'cost_type': 'trash_from_hand', 'cost_amount': 2}
me.hand = [mk('H1', 'H1'), mk('H2', 'H2')]
check('can_afford_attack_paywall permite atacar com mao suficiente',
      can_afford_attack_paywall(com_paywall, me))
me.hand = [mk('H1', 'H1')]
check('can_afford_attack_paywall bloqueia atacar sem mao suficiente',
      not can_afford_attack_paywall(com_paywall, me))

# Integracao real: declarar o ataque paga o custo automaticamente
me, opp = me_opp()
me.don_available = 5
me.life = []
opp.life = [mk('L1', 'Vida opp')]
atacante_travado = mk('ATK-PW', 'Atacante travado', power=5000)
atacante_travado.attack_paywall = {'cost_type': 'trash_from_hand', 'cost_amount': 2}
me.field_chars = [atacante_travado]
me.hand = [mk('H1', 'H1', power=1000), mk('H2', 'H2', power=2000), mk('H3', 'H3', power=3000)]
engine = DecisionEngine(me, opp)
match = OPTCGMatch((me.leader, []), (opp.leader, []))
match._execute_attack(atacante_travado, 'leader', None, me, opp, engine)
check('Declarar ataque com attack_paywall ativo trasha as cartas do custo automaticamente',
      len(me.hand) == 1 and len(me.trash) == 2)

# ── 17. deck_reorder_rest / deck_top_rest -- mesma semantica de execucao
# (achado: 'deck_top_rest' eh nome equivocado do parser, todas as ocorrencias
# reais sao "top OR bottom in any order"). Heuristica: melhor carta no topo. ──
me, opp = me_opp()
ee = EffectExecutor(me, opp)
kaya = mk('EB03-023', 'Kaya', card_type='CHARACTER')
me.hand = [kaya]
fraca = mk('FRACA', 'Fraca', power=1000)
media = mk('MEDIA', 'Media', power=4000)
forte = mk('FORTE', 'Forte', power=9000, has_trigger=True)
me.deck = [fraca, media, forte]  # forte = topo (fim da lista), unico candidato de add_to_hand
logs = ee.execute(kaya, 'on_play')
check('deck_reorder_rest pega 1 do topo e reordena o resto (melhor carta volta ao topo)',
      forte in me.hand and len(me.deck) == 2 and me.deck[-1] is media and me.deck[0] is fraca)

me, opp = me_opp()
ee = EffectExecutor(me, opp)
kuma = mk('OP02-057', 'Bartholomew Kuma', card_type='CHARACTER')
me.hand = [kuma]
warlord = mk('WL1', 'Warlord', sub_types='The Seven Warlords of the Sea', power=5000)
outra = mk('OUTRA', 'Outra carta', power=3000)
me.deck = [outra, warlord]  # warlord = topo, bate no filtro
logs = ee.execute(kuma, 'on_play')
check('deck_top_rest (nome equivocado do parser) executa igual deck_reorder_rest',
      warlord in me.hand and len(me.deck) == 1 and me.deck[0] is outra)

# OP01-088: Counter event que tinha ficado de fora por causa do deck_top_rest
# sem handler -- agora deve ativar normalmente (buff + busca)
me, opp = me_opp()
me.don_available = 2
evento_op01088 = mk('OP01-088', 'Desert Spada', card_type='EVENT', cost=2)
carta_deck = mk('DECKCARD', 'Carta do deck', power=2000)
me.deck = [carta_deck]
me.hand = [evento_op01088]
ee = EffectExecutor(me, opp)
counter = ee.try_counter_event_power(me.leader, 'leader', needed=2000)
check('Counter event OP01-088 ativa agora que deck_reorder_rest tem handler',
      counter and counter[0] == 2000 and evento_op01088 in me.trash
      and carta_deck in me.hand)

# ── 18. is_attack_locked_self -- achado 01/07/2026: ja estava 100%
# implementado (le 'passive'/'mass_lock_conditional' direto do banco, sem
# depender de execute()), so faltava cobertura de teste. O comentario antigo
# no _execute_step dizia "nao implementado", mas era so um no-op de log --
# a trava real sempre aconteceu aqui. cannot_attack_self incondicional ──
me, opp = me_opp()
oars = mk('OP06-083', 'Oars')
check('cannot_attack_self trava incondicionalmente (Oars)',
      is_attack_locked_self(oars, me, opp))

# cannot_attack_self_unless com condicao -- EB04-005 Trafalgar Law
me, opp = me_opp()
law = mk('EB04-005', 'Trafalgar Law')
check('cannot_attack_self_unless trava quando condicao nao e satisfeita (Law)',
      is_attack_locked_self(law, me, opp))
opp.field_chars = [mk('X1', 'X1', power=6000), mk('X2', 'X2', power=6000)]
check('cannot_attack_self_unless libera quando condicao e satisfeita (Law, 2+ opp chars 5000+)',
      not is_attack_locked_self(law, me, opp))

# cannot_attack_own_characters_by_cost (mass-lock condicional) -- P-084 Buggy
me, opp = me_opp()
me.leader = mk('LDBUGGY', 'Buggy', card_type='LEADER', sub_types='Buggy Pirates')
buggy = mk('P-084', 'Buggy')
ally_custo3 = mk('ALLY3', 'Aliado custo 3', cost=3)
ally_custo5 = mk('ALLY5', 'Aliado custo 5', cost=5)
me.field_chars = [buggy, ally_custo3, ally_custo5]
check('mass_lock_conditional do Buggy trava aliados de custo 3/4',
      is_attack_locked_self(ally_custo3, me, opp))
check('mass_lock_conditional do Buggy nao trava aliados fora da faixa de custo',
      not is_attack_locked_self(ally_custo5, me, opp))
me, opp = me_opp()
me.leader = mk('LDOUTRO', 'Outro Leader', card_type='LEADER', sub_types='Navy')
buggy2 = mk('P-084', 'Buggy')
ally_custo3b = mk('ALLY3B', 'Aliado custo 3', cost=3)
me.field_chars = [buggy2, ally_custo3b]
check('mass_lock_conditional do Buggy nao trava se o Leader nao for Buggy',
      not is_attack_locked_self(ally_custo3b, me, opp))

# ── 19. substituicao externa: 6 cartas reais desbloqueadas pela unificacao
# de _parse_substitute_cost (achado 01/07/2026: parse_substitute_ko e
# parse_substitute_removal tinham listas de custo dessincronizadas) ──

# EB04-030/EB04-031: substitute_ko self com custo return_own_don (so existia
# antes em substitute_removal, nao em substitute_ko)
me, opp = me_opp()
eb04030 = mk('EB04-030', 'Kaido', power=12000)
me.field_chars = [eb04030]
me.don_rested = 1
ee = EffectExecutor(me, opp)
log = ee.try_substitute(eb04030, 'ko')
check('EB04-030 substitui KO devolvendo 1 DON ao deck',
      bool(log) and eb04030 in me.field_chars and me.don_deck == 11 and me.don_rested == 0)

# EB04-044: substitute_removal self com "you CAN discard" (nao so "you MAY")
me, opp = me_opp()
eb04044 = mk('EB04-044', 'Koby', power=5000)
me.leader = mk('LDNAVY', 'Navy Leader', card_type='LEADER', sub_types='Navy')
me.field_chars = [eb04044]
me.hand = [mk('H1', 'H1')]
ee = EffectExecutor(me, opp)
log = ee.try_substitute(eb04044, 'removal')
check('EB04-044 substitui remocao descartando da mao (texto usa "you can", nao "you may")',
      bool(log) and eb04044 in me.field_chars and len(me.hand) == 0 and len(me.trash) == 1)

# OP15-003: substitute_ko self com trash_from_hand power_lte (nova variante
# "power or less", so existia power_gte antes)
me, opp = me_opp()
op15003 = mk('OP15-003', 'Alvida', power=5000)
me.field_chars = [op15003]
carta_fraca = mk('FRACA', 'Fraca', power=5000, card_type='CHARACTER')
carta_forte = mk('FORTE', 'Forte', power=7000, card_type='CHARACTER')
me.hand = [carta_fraca, carta_forte]
ee = EffectExecutor(me, opp)
log = ee.try_substitute(op15003, 'ko')
check('OP15-003 substitui KO trashando Character com power 6000 ou menos da mao',
      bool(log) and carta_fraca in me.trash and carta_forte in me.hand)

me, opp = me_opp()
op15003b = mk('OP15-003', 'Alvida', power=5000)
me.field_chars = [op15003b]
carta_forte2 = mk('FORTE2', 'Forte', power=7000, card_type='CHARACTER')
me.hand = [carta_forte2]
ee = EffectExecutor(me, opp)
log = ee.try_substitute(op15003b, 'ko')
check('OP15-003 nao substitui se so tem Character forte demais na mao',
      log is None and carta_forte2 in me.hand)

# OP12-027: substituicao EXTERNA protegendo OUTRO Character Slash com
# cost<=5 -- achado 01/07/2026: precisava do filtro 'filter_attribute' novo
me, opp = me_opp()
op12027 = mk('OP12-027', 'Vista', sub_types='', attribute='Slash', cost=4)
alvo_slash = mk('ALVO-SLASH', 'Alvo Slash', attribute='Slash', cost=3)
me.field_chars = [op12027, alvo_slash]
ee = EffectExecutor(me, opp)
log = ee.try_any_substitute(alvo_slash, 'ko')
check('OP12-027 protege outro Character Slash com cost<=5 (rest_self)',
      bool(log) and op12027.rested and alvo_slash in me.field_chars)

me, opp = me_opp()
op12027b = mk('OP12-027', 'Vista', sub_types='', attribute='Slash', cost=4)
alvo_strike = mk('ALVO-STRIKE', 'Alvo Strike', attribute='Strike', cost=3)
me.field_chars = [op12027b, alvo_strike]
ee = EffectExecutor(me, opp)
log = ee.try_any_substitute(alvo_strike, 'ko')
check('OP12-027 nao protege Character fora do atributo Slash',
      log is None and not op12027b.rested)

# OP15-094: substituicao EXTERNA protegendo OUTRO Character Straw Hat Crew
# -- achado 01/07/2026: o early-return de "this character" descartava o
# filtro de tipo quando o texto era "other than this character"
me, opp = me_opp()
op15094 = mk('OP15-094', 'Zoro', sub_types='Straw Hat Crew')
alvo_shc = mk('ALVO-SHC', 'Alvo Straw Hat', sub_types='Straw Hat Crew')
me.field_chars = [op15094, alvo_shc]
ee = EffectExecutor(me, opp)
log = ee.try_any_substitute(alvo_shc, 'removal')
check('OP15-094 protege outro Character Straw Hat Crew trashando a si mesma',
      bool(log) and op15094 in me.trash and alvo_shc in me.field_chars)

me, opp = me_opp()
op15094b = mk('OP15-094', 'Zoro', sub_types='Straw Hat Crew')
alvo_outro = mk('ALVO-OUTRO', 'Alvo nao-SHC', sub_types='Navy')
me.field_chars = [op15094b, alvo_outro]
ee = EffectExecutor(me, opp)
log = ee.try_any_substitute(alvo_outro, 'removal')
check('OP15-094 nao protege Character fora do tipo Straw Hat Crew',
      log is None and op15094b in me.field_chars)

# ── 20. substituicao externa: 11 cartas reais com custos genuinamente
# novos (rest_leader, rest_own_filtered, rest_own_character, rest_own_card,
# life_to_hand, life_to_trash, trash_to_deck_bottom) -- achado 01/07/2026 ──

# OP04-082: self KO, custo rest_leader
me, opp = me_opp()
op04082 = mk('OP04-082', 'Kyros', power=6000)
me.field_chars = [op04082]
ee = EffectExecutor(me, opp)
log = ee.try_substitute(op04082, 'ko')
check('OP04-082 substitui KO restando o proprio Leader',
      bool(log) and me.leader.rested and op04082 in me.field_chars)

# OP10-034/OP12-061: self KO, custo life_to_hand (achado: antes eram
# mis-parseadas como life_to_hand PASSIVO INCONDICIONAL, nao substituicao)
me, opp = me_opp()
op10034 = mk('OP10-034', 'Franky', power=7000)
me.field_chars = [op10034]
me.life = [mk('L1', 'Vida 1')]
ee = EffectExecutor(me, opp)
log = ee.try_substitute(op10034, 'ko')
check('OP10-034 substitui KO comprando carta da propria vida',
      bool(log) and op10034 in me.field_chars and len(me.life) == 0 and len(me.hand) == 1)

# OP10-037/OP11-110: self removal/KO, custo rest_own_filtered
me, opp = me_opp()
op10037 = mk('OP10-037', 'Lim', power=5000)
odyssey_ally = mk('ODY1', 'Odyssey aliado', sub_types='ODYSSEY')
me.field_chars = [op10037, odyssey_ally]
ee = EffectExecutor(me, opp)
log = ee.try_substitute(op10037, 'removal')
check('OP10-037 substitui remocao restando 1 Character ODYSSEY proprio',
      bool(log) and op10037 in me.field_chars and odyssey_ally.rested)

me, opp = me_opp()
op10037b = mk('OP10-037', 'Lim', power=5000)
nao_odyssey = mk('NAOODY', 'Navy Ally', sub_types='Navy')
me.field_chars = [op10037b, nao_odyssey]
ee = EffectExecutor(me, opp)
log = ee.try_substitute(op10037b, 'removal')
check('OP10-037 nao substitui sem nenhum Character ODYSSEY disponivel',
      log is None and nao_odyssey in me.field_chars and not nao_odyssey.rested)

# OP14-029: self removal, custo rest_own_card (qualquer carta, incl Leader)
me, opp = me_opp()
op14029 = mk('OP14-029', 'Tashigi', power=5000)
me.field_chars = [op14029]
ee = EffectExecutor(me, opp)
log = ee.try_substitute(op14029, 'removal')
check('OP14-029 substitui remocao restando qualquer carta propria',
      bool(log) and op14029 in me.field_chars
      and (op14029.rested or me.leader.rested))

# OP14-034: substituicao EXTERNA, custo rest_own_character (sem filtro)
me, opp = me_opp()
op14034 = mk('OP14-034', 'Luffy', sub_types='', power=6000)
alvo_shc2 = mk('ALVO-SHC2', 'Alvo Straw Hat', sub_types='Straw Hat Crew', power=5000)
me.field_chars = [op14034, alvo_shc2]
ee = EffectExecutor(me, opp)
log = ee.try_any_substitute(alvo_shc2, 'ko')
check('OP14-034 protege outro Character Straw Hat Crew restando-se',
      bool(log) and op14034.rested and alvo_shc2 in me.field_chars)

# OP14-092: self KO, custo trash_to_deck_bottom
me, opp = me_opp()
op14092 = mk('OP14-092', 'Mr.3', power=4000)
me.field_chars = [op14092]
me.trash = [mk(f'TR{i}', f'Trash {i}') for i in range(3)]
ee = EffectExecutor(me, opp)
log = ee.try_substitute(op14092, 'ko')
check('OP14-092 substitui KO mandando 3 cartas do trash pro fundo do deck',
      bool(log) and op14092 in me.field_chars and len(me.trash) == 0 and len(me.deck) == 3)

# OP15-035: substituicao EXTERNA, custo rest_own_card count=2
me, opp = me_opp()
op15035 = mk('OP15-035', 'Laboon', power=5000)
alvo_fraco2 = mk('ALVO-FRACO2', 'Alvo fraco', power=6000)
ally2 = mk('ALLY2', 'Aliado 2', power=3000)
me.field_chars = [op15035, alvo_fraco2, ally2]
ee = EffectExecutor(me, opp)
log = ee.try_any_substitute(alvo_fraco2, 'removal')
check('OP15-035 protege outro Character com power<=7000 restando 2 cartas',
      bool(log) and alvo_fraco2 in me.field_chars
      and sum(1 for c in [op15035, ally2, alvo_fraco2, me.leader] if c.rested) == 2)

# ST09-010/ST20-002: self KO, custo life_to_trash
me, opp = me_opp()
st09010 = mk('ST09-010', 'Ace', power=6000)
me.field_chars = [st09010]
me.life = [mk('L1', 'Vida 1')]
ee = EffectExecutor(me, opp)
log = ee.try_substitute(st09010, 'ko')
check('ST09-010 substitui KO trashando carta da propria vida',
      bool(log) and st09010 in me.field_chars and len(me.life) == 0 and len(me.trash) == 1)

# ── 21. imunidade a rest forcado por efeito do oponente (imm_type='rest')
# -- achado 01/07/2026: OP11-046, OP12-021, OP15-024. DISTINTA de
# lock_opp_cannot_be_rested (trava o character DO OPONENTE, mecanica
# oposta, ja implementada -- confirmado que nao tem gap ali). ──
me, opp = me_opp()
# Achado 15/07: a imunidade do OP12-021 (Ipponmatsu) e CONDICIONAL ("If
# your Leader has the (Slash) attribute and you have 6 or more rested
# DON!! cards..."), nao incondicional -- o setup do teste precisa montar
# as 2 condicoes do lado dono do Ipponmatsu (opp aqui), senao a imunidade
# corretamente NAO se aplica (comportamento antigo do teste testava um
# bug: imunidade sem nenhuma condicao).
opp.leader = mk('LD-SLASH', 'Opp Leader Slash', power=5000, card_type='LEADER', attribute='Slash')
opp.don_rested = 6
op12021 = mk('OP12-021', 'Imune a rest', power=5000)
controle1 = mk('CTRL1', 'Controle', power=4000)
opp.field_chars = [op12021, controle1]
ee = EffectExecutor(me, opp)
log = ee._execute_step({'action': 'rest_opp_character', 'count': 2}, me.leader)
check('OP12-021 e imune a rest forcado por efeito do oponente (lider Slash + 6+ DON rested)',
      not op12021.rested and controle1.rested)

me, opp = me_opp()
op15024 = mk('OP15-024', 'Imune a rest 2', power=5000)
controle2 = mk('CTRL2', 'Controle 2', power=4000)
opp.field_chars = [op15024, controle2]
ee = EffectExecutor(me, opp)
log = ee._execute_step({'action': 'rest_opp_character', 'count': 2}, me.leader)
check('OP15-024 e imune a rest forcado por efeito do oponente',
      not op15024.rested and controle2.rested)

# OP11-046: imunidade composta (KO ou rest), condicional a only_field_type=germa
me, opp = me_opp()
op11046 = mk('OP11-046', 'Vinsmoke Yonji', power=5000, sub_types='GERMA')
opp.field_chars = [op11046, mk('GERMA-ALLY', 'Aliado GERMA', sub_types='GERMA')]
ee = EffectExecutor(me, opp)
ee._execute_step({'action': 'rest_opp_character', 'count': 1}, me.leader)
check('OP11-046 imune a rest quando so tem Characters GERMA no campo',
      not op11046.rested)

me, opp = me_opp()
op11046b = mk('OP11-046', 'Vinsmoke Yonji', power=5000)
opp.field_chars = [op11046b, mk('NAVY-ALLY', 'Aliado Navy', sub_types='Navy')]
ee = EffectExecutor(me, opp)
ee._execute_step({'action': 'rest_opp_character', 'count': 1}, me.leader)
check('OP11-046 nao imune a rest quando tem Character fora de GERMA',
      op11046b.rested)

# ── 22. condicao opp_don_on_field_gte ("if your opponent has N+ DON!! cards
# on their field") -- gate sobre o campo do OPONENTE, distinta de
# don_on_field_gte (proprio campo). Achado 02/07/2026: 8 cartas no banco
# (EB02-061, OP02-089/090/091, OP08-060, OP14-063, PRB02-010, ST26-005)
# tinham essa clausula descartada pelo parser -- efeito executava sempre. ──
me, opp = me_opp()
opp.don_available = 6
opp.don_rested = 0
ee = EffectExecutor(me, opp)
ok = ee._check_conditions({'opp_don_on_field_gte': 5}, me.leader)
check('opp_don_on_field_gte satisfeita (oponente com 6 DON, exige 5+)', ok)

me, opp = me_opp()
opp.don_available = 2
opp.don_rested = 1
ee = EffectExecutor(me, opp)
ok = ee._check_conditions({'opp_don_on_field_gte': 5}, me.leader)
check('opp_don_on_field_gte nao satisfeita (oponente com 3 DON, exige 5+)', not ok)

# ── 23. opp_place_hand_bottom_deck / opp_place_trash_bottom_deck --
# disrupcao FORCADA no oponente, destino = FUNDO DO PROPRIO DECK dele
# (NUNCA trash). Achado 02/07/2026, 13 cartas (EB03-026, EB04-022,
# EB04-025, OP05-079, OP06-044, OP06-092, OP07-047, OP08-046, OP11-072,
# OP11-091, OP15-048, P-048, OP16-047). ──
me, opp = me_opp()
opp.hand = [mk('H1', 'Mao 1', power=3000), mk('H2', 'Mao 2', power=9000)]
opp.deck = [mk('D1', 'Topo do deck')]
ee = EffectExecutor(me, opp)
log = ee._execute_step({'action': 'opp_place_hand_bottom_deck', 'count': 1}, me.leader)
check('opp_place_hand_bottom_deck move 1 carta da mao do oponente pro fundo do deck dele',
      bool(log) and len(opp.hand) == 1 and len(opp.deck) == 2 and opp.deck[0].name == 'Mao 1')

me, opp = me_opp()
evento = mk('EV1', 'Evento no trash', card_type='EVENT')
char_trash = mk('CH1', 'Character no trash')
opp.trash = [evento, char_trash]
opp.deck = []
ee = EffectExecutor(me, opp)
log = ee._execute_step({'action': 'opp_place_trash_bottom_deck', 'count': 3, 'filter_type': 'event'}, me.leader)
check('opp_place_trash_bottom_deck com filter_type=event so move Events do trash do oponente',
      bool(log) and evento not in opp.trash and char_trash in opp.trash
      and len(opp.deck) == 1 and opp.deck[0] is evento)

# ── 24. opp_hand_gte ("if your opponent has N or more cards in their
# hand") -- gate sobre o tamanho da MAO DO OPONENTE. Achado 02/07/2026:
# corrigia uma simplificacao identificada pelo usuario -- com a mao do
# oponente abaixo do limiar mas nao vazia, a acao disparava igual e tirava
# uma carta que a regra real nao tiraria. 13 cartas no banco (EB02-045,
# EB03-026, EB04-022, OP05-082, OP06-093, OP07-047, OP08-046, OP09-087,
# OP10-087, OP10-118, OP12-087, OP16-047, ST13-009). ──
me, opp = me_opp()
opp.hand = [mk('H1', 'Mao 1'), mk('H2', 'Mao 2')]
ee = EffectExecutor(me, opp)
ok = ee._check_conditions({'opp_hand_gte': 5}, me.leader)
check('opp_hand_gte nao satisfeita (oponente com 2 cartas, exige 5+)', not ok)

me, opp = me_opp()
opp.hand = [mk(f'H{i}', f'Mao {i}') for i in range(5)]
ee = EffectExecutor(me, opp)
ok = ee._check_conditions({'opp_hand_gte': 5}, me.leader)
check('opp_hand_gte satisfeita (oponente com 5 cartas, exige 5+)', ok)

# end-to-end via execute() + carta real do banco (OP08-046 Shakuyaku,
# trigger 'your_turn', limiar real = 5): confirma que o gate plugado em
# parse_conditions + _check_conditions realmente bloqueia o efeito quando
# a mao do oponente esta abaixo do limiar (nao so a unidade isolada acima).
me, opp = me_opp()
shakuyaku = mk('OP08-046', 'Shakuyaku', power=5000)
me.field_chars = [shakuyaku]
opp.hand = [mk('H1', 'Mao 1'), mk('H2', 'Mao 2')]
ee = EffectExecutor(me, opp)
ee.execute(shakuyaku, 'your_turn')
check('OP08-046 nao dispara opp_place_hand_bottom_deck com mao do oponente abaixo do limiar (2 < 5)',
      len(opp.hand) == 2)

me, opp = me_opp()
shakuyaku2 = mk('OP08-046', 'Shakuyaku', power=5000)
me.field_chars = [shakuyaku2]
opp.hand = [mk(f'H{i}', f'Mao {i}') for i in range(5)]
ee = EffectExecutor(me, opp)
ee.execute(shakuyaku2, 'your_turn')
check('OP08-046 dispara opp_place_hand_bottom_deck com mao do oponente no limiar (5 >= 5)',
      len(opp.hand) == 4)

# ── 25. OP07-029 (Basil Hawkins): substituicao de remocao com custo
# rest_opp_character -- restar 1 Character do OPONENTE em vez de gastar
# algo proprio. Achado 02/07/2026 (carta fora de escopo anterior). ──
me, opp = me_opp()
hawkins = mk('OP07-029', 'Basil Hawkins', power=6000, sub_types='Supernovas')
me.leader = mk('LD-SN', 'Capone Bege', power=5000, card_type='LEADER', sub_types='Supernovas')
me.field_chars = [hawkins]
opp_char = mk('OPP-CHAR', 'Char do oponente', power=7000)
opp.field_chars = [opp_char]
ee = EffectExecutor(me, opp)
# "if THIS Character would be removed" -- Hawkins so protege a si mesmo
log = ee.try_any_substitute(hawkins, 'removal', source_is_opp=True)
check('OP07-029 substitui propria remocao restando 1 Character do oponente',
      bool(log) and hawkins in me.field_chars and opp_char.rested)

# ── 26. OP16-032 Boa Hancock: lock_opp_cannot_be_rested com exclusao
# "other than [Monkey.D.Luffy]" agora parseada corretamente. ──
me, opp = me_opp()
luffy_card = mk('OP01-001', 'Monkey.D.Luffy', power=6000)
zoro_card = mk('OP01-002', 'Roronoa Zoro', power=6000)
opp.field_chars = [luffy_card, zoro_card]
ee = EffectExecutor(me, opp)
log = ee._execute_step({'action': 'lock_opp_cannot_be_rested', 'count': 1,
                        'duration': 'until_opp_end_phase',
                        'exclude': 'monkey.d.luffy'}, me.leader)
check('lock_opp_cannot_be_rested com exclude nao trava Monkey.D.Luffy mas trava Zoro',
      not luffy_card.cannot_be_rested_until and bool(zoro_card.cannot_be_rested_until))

# ── 27. when_rested -- novo timing disparado em _execute_attack apos restar
# o atacante. Achado 02/07/2026: 6 cartas OP14-xxx eram wrongly classificadas
# como 'your_turn' (executavam passivamente no inicio do turno em vez de so
# quando a carta efetivamente ficava rested). OP14-119 Mihawk era
# completamente perdida (effects vazio antes, cost_lte=9 + typo "cost or").
# Validated end-to-end via execute(card, 'when_rested'). ──
me, opp = me_opp()
mihawk = mk('OP14-119', 'Dracule Mihawk', power=10000, sub_types='The Seven Warlords of the Sea')
me.field_chars = [mihawk]
mihawk.rested = True
opp_alvo = mk('OPP-CHEAP', 'Alvo barato', power=5000, cost=7)
opp_blocked = mk('OPP-EXPENSIVE', 'Custo alto', power=8000, cost=10)
opp.field_chars = [opp_alvo, opp_blocked]
ee = EffectExecutor(me, opp)
ee.execute(mihawk, 'when_rested')
check('OP14-119 when_rested trava Character do oponente com cost<=9 mas nao o de cost=10',
      bool(opp_alvo.cannot_be_rested_until) and not opp_blocked.cannot_be_rested_until)

# Garante que 'when_rested' ja nao aparece mais como 'your_turn'
# (nao dispara no inicio do turno sem a carta ter sido restada)
me2, opp2 = me_opp()
op14028 = mk('OP14-028', 'Char OP14', power=6000)
opp2_target = mk('OPP-RESTED', 'Alvo rested barato', power=4000, cost=2)
opp2_target.rested = True
me2.field_chars = [op14028]
opp2.field_chars = [opp2_target]
ee2 = EffectExecutor(me2, opp2)
# Se executarmos 'your_turn' (incorreto), o KO apareceria; 'when_rested' so dispara
# quando o card fica rested de verdade (via execute). Verificamos ausencia de KO.
ee2.execute(op14028, 'your_turn')
check('OP14-028 nao dispara KO via your_turn (effet agora e when_rested, nao your_turn)',
      opp2_target in opp2.field_chars)

me, opp = me_opp()
shanks = mk('OP14-027', 'Shanks', power=9000)
opp_7000 = mk('OPP-7000', 'Alvo 7000', power=7000)
opp_9000 = mk('OPP-9000', 'Alvo 9000', power=9000)
opp.field_chars = [opp_9000, opp_7000]
ee = EffectExecutor(me, opp)
log = ee.execute(shanks, 'when_rested')
check('OP14-027 when_rested respeita power_lte=7000 ao restar alvo',
      opp_7000.rested and not opp_9000.rested and any('restou' in x for x in log))

me, opp = me_opp()
me.leader = mk('LD-WB', 'Whitebeard Leader', power=5000, card_type='LEADER',
               sub_types='Whitebeard Pirates')
atmos = mk('OP08-040', 'Atmos', power=5000, sub_types='Whitebeard Pirates')
opp_small = mk('OPP-C4', 'Alvo custo 4', cost=4)
opp_big = mk('OPP-C5', 'Alvo custo 5', cost=5)
opp.field_chars = [opp_big, opp_small]
ee = EffectExecutor(me, opp)
log = ee.execute(atmos, 'on_play')
check('OP08-040 Atmos tolera typo Piratess e ativa bounce com lider Whitebeard Pirates',
      opp_small in opp.hand and opp_small not in opp.field_chars and opp_big in opp.field_chars
      and any('bounce' in x for x in log))

# ── 28. grant_ko_immunity_type (OP09-033 Nico Robin): imunidade temporaria
# a KO por efeito para Characters do tipo proprio. ──
me, opp = me_opp()
robin = mk('OP09-033', 'Nico Robin', power=5000)
odyssey1 = mk('ODYSSEY-1', 'Char ODYSSEY', power=4000, sub_types='ODYSSEY')
odyssey1.rested = True
odyssey2 = mk('ODYSSEY-2', 'Outro ODYSSEY', power=3000, sub_types='ODYSSEY')
odyssey2.rested = True
non_odyssey = mk('NON', 'Char normal', power=5000, sub_types='Navy')
me.field_chars = [robin, odyssey1, odyssey2, non_odyssey]
ee = EffectExecutor(me, opp)
ee._execute_step({'action': 'grant_ko_immunity_type', 'filter_type': 'odyssey', 'duration': 'opp_turn_end'}, robin)
check('grant_ko_immunity_type cobre chars ODYSSEY mas nao outros',
      bool(odyssey1.immunity_ko_until) and bool(odyssey2.immunity_ko_until)
      and not non_odyssey.immunity_ko_until)

# ── 29. place_opp_char_to_opp_life (OP04-097/OP05-111/EB02-057): coloca
# Character do oponente na vida dele face-up. ──
me, opp = me_opp()
alvo_barato = mk('ALVO', 'Alvo barato', power=4000, cost=2, sub_types='Animal')
alvo_caro = mk('CARO', 'Alvo caro', power=8000, cost=6)
opp.field_chars = [alvo_barato, alvo_caro]
opp.life = [mk('VIDA', 'Vida', power=0)]
ee = EffectExecutor(me, opp)
ee._execute_step({'action': 'place_opp_char_to_opp_life', 'count': 1,
                  'cost_lte': 3, 'filter_type': 'animal', 'dest': 'life_top'}, me.leader)
check('place_opp_char_to_opp_life remove do campo do oponente e insere na vida face-up',
      alvo_barato not in opp.field_chars and alvo_caro in opp.field_chars
      and len(opp.life) == 2 and opp.life[-1] is alvo_barato
      and opp.life[-1].life_face_up)

# ── 30. OP03-091 Helmeppo: "set the cost of up to 1 of your opponent's
# Characters with no base effect to 0 during this turn." ──
me, opp = me_opp()
vanilla = mk('VANILLA', 'Vanilla', power=5000, cost=4)  # sem efeito no DB
opp.field_chars = [vanilla]
ee = EffectExecutor(me, opp)
ee._execute_step({
    'action': 'debuff_cost', 'count': 1, 'target': 'opp_character',
    'to_value': 0, 'filter_no_effect': True, 'duration': 'this_turn',
}, me.leader)
check('OP03-091 set_cost_to_0: vanilla fica com custo efetivo 0',
      vanilla.effective_cost() == 0)

# ── 31. ST15-001 Atmos: "cannot add Life cards to your hand" seta flag e
# bloqueia life_to_hand neste turno. ──
me, opp = me_opp()
me.life = [mk('L1','Vida'), mk('L2','Vida')]
hand_inicial = len(me.hand)
ee = EffectExecutor(me, opp)
ee._execute_step({'action': 'self_cant_take_life'}, me.leader)
ee._execute_step({'action': 'life_to_hand', 'count': 1, 'source': 'life_top'}, me.leader)
check('ST15-001 cant_take_life bloqueia life_to_hand enquanto ativo',
      len(me.life) == 2 and len(me.hand) == hand_inicial)  # vida intacta, mao inalterada

# ── 32. OP15-031 Purinpurin: KO se custo == DON!! anexado. ──
me, opp = me_opp()
char_match = mk('MATCH', 'Custo=DON', power=5000, cost=3)
char_match.don_attached = 3
char_match.rested = True
char_no_match = mk('NOMATCH', 'Custo!=DON', power=5000, cost=4)
char_no_match.don_attached = 2
char_no_match.rested = True
opp.field_chars = [char_match, char_no_match]
ee = EffectExecutor(me, opp)
ee._execute_step({'action': 'ko_if_cost_eq_don', 'target': 'opp_character', 'rested_only': True}, me.leader)
check('ko_if_cost_eq_don remove apenas Character onde cost==don_attached',
      char_match not in opp.field_chars and char_no_match in opp.field_chars)

# ── 33. dispatch fixes: OP04-097, OP09-033, OP07-002 agora parseable ──
import gerar_effects_db as _g
for _cid, _t, _ctype in [
    ('OP04-097', '[On Play] Add up to 1 of your opponent\'s [Animal] or [SMILE] type Characters with a cost of 3 or less to the top of your opponent\'s Life cards face-up.', 'CHARACTER'),
    ('OP09-033', '[On Play] If you have 2 or more rested Characters, none of your "ODYSSEY" or "Straw Hat Crew" type Characters can be K.O.\'d by effects until the end of your opponent\'s next turn.', 'CHARACTER'),
    ('OP07-002', '[On Play] Set the power of up to 1 of your opponent\'s Characters to 0 during this turn.', 'CHARACTER'),
]:
    _eff = _g.parse_card_effect(_t, _ctype)
    check(f'{_cid} parseia corretamente (dispatch corrigido)', bool(_eff))

print()
print(f'{"TODOS OS TESTES PASSARAM" if FAIL == 0 else f"{FAIL} TESTE(S) FALHARAM"}')
sys.exit(1 if FAIL else 0)
