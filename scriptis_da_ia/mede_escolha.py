"""QUALIDADE DA ESCOLHA do Q, e nao erro de previsao (bloco 970).

Achado que motivou: o desafiante do ciclo 92 PREVE melhor que o campeao (erro
menor em toda geracao recente e em toda familia) e PERDE 42% no portao. O erro
de previsao mede so as jogadas ESCOLHIDAS; o que decide a partida e a ORDEM entre
as opcoes da mesma decisao.

Mede, nas decisoes em que a simulacao deu nota a VARIAS opcoes (escolhida +
alternativas, ultimas geracoes em `q_alternativas.jsonl`):
  - top-1: o modelo poe em 1o a opcao que a simulacao poe em 1o?
  - pares: em quantos % dos pares de opcoes a ordem do modelo bate com a da simulacao
CONTROLE QUE PODE FALHAR: a metrica tem que reproduzir o PORTAO (campeao melhor
que o desafiante que ele venceu). Se nao reproduzir, ela nao mede o que importa.
E ruido de referencia: notas da simulacao EMBARALHADAS dentro da decisao.

Uso: python mede_escolha.py [--gen 92] [modelo1.joblib modelo2.joblib ...]
"""
import argparse
import json
import random
from collections import defaultdict

import joblib
import numpy as np

import corpus_bin
import corpus_escolhidas


def decisoes(gens):
    g = defaultdict(list)            # chave -> [(feats, nota_sim, escolhida)]
    for d in corpus_bin.linhas():
        if d.get('gen') in gens and d.get('decisao') is not None and d.get('alvo') is not None \
                and d.get('feats') is not None:
            g[(d['gen'], d.get('match'), d.get('leader'), d['decisao'])].append(
                (np.asarray(d['feats'], dtype=np.float32), float(d['alvo']), True))
    with open(corpus_escolhidas.ALTERNATIVAS, encoding='utf-8') as fh:
        for ln in fh:
            d = json.loads(ln)
            if d.get('gen') not in gens or d.get('alvo') is None or not d.get('feats'):
                continue
            k = (d['gen'], d.get('match'), d.get('leader'), d.get('decisao'))
            if k in g:
                g[k].append((np.asarray(d['feats'], dtype=np.float32), float(d['alvo']), False))
    return {k: v for k, v in g.items() if len(v) >= 2 and len({round(x[1], 6) for x in v}) > 1}


def mede(modelo, grupos, embaralha=False):
    W = modelo.n_features_in_
    top, pares_ok, pares = 0, 0, 0
    rng = random.Random(0)
    for v in grupos.values():
        X = np.stack([x[0][:W] for x in v])
        s = [x[1] for x in v]
        if embaralha:
            rng.shuffle(s)
        q = modelo.predict(X)
        top += int(np.argmax(q) == int(np.argmax(s)))
        for i in range(len(v)):
            for j in range(i + 1, len(v)):
                if s[i] != s[j]:
                    pares += 1
                    pares_ok += int((q[i] > q[j]) == (s[i] > s[j]))
    n = len(grupos)
    return top / max(1, n), pares_ok / max(1, pares), n, pares


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--gen', type=int, nargs='+', default=[92])
    ap.add_argument('modelos', nargs='*', default=['metrics/q_net.joblib', 'metrics/q_net_desafiante.joblib'])
    a = ap.parse_args()
    grupos = decisoes(set(a.gen))
    print('decisoes com >=2 opcoes avaliadas pela simulacao: %d (gens %s)' % (len(grupos), a.gen))
    m0 = None
    for caminho in a.modelos:
        m = joblib.load(caminho)['modelo']
        m0 = m0 or m
        t, p, n, np_ = mede(m, grupos)
        print('  %-38s top-1 %.1f%% | pares %.1f%% (%d pares)' % (caminho, 100 * t, 100 * p, np_))
    t, p, _, _ = mede(m0, grupos, embaralha=True)
    print('  %-38s top-1 %.1f%% | pares %.1f%%  (tem que cair pra ~acaso)' % ('CONTROLE notas embaralhadas', 100 * t, 100 * p))


if __name__ == '__main__':
    main()
