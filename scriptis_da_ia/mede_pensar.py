"""As colunas novas (FEATURE_NAMES_PENSAR, bloco 968) ajudam a rede a separar posicoes?

Mesmas partidas, mesmo rotulo, mesma rede (64,32): treina SEM as 20 colunas
novas e COM elas, validando por PARTIDA. O que importa e o erro NO TREINO (a
rede consegue distinguir o que ve?) e FORA (generaliza?). Antes: 0,183 no
treino, 0,190 fora.
CONTROLE QUE PODE FALHAR: as colunas novas EMBARALHADAS entre linhas tem que
nao ajudar -- se ajudarem, o ganho e so de ter mais colunas, nao da informacao.

Uso: python mede_pensar.py [--q metrics/_pensar/q.jsonl --selfplay metrics/_pensar/selfplay.jsonl]
"""
import argparse
import json
from pathlib import Path

import numpy as np
from sklearn.model_selection import GroupKFold
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

import treinar_q as tq
from optcg_engine import value_net as vn
from optcg_engine.decision_engine import MODELO_ORDENA_PATH


def carrega(q, sp):
    traj = tq.carrega_trajetorias(Path(sp), avaliador=vn.load_value_net(MODELO_ORDENA_PATH))
    i_ld = list(vn.FEATURE_NAMES_ALUNO).index('life_diff')
    X, y, par = [], [], []
    with open(q, encoding='utf-8') as fh:
        for linha in fh:
            if not linha.strip():
                continue
            d = json.loads(linha)
            f = d.get('feats')
            if not f or not d.get('escolhida') or (d.get('acao') or '?') in tq.FAMILIAS_APOSENTADAS:
                continue
            d['ld_agora'] = f[i_ld]
            c = tq.alvo_consequencia(d, traj, modo='td')
            if c is None:
                continue
            X.append(f); y.append(float(c)); par.append('%s:%s' % (d.get('gen'), d.get('match')))
    return np.asarray(X, dtype=np.float32), np.asarray(y), np.asarray(par)


def valida(X, y, g):
    fora, dentro = [], []
    for tr, te in GroupKFold(n_splits=2).split(X, y, g):
        m = make_pipeline(StandardScaler(), MLPRegressor(
            hidden_layer_sizes=(64, 32), solver='adam', learning_rate_init=3e-3,
            max_iter=60, early_stopping=True, n_iter_no_change=5, random_state=0)).fit(X[tr], y[tr])
        fora.append(np.mean(np.abs(m.predict(X[te]) - y[te])))
        dentro.append(np.mean(np.abs(m.predict(X[tr]) - y[tr])))
    return float(np.mean(fora)), float(np.mean(dentro))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--q', default='metrics/_pensar/q.jsonl')
    ap.add_argument('--selfplay', default='metrics/_pensar/selfplay.jsonl')
    a = ap.parse_args()
    X, y, par = carrega(a.q, a.selfplay)
    n_novo = len(vn.FEATURE_NAMES_PENSAR)
    assert X.shape[1] == len(vn.FEATURE_NAMES_ALUNO) + len(vn.FEATURE_NAMES_ACAO) + len(vn.FEATURE_NAMES_CORRIDA) + n_novo
    print('linhas %d | partidas %d | prever a media %.4f' % (len(y), len(set(par)), float(np.mean(np.abs(y - y.mean())))))
    novas = X[:, -n_novo:]
    print('colunas novas: %s' % ', '.join('%s=%.2f' % (n, v) for n, v in zip(vn.FEATURE_NAMES_PENSAR, novas.mean(0))))
    print('  (coluna sempre igual = nao esta sendo calculada: %s)'
          % [n for n, s in zip(vn.FEATURE_NAMES_PENSAR, novas.std(0)) if s == 0])
    f, d = valida(X[:, :-n_novo], y, par)
    print('SEM as colunas novas : fora %.4f | no treino %.4f' % (f, d))
    f, d = valida(X, y, par)
    print('COM as colunas novas : fora %.4f | no treino %.4f' % (f, d))
    Xb = X.copy()
    Xb[:, -n_novo:] = novas[np.random.default_rng(0).permutation(len(y))]
    f, d = valida(Xb, y, par)
    print('CONTROLE embaralhadas: fora %.4f | no treino %.4f (nao pode ajudar)' % (f, d))


if __name__ == '__main__':
    main()
