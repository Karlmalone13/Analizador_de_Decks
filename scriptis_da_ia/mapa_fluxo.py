"""MAPA AS-IS do fluxo de decisao: quanto custa CADA ETAPA (bloco 765).

Pedido do usuario: parar de otimizar funcao isolada e mapear o PROCESSO --
onde o dado trava, onde ha espera, e priorizar por impacto (Pareto/Lean).

O motor, a cada decisao, faz isto para CADA candidata:
  1. gera e pontua as candidatas
  2. clona o estado inteiro (deepcopy)
  3. aplica a 1a acao e continua gulosamente ate o fim do turno
  4. simula o TURNO INTEIRO de resposta do oponente
  5. as vezes simula o PROPRIO turno seguinte (lookahead)
  6. avalia a posicao final (heuristica + modelo)

A repartição entre 3, 4, 5 e 6 NUNCA foi medida. Se a resposta do oponente
custar metade do tempo, a pergunta deixa de ser "como deixar isso rapido" e
vira "isso precisa rodar pra TODAS as candidatas ou so pras finalistas?" --
mesma qualidade na decisao final, fracao do custo.

Instrumenta por FORA (monkeypatch), sem tocar no motor.
"""
import random, time, collections
from optcg_engine import decision_engine as de
from optcg_engine import value_net as vn

T = collections.Counter()
N = collections.Counter()
_prof = {'dentro_sim': 0}


def cron(tag, fn, *a, **k):
    t0 = time.perf_counter()
    try:
        return fn(*a, **k)
    finally:
        T[tag] += time.perf_counter() - t0
        N[tag] += 1


def main():
    M = de.OPTCGMatch
    o_sim = M._simulate_sequence_once
    o_ger = M._generate_and_score_actions
    o_gre = M._play_turn_greedy
    o_ev2 = M._evaluate_state_v2
    o_apl = M._apply_action
    o_wp = vn.win_prob

    def sim(self, *a, **k):
        _prof['dentro_sim'] += 1
        _prof['greedy_no_sim'] = 0
        try:
            return cron('2..6 SIMULACAO (total por candidata)', o_sim, self, *a, **k)
        finally:
            _prof['dentro_sim'] -= 1

    def ger(self, *a, **k):
        # So conta a geracao de TOPO (fora da simulacao); a de dentro do laco
        # guloso ja esta contabilizada na etapa 3.
        tag = ('3 continuacao gulosa (gera dentro da sim)' if _prof['dentro_sim']
               else '1 GERAR+PONTUAR candidatas (topo)')
        return cron(tag, o_ger, self, *a, **k)

    def gre(self, p, opp, *a, **k):
        if _prof['dentro_sim']:
            _prof['greedy_no_sim'] += 1
            tag = ('4 RESPOSTA DO OPONENTE' if _prof['greedy_no_sim'] == 1
                   else '5 LOOKAHEAD proprio turno')
        else:
            tag = 'greedy fora da simulacao'
        return cron(tag, o_gre, self, p, opp, *a, **k)

    def ev2(self, *a, **k):
        return cron('6a AVALIAR posicao (heuristica)', o_ev2, self, *a, **k)

    def apl(self, *a, **k):
        return cron('2b APLICAR acao', o_apl, self, *a, **k)

    def wp(*a, **k):
        return cron('6b AVALIAR posicao (modelo ML)', o_wp, *a, **k)

    M._simulate_sequence_once = sim
    M._generate_and_score_actions = ger
    M._play_turn_greedy = gre
    M._evaluate_state_v2 = ev2
    M._apply_action = apl
    vn.win_prob = wp

    from gerar_selfplay_dataset import _load_deck_list
    dl = _load_deck_list()
    rng = random.Random(909)
    ia, ib = rng.sample(range(len(dl)), 2)
    random.seed(909)
    m = de.OPTCGMatch(dl[ia][1], dl[ib][1])
    m.setup()
    m.state_a.value_net_weight = 200.0
    m.state_b.value_net_weight = 200.0

    t0 = time.perf_counter()
    for turn in range(m.MAX_TURNS * 2):
        p = (m.state_a if m.state_a.is_first else m.state_b) if turn % 2 == 0 else (m.state_b if m.state_a.is_first else m.state_a)
        opp = m.state_b if p is m.state_a else m.state_a
        if m.play_turn(p, opp):
            break
    total = time.perf_counter() - t0

    print('')
    print('MAPA AS-IS -- uma partida completa: {:.1f}s'.format(total))
    print('(com overhead de instrumentacao; use as PROPORCOES, nao os absolutos)')
    print('')
    print('{:<44}{:>9}{:>10}{:>9}'.format('etapa', 'chamadas', 'tempo', '% total'))
    for tag in sorted(T, key=lambda k: -T[k]):
        print('{:<44}{:>9,}{:>9.1f}s{:>8.1f}%'.format(
            tag, N[tag], T[tag], 100 * T[tag] / total))
    print('')
    dentro = (T.get('4 RESPOSTA DO OPONENTE', 0)
              + T.get('5 LOOKAHEAD proprio turno', 0)
              + T.get('6a AVALIAR posicao (heuristica)', 0)
              + T.get('6b AVALIAR posicao (modelo ML)', 0)
              + T.get('3 continuacao gulosa (gera dentro da sim)', 0))
    sim_total = T.get('2..6 SIMULACAO (total por candidata)', 0)
    print('DENTRO da simulacao por candidata ({:.1f}s no total):'.format(sim_total))
    if sim_total:
        for tag in ('3 continuacao gulosa (gera dentro da sim)',
                    '4 RESPOSTA DO OPONENTE', '5 LOOKAHEAD proprio turno',
                    '6a AVALIAR posicao (heuristica)', '6b AVALIAR posicao (modelo ML)'):
            if T.get(tag):
                print('   {:<46} {:>5.1f}% da simulacao'.format(
                    tag, 100 * T[tag] / sim_total))
        print('   {:<46} {:>5.1f}% (clone/remap/resto)'.format(
            'NAO atribuido', 100 * (sim_total - dentro) / sim_total))


if __name__ == '__main__':
    main()
