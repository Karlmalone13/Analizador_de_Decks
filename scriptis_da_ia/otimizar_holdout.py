"""Otimiza os pesos SO num subconjunto de lideres e grava o vetor.

POR QUE (bloco 712): o A/B do bloco 711 deu +8,5pp na regua real, mas o
vetor tinha sido buscado no CORPUS INTEIRO -- **otimizado e medido no
mesmo dado**. Numero in-sample, nao pode ser reportado como ganho. A CV
offline estimou a generalizacao real em +0,8pp.

Aqui: busca so nos lideres de TREINO. Depois a regua real roda com este
vetor e o que importa e o recorte nos lideres de HOLDOUT -- que a busca
nunca viu. E o unico jeito de saber o ganho honesto NA REGUA.
"""
import argparse, json
import numpy as np
from optcg_engine.decision_engine import EVAL_WEIGHTS
from otimizar_pesos import busca, carrega, prepara, play_de

ap = argparse.ArgumentParser()
ap.add_argument('--iter', type=int, default=4000)
ap.add_argument('--frac-holdout', type=float, default=0.4)
ap.add_argument('--seed', type=int, default=7)
ap.add_argument('--out', default='eval_weights_holdout.json')
a = ap.parse_args()

chaves, turnos = prepara(carrega())
lideres = sorted({d[0]['leader'] for d in turnos})
rng = np.random.RandomState(a.seed)
ordem = list(lideres); rng.shuffle(ordem)
n_h = max(1, int(len(lideres) * a.frac_holdout))
holdout = sorted(ordem[:n_h])
tr = [d for d in turnos if d[0]['leader'] not in set(holdout)]

w0 = np.array([EVAL_WEIGHTS.get(k, 0.0) for k in chaves])
w, v = busca(tr, w0, chaves, a.iter, seed=a.seed)
print(f'treino: {len(tr)} turnos, {len(lideres)-n_h} lideres')
print(f'HOLDOUT ({n_h} lideres, a busca NUNCA viu): {holdout}')
print(f'play no treino: {play_de(tr, w0)[0]*100:.1f}% -> {v*100:.1f}%')

json.dump({**{k: EVAL_WEIGHTS[k] for k in EVAL_WEIGHTS if k != '_meta'},
           **{k: float(x) for k, x in zip(chaves, w)},
           '_meta': {'origem': 'otimizar_holdout.py bloco 712',
                     'holdout': holdout,
                     'aviso': 'so o recorte nos lideres de holdout e honesto'}},
          open(a.out, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
json.dump(holdout, open('metrics/holdout_lideres.json', 'w'), indent=1)
print(f'gravado em {a.out}')
