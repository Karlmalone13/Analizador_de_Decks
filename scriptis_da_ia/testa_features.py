"""Confere que as features ricas (a) calculam, (b) sao compativeis com o
modelo VELHO (32) e (c) DISTINGUEM boards que as 32 nao distinguiam."""
import random
from optcg_engine import value_net as vn


def main():
    from gerar_selfplay_dataset import _load_deck_list
    from optcg_engine.decision_engine import OPTCGMatch
    dl = _load_deck_list()
    rng = random.Random(909)
    ia, ib = rng.sample(range(len(dl)), 2)
    random.seed(909)
    m = OPTCGMatch(dl[ia][1], dl[ib][1])
    m.setup()
    for t in range(8):
        p = (m.state_a if m.state_a.is_first else m.state_b) if t % 2 == 0 else (m.state_b if m.state_a.is_first else m.state_a)
        opp = m.state_b if p is m.state_a else m.state_a
        if m.play_turn(p, opp):
            break

    p, opp = m.state_a, m.state_b
    v32 = vn.state_features(p, opp)
    v49 = vn.state_features(p, opp, nomes=vn.FEATURE_NAMES_RICAS)
    print('default (compat modelo velho): {} valores'.format(len(v32)))
    print('ricas                        : {} valores'.format(len(v49)))
    print('as 32 primeiras batem        :', v32 == v49[:32])
    print('')
    print('valores das 17 novas neste board:')
    for nome, val in zip(vn.FEATURE_NAMES_RICAS[32:], v49[32:]):
        print('  {:<22} {}'.format(nome, val))
    print('')
    print('modelo velho ainda carrega e roda:')
    b = vn.load_value_net()
    print('  win_prob:', vn.win_prob(p, opp, bundle=b))


if __name__ == '__main__':
    main()
