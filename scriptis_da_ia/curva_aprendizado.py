"""Quanto dado humano seria preciso? Curva de aprendizado por N de LIDERES.

POR QUE (bloco 707)
-------------------
O bloco 706 concluiu que o gargalo e VOLUME de dado humano -- mas isso
era inferencia, nao medicao. Antes de pedir ao usuario que colete mais
partidas (esforco real dele), a pergunta honesta e: **a curva sobe?**

- Se a validacao MELHORA conforme se treina com mais lideres, mais dado
  ajuda, e a inclinacao diz quanto.
- Se fica PLANA, mais dado do mesmo tipo NAO resolve, e pedir coleta
  seria mandar o usuario trabalhar a toa.

Protocolo: fixa um conjunto de lideres de VALIDACAO e varia quantos
lideres entram no TREINO. Repete com varias amostragens pra reduzir o
efeito de quais lideres cairam em cada lado. O baseline e recomputado no
mesmo conjunto de validacao (delta pareado).
"""
from __future__ import annotations

import numpy as np

from fast_eval import agrupa_por_turno, avalia, carrega, rank_motor
from treinar_ranqueador import descobre_categorias, props_das_cartas
from selecao_conjunto import (avalia_conjunto, monta_conjunto,
                              regra_topk_por_limiar)

PARAMS = dict(max_iter=250, learning_rate=0.05, max_depth=4,
              l2_regularization=5.0, min_samples_leaf=25)


def main(repeticoes=4):
    from sklearn.ensemble import HistGradientBoostingClassifier
    linhas = carrega()
    descobre_categorias(linhas)
    props = props_das_cartas()
    turnos = agrupa_por_turno(linhas)
    regra = regra_topk_por_limiar(0.40, 2)
    lideres = sorted({t['leader'] for t in turnos})
    print(f'{len(turnos)} turnos, {len(lideres)} lideres\n')
    print(f'{"lideres no treino":>18}{"turnos":>9}{"validacao":>11}'
          f'{"baseline":>10}{"delta":>9}')
    print('=' * 58)

    for n_tr in (5, 10, 15, 20, 24):
        vals, bases, nturnos = [], [], []
        for rep in range(repeticoes):
            rng = np.random.RandomState(100 + rep)
            ordem = list(lideres)
            rng.shuffle(ordem)
            val_l = set(ordem[:6])
            tr_l = set(ordem[6:6 + n_tr])
            tr = [t for t in turnos if t['leader'] in tr_l]
            va = [t for t in turnos if t['leader'] in val_l]
            if not tr or not va:
                continue
            X, y = monta_conjunto(tr, props)
            if len(X) < 50 or y.sum() < 10:
                continue
            m = HistGradientBoostingClassifier(random_state=13, **PARAMS)
            m.fit(X, y)
            r = avalia_conjunto(va, m, props, regra)
            b = avalia(va, rank_motor)
            vals.append(r['play']); bases.append(b['play'])
            nturnos.append(len(tr))
        if not vals:
            continue
        v, b = float(np.mean(vals)), float(np.mean(bases))
        print(f'{n_tr:>18}{int(np.mean(nturnos)):9}{v*100:10.1f}%'
              f'{b*100:9.1f}%{(v-b)*100:+8.1f}pp')

    print('\n  Leitura: se a coluna `validacao` SOBE com mais lideres,')
    print('  coletar mais partidas ajuda. Se ficar plana, nao ajuda.')


if __name__ == '__main__':
    main()
