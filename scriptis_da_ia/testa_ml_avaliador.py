"""ML COMO AVALIADOR: quanto custa a partida, comparado com o rollout?

Bloco 769. A afirmacao estrutural a verificar: avaliar LOGO APOS a acao
(uma consulta ao modelo) em vez de simular dois turnos por candidata deve
derrubar o custo por partida em ordem de grandeza -- 85% do tempo hoje e
simulacao (bloco 765).

AVISO DE INTERPRETACAO: o modelo disponivel foi treinado em estados de FIM
DE TURNO. Usado aqui, ele ve estados de OUTRA natureza (logo apos a acao).
Entao este teste mede CUSTO, nao QUALIDADE -- a qualidade exige retreinar
sobre estados pos-acao, que e o proximo passo.
"""
from __future__ import annotations
import random
import time

from optcg_engine import decision_engine as de


def uma(seed, ml_avaliador):
    from gerar_selfplay_dataset import _load_deck_list
    dl = _load_deck_list()
    rng = random.Random(seed)
    ia, ib = rng.sample(range(len(dl)), 2)
    random.seed(seed)
    m = de.OPTCGMatch(dl[ia][1], dl[ib][1])
    m.setup()
    for lado in (m.state_a, m.state_b):
        lado.value_net_weight = 200.0
        lado.ml_avaliador = ml_avaliador
    venc, turnos = None, 0
    t_w, t_c = time.perf_counter(), time.process_time()
    for t in range(m.MAX_TURNS * 2):
        p = (m.state_a if m.state_a.is_first else m.state_b) if t % 2 == 0 \
            else (m.state_b if m.state_a.is_first else m.state_a)
        opp = m.state_b if p is m.state_a else m.state_a
        turnos += 1
        r = m.play_turn(p, opp)
        if r:
            venc = r
            break
    return (venc, turnos, time.perf_counter() - t_w, time.process_time() - t_c)


def main():
    print('{:<22}{:>10}{:>9}{:>9}{:>10}'.format(
        'modo', 'relogio', 'CPU', 'turnos', 'vencedor'))
    res = {}
    for nome, flag in (('rollout (hoje)', False), ('ML avaliador', True)):
        tempos = []
        for seed in (909, 4242):
            v, tn, w, c = uma(seed, flag)
            tempos.append((w, c))
            print('{:<22}{:>9.1f}s{:>8.1f}s{:>9}{:>10}'.format(
                nome + ' s' + str(seed), w, c, tn, str(v)))
        res[nome] = min(t[0] for t in tempos)
    a, b = res['rollout (hoje)'], res['ML avaliador']
    print('')
    print('menor tempo  rollout: {:.1f}s | ML avaliador: {:.1f}s'.format(a, b))
    if b > 0:
        print('ACELERACAO: {:.1f}x'.format(a / b))
    print('')
    print('LEMBRETE: isto mede CUSTO. A QUALIDADE exige retreinar o modelo')
    print('sobre estados POS-ACAO -- o modelo atual viu FIM DE TURNO.')


if __name__ == '__main__':
    main()
