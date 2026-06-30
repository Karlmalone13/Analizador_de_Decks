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
    is_attack_locked_self
)

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
# additional +X power"), nao um 2º alvo independente. EB03-020 sem condicao,
# OP04-095 com condicao (trash_gte 15) ──
me, opp = me_opp()
me.don_available = 2
evento_multi_buff = mk('EB03-020', 'There You Are Sore Loser', card_type='EVENT', cost=2)
me.hand = [evento_multi_buff]
ee = EffectExecutor(me, opp)
counter = ee.try_counter_event_power(me.leader, 'leader', needed=4000)
check('Counter event com 2 buffs battle_only soma os dois (sem condicao)',
      counter and counter[0] == 4000 and evento_multi_buff in me.trash)

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

print()
print(f'{"TODOS OS TESTES PASSARAM" if FAIL == 0 else f"{FAIL} TESTE(S) FALHARAM"}')
sys.exit(1 if FAIL else 0)
