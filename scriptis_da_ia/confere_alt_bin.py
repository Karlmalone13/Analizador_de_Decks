#!/usr/bin/env python
"""Confere que o binario das alternativas (`alt_bin.py`, bloco 986) entrega ao
treino EXATAMENTE o que o texto entregava: mesma ordem, mesmos campos, mesmas
features depois de completar com zeros (regra do treino). E cronometra as duas
leituras.

    python confere_alt_bin.py [--constroi]
"""
import json
import sys
import time

import numpy as np

import alt_bin
import corpus_escolhidas as ce

if '--constroi' in sys.argv:
    t = time.perf_counter()
    n = alt_bin.constroi()
    print(f'construido: {n} linhas em {time.perf_counter() - t:.0f}s')

W = alt_bin.largura()
CAMPOS = ('alvo', 'gen', 'match', 'decisao', 'leader', 'acao', 'modo')

t = time.perf_counter()
n_txt = sum(1 for l in open(ce.ALTERNATIVAS, encoding='utf-8')
            if l.strip() and json.loads(l))
t_txt = time.perf_counter() - t
t = time.perf_counter()
n_bin = sum(1 for _ in alt_bin.linhas())
t_bin = time.perf_counter() - t
print(f'leitura: texto {t_txt:.0f}s ({n_txt}) | binario {t_bin:.0f}s ({n_bin})')

dif, n = 0, 0
with open(ce.ALTERNATIVAS, encoding='utf-8') as fh:
    txt = (json.loads(l) for l in fh if l.strip())
    for a, b in zip(txt, alt_bin.linhas()):
        n += 1
        for c in CAMPOS:
            va, vb = a.get(c), b.get(c)
            if c == 'gen':
                va = int(va or 0)
            if c == 'match':
                va = int(va or 0)
            if va != vb and not (va in (None, '') and vb in (None, '')):
                dif += 1
                if dif <= 5:
                    print('DIF campo', c, n, repr(va), repr(vb))
        f = a.get('feats')
        ok = bool(f) and a.get('alvo') is not None and W - 60 <= len(f) <= W
        if ok != (b['feats'] is not None):
            dif += 1
            if dif <= 5:
                print('DIF ok', n, ok, b['feats'] is None)
        elif ok:
            fa = np.zeros(W, dtype=np.float32)
            fa[:len(f)] = np.asarray(f, dtype=np.float32)
            if not np.array_equal(fa, np.asarray(b['feats'])):
                dif += 1
                if dif <= 5:
                    print('DIF feats', n)
print(f'comparadas {n} linhas (texto {n_txt}, binario {n_bin}) | diferencas: {dif}')
sys.exit(0 if dif == 0 and n_txt == n_bin == n else 1)
