"""Com que frequencia o "lethal GARANTIDO" e FALSO? Bloco 778.

Bug achado pelo usuario: `_lethal_search` declara vitoria garantida
considerando atacantes, DON, blockers e counters -- mas **ignora TRIGGERS**
da vida do oponente, que podem KOar um atacante no meio da sequencia e
quebrar o lethal.

A funcao existe pra dar uma GARANTIA. Se a garantia falha, o bot ataca com
tudo, se expoe, e perde na volta -- exatamente o cenario que o usuario
descreveu como decisivo.

ANTES DE CONSERTAR, MEDIR: o bug morde na pratica, ou e teorico? Consertar
de forma conservadora demais desliga lethal legitimo e REGRIDE o jogo, entao
o tamanho do problema define o tamanho do remedio.

Mede: turnos em que `can_lethal_this_turn()` devolveu True e o oponente
SOBREVIVEU ao turno.
"""
from __future__ import annotations
import argparse
import random

from optcg_engine import decision_engine as de


def uma(seed):
    from gerar_selfplay_dataset import _load_deck_list
    dl = _load_deck_list()
    rng = random.Random(seed)
    ia, ib = rng.sample(range(len(dl)), 2)
    random.seed(seed)
    try:
        m = de.OPTCGMatch(dl[ia][1], dl[ib][1])
        m.setup()
    except Exception:
        return None

    prometeu = {'on': False}
    orig = de.GameAnalyzer.can_lethal_this_turn

    def espiao(self):
        r = orig(self)
        if r:
            prometeu['on'] = True
        return r

    de.GameAnalyzer.can_lethal_this_turn = espiao
    declarados = cumpridos = 0
    try:
        for t in range(m.MAX_TURNS * 2):
            p = (m.state_a if m.state_a.is_first else m.state_b) if t % 2 == 0 \
                else (m.state_b if m.state_a.is_first else m.state_a)
            opp = m.state_b if p is m.state_a else m.state_a
            prometeu['on'] = False
            r = m.play_turn(p, opp)
            if prometeu['on']:
                declarados += 1
                if r:
                    cumpridos += 1
            if r:
                break
    except Exception:
        return None
    finally:
        de.GameAnalyzer.can_lethal_this_turn = orig
    return declarados, cumpridos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=40)
    ap.add_argument('--seed', type=int, default=5151)
    a = ap.parse_args()

    tot_d = tot_c = partidas = 0
    for i in range(a.n):
        r = uma(a.seed * 1_000_003 + i)
        if r is None:
            continue
        d, c = r
        tot_d += d
        tot_c += c
        partidas += 1

    print('')
    print('LETHAL "GARANTIDO": cumpre a promessa?')
    print('  partidas validas          : {}'.format(partidas))
    print('  turnos com lethal DECLARADO: {}'.format(tot_d))
    print('  desses, o jogo ACABOU      : {}'.format(tot_c))
    if tot_d:
        print('  promessa FALHOU em         : {} ({:.1%})'.format(
            tot_d - tot_c, (tot_d - tot_c) / tot_d))
    print('')
    print('RESSALVA: "falhou" aqui inclui causas alem de trigger -- o bot')
    print('pode declarar lethal e a BUSCA escolher outra linha, ou a execucao')
    print('divergir da alocacao certificada. Este numero e o TETO do problema,')
    print('nao a medida isolada do trigger.')


if __name__ == '__main__':
    main()
