"""Por que a arvore e ESTREITA na distribuicao de DON? Bloco 780.

Achado ao ler `_generate_attach_don_actions_inner`: o candidato de "anexar
DON pra atacar" so nasce quando ha GAP DE PODER a fechar --

    gap = alvo_power - atk_now
    if gap > 0 and gap <= p.don_available * 1000:
        falta = -(-gap // 1000)     # so o necessario pra EMPATAR

Tres consequencias, se confirmadas:
  1. atacante que JA ganha do alvo (gap <= 0) nao gera candidata nenhuma de
     DON -- mesmo quando anexar seria certo pra furar counter;
  2. so UM valor de DON por (atacante, alvo): o de empatar. Nunca mais;
  3. nunca se considera DISTRIBUIR DON entre varios atacantes.

Se for isso, a familia "distribuicao de DON" -- 2a pior contra humano (23,5%)
e coracao de qualquer combo -- tem a arvore estreitada NA GERACAO, antes de
qualquer pontuacao. Nenhum modelo melhor alcanca o que nao foi gerado.

CONTRASTE que torna o achado mais forte: `_lethal_search` JA enumera TODAS as
alocacoes de DON exaustivamente (`search_alloc`). O motor tem a maquinaria --
ela so nao e usada no jogo normal.
"""
from __future__ import annotations
import argparse
import collections
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

    orig = de.OPTCGMatch._generate_and_score_actions

    def espiao(self, p, opp, engine, exclude_activate_uids=None):
        acts = orig(self, p, opp, engine, exclude_activate_uids)
        if not getattr(self, '_suppress_replay_log', False):
            ad = [a for a in acts if a[1] == 'attach_don']
            atk = [a for a in acts if a[1] == 'attack']
            acc['decisoes'] += 1
            acc['n_attach'].append(len(ad))
            acc['n_attack'].append(len(atk))
            # quantos DON distintos por atacante?
            por_alvo = collections.defaultdict(set)
            for a in ad:
                por_alvo[id(a[2])].add(a[3])
            for v in por_alvo.values():
                acc['valores_por_atacante'].append(len(v))
            for a in ad:
                acc['quanto_don'][a[3]] += 1
            # atacantes SEM nenhuma candidata de DON
            ids_com = set(por_alvo)
            for a in atk:
                if id(a[2]) not in ids_com:
                    acc['atacante_sem_don'] += 1
                else:
                    acc['atacante_com_don'] += 1
        return acts

    de.OPTCGMatch._generate_and_score_actions = espiao
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
        de.OPTCGMatch._generate_and_score_actions = orig


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=6)
    ap.add_argument('--seed', type=int, default=4242)
    a = ap.parse_args()

    acc = {'decisoes': 0, 'n_attach': [], 'n_attack': [],
           'valores_por_atacante': [], 'quanto_don': collections.Counter(),
           'atacante_sem_don': 0, 'atacante_com_don': 0}
    for i in range(a.n):
        uma(a.seed * 1_000_003 + i, acc)

    na, nk = acc['n_attach'], acc['n_attack']
    v = acc['valores_por_atacante']
    print('')
    print('DISTRIBUICAO DE DON -- o que chega a ser CANDIDATO')
    print('  decisoes observadas                : {}'.format(acc['decisoes']))
    if na:
        print('  candidatas attach_don por decisao  : media {:.2f} | max {}'.format(
            sum(na) / len(na), max(na)))
        print('  decisoes com ZERO attach_don      : {:.1%}'.format(
            sum(1 for x in na if x == 0) / len(na)))
    if v:
        print('')
        print('  VALORES de DON distintos por atacante:')
        print('    media {:.2f} | max {}'.format(sum(v) / len(v), max(v)))
        print('    atacantes com so 1 valor: {:.1%}   <-- so "empatar o alvo"'.format(
            sum(1 for x in v if x == 1) / len(v)))
    s, c = acc['atacante_sem_don'], acc['atacante_com_don']
    if s + c:
        print('')
        print('  candidatas de ATAQUE cujo atacante NAO tem nenhuma opcao de DON:')
        print('    {} de {} ({:.1%})'.format(s, s + c, s / (s + c)))
    print('')
    print('  quanto DON as candidatas propoem: {}'.format(', '.join(
        '{} DON: {}x'.format(k, n) for k, n in sorted(acc['quanto_don'].items()))))
    print('')
    print('CONTRASTE: `_lethal_search` enumera TODAS as alocacoes de DON')
    print('(search_alloc, recursao exaustiva). A maquinaria existe -- so nao')
    print('e usada fora da prova de lethal.')


if __name__ == '__main__':
    main()
