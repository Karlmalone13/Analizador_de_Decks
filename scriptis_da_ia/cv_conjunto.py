"""Validacao cruzada AGRUPADA POR LIDER + combate ao overfit (bloco 706).

POR QUE CV, E NAO O SPLIT UNICO DO BLOCO 705
---------------------------------------------
La a validacao era UM split com 9 lideres, e **138 dos 210 turnos eram de
um unico lider (OP11-062)**. O "+4,8pp" agregado eram ~10 turnos, a
maioria vinda de lideres com n=5..8 onde 1 turno vale 20-25pp. Numero
fragil demais pra decidir qualquer coisa.

Aqui: **GroupKFold por LIDER** -- todo lider entra na validacao exatamente
uma vez, e nenhum lider aparece nos dois lados do mesmo fold. Todo turno
do banco e avaliado como "deck nunca visto" em algum fold. Isso mede
diretamente o requisito do usuario ("qualquer deck que o usuario montar")
e da uma estimativa muito mais estavel.

O baseline e recomputado NOS MESMOS folds, entao o delta e pareado.

DISCIPLINA (erro do bloco 704): nenhum hiperparametro e escolhido olhando
a validacao. Cada configuracao e avaliada pelo MESMO protocolo e o que
se compara e o delta contra o baseline nos mesmos folds.
"""
from __future__ import annotations

import numpy as np
from collections import defaultdict

from fast_eval import agrupa_por_turno, avalia, carrega, rank_motor
from treinar_ranqueador import descobre_categorias, props_das_cartas, vetor
from selecao_conjunto import (avalia_conjunto, monta_conjunto,
                              regra_topk_por_limiar)


def cv_por_lider(turnos, props, params, regra, n_folds=5, seed=13):
    from sklearn.ensemble import HistGradientBoostingClassifier
    lideres = sorted({t['leader'] for t in turnos})
    rng = np.random.RandomState(seed)
    ordem = list(lideres)
    rng.shuffle(ordem)
    folds = [set(ordem[i::n_folds]) for i in range(n_folds)]

    acertos = tot = 0
    b_acertos = b_tot = 0
    treino_acc = []
    por_lider = {}
    for f in folds:
        tr = [t for t in turnos if t['leader'] not in f]
        va = [t for t in turnos if t['leader'] in f]
        if not va or not tr:
            continue
        Xtr, ytr = monta_conjunto(tr, props)
        m = HistGradientBoostingClassifier(random_state=seed, **params)
        m.fit(Xtr, ytr)
        r = avalia_conjunto(va, m, props, regra)
        b = avalia(va, rank_motor)
        acertos += r['play'] * r['n']; tot += r['n']
        b_acertos += b['play'] * b['n']; b_tot += b['n']
        treino_acc.append(avalia_conjunto(tr, m, props, regra)['play'])
        for lid, (tx, n) in r['por_lider'].items():
            por_lider[lid] = (tx, b['por_lider'].get(lid, (0, 0))[0], n)
    return {'play': acertos / tot if tot else 0.0,
            'baseline': b_acertos / b_tot if b_tot else 0.0,
            'treino': float(np.mean(treino_acc)) if treino_acc else 0.0,
            'n': tot, 'por_lider': por_lider}


CONFIGS = {
    'atual (bloco 705)': dict(max_iter=400, learning_rate=0.06, max_depth=6,
                              l2_regularization=1.0),
    'regularizado':      dict(max_iter=150, learning_rate=0.05, max_depth=3,
                              l2_regularization=10.0, min_samples_leaf=40),
    'muito raso':        dict(max_iter=120, learning_rate=0.05, max_depth=2,
                              l2_regularization=20.0, min_samples_leaf=60),
    'medio':             dict(max_iter=250, learning_rate=0.05, max_depth=4,
                              l2_regularization=5.0, min_samples_leaf=25),
}


def main():
    linhas = carrega()
    descobre_categorias(linhas)
    props = props_das_cartas()
    turnos = agrupa_por_turno(linhas)
    regra = regra_topk_por_limiar(0.40, 2)

    print(f'{len(turnos)} turnos, {len({t["leader"] for t in turnos})} lideres')
    print('GroupKFold por LIDER (k=5): todo lider e validado como deck nunca visto\n')
    print(f'{"config":22}{"treino":>9}{"CV valid":>10}{"baseline":>10}{"delta":>9}')
    print('=' * 60)
    melhor = (None, -9e9, None)
    for nome, params in CONFIGS.items():
        r = cv_por_lider(turnos, props, params, regra)
        d = (r['play'] - r['baseline']) * 100
        print(f'{nome:22}{r["treino"]*100:8.1f}%{r["play"]*100:9.1f}%'
              f'{r["baseline"]*100:9.1f}%{d:+8.1f}pp')
        if d > melhor[1]:
            melhor = (nome, d, r)

    nome, d, r = melhor
    print(f'\n  melhor: {nome} ({d:+.1f}pp em {r["n"]} turnos)')
    print(f'\n--- POR LIDER (>=10 turnos) ---')
    print(f'  {"lider":12}{"baseline":>10}{"modelo":>9}{"delta":>9}{"n":>6}')
    sobe = desce = 0
    for lid in sorted(r['por_lider'], key=lambda k: -r['por_lider'][k][2]):
        tx, bx, n = r['por_lider'][lid]
        if n < 10:
            continue
        dd = (tx - bx) * 100
        sobe += dd > 0.5; desce += dd < -0.5
        print(f'  {lid:12}{bx*100:9.1f}%{tx*100:8.1f}%{dd:+8.1f}pp{n:6}')
    print(f'\n  {sobe} melhoraram / {desce} pioraram (lideres com n>=10)')


if __name__ == '__main__':
    main()
