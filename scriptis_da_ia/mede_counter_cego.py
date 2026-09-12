"""A certificacao de lethal enxerga o counter da mao do oponente? Bloco 779.

`opp_counter_chunks_for_lethal()` tem tres docstrings afirmando que os slots
OCULTOS da mao entram como estimativa ("slots desconhecidos contam como
possiveis counters de 2000", "slots ocultos usam estimativa por tamanho da
mao"). O CODIGO faz o contrario:

    _ = unknown_hand_size  # reservado para futura estimativa probabilistica

e `known_hand_cards()` devolve so as cartas REVELADAS POR EFEITO -- em partida
normal, quase sempre vazio. Ou seja: a prova de "lethal GARANTIDO" e calculada
como se a mao do oponente nao tivesse counter nenhum.

Este script mede a distancia entre o que a certificacao ASSUMIU e o que o
oponente REALMENTE gastou, no mesmo turno: para cada turno com lethal
certificado, soma os chunks estimados e compara com a soma de `counter_add`
dos `attack_outcome` daquele turno.
"""
from __future__ import annotations
import argparse
import random

from optcg_engine import decision_engine as de


def uma(seed, acc):
    from gerar_selfplay_dataset import _load_deck_list
    dl = _load_deck_list()
    rng = random.Random(seed)
    ia, ib = rng.sample(range(len(dl)), 2)
    random.seed(seed)
    try:
        m = de.OPTCGMatch(dl[ia][1], dl[ib][1])
        m.enable_decision_audit()
        m.setup()
    except Exception:
        return

    est = {'c': None}
    orig = de.GameAnalyzer.can_lethal_this_turn

    def espiao(self):
        r = orig(self)
        if not getattr(m, '_suppress_replay_log', False) and est['c'] is None:
            if r:
                est['c'] = {
                    'chunks': list(self.opp_counter_chunks_for_lethal()),
                    'campo': list(self.opp_reactive_field_buffs()),
                    'mao_opp': len(self.opp.hand),
                    'conhecidas': len(self.opp.known_hand_cards()),
                }
            else:
                est['c'] = False
        return r

    de.GameAnalyzer.can_lethal_this_turn = espiao
    try:
        for t in range(m.MAX_TURNS * 2):
            p = (m.state_a if m.state_a.is_first else m.state_b) if t % 2 == 0 \
                else (m.state_b if m.state_a.is_first else m.state_a)
            opp = m.state_b if p is m.state_a else m.state_a
            est['c'] = None
            marca = len(m.decision_log)
            r = m.play_turn(p, opp)
            if est['c']:
                lado = 'A' if p is m.state_a else 'B'
                atks = [d for d in m.decision_log[marca:]
                        if d.get('kind') == 'attack_outcome' and d.get('player') == lado]
                c = est['c']
                acc.append({
                    'fechou': bool(r),
                    'estimado': sum(c['chunks']),
                    'de_campo': sum(c['campo']),
                    'real': sum(d.get('counter_add') or 0 for d in atks),
                    'mao_opp': c['mao_opp'],
                    'conhecidas': c['conhecidas'],
                })
            if r:
                break
    except Exception:
        pass
    finally:
        de.GameAnalyzer.can_lethal_this_turn = orig


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=40)
    ap.add_argument('--seed', type=int, default=5151)
    a = ap.parse_args()

    acc = []
    for i in range(a.n):
        uma(a.seed * 1_000_003 + i, acc)

    if not acc:
        print('nenhum turno com lethal certificado')
        return
    falhos = [x for x in acc if not x['fechou']]
    subest = [x for x in acc if x['real'] > x['estimado']]
    print('')
    print('CERTIFICACAO DE LETHAL x COUNTER REAL DO OPONENTE')
    print('  turnos com lethal certificado : {}'.format(len(acc)))
    print('  desses, NAO fecharam          : {} ({:.1%})'.format(
        len(falhos), len(falhos) / len(acc)))
    print('')
    print('  mao do oponente (media)       : {:.1f} cartas'.format(
        sum(x['mao_opp'] for x in acc) / len(acc)))
    print('  dessas, CONHECIDAS (reveladas): {:.2f}'.format(
        sum(x['conhecidas'] for x in acc) / len(acc)))
    print('')
    print('  counter que a prova ASSUMIU   : {:.0f} em media'.format(
        sum(x['estimado'] for x in acc) / len(acc)))
    print('    (disso, vindo do CAMPO      : {:.0f})'.format(
        sum(x['de_campo'] for x in acc) / len(acc)))
    print('  counter que o oponente GASTOU : {:.0f} em media'.format(
        sum(x['real'] for x in acc) / len(acc)))
    print('')
    print('  turnos em que o real PASSOU do assumido: {} ({:.1%})'.format(
        len(subest), len(subest) / len(acc)))
    if falhos:
        sf = [x for x in falhos if x['real'] > x['estimado']]
        print('  entre os que NAO fecharam             : {} de {} ({:.1%})'.format(
            len(sf), len(falhos), len(sf) / len(falhos)))


if __name__ == '__main__':
    main()
