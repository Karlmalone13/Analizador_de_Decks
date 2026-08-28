"""FASE 2b: decidir o turno como SELECAO DE CONJUNTO, nao N escolhas gulosas.

POR QUE (portao do bloco 704)
------------------------------
O ranqueador por DECISAO fechou o portao: ~20-24% contra teto de 96,6%,
e isso OFFLINE, onde o *distribution shift* nem entra -- logo o shift nao
e a causa principal. A pista que sobrou: **o rotulo disponivel e de
CONJUNTO** ("esta carta esta entre as que o humano jogou no turno"), nao
de decisao -- o log humano nao da alinhamento decisao-a-decisao. O
oraculo chega a 96,6% porque enxerga o conjunto INTEIRO de uma vez; um
modelo que compromete UMA acao por vez, nao.

Aqui a formulacao casa com o rotulo QUE EXISTE **e** com a metrica
oficial, que tambem e de conjunto (`play` = mesmas cartas jogadas no
turno). E e mudanca ESTRUTURAL de como a decisao e tomada -- "planejar o
turno" em vez de "passo guloso" -- nao mais um ajuste de peso.

DISCIPLINA DE METODO (erro cometido no bloco 704, nao repetir)
--------------------------------------------------------------
La eu escolhi o limiar testando 7 valores NA PROPRIA VALIDACAO e quase
reportei +2,4pp que nao existiam. **Aqui TODO hiperparametro e escolhido
no TREINO**; a validacao (lideres nunca vistos) e olhada UMA vez, no fim.

RESTRICAO MANTIDA: zero identidade de carta ou lider nas features.
"""
from __future__ import annotations

import numpy as np

from fast_eval import agrupa_por_turno, carrega, split_por_lider
from treinar_ranqueador import (CATS, descobre_categorias, props_das_cartas,
                                vetor)


def pool_do_turno(t):
    """Candidatas `play` DISTINTAS do turno + a decisao onde apareceram."""
    vistos, pool = set(), []
    for d in t['decisoes']:
        for c in d['candidates']:
            if c['kind'] == 'play' and c['code'] not in vistos:
                vistos.add(c['code'])
                pool.append((d, c))
    return pool


def monta_conjunto(turnos, props):
    X, y = [], []
    for t in turnos:
        for d, c in pool_do_turno(t):
            X.append(vetor(d, c, props))
            y.append(1 if c.get('humano_fez') else 0)
    return np.array(X, dtype=np.float32), np.array(y)


def avalia_conjunto(turnos, modelo, props, regra):
    """`regra(probs) -> indices escolhidos`. Devolve play agregado e por lider."""
    from collections import defaultdict
    ok = n = 0
    por = defaultdict(lambda: [0, 0])
    for t in turnos:
        pool = pool_do_turno(t)
        if not t['avaliavel']:
            continue
        n += 1
        if pool:
            V = np.array([vetor(d, c, props) for d, c in pool], dtype=np.float32)
            p = modelo.predict_proba(V)[:, 1]
            escolhido = {pool[i][1]['code'] for i in regra(p)}
        else:
            escolhido = set()
        acerto = escolhido == t['humano']
        ok += acerto
        por[t['leader']][0] += acerto
        por[t['leader']][1] += 1
    return {'play': ok / n if n else 0.0, 'n': n,
            'por_lider': {k: (a / b, b) for k, (a, b) in por.items()}}


def regra_limiar(lim):
    return lambda p: [i for i, v in enumerate(p) if v >= lim]


def regra_topk_por_limiar(lim, kmax):
    def r(p):
        idx = np.argsort(-p)
        return [i for i in idx[:kmax] if p[i] >= lim]
    return r


def main():
    linhas = carrega()
    descobre_categorias(linhas)
    props = props_das_cartas()
    turnos = agrupa_por_turno(linhas)
    tr, va, lid_val = split_por_lider(turnos)

    Xtr, ytr = monta_conjunto(tr, props)
    print(f'treino: {len(tr)} turnos, {len(Xtr)} cartas distintas, '
          f'{ytr.sum()} positivas ({ytr.mean()*100:.1f}%)')
    print(f'validacao: {len(va)} turnos, {len(lid_val)} lideres NUNCA vistos')

    from sklearn.ensemble import HistGradientBoostingClassifier
    m = HistGradientBoostingClassifier(max_iter=400, learning_rate=0.06,
                                       max_depth=6, l2_regularization=1.0,
                                       random_state=13)
    m.fit(Xtr, ytr)

    # ── hiperparametro escolhido SO no TREINO ──
    print('\n--- escolha do limiar: SO no treino (bloco 704) ---')
    melhor = (None, -1.0)
    for lim in (0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80):
        for kmax in (2, 3, 99):
            v = avalia_conjunto(tr, m, props, regra_topk_por_limiar(lim, kmax))
            if v['play'] > melhor[1]:
                melhor = ((lim, kmax), v['play'])
    (lim, kmax), v_tr = melhor
    print(f'  melhor no TREINO: limiar={lim:.2f} kmax={kmax} -> {v_tr*100:.1f}%')

    regra = regra_topk_por_limiar(lim, kmax)
    r_tr = avalia_conjunto(tr, m, props, regra)
    r_va = avalia_conjunto(va, m, props, regra)

    from fast_eval import avalia, faz_oraculo, rank_motor
    b_tr, b_va = avalia(tr, rank_motor), avalia(va, rank_motor)
    o_va = avalia(va, faz_oraculo())

    print('\n' + '=' * 60)
    print(f'{"":30}{"TREINO":>10}{"VALIDACAO":>14}')
    print('=' * 60)
    print(f'{"motor real (baseline)":30}{b_tr["play"]*100:9.1f}%{b_va["play"]*100:13.1f}%')
    print(f'{"SELECAO DE CONJUNTO":30}{r_tr["play"]*100:9.1f}%{r_va["play"]*100:13.1f}%')
    print(f'{"oraculo (teto)":30}{"":10}{o_va["play"]*100:13.1f}%')
    d = (r_va['play'] - b_va['play']) * 100
    print(f'\n  >> delta na VALIDACAO (decks nunca vistos): {d:+.1f}pp')

    print(f'\n--- POR LIDER na validacao ---')
    print(f'  {"lider":12}{"baseline":>10}{"modelo":>9}{"delta":>9}{"n":>6}')
    sobe = desce = 0
    for lid in sorted(r_va['por_lider']):
        tx, n = r_va['por_lider'][lid]
        bx = b_va['por_lider'].get(lid, (0, 0))[0]
        dd = (tx - bx) * 100
        sobe += dd > 0.5
        desce += dd < -0.5
        print(f'  {lid:12}{bx*100:9.1f}%{tx*100:8.1f}%{dd:+8.1f}pp{n:6}')
    print(f'\n  {sobe} lideres melhoraram / {desce} pioraram')


if __name__ == '__main__':
    main()
