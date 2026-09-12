"""FASE 0 do plano professor/aluno: qual o TAMANHO da espiada? Bloco 782.

O motor e inconsistente hoje:
  - o rollout Monte Carlo MASCARA a mao do oponente (`OpponentModel.sample`)
  - `opp_counter_potential()` LE A MAO REAL em auto-jogo
  - a flag que cegaria (`self_play_info_hidden`) existe e NUNCA e ligada

Consequencia: calibramos num mundo (bot ve a mao) e jogamos noutro (ao vivo a
mao chega mascarada, `hidden_information_masked`). Todo dado de treino sai de
um jogador que NAO PODE EXISTIR ao vivo.

CONSUMIDORES de `opp_counter_potential()` -- listados antes de mexer, como
manda a regra do bloco 780 (a flag de lethal alimentava 7 pontos e eu mexi nos
7 de uma vez):
  1. `don_needed_for_attack`   -> quanto DON anexar num ataque
  2. linha 15091               -> se o ataque passa a defesa do lider
  3. linha 19257               -> defesa esperada no alvo

Os tres respondem "quanta defesa o oponente vai montar". Mede o quanto a
resposta MUDA ao parar de espiar -- se muda pouco, a Fase 0 e barata; se muda
muito, ela explica parte da distancia entre auto-jogo e partida real.
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
        m.setup()
    except Exception:
        return

    orig = de.GameAnalyzer.opp_counter_potential

    def espiao(self):
        espiando = orig(self)               # como e hoje: le a mao real
        antes = getattr(self.opp, 'self_play_info_hidden', False)
        self.opp.self_play_info_hidden = True
        try:
            cego = orig(self)               # como seria cego: estimativa
        finally:
            if antes:
                self.opp.self_play_info_hidden = True
            else:
                try:
                    del self.opp.self_play_info_hidden
                except Exception:
                    self.opp.self_play_info_hidden = False
        if not getattr(m, '_suppress_replay_log', False):
            acc['n'] += 1
            acc['espiando'].append(espiando)
            acc['cego'].append(cego)
            if espiando != cego:
                acc['difere'] += 1
            # a diferenca cruza um limiar de 1000 (1 DON)?
            if abs(espiando - cego) >= 1000:
                acc['difere_1don'] += 1
        return espiando

    de.GameAnalyzer.opp_counter_potential = espiao
    try:
        for t in range(m.MAX_TURNS * 2):
            p = (m.state_a if m.state_a.is_first else m.state_b) if t % 2 == 0 \
                else (m.state_b if m.state_a.is_first else m.state_a)
            opp = m.state_b if p is m.state_a else m.state_a
            if m.play_turn(p, opp):
                break
    except Exception:
        pass
    finally:
        de.GameAnalyzer.opp_counter_potential = orig


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=8)
    ap.add_argument('--seed', type=int, default=6161)
    a = ap.parse_args()

    acc = {'n': 0, 'difere': 0, 'difere_1don': 0, 'espiando': [], 'cego': []}
    for i in range(a.n):
        uma(a.seed * 1_000_003 + i, acc)

    if not acc['n']:
        print('sem consultas observadas'); return
    e, c = acc['espiando'], acc['cego']
    print('')
    print('TAMANHO DA ESPIADA -- `opp_counter_potential()`')
    print('  consultas REAIS observadas : {}'.format(acc['n']))
    print('')
    print('  counter previsto ESPIANDO  : {:.0f} (media)'.format(sum(e) / len(e)))
    print('  counter previsto CEGO      : {:.0f} (media)'.format(sum(c) / len(c)))
    print('  vies (espiando - cego)     : {:+.0f}'.format(
        (sum(e) - sum(c)) / len(e)))
    print('')
    print('  consultas em que os dois DIFEREM : {} ({:.1%})'.format(
        acc['difere'], acc['difere'] / acc['n']))
    print('  diferenca >= 1000 (1 DON inteiro): {} ({:.1%})'.format(
        acc['difere_1don'], acc['difere_1don'] / acc['n']))
    print('')
    print('LEITURA: >= 1000 e o que muda DECISAO -- e o degrau de 1 DON no')
    print('calculo de quanto anexar pra um ataque passar.')


if __name__ == '__main__':
    main()
