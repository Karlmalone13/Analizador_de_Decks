"""TETO dos 14 termos atuais: qual o melhor `play` que QUALQUER ponderacao deles alcanca?

POR QUE (bloco 716)
-------------------
Dois caminhos independentes de hoje apontam pra "faltam sinais", nao pra
"sinais mal ponderados": a curva de aprendizado satura (bloco 707) e a
busca conjunta nos pesos nao da ganho estavel (bloco 715). **Mas isso e
inferencia.** Aqui vira medicao.

Em vez de BUSCAR pesos (subida de encosta, que pode parar em otimo local
e cujo resultado varia com a semente -- foi assim que o "+1,9pp" do bloco
713 virou "-2,7pp" no 715), AJUSTA os pesos DIRETAMENTE ao alvo humano
com regressao logistica sobre os proprios termos. Isso da uma estimativa
do TETO: se nem o melhor ajuste direto separa, o problema **nao pode ser**
o valor dos pesos.

Tres numeros, todos no mesmo holdout por lider:
  1. baseline (pesos de producao)
  2. pesos AJUSTADOS aos termos (o teto desta representacao)
  3. oraculo (o teto se a ordenacao fosse perfeita)

Se (2) ficar perto de (1) e longe de (3): **provado que os 14 termos nao
carregam a informacao**, e o trabalho e adicionar TERMOS.
"""
import json
import numpy as np
from collections import defaultdict
from optcg_engine.decision_engine import EVAL_WEIGHTS
from otimizar_pesos import carrega, metricas_de, prepara

chaves, turnos = prepara(carrega())
hold = set(json.load(open('metrics/holdout_lideres.json')))
tr = [d for d in turnos if d[0]['leader'] not in hold]
va = [d for d in turnos if d[0]['leader'] in hold]
w0 = np.array([EVAL_WEIGHTS.get(k, 0.0) for k in chaves])

# ── monta (termos -> o humano fez esta jogada?) no TREINO ──
X, y = [], []
for decisoes in tr:
    for d in decisoes:
        hum = decisoes[0]['humano']
        for i, k in enumerate(d['kind']):
            if k != 'play' or not d['code'][i]:
                continue
            X.append(d['M'][i])
            y.append(1 if d['code'][i] in hum else 0)
X, y = np.array(X), np.array(y)
print(f'{len(X)} candidatas `play` no treino, {y.sum()} escolhidas pelo humano '
      f'({y.mean()*100:.1f}%)')
print(f'termos: {chaves}\n')

from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
sc = StandardScaler().fit(X)
lr = LogisticRegression(max_iter=2000, C=1.0).fit(sc.transform(X), y)
from sklearn.metrics import roc_auc_score
print(f'AUC do melhor ajuste LINEAR sobre os 14 termos (treino): '
      f'{roc_auc_score(y, lr.decision_function(sc.transform(X))):.3f}')

# pesos ajustados, na escala dos termos crus
w_fit = lr.coef_[0] / sc.scale_

def oraculo(turnos_):
    ok = n = 0
    for decisoes in turnos_:
        hum = decisoes[0]['humano']
        disp = set()
        for d in decisoes:
            for i, k in enumerate(d['kind']):
                if k == 'play' and d['code'][i]:
                    disp.add(d['code'][i])
        esc = hum & disp
        if hum or esc:
            n += 1
            ok += esc == hum
    return ok / n if n else 0.0

print(f'\n{"":34}{"TREINO":>9}{"HOLDOUT":>10}')
print('=' * 54)
for nome, w in (('baseline (pesos de producao)', w0),
                ('pesos AJUSTADOS aos termos', w_fit)):
    a, b = metricas_de(tr, w)['play'], metricas_de(va, w)['play']
    print(f'{nome:34}{a*100:8.1f}%{b*100:9.1f}%')
print(f'{"oraculo (ordenacao perfeita)":34}{oraculo(tr)*100:8.1f}%{oraculo(va)*100:9.1f}%')
