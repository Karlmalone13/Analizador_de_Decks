"""FASE 1 -- PREMISSA: o rotulo de hoje e ruim? Bloco 783.

Sem simulacao: reanalisa o corpus que ja existe.

O rotulo atual e `win` -- "esta PARTIDA terminou em vitoria?" -- copiado
igual pra TODOS os estados da partida. Um estado do turno 4 recebe o mesmo
rotulo que o do turno 22.

Duas consequencias testaveis, e as duas so precisam de aritmetica:

  1. RUIDO DE ATRIBUICAO: se o rotulo e da PARTIDA e nao da POSICAO, entao
     saber de que partida o estado veio explica quase toda a variacao do
     rotulo. Mede-se comparando a variancia DENTRO da partida (que e ZERO
     por construcao) com a variancia ENTRE partidas.

  2. SINAL DESPERDICADO: a vantagem de vida nos proximos N turnos e um sinal
     DENSO, especifico da posicao, e ja esta no corpus (`life_diff` esta nas
     features). Se ele discordar muito do rotulo atual, ha informacao sendo
     jogada fora.

Se as duas confirmarem, a Fase 1 esta justificada SEM rodar uma partida.
"""
from __future__ import annotations
import argparse
import collections
import io
import json

import numpy as np

from optcg_engine import value_net as vn


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--corpus', default='metrics/selfplay_pos_acao_grande.jsonl')
    ap.add_argument('--n', type=int, default=2, help='horizonte em TURNOS do lado')
    a = ap.parse_args()

    nomes = list(vn.FEATURE_NAMES_V3)
    i_ld = nomes.index('life_diff')
    i_lm = nomes.index('life_mine')
    i_lo = nomes.index('life_opp')

    regs = []
    for L in io.open(a.corpus, encoding='utf-8'):
        d = json.loads(L)
        if 'win' not in d or 'feats' not in d:
            continue
        f = d['feats']
        regs.append((d.get('match'), d.get('side'), d.get('turn'), int(d['win']),
                     f[i_ld], f[i_lm], f[i_lo]))
    print('')
    print('CORPUS: {} estados'.format(len(regs)))

    # ── 1. quanto o rotulo e da PARTIDA e nao da POSICAO ───────────────────
    por_partida = collections.defaultdict(list)
    for m, s, t, w, ld, lm, lo in regs:
        por_partida[(m, s)].append(w)
    y = np.array([w for _, _, _, w, _, _, _ in regs], float)
    var_total = y.var()
    # variancia DENTRO de cada partida-lado
    dentro = np.mean([np.var(v) for v in por_partida.values() if len(v) > 1])
    print('')
    print('1) O ROTULO E DA PARTIDA OU DA POSICAO?')
    print('   partidas-lado distintos      : {}'.format(len(por_partida)))
    print('   estados por partida-lado     : {:.1f}'.format(len(regs) / len(por_partida)))
    print('   variancia TOTAL do rotulo    : {:.4f}'.format(var_total))
    print('   variancia DENTRO da partida  : {:.4f}'.format(dentro))
    print('   -> {:.1%} da variacao do rotulo e EXPLICADA pela partida,'.format(
        1 - (dentro / var_total if var_total else 0)))
    print('      nao pela posicao. Todo estado da mesma partida leva o MESMO')
    print('      rotulo, do turno 1 ao ultimo.')

    # ── 2. o sinal denso que esta sendo desperdicado ───────────────────────
    seq = collections.defaultdict(list)
    for idx, (m, s, t, w, ld, lm, lo) in enumerate(regs):
        seq[(m, s)].append((t if t is not None else 0, idx, ld))
    ganho, atual = [], []
    for k, v in seq.items():
        v.sort()
        for j in range(len(v)):
            alvo = min(j + a.n, len(v) - 1)
            if alvo == j:
                continue
            ganho.append(v[alvo][2] - v[j][2])     # variacao de life_diff
            atual.append(regs[v[j][1]][3])          # rotulo de hoje
    ganho, atual = np.array(ganho, float), np.array(atual, float)
    print('')
    print('2) O SINAL DENSO QUE ESTA SENDO IGNORADO')
    print('   pares (estado, estado+{} passos): {}'.format(a.n, len(ganho)))
    print('   variacao de life_diff: media {:+.3f} | desvio {:.3f}'.format(
        ganho.mean(), ganho.std()))
    melhora = ganho > 0
    print('   posicoes que MELHORARAM      : {:.1%}'.format(melhora.mean()))
    print('   dessas, o rotulo diz VITORIA : {:.1%}'.format(atual[melhora].mean()))
    piora = ganho < 0
    print('   posicoes que PIORARAM        : {:.1%}'.format(piora.mean()))
    print('   dessas, o rotulo diz VITORIA : {:.1%}'.format(atual[piora].mean()))
    if len(ganho) > 2 and ganho.std() > 0:
        print('   correlacao (ganho x rotulo)  : {:+.4f}'.format(
            float(np.corrcoef(ganho, atual)[0, 1])))
    print('')
    print('LEITURA: se jogadas que MELHORAM e que PIORAM a posicao recebem')
    print('rotulo quase igual, o modelo nao tem como distinguir jogada boa de')
    print('ruim -- ele so aprende quem ganhou a partida.')


if __name__ == '__main__':
    main()
