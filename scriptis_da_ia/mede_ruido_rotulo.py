"""Quanto do erro do Q e RUIDO do rotulo, que nenhuma rede consegue tirar (bloco 968).

Pergunta: a rede bateu no limite dela, ou no limite do DADO? Se a MESMA posicao
com a MESMA jogada (vetor de entrada identico) recebe rotulos muito diferentes
em partidas diferentes, o melhor preditor possivel ainda erra -- e esse erro e
um piso que nenhum tamanho de rede atravessa.

Mede, so nas linhas que se repetem (vetor identico, >= 2 vezes):
  - erro medio do MELHOR preditor possivel (a mediana do proprio grupo) = PISO
  - erro de prever a media geral nas mesmas linhas (referencia, sem aprender)
CONTROLE QUE PODE FALHAR: embaralha os rotulos entre as linhas. Se o piso
embaralhado nao subir pra perto da referencia, o instrumento esta cego.

Rotulo IDENTICO ao do treino: reusa `alvo_consequencia`/`carrega_trajetorias`
de `treinar_q.py` (sem copiar a regra).
"""
import json
import random
from collections import defaultdict

import numpy as np

import treinar_q as tq
import corpus_escolhidas
from optcg_engine import value_net as vn
from optcg_engine.decision_engine import MODELO_ORDENA_PATH


def carrega():
    traj = tq.carrega_trajetorias(tq.SELFPLAY, avaliador=vn.load_value_net(MODELO_ORDENA_PATH))
    i_ld = list(vn.FEATURE_NAMES_ALUNO).index('life_diff')
    chaves, ys, fams = [], [], []
    with corpus_escolhidas.atualiza().open(encoding='utf-8') as fh:
        for linha in fh:
            if not linha.strip():
                continue
            d = json.loads(linha)
            f = d.get('feats')
            if not f or (d.get('acao') or '?') in tq.FAMILIAS_APOSENTADAS:
                continue
            d['ld_agora'] = f[i_ld]
            c = tq.alvo_consequencia(d, traj, modo='td')
            if c is None:
                continue
            chaves.append(hash((d.get('leader'), tuple(f))))
            ys.append(float(c))
            fams.append(d.get('acao') or '?')
    return chaves, np.asarray(ys), fams


def piso(chaves, y):
    g = defaultdict(list)
    for i, k in enumerate(chaves):
        g[k].append(i)
    idx = [ix for ix in g.values() if len(ix) >= 2]
    linhas = np.concatenate([np.asarray(ix) for ix in idx]) if idx else np.array([], int)
    erro_piso = sum(np.abs(y[ix] - np.median(y[ix])).sum() for ix in idx) / max(1, len(linhas))
    erro_media = float(np.mean(np.abs(y[linhas] - y.mean()))) if len(linhas) else float('nan')
    return len(idx), len(linhas), float(erro_piso), erro_media


def main():
    chaves, y, fams = carrega()
    print('linhas com rotulo de consequencia: %d' % len(y))
    print('rotulo: media %.3f | desvio %.3f' % (y.mean(), y.std()))
    print('erro de prever a media (corpus todo): %.4f' % float(np.mean(np.abs(y - y.mean()))))
    ng, nl, ep, em = piso(chaves, y)
    print()
    print('posicoes repetidas: %d grupos, %d linhas (%.1f%% do corpus)' % (ng, nl, 100.0 * nl / len(y)))
    print('  PISO (melhor preditor possivel, mediana do grupo): %.4f' % ep)
    print('  prever a media nessas mesmas linhas            : %.4f' % em)
    yb = y.copy()
    random.Random(0).shuffle(yb)
    _, _, epb, emb = piso(chaves, yb)
    print('  CONTROLE rotulo embaralhado: piso %.4f | media %.4f (o piso tem que subir)' % (epb, emb))
    print()
    print('por familia (so grupos repetidos):')
    por = defaultdict(list)
    for i, f in enumerate(fams):
        por[f].append(i)
    for f, ix in sorted(por.items(), key=lambda t: -len(t[1]))[:10]:
        ix = np.asarray(ix)
        a, b, c, d = piso([chaves[i] for i in ix], y[ix])
        print('  %-14s %8d linhas | repetidas %7d | piso %.4f | media %.4f' % (f, len(ix), b, c, d))


if __name__ == '__main__':
    main()
