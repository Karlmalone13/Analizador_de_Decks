"""Sanidade: o caminho ALVO_EFEITO_NA_BUSCA=True roda sem quebrar?

Ele existe desde 29/08 (commit 3c3f4a0) e nunca foi ligado. Antes de gastar
uma hora de duelo, conferir que (a) nao levanta excecao e (b) de fato GERA
candidatas por alvo -- se gerar zero, nao ha o que medir.
"""
import random
from optcg_engine import decision_engine as de


def uma(seed, ligado):
    from gerar_selfplay_dataset import _load_deck_list
    dl = _load_deck_list()
    rng = random.Random(seed)
    ia, ib = rng.sample(range(len(dl)), 2)
    random.seed(seed)
    m = de.OPTCGMatch(dl[ia][1], dl[ib][1])
    m.setup()
    for lado in (m.state_a, m.state_b):
        lado.value_net_weight = 0.0
        lado.alvo_efeito_na_busca = ligado
    venc, turnos = None, 0
    for turn in range(m.MAX_TURNS * 2):
        p = (m.state_a if m.state_a.is_first else m.state_b) if turn % 2 == 0 else (m.state_b if m.state_a.is_first else m.state_a)
        opp = m.state_b if p is m.state_a else m.state_a
        turnos += 1
        r = m.play_turn(p, opp)
        if r:
            venc = r
            break
    return venc, turnos


def main():
    # conta quantas candidatas 'effect_target' sao geradas
    n = [0]
    orig = de._variantes_de_alvo

    def espiao(*a, **k):
        r = orig(*a, **k)
        n[0] += len(r)
        return r
    de._variantes_de_alvo = espiao

    for ligado in (False, True):
        n[0] = 0
        try:
            venc, turnos = uma(909, ligado)
            print('knob={:<5} -> vencedor {} em {} turnos | candidatas por alvo geradas: {}'
                  .format(str(ligado), venc, turnos, n[0]))
        except Exception as e:
            print('knob={:<5} -> QUEBROU: {}: {}'.format(
                str(ligado), type(e).__name__, str(e)[:120]))
            raise


if __name__ == '__main__':
    main()
