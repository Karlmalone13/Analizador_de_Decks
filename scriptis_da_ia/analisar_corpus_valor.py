"""
analisar_corpus_valor.py
========================
Analise OFFLINE do corpus de auto-jogo (`metrics/selfplay_dataset.jsonl`).
Nao roda partida nenhuma -- responde com o dado que ja existe.

Pedido do usuario (08/09/2026), depois de suspender o laco de geracoes
por custo de tempo: *"analise os dados que ja temos e vamos continuar
com o nosso ML"*.

AS 4 PERGUNTAS
--------------
1. **A curva de aprendizado esta subindo ou saturada?**
   Treina com fracoes crescentes do corpus e mede AUC FORA DA AMOSTRA.
   Esta e a pergunta que decide se vale gerar mais partidas: a curva de
   logs HUMANOS ja foi medida SATURADA em ~26% (bloco 707), e por isso
   "coletar mais partidas humanas" nao desbloqueia aquele caminho. Se a
   curva de auto-jogo ainda sobe, gerar mais partidas PAGA -- e a
   diferenca entre as duas fontes deixa de ser opiniao.

2. **O dado das geracoes 1-3 ajudou ou atrapalhou?**
   As 3 geracoes rodaram com o modelo ligado (peso 200) e o campeao
   NUNCA mudou (nada foi promovido) -- ou seja, ~2.800 estados vieram de
   UM regime so. Compara treinar so com `gen 0` contra treinar com tudo,
   avaliando nos MESMOS folds. Sem isso, a queda de AUC observada
   (0,7704 no corpus de 4.619 -> 0,7682 em 7.413) fica ambigua entre
   "dado novo e pior" e "corpus novo e mais dificil".

3. **O que o modelo esta realmente usando?**
   Importancia por PERMUTACAO (fora da amostra, nao no treino). Se o
   sinal for quase todo `life_diff`, o modelo e um placar glorificado e
   nao tem por que ajudar a busca -- que ja enxerga vida. Se houver
   sinal em board/mao/DON, ele carrega algo que a heuristica nao tem.

4. **As geracoes mudaram a distribuicao de estados?**
   Treina um classificador `gen 0` x `gen 1-3`. AUC ~0,5 = as politicas
   visitam os mesmos estados (e o laco nao esta explorando nada novo);
   AUC alta = o modelo ligado leva o jogo pra outro lugar. Isso mede
   diretamente se o laco esta iterando de fato ou so acumulando.

Uso:
  python analisar_corpus_valor.py
  python analisar_corpus_valor.py --dataset metrics/selfplay_dataset.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from optcg_engine.value_net import FEATURE_NAMES

DATASET = 'metrics/selfplay_dataset.jsonl'


def carregar(caminho: str):
    X, y, grupos, gens = [], [], [], []
    with open(caminho, encoding='utf-8') as fh:
        for linha in fh:
            linha = linha.strip()
            if not linha:
                continue
            d = json.loads(linha)
            if 'win' not in d or 'feats' not in d:
                continue
            X.append(d['feats'])
            y.append(int(d['win']))
            grupos.append(d.get('leader') or '?')
            gens.append(int(d.get('gen', 0)))
    return X, y, grupos, gens


def novo_modelo(seed=0):
    from sklearn.ensemble import HistGradientBoostingClassifier
    return HistGradientBoostingClassifier(
        max_iter=200, learning_rate=0.06, max_depth=4,
        min_samples_leaf=40, l2_regularization=1.0, random_state=seed)


def auc_cv(X, y, grupos, folds=5, mascara_treino=None):
    """AUC fora da amostra sob GroupKFold POR LIDER.

    `mascara_treino` permite TREINAR so num subconjunto (ex: geracao 0)
    e AVALIAR no mesmo teste de sempre -- e o unico jeito honesto de
    comparar duas composicoes de corpus: mudar o treino e manter o teste
    fixo. Comparar AUC de corpora diferentes (cada um com seu proprio
    teste) nao diz nada, e foi assim que a leitura ficou ambigua."""
    import numpy as np
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import GroupKFold

    aucs = []
    for i_tr, i_te in GroupKFold(n_splits=folds).split(X, y, grupos):
        if mascara_treino is not None:
            i_tr = np.array([i for i in i_tr if mascara_treino[i]])
        if len(i_tr) < 50 or len(set(y[i_te])) < 2 or len(set(y[i_tr])) < 2:
            continue
        m = novo_modelo().fit(X[i_tr], y[i_tr])
        aucs.append(roc_auc_score(y[i_te], m.predict_proba(X[i_te])[:, 1]))
    return (float(np.mean(aucs)) if aucs else None), len(aucs)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dataset', default=DATASET)
    ap.add_argument('--folds', type=int, default=5)
    args = ap.parse_args()

    import numpy as np
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import GroupKFold

    X, y, grupos, gens = carregar(args.dataset)
    X = np.array(X, dtype=float)
    y = np.array(y, dtype=int)
    grupos = np.array(grupos)
    gens = np.array(gens)
    rng = np.random.default_rng(0)

    print(f'corpus: {len(X)} estados | {len(set(grupos))} lideres | '
          f'positivos {y.mean():.1%}')
    print('por geracao:', {int(g): int((gens == g).sum()) for g in sorted(set(gens))})

    # ── 1. CURVA DE APRENDIZADO ─────────────────────────────────────────
    print('\n' + '=' * 62)
    print('1. CURVA DE APRENDIZADO -- gerar mais partidas ainda paga?')
    print('=' * 62)
    print(f'{"fracao":>7} {"estados":>8} {"AUC fora da amostra":>21}')
    anterior = None
    for frac in (0.25, 0.40, 0.55, 0.70, 0.85, 1.0):
        # Amostra por ESTADO, mas o teste continua agrupado por lider.
        sel = rng.random(len(X)) < frac
        a, nf = auc_cv(X, y, grupos, args.folds, mascara_treino=sel)
        delta = '' if anterior is None or a is None else f'  ({a - anterior:+.4f})'
        print(f'{frac:>6.0%} {int(sel.sum()):>8} {a if a else 0:>21.4f}{delta}')
        anterior = a
    print('\n  Leitura: se os ultimos passos ainda somam, gerar mais partidas')
    print('  paga. Se achatou, o gargalo passou a ser REPRESENTACAO (features),')
    print('  nao volume -- foi exatamente o diagnostico do bloco 707 pra')
    print('  logs humanos, e o motivo de nao pedir mais coleta humana.')

    # ── 2. O DADO DAS GERACOES 1-3 AJUDOU? ──────────────────────────────
    print('\n' + '=' * 62)
    print('2. O dado das geracoes 1-3 AJUDOU? (mesmo teste, treino diferente)')
    print('=' * 62)
    so_gen0 = gens == 0
    a_gen0, _ = auc_cv(X, y, grupos, args.folds, mascara_treino=so_gen0)
    a_tudo, _ = auc_cv(X, y, grupos, args.folds, mascara_treino=None)
    print(f'  treino SO com gen 0 ({int(so_gen0.sum())} estados): AUC {a_gen0:.4f}')
    print(f'  treino com TUDO      ({len(X)} estados): AUC {a_tudo:.4f}')
    print(f'  delta: {a_tudo - a_gen0:+.4f}')
    print('\n  Este e o teste que a comparacao anterior NAO fez: mesmo conjunto')
    print('  de teste nos dois lados. Comparar 0,7704 (corpus 4.619) com 0,7682')
    print('  (corpus 7.413) misturava mudanca de treino com mudanca de teste.')

    # ── 3. O QUE O MODELO USA ───────────────────────────────────────────
    print('\n' + '=' * 62)
    print('3. IMPORTANCIA POR PERMUTACAO (fora da amostra)')
    print('=' * 62)
    from sklearn.inspection import permutation_importance
    i_tr, i_te = next(iter(GroupKFold(n_splits=args.folds).split(X, y, grupos)))
    m = novo_modelo().fit(X[i_tr], y[i_tr])
    base = roc_auc_score(y[i_te], m.predict_proba(X[i_te])[:, 1])
    r = permutation_importance(m, X[i_te], y[i_te], n_repeats=8,
                               random_state=0, scoring='roc_auc')
    ordem = np.argsort(r.importances_mean)[::-1][:12]
    print(f'  AUC base do fold: {base:.4f}')
    print(f'  {"feature":<22} {"queda de AUC":>13}')
    for i in ordem:
        print(f'  {FEATURE_NAMES[i]:<22} {r.importances_mean[i]:>13.4f}')
    print('\n  Leitura: se `life_diff` domina sozinho, o modelo e um placar --')
    print('  a busca ja enxerga vida, entao ele nao acrescenta. Sinal em')
    print('  board/mao/DON e o que a heuristica pode nao estar pesando bem.')

    # ── 4. AS GERACOES MUDARAM A DISTRIBUICAO? ──────────────────────────
    print('\n' + '=' * 62)
    print('4. O LACO ESTA ITERANDO OU SO ACUMULANDO?')
    print('=' * 62)
    if (gens > 0).sum() < 100:
        print('  poucas amostras de geracoes > 0 -- teste pulado')
    else:
        z = (gens > 0).astype(int)
        aucs = []
        for i_tr, i_te in GroupKFold(n_splits=args.folds).split(X, z, grupos):
            if len(set(z[i_te])) < 2:
                continue
            mm = novo_modelo().fit(X[i_tr], z[i_tr])
            aucs.append(roc_auc_score(z[i_te], mm.predict_proba(X[i_te])[:, 1]))
        sep = float(np.mean(aucs))
        print(f'  separabilidade gen 0 x gen 1-3: AUC {sep:.4f}')
        if sep < 0.60:
            print('  -> ~0,5-0,6: as politicas visitam os MESMOS estados. O laco')
            print('     esta ACUMULANDO dado, nao explorando regiao nova. Isso')
            print('     explica por que mais partidas do mesmo regime somam pouco.')
        else:
            print('  -> alta: o modelo ligado leva o jogo pra outra regiao. O laco')
            print('     ESTA iterando; ai o dado novo tem valor proprio.')


if __name__ == '__main__':
    main()
