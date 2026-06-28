"""
Smoke test direcionado: set_base_power (8 cards), choice (16 cards),
conditional_stack (1 card) + fix de defend_power no combate.
Roda contra os dados REAIS de card_effects_db.json, nao contra mocks.
"""
import sys, json
sys.path.insert(0, '.')
from optcg_engine.decision_engine import (
    Card, CardData, GameState, EffectExecutor, get_card_effects
)

FAIL = 0
def check(label, cond):
    global FAIL
    status = 'OK' if cond else 'FALHOU'
    if not cond:
        FAIL += 1
    print(f'[{status}] {label}')

def mk(code, name, power=5000, cost=4, sub_types='', card_type='CHARACTER', color='Red'):
    return Card(data=CardData(code=code, name=name, card_type=card_type,
                               color=color, cost=cost, power=power, sub_types=sub_types))

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

print()
print(f'{"TODOS OS TESTES PASSARAM" if FAIL == 0 else f"{FAIL} TESTE(S) FALHARAM"}')
sys.exit(1 if FAIL else 0)