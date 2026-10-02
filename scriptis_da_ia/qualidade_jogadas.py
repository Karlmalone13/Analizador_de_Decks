# -*- coding: utf-8 -*-
"""QUALIDADE DE CADA JOGADA, medida pelo que ela CAUSOU (bloco 928).

Pedido do usuario: o bot analisa a qualidade e o desempenho das jogadas -- se
foram ruins ele tenta melhorar, se foram boas ele mantem.

  VANTAGEM = consequencia da jogada  -  valor da posicao ANTES dela

  * consequencia = o que aconteceu depois (valor da posicao 2 turnos proprios
    depois, ja com a resposta do oponente; resultado real se a partida acabou
    no horizonte) -- a MESMA que `treinar_q.alvo_consequencia` usa no treino;
  * valor da posicao antes = a regua aplicada ao estado gravado na linha.

Positivo = a jogada deixou o bot melhor do que estava; negativo = pior. Tudo
com UMA regua so (a atual) aplicada a TODAS as geracoes -- e o que torna as
geracoes comparaveis (a taxa de "ruins" do `porque_decisoes.py` usa a regua de
cada epoca e nao compara).

Uso:
  python qualidade_jogadas.py                 # todas as geracoes, por tipo
  python qualidade_jogadas.py --gen-min 30    # so as recentes
  python qualidade_jogadas.py --por-lider

CONTROLE QUE PODE FALHAR (impresso sempre): jogadas de partidas GANHAS tem que
ter vantagem media MAIOR que as de partidas PERDIDAS. Se nao tiver, a vantagem
nao mede nada e o relatorio nao vale.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

LIMIAR = 0.05      # |vantagem| acima disso conta como jogada boa/ruim


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--dataset', default=str(RAIZ / 'metrics' / 'q_alvos.jsonl'))
    ap.add_argument('--selfplay', default=str(RAIZ / 'metrics' / 'selfplay_v2.jsonl'))
    ap.add_argument('--regua', default=str(RAIZ / 'metrics' / 'value_net_aluno.joblib'))
    ap.add_argument('--gen-min', dest='gen_min', type=int, default=1)
    ap.add_argument('--por-lider', dest='por_lider', action='store_true')
    ap.add_argument('--limiar', type=float, default=LIMIAR)
    args = ap.parse_args()

    import numpy as np
    from optcg_engine import value_net as vn
    import treinar_q

    regua = vn.load_value_net(args.regua)
    if not regua:
        raise SystemExit('regua indisponivel: %s' % args.regua)
    traj = treinar_q.carrega_trajetorias(args.selfplay, avaliador=regua)
    n_est = len(vn.FEATURE_NAMES_ALUNO)
    i_ld = list(vn.FEATURE_NAMES_ALUNO).index('life_diff')
    modelo = regua['modelo']

    linhas = []        # (gen, familia, lider, consequencia, feats do estado, venceu)
    with open(args.dataset, encoding='utf-8') as fh:
        for l in fh:
            d = json.loads(l)
            g = d.get('gen') or 0
            if g < args.gen_min or not d.get('escolhida') or not d.get('feats'):
                continue
            d['ld_agora'] = d['feats'][i_ld]
            c = treinar_q.alvo_consequencia(d, traj)
            if c is None:
                continue
            t = traj.get((g, d.get('match'), d.get('leader')))
            linhas.append((g, d.get('acao') or '?', d.get('leader') or '?', float(c),
                           d['feats'][:n_est], bool(t and t[-1][2])))
    if not linhas:
        raise SystemExit('nenhuma jogada com consequencia')

    X = np.asarray([r[4] for r in linhas], dtype=float)
    v_antes = (modelo.predict_proba(X)[:, 1] if hasattr(modelo, 'predict_proba')
               else modelo.predict(X))
    A = np.asarray([r[3] for r in linhas]) - np.asarray(v_antes, dtype=float)
    gens = np.asarray([r[0] for r in linhas])
    fams = np.asarray([r[1] for r in linhas])
    lids = np.asarray([r[2] for r in linhas])
    venceu = np.asarray([r[5] for r in linhas])

    print('jogadas escolhidas com consequencia: %d | gens %d-%d | limiar +-%.2f'
          % (len(A), gens.min(), gens.max(), args.limiar))
    print()
    # CONTROLE
    ganha, perde = A[venceu].mean(), A[~venceu].mean()
    ok = ganha > perde
    print('CONTROLE: vantagem media em partidas GANHAS %+.4f | PERDIDAS %+.4f -> %s'
          % (ganha, perde, 'ok, a vantagem separa' if ok else 'FALHOU: nao separa, nao confie'))
    print()

    def linha(rot, m):
        a = A[m]
        if not len(a):
            return
        print('  %-14s %8d  media %+.4f | ruins %5.1f%% | boas %5.1f%%'
              % (rot, len(a), a.mean(), 100 * (a < -args.limiar).mean(),
                 100 * (a > args.limiar).mean()))

    print('POR TIPO DE JOGADA (todas as geracoes)')
    for f in sorted(set(fams.tolist()), key=lambda x: -(fams == x).sum()):
        linha(f, fams == f)
    print()
    print('POR GERACAO (mesma regua em todas -- comparavel)')
    ug = sorted(set(gens.tolist()))
    passo = max(1, len(ug) // 14)
    for g in ug[::passo]:
        linha('gen %d' % g, gens == g)
    if args.por_lider:
        print()
        print('POR LIDER (>= 300 jogadas)')
        for lid in sorted(set(lids.tolist()), key=lambda x: -(lids == x).sum()):
            if (lids == lid).sum() >= 300:
                linha(lid, lids == lid)
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
