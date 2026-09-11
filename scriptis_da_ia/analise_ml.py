"""EDA + metricas completas + importancia de atributos (bloco 768).

Fecha as pendencias que o roteiro de ML do usuario apontou e que este
projeto nunca tinha feito:

  2.1 EDA .................. nunca feita -- modelavamos dado que nao olhamos
  2.2 Selecao de atributos . 46 features foram adicionadas em 10/09 e NUNCA
                             foi medido se o modelo as usa
  2.3 Conjunto de TESTE .... so havia treino + validacao cruzada, e como o
                             AUC da validacao era usado pra DECIDIR, ele
                             deixou de ser imparcial
  4.  Metricas ............. so AUC; sem acuracia, precisao, recall, F1,
                             matriz de confusao, Brier

Divisao em TRES por LIDER: treino/validacao saem de um conjunto de
lideres, e o TESTE sai de lideres que o modelo NUNCA viu -- unica forma
honesta de estimar generalizacao aqui, porque o objetivo registrado do
projeto e jogar bem com QUALQUER deck.

Importancia por PERMUTACAO (nao a `feature_importances_` da arvore): mede
a queda de desempenho ao embaralhar a coluna, e nao se ilude com feature
de alta cardinalidade.

Uso: python analise_ml.py --dataset metrics/selfplay_ricas.jsonl --features v3
"""
from __future__ import annotations
import argparse
import collections
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
    return np.array(X, dtype=float), np.array(y, dtype=int), np.array(g)


def eda(X, y, g, nomes):
    print('=' * 72)
    print('1. ANALISE EXPLORATORIA (EDA)')
    print('=' * 72)
    cont = list(collections.Counter(g).values())
    print('  estados        : {:,}'.format(len(X)))
    print('  features       : {}'.format(X.shape[1]))
    print('  lideres        : {}'.format(len(set(g))))
    print('  estados/lider  : min {} | mediana {} | max {}'.format(
        min(cont), int(np.median(cont)), max(cont)))
    print('  rotulo positivo: {:.1%}  ({})'.format(
        y.mean(), 'equilibrado' if 0.35 <= y.mean() <= 0.65 else 'DESBALANCEADO'))
    print('  valores faltantes (NaN): {}'.format(int(np.isnan(X).sum())))

    const = [nomes[i] for i in range(X.shape[1]) if np.std(X[:, i]) == 0]
    print('')
    print('  features CONSTANTES (o modelo nao tem como usar): {}'.format(len(const)))
    for n in const:
        print('     - {}'.format(n))

    quase = [(nomes[i], float(np.std(X[:, i]))) for i in range(X.shape[1])
             if 0 < np.std(X[:, i]) < 0.05]
    if quase:
        print('  quase constantes (desvio < 0,05): {}'.format(len(quase)))
        for n, s in quase[:8]:
            print('     - {:<26} desvio {:.4f}'.format(n, s))

    viv = [i for i in range(X.shape[1]) if np.std(X[:, i]) > 0]
    if len(viv) > 1:
        C = np.corrcoef(X[:, viv], rowvar=False)
        pares = [(nomes[viv[i]], nomes[viv[j]], C[i, j])
                 for i in range(len(viv)) for j in range(i + 1, len(viv))
                 if abs(C[i, j]) > 0.95]
        print('')
        print('  pares com correlacao > 0,95 (redundantes): {}'.format(len(pares)))
        for a, b, c in sorted(pares, key=lambda t: -abs(t[2]))[:10]:
            print('     {:+.3f}  {}  <->  {}'.format(c, a, b))
    return const


