"""
avaliar_pares_contrafactuais.py
===============================
Usa os pares contrafactuais (`gerar_pares_contrafactuais.py`) pra
responder DUAS perguntas, nesta ordem -- e a primeira e mais importante
que a segunda.

PERGUNTA 1 (diagnostico): o motor de HOJE escolhe a irma certa?
---------------------------------------------------------------
Para cada par informativo (aquele em que os dois ramos deram vencedores
DIFERENTES), sabemos qual das duas candidatas de fato levava a ganhar.
Da pra perguntar, sem treinar nada:

  - o **score estatico** do motor prefere a candidata vencedora?
  - o **valor aprendido** (`value_net`) prefere a candidata vencedora?

Se os dois ficam em ~50%, esta medido que nenhum dos dois distingue
irmas -- que e exatamente a hipotese do bloco 754, ate aqui inferida de
sinais indiretos (metrica parada, distribuicao identica, duelo em 50%) e
nunca testada de frente. Um numero acima de 50% em qualquer um deles
mostra que ha sinal aproveitavel.

PERGUNTA 2 (o ML): da pra APRENDER a preferencia entre irmas?
-------------------------------------------------------------
Treina um classificador na DIFERENCA entre as duas candidatas
(features da irma 0 menos as da irma 1, mais o estado compartilhado) pra
prever qual vence. Validado com GroupKFold POR LIDER, pela mesma razao de
sempre (bloco 702/706: split que nao separa lider nao detecta falha de
generalizacao).

**Acuracia de referencia e 50%**, nao a taxa de positivos: o par e
simetrico por construcao.

RUIDO -- ler antes de comemorar ou enterrar
-------------------------------------------
Cada rotulo vem de UM playout por ramo. Com poucas dezenas de pares
informativos, o intervalo de confianca e enorme (com 60 pares, +-13pp).
Este script IMPRIME o IC de tudo que reporta. Um numero sem IC aqui seria
pior que numero nenhum -- e a licao dos blocos 705->706 e 712->713, em que
resultados comemorados foram RETRATADOS depois.

Uso:
  python avaliar_pares_contrafactuais.py
  python avaliar_pares_contrafactuais.py --pares metrics/pares_contrafactuais.jsonl
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from optcg_engine.value_net import load_value_net

PARES = 'metrics/pares_contrafactuais.jsonl'
CHAVES_CAND = ('score', 'cost', 'power', 'counter', 'don', 'blocker', 'rush')


def ic95(acertos: int, n: int) -> str:
    if not n:
        return 'n/d'
    p = acertos / n
    se = math.sqrt(p * (1 - p) / n)
    return f'{p:.1%} [{(p - 1.96 * se) * 100:.1f}; {(p + 1.96 * se) * 100:.1f}]'


def carregar(caminho: str) -> list:
    linhas = []
    for l in open(caminho, encoding='utf-8'):
        l = l.strip()
        if l:
            linhas.append(json.loads(l))
    return linhas


def vetor_par(r: dict) -> list:
    """Estado pre-decisao + DIFERENCA entre os estados POS-LINHA das duas
    irmas + diferenca das descricoes de acao.

    O estado POS-LINHA e o que o motor realmente avalia
    (`value_net.win_prob(p2, opp2)`) e a unica parte que DIFERE entre
    irmas -- o estado de antes e identico pras duas. A 1a versao deste
    script usava so o estado de antes: um modelo alimentado com aquilo
    nao teria como preferir uma irma, e nao era o que esta em producao.
    Erro meu, corrigido aqui; os pares antigos foram descartados."""
    c0, c1 = r['candidatas'][0], r['candidatas'][1]
    dif_acao = [float(c0.get(k, 0) or 0) - float(c1.get(k, 0) or 0) for k in CHAVES_CAND]
    pos = r.get('pos') or []
    if len(pos) == 2 and pos[0] and pos[1]:
        dif_pos = [float(a) - float(b) for a, b in zip(pos[0], pos[1])]
    else:
        dif_pos = [0.0] * len(r['estado'])
    mesmo_kind = [1.0 if c0.get('kind') == c1.get('kind') else 0.0]
    return list(r['estado']) + dif_pos + dif_acao + mesmo_kind


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--pares', default=PARES)
    ap.add_argument('--folds', type=int, default=5)
    args = ap.parse_args()

    todos = carregar(args.pares)
    inf = [r for r in todos if not r['empate_de_desfecho'] and r.get('preferencia') is not None]
    print(f'pares: {len(todos)} | INFORMATIVOS: {len(inf)} '
          f'({len(inf)/max(1,len(todos)):.1%})')
    if len(inf) < 20:
        print('\npoucos pares informativos pra qualquer conclusao -- gere mais.')
        return

    # ── PERGUNTA 1 ──────────────────────────────────────────────────────
    print('\n' + '=' * 62)
    print('1. O motor de HOJE escolhe a irma certa? (referencia = 50%)')
    print('=' * 62)

    # O score estatico: a candidata rank 0 e, por construcao, a de maior
    # score. Entao "score acerta" == "a preferencia era a rank 0".
    acertos_score = sum(1 for r in inf if r['preferencia'] == 1)
    print(f'  score estatico:   {ic95(acertos_score, len(inf))}')

    bundle = load_value_net()
    if bundle is None:
        print('  value_net:        modelo indisponivel')
    else:
        modelo = bundle['modelo']
        acertos_vn = com_pos = 0
        for r in inf:
            pos = r.get('pos') or []
            if len(pos) != 2 or not pos[0] or not pos[1]:
                continue
            com_pos += 1
            # COMO O MOTOR USA DE VERDADE: `win_prob` no estado POS-LINHA
            # de cada irma, e prefere a de maior probabilidade. Isto mede
            # o `value_net` na tarefa real, nao numa versao empobrecida.
            p0 = float(modelo.predict_proba([pos[0]])[0][1])
            p1 = float(modelo.predict_proba([pos[1]])[0][1])
            if p0 == p1:
                continue
            acertos_vn += 1 if (p0 > p1) == (r['preferencia'] == 1) else 0
        print(f'  value_net (pos-linha, como o motor usa): '
              f'{ic95(acertos_vn, com_pos)}')

    # ── PERGUNTA 2 ──────────────────────────────────────────────────────
    print('\n' + '=' * 62)
    print('2. Da pra APRENDER a preferencia entre irmas?')
    print('=' * 62)
    import numpy as np
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.model_selection import GroupKFold

    X = np.array([vetor_par(r) for r in inf], dtype=float)
    y = np.array([int(r['preferencia']) for r in inf], dtype=int)
    g = np.array([r.get('leader') or '?' for r in inf])
    n_lid = len(set(g))
    folds = min(args.folds, n_lid)
    if folds < 2 or len(set(y)) < 2:
        print(f'  impossivel validar: {n_lid} lideres, classes {set(y)}')
        return

    acertos = tot = 0
    for i_tr, i_te in GroupKFold(n_splits=folds).split(X, y, g):
        if len(set(y[i_tr])) < 2:
            continue
        m = HistGradientBoostingClassifier(
            max_iter=150, learning_rate=0.06, max_depth=3,
            min_samples_leaf=15, l2_regularization=1.0,
            random_state=0).fit(X[i_tr], y[i_tr])
        pred = m.predict(X[i_te])
        acertos += int((pred == y[i_te]).sum())
        tot += len(i_te)
    print(f'  ranker de irmas (fora da amostra, por lider): {ic95(acertos, tot)}')
    print(f'  ({tot} pares testados, {n_lid} lideres, {folds} folds)')
    print('\n  Se o IC inclui 50%, NAO ha evidencia de que aprendeu --')
    print('  independente de a media estar acima. Gerar mais pares e a')
    print('  unica saida: e a mesma disciplina que fez os blocos 705 e 712')
    print('  serem RETRATADOS depois de comemorados cedo demais.')


if __name__ == '__main__':
    main()
