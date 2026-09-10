"""Existe oportunidade real em trazer a ESCOLHA DE ALVO pra dentro da busca?

Hipotese (bloco 761): o value_net tem alavanca baixa porque so ordena a
acao de topo -- o "em quem" e decidido por `choose_highest_board_value`
(literalmente `max(cards, key=board_value)`), regra fixa fora da busca.

Mas isso so importa se houver ESCOLHA de fato. Se quase sempre houver 1
alvo legal, ou se o segundo colocado for muito pior que o primeiro, nao ha
o que ganhar -- e o custo seria alto, porque cada alvo vira uma candidata
a mais na busca.

Mede, numa partida real: quantos alvos candidatos existem por chamada, se
ha empate no topo, e a distancia entre 1o e 2o.
"""
import random, collections
from optcg_engine import rules_facade

_orig = rules_facade.choose_highest_board_value
hist = collections.Counter()
gaps = []
empates = [0]


def espiao(cards):
    n = len(cards) if cards else 0
    hist[n] += 1
    if n >= 2:
        vals = sorted((c.board_value() for c in cards), reverse=True)
        if vals[0] == vals[1]:
            empates[0] += 1
        gaps.append((vals[0] - vals[1]) / max(abs(vals[0]), 1e-9))
    return _orig(cards)


def main():
    rules_facade.choose_highest_board_value = espiao
    import optcg_engine.decision_engine as de
    de.choose_highest_board_value = espiao
    from gerar_selfplay_dataset import _load_deck_list
    from optcg_engine.decision_engine import OPTCGMatch

    dl = _load_deck_list()
    for seed in (909, 4242):
        rng = random.Random(seed)
        ia, ib = rng.sample(range(len(dl)), 2)
        random.seed(seed)
        m = OPTCGMatch(dl[ia][1], dl[ib][1])
        m.setup()
        m.state_a.value_net_weight = 200.0
        m.state_b.value_net_weight = 200.0
        for turn in range(m.MAX_TURNS * 2):
            p = (m.state_a if m.state_a.is_first else m.state_b) if turn % 2 == 0 else (m.state_b if m.state_a.is_first else m.state_a)
            opp = m.state_b if p is m.state_a else m.state_a
            if m.play_turn(p, opp):
                break

    tot = sum(hist.values())
    com_escolha = sum(v for k, v in hist.items() if k >= 2)
    print('')
    print('chamadas a choose_highest_board_value: {:,} (2 partidas)'.format(tot))
    print('')
    print('{:>10}{:>10}{:>9}'.format('candidatos', 'chamadas', '%'))
    for n in sorted(hist):
        print('{:>10}{:>10,}{:>8.1%}'.format(n, hist[n], hist[n] / tot))
    print('')
    print('COM escolha real (>=2 alvos): {:,} ({:.1%})'.format(
        com_escolha, com_escolha / max(tot, 1)))
    if gaps:
        gaps.sort()
        print('empate no topo (1o == 2o)   : {:,} ({:.1%} das com escolha)'.format(
            empates[0], empates[0] / len(gaps)))
        print('distancia relativa 1o vs 2o : mediana {:.1%} | p25 {:.1%} | p75 {:.1%}'.format(
            gaps[len(gaps)//2], gaps[len(gaps)//4], gaps[3*len(gaps)//4]))
        quase = sum(1 for g in gaps if g < 0.10)
        print('casos "quase empate" (<10% de diferenca): {:,} ({:.1%})'.format(
            quase, quase / len(gaps)))


if __name__ == '__main__':
    main()
