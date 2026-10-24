#!/usr/bin/env python
"""Confere `alt_bin.selecao` (vetorizado, bloco 987) contra o laco linha a linha
do treino sobre `alt_bin.linhas()` (que ja bate com o texto -- bloco 986).
Ancora de teste: chaves REAIS das alternativas (1 a cada 3 decisoes)."""
import random
import sys
import time

import numpy as np

import alt_bin
from treinar_q import FAMILIAS_JOGO, passa_filtro_modo, MODO_PADRAO

W = alt_bin.largura()
rng = random.Random(7)
ancora, vistos = {}, set()
for d in alt_bin.linhas():
    k = (d['gen'], d['match'], d['leader'], d['decisao'])
    if k in vistos:
        continue
    vistos.add(k)
    if rng.random() < 1 / 3:
        ancora[k] = (rng.random(), rng.random())
modo_ok = lambda d: passa_filtro_modo(d, MODO_PADRAO)

t = time.perf_counter()
Xa1, ya1 = [], []
for d in alt_bin.linhas():
    f, a = d.get('feats'), d.get('alvo')
    if f is None or len(f) == 0 or a is None or d.get('acao') not in FAMILIAS_JOGO:
        continue
    anc = ancora.get((d.get('gen'), d.get('match'), d.get('leader'), d.get('decisao')))
    if anc is None:
        continue
    a = anc[1] + (float(a) - anc[0])
    if not modo_ok(d):
        continue
    if len(f) != W:
        continue
    Xa1.append(f)
    ya1.append(float(a))
Xa1 = np.asarray(Xa1, dtype=np.float32)
t1 = time.perf_counter() - t

t = time.perf_counter()
Xa2, ya2 = alt_bin.selecao(ancora, FAMILIAS_JOGO, modo_ok, W)
t2 = time.perf_counter() - t

igual = Xa1.shape == Xa2.shape and np.array_equal(Xa1, Xa2) and ya1 == ya2
print(f'ancora: {len(ancora)} decisoes | linhas aprovadas: {len(ya1)} x {len(ya2)}')
print(f'linha a linha {t1:.1f}s | vetorizado {t2:.1f}s | IDENTICO: {igual}')
sys.exit(0 if igual else 1)