def treinar_e_avaliar(X, y, g, nomes):
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.inspection import permutation_importance
    from sklearn.metrics import (accuracy_score, brier_score_loss,
                                 confusion_matrix, f1_score, precision_score,
                                 recall_score, roc_auc_score)
    from sklearn.model_selection import GroupKFold

    lideres = sorted(set(g))
    rng = np.random.RandomState(42)
    rng.shuffle(lideres)
    lid_teste = set(lideres[:max(1, len(lideres) // 5)])
    m_te = np.array([x in lid_teste for x in g])
    Xtr, ytr, gtr = X[~m_te], y[~m_te], g[~m_te]
    Xte, yte = X[m_te], y[m_te]

    print('')
    print('=' * 72)
    print('2. DIVISAO TREINO / VALIDACAO / TESTE  (por LIDER)')
    print('=' * 72)
    print('  treino+validacao : {:,} estados, {} lideres'.format(
        len(Xtr), len(set(gtr))))
    print('  TESTE            : {:,} estados, {} lideres NUNCA VISTOS'.format(
        len(Xte), len(lid_teste)))
    print('  lideres de teste : {}'.format(', '.join(sorted(lid_teste))))

    def novo():
        return HistGradientBoostingClassifier(
            max_iter=200, learning_rate=0.06, max_depth=4, random_state=0)

    aucs = []
    folds = min(5, len(set(gtr)))
    for tr, va in GroupKFold(n_splits=folds).split(Xtr, ytr, gtr):
        m = novo().fit(Xtr[tr], ytr[tr])
        aucs.append(roc_auc_score(ytr[va], m.predict_proba(Xtr[va])[:, 1]))

    modelo = novo().fit(Xtr, ytr)
    p_te = modelo.predict_proba(Xte)[:, 1]
    pred = (p_te >= 0.5).astype(int)

    print('')
    print('=' * 72)
    print('3. METRICAS no conjunto de TESTE (lideres nunca vistos)')
    print('=' * 72)
    print('  AUC treino            : {:.4f}'.format(
        roc_auc_score(ytr, modelo.predict_proba(Xtr)[:, 1])))
    print('  AUC validacao cruzada : {:.4f}  (desvio {:.4f})'.format(
        float(np.mean(aucs)), float(np.std(aucs))))
    print('  AUC TESTE             : {:.4f}'.format(roc_auc_score(yte, p_te)))
    print('  acuracia              : {:.1%}'.format(accuracy_score(yte, pred)))
    print('  precisao              : {:.1%}'.format(
        precision_score(yte, pred, zero_division=0)))
    print('  recall                : {:.1%}'.format(
        recall_score(yte, pred, zero_division=0)))
    print('  F1                    : {:.1%}'.format(
        f1_score(yte, pred, zero_division=0)))
    print('  Brier (calibracao)    : {:.4f}   0 = perfeito, 0,25 = chute'.format(
        brier_score_loss(yte, p_te)))
    cm = confusion_matrix(yte, pred)
    print('')
    print('  matriz de confusao (linha = real, coluna = previsto):')
    print('                 prev.DERROTA   prev.VITORIA')
    print('  real DERROTA  {:>12}   {:>12}'.format(cm[0][0], cm[0][1]))
    print('  real VITORIA  {:>12}   {:>12}'.format(cm[1][0], cm[1][1]))

    print('')
    print('=' * 72)
    print('4. IMPORTANCIA DE ATRIBUTOS (permutacao, no TESTE)')
    print('=' * 72)
    r = permutation_importance(modelo, Xte, yte, n_repeats=8,
                               random_state=0, scoring='roc_auc')
    ordem = np.argsort(-r.importances_mean)
    print('  {:<30}{:>12}{:>11}'.format('feature', 'queda AUC', 'desvio'))
    for i in ordem[:18]:
        print('  {:<30}{:>12.4f}{:>11.4f}'.format(
            nomes[i], r.importances_mean[i], r.importances_std[i]))
    inuteis = [nomes[i] for i in range(len(nomes)) if r.importances_mean[i] <= 0]
    print('')
    print('  importancia <= 0 (o modelo NAO usa): {} de {}'.format(
        len(inuteis), len(nomes)))
    for n in inuteis[:24]:
        print('     - {}'.format(n))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dataset', default='metrics/selfplay_ricas.jsonl')
    ap.add_argument('--features', choices=tuple(CONJ), default='v3')
    a = ap.parse_args()

    X, y, g = carregar(a.dataset)
    nomes_ds = {len(v): v for v in CONJ.values()}[X.shape[1]]
    nomes = CONJ[a.features]
    X = X[:, [nomes_ds.index(n) for n in nomes]]
    print('dataset: {}   |   {} features ({})'.format(
        a.dataset, len(nomes), a.features))
    eda(X, y, g, nomes)
    treinar_e_avaliar(X, y, g, nomes)


if __name__ == '__main__':
    main()
