"""Busca de hiperparametros + selecao de atributos (bloco 771).

Fecha as duas ultimas pendencias do roteiro de ML que o usuario trouxe:

  3. Ajuste de hiperparametros ... nunca feito -- `max_iter=200,
     learning_rate=0.06, max_depth=4` estavam FIXOS no chute
  3. Overfitting ................. detectado e NAO tratado: 0,977 no treino
     contra 0,776 no teste, vao extremo

Isto E trabalho de "tornar o ML bom", nao periferia: um modelo que decora
nao aprende, e a exigencia central registrada e que o bot aprenda
EMPIRICAMENTE.

Avalia tudo no MESMO conjunto de teste por LIDER (lideres nunca vistos),
que e o unico numero honesto aqui -- o objetivo do projeto e jogar bem com
QUALQUER deck.

Testa tambem REMOVER as features que a analise do bloco 768 mostrou
inuteis: com 1.582 estados, menos coluna costuma valer mais que mais
coluna.

Uso: python tunar_value.py --dataset metrics/selfplay_ricas.jsonl --features ricas
"""
from __future__ import annotations
import argparse
import itertools
import json

import numpy as np

from optcg_engine.value_net import (FEATURE_NAMES, FEATURE_NAMES_RICAS,
                                    FEATURE_NAMES_V3)

CONJ = {'basicas': FEATURE_NAMES, 'ricas': FEATURE_NAMES_RICAS,
        'v3': FEATURE_NAMES_V3}


def carregar(path):
    X, y, g = [], [], []
    for linha in open(path, encoding='utf-8'):
        linha = linha.strip()
        if not linha:
            continue
        d = json.loads(linha)
        X.append(d['feats'])
        y.append(int(d['win']))
        g.append(d.get('leader', '?'))
    return np.array(X, float), np.array(y, int), np.array(g)


def main():
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.inspection import permutation_importance
    from sklearn.metrics import roc_auc_score

    ap = argparse.ArgumentParser()
    ap.add_argument('--dataset', default='metrics/selfplay_ricas.jsonl')
    ap.add_argument('--features', choices=tuple(CONJ), default='ricas')
    a = ap.parse_args()

    X, y, g = carregar(a.dataset)
    nomes_ds = {len(v): v for v in CONJ.values()}[X.shape[1]]
    nomes = list(CONJ[a.features])
    X = X[:, [nomes_ds.index(n) for n in nomes]]

    lideres = sorted(set(g))
    rng = np.random.RandomState(42)
    rng.shuffle(lideres)
    lid_te = set(lideres[:max(1, len(lideres) // 5)])
    m_te = np.array([x in lid_te for x in g])
    Xtr, ytr = X[~m_te], y[~m_te]
    Xte, yte = X[m_te], y[m_te]
    print('dataset {} | {} features ({})'.format(a.dataset, len(nomes), a.features))
    print('treino {:,} estados | TESTE {:,} estados, {} lideres nunca vistos'
          .format(len(Xtr), len(Xte), len(lid_te)))

    def avalia(Xa, Xb, **kw):
        m = HistGradientBoostingClassifier(random_state=0, **kw).fit(Xa, ytr)
        return (roc_auc_score(ytr, m.predict_proba(Xa)[:, 1]),
                roc_auc_score(yte, m.predict_proba(Xb)[:, 1]), m)

    base_kw = dict(max_iter=200, learning_rate=0.06, max_depth=4)
    tr0, te0, _ = avalia(Xtr, Xte, **base_kw)
    print('')
    print('BASE (os parametros fixos de hoje): treino {:.4f} | TESTE {:.4f}'
          .format(tr0, te0))

    print('')
    print('=' * 68)
    print('1. BUSCA DE HIPERPARAMETROS (regularizacao contra o sobre-ajuste)')
    print('=' * 68)
    grade = {
        'max_depth': [2, 3, 4, None],
        'learning_rate': [0.02, 0.06],
        'min_samples_leaf': [20, 60, 150],
        'l2_regularization': [0.0, 1.0, 10.0],
    }
    print('{:>6}{:>8}{:>8}{:>8}{:>10}{:>10}{:>8}'.format(
        'depth', 'lr', 'minleaf', 'l2', 'treino', 'TESTE', 'vao'))
    melhor = (te0, base_kw)
    combos = list(itertools.product(*grade.values()))
    for d, lr, msl, l2 in combos:
        kw = dict(max_iter=300, learning_rate=lr, max_depth=d,
                  min_samples_leaf=msl, l2_regularization=l2,
                  early_stopping=True, validation_fraction=0.15)
        tr, te, _ = avalia(Xtr, Xte, **kw)
        if te > melhor[0]:
            melhor = (te, kw)
            print('{:>6}{:>8}{:>8}{:>8}{:>10.4f}{:>10.4f}{:>8.3f}  <-- melhor'
                  .format(str(d), lr, msl, l2, tr, te, tr - te))
    print('')
    print('MELHOR fora da amostra: {:.4f}  (base {:.4f}, ganho {:+.4f})'
          .format(melhor[0], te0, melhor[0] - te0))
    print('parametros: {}'.format(
        {k: v for k, v in melhor[1].items() if k != 'random_state'}))

    print('')
    print('=' * 68)
    print('2. SELECAO DE ATRIBUTOS (remover o que o modelo nao usa)')
    print('=' * 68)
    _, _, m_best = avalia(Xtr, Xte, **melhor[1])
    r = permutation_importance(m_best, Xte, yte, n_repeats=8,
                               random_state=0, scoring='roc_auc')
    ordem = np.argsort(-r.importances_mean)
    print('{:>8}{:>12}{:>12}{:>9}'.format('mantidas', 'treino', 'TESTE', 'vao'))
    melhor_sel = (melhor[0], len(nomes))
    for k in (8, 12, 16, 20, 26, 32, len(nomes)):
        if k > len(nomes):
            continue
        idx = sorted(ordem[:k])
        tr, te, _ = avalia(Xtr[:, idx], Xte[:, idx], **melhor[1])
        marca = ''
        if te > melhor_sel[0]:
            melhor_sel = (te, k)
            marca = '  <-- melhor'
        print('{:>8}{:>12.4f}{:>12.4f}{:>9.3f}{}'.format(k, tr, te, tr - te, marca))

    print('')
    print('=' * 68)
    print('RESUMO')
    print('=' * 68)
    print('  hoje (fixo no chute)      : TESTE {:.4f}  vao {:.3f}'.format(te0, tr0 - te0))
    print('  + hiperparametros         : TESTE {:.4f}'.format(melhor[0]))
    print('  + selecao ({} features)   : TESTE {:.4f}'.format(
        melhor_sel[1], melhor_sel[0]))
    print('  GANHO TOTAL               : {:+.4f} de AUC fora da amostra'.format(
        melhor_sel[0] - te0))


if __name__ == '__main__':
    main()
