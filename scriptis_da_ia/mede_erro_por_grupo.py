"""O erro do Q trava por GENERALIZAR entre lideres ou por nao ENXERGAR a posicao? (bloco 968)

A validacao do `treinar_q.py` separa por LIDER: os 0,196 medem acertar com
lideres que a rede nunca viu. Aqui o MESMO modelo, na MESMA amostra, e validado
de tres jeitos:
  - por LIDER   (como o ciclo mede hoje)
  - por PARTIDA (lideres conhecidos, partidas novas)
  - no TREINO   (o que a rede consegue decorar -- se ate isso for alto, ela nao
                 enxerga a diferenca entre as posicoes)
CONTROLE QUE PODE FALHAR: rotulo embaralhado tem que dar erro ~ prever a media.
Rotulo identico ao do treino (reusa `alvo_consequencia`).
"""
import json
import random

import numpy as np
from sklearn.model_selection import GroupKFold
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

import treinar_q as tq
import corpus_escolhidas
from optcg_engine import value_net as vn
from optcg_engine.decision_engine import MODELO_ORDENA_PATH

AMOSTRA = 200_000


def carrega():
    traj = tq.carrega_trajetorias(tq.SELFPLAY, avaliador=vn.load_value_net(MODELO_ORDENA_PATH))
    i_ld = list(vn.FEATURE_NAMES_ALUNO).index('life_diff')
    n_cols = len(vn.FEATURE_NAMES_ALUNO) + len(vn.FEATURE_NAMES_ACAO) + len(vn.FEATURE_NAMES_CORRIDA)
    X, y, lid, par = [], [], [], []
    with corpus_escolhidas.atualiza().open(encoding='utf-8') as fh:
        for linha in fh:
            if not linha.strip():
                continue
            d = json.loads(linha)
            f = d.get('feats')
            if not f or (d.get('acao') or '?') in tq.FAMILIAS_APOSENTADAS:
                continue
            if n_cols - 40 <= len(f) < n_cols:
                f = f + [0.0] * (n_cols - len(f))
            d['ld_agora'] = f[i_ld]
            c = tq.alvo_consequencia(d, traj, modo='td')
            if c is None:
                continue
            X.append(f); y.append(float(c))
            lid.append(d.get('leader') or '?')
            par.append('%s:%s' % (d.get('gen'), d.get('match')))
    return np.asarray(X, dtype=np.float32), np.asarray(y), np.asarray(lid), np.asarray(par)


def modelo():
    return make_pipeline(StandardScaler(), MLPRegressor(
        hidden_layer_sizes=(64, 32), activation='relu', solver='adam',
        learning_rate_init=3e-3, max_iter=60, early_stopping=True,
        n_iter_no_change=5, random_state=0))


def valida(X, y, grupos):
    fora, dentro = [], []
    for tr, te in GroupKFold(n_splits=2).split(X, y, grupos):
        m = modelo().fit(X[tr], y[tr])
        fora.append(np.mean(np.abs(m.predict(X[te]) - y[te])))
        dentro.append(np.mean(np.abs(m.predict(X[tr]) - y[tr])))
    return float(np.mean(fora)), float(np.mean(dentro))


def main():
    X, y, lid, par = carrega()
    rng = np.random.default_rng(0)
    i = rng.choice(len(y), size=min(AMOSTRA, len(y)), replace=False)
    X, y, lid, par = X[i], y[i], lid[i], par[i]
    base = float(np.mean(np.abs(y - y.mean())))
    print('amostra %d linhas | %d lideres | %d partidas | prever a media: %.4f'
          % (len(y), len(set(lid)), len(set(par)), base))
    f, d = valida(X, y, lid)
    print('por LIDER   : fora %.4f | no treino %.4f' % (f, d))
    f, d = valida(X, y, par)
    print('por PARTIDA : fora %.4f | no treino %.4f' % (f, d))
    yb = y.copy(); random.Random(0).shuffle(yb)
    f, d = valida(X, yb, par)
    print('CONTROLE embaralhado (por partida): fora %.4f (tem que ficar perto de %.4f)' % (f, base))


if __name__ == '__main__':
    main()
