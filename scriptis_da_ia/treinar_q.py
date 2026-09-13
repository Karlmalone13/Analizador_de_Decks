# -*- coding: utf-8 -*-
"""Treina o modelo Q: (estado + acao) -> valor, SEM simular.

Passo 2 de 3 da substituicao da ARVORE (bloco 796, pedido do usuario).

## O que este modelo faz, e por que ele existe

Hoje, pra saber aonde cada acao leva, o motor SIMULA: clona o estado, aplica a
acao, gera as acoes legais do no e avalia. Sao ~64 estados materializados por
decisao, e e de onde vem **77% do tempo de partida** (AS-IS, bloco 795) -- o
modelo em si e so 23%.

O Q aprende a devolver o MESMO valor que a busca calculou, a partir de
(estado, acao), sem clonar e sem aplicar nada. Uma consulta por candidata (~8)
no lugar de ~64 estados materializados.

E o **DQN** da lista de metodos que o usuario trouxe: *"o agente joga contra si
mesmo e aprende o valor Q -- retorno futuro acumulado de CADA ACAO numa
posicao"*.

## Professor e aluno, um nivel acima

A **busca e o professor**: ela ja produz um valor por candidata, simulando.
Esse valor e o alvo. O **Q e o aluno**: aprende a responder sem simular. Mesma
estrutura que o projeto ja usou pro rotulo (bloco 783), aplicada agora a
ACAO em vez do estado.

A arvore nao desaparece -- ela continua rodando OFFLINE pra gerar alvos. O que
ela deixa de fazer e decidir.

## Validacao POR LIDER, como o resto do projeto

`GroupKFold` por lider: o objetivo registrado e jogar bem com QUALQUER deck,
entao o teste tem que ser em lider que o modelo nao viu treinando. Sem isso, um
modelo que decorou lider passa e quebra no deck novo.

Uso:
    python treinar_q.py --dataset metrics/q_alvos.jsonl --out metrics/q_net.joblib
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--dataset', default='metrics/q_alvos.jsonl')
    ap.add_argument('--out', default='metrics/q_net.joblib')
    ap.add_argument('--folds', type=int, default=5)
    args = ap.parse_args()

    import numpy as np
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.model_selection import GroupKFold

    caminho = RAIZ / args.dataset
    X, y, grupos = [], [], []
    with caminho.open(encoding='utf-8') as fh:
        for linha in fh:
            linha = linha.strip()
            if not linha:
                continue
            d = json.loads(linha)
            feats, alvo = d.get('feats'), d.get('alvo')
            if not feats or alvo is None:
                continue
            X.append(feats)
            y.append(float(alvo))
            grupos.append(d.get('leader') or '?')

    if len(X) < 500:
        raise SystemExit('corpus pequeno demais (%d alvos) -- gere mais antes'
                         % len(X))
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    grupos = np.asarray(grupos)
    n_lideres = len(set(grupos.tolist()))

    print()
    print('  alvos: %d | features: %d | lideres: %d'
          % (len(X), X.shape[1], n_lideres))
    print('  alvo: media %.3f | desvio %.3f | distintos %d'
          % (y.mean(), y.std(), len(set(np.round(y, 4).tolist()))))

    def novo():
        # Mesmos hiperparametros do `treinar_value.py`, de proposito: assim a
        # comparacao entre "avaliar estado" e "avaliar acao" isola O QUE se
        # preve, nao a capacidade do modelo.
        return HistGradientBoostingRegressor(
            max_iter=300, learning_rate=0.02, max_depth=3,
            min_samples_leaf=60, early_stopping=True, validation_fraction=0.15,
            l2_regularization=1.0, random_state=0)

    folds = min(args.folds, n_lideres)
    if folds < 2:
        raise SystemExit('precisa de pelo menos 2 lideres pra validar por lider')

    # BASE DE COMPARACAO: prever sempre a media. Sem isto, um R2 qualquer
    # parece bom -- e a regra do projeto e ter um controle que pode falhar.
    erros_modelo, erros_base = [], []
    gkf = GroupKFold(n_splits=folds)
    print()
    print('  fold | lideres no teste | erro medio do MODELO | erro da MEDIA')
    for k, (tr, te) in enumerate(gkf.split(X, y, grupos), 1):
        m = novo().fit(X[tr], y[tr])
        pred = m.predict(X[te])
        em = float(np.mean(np.abs(pred - y[te])))
        eb = float(np.mean(np.abs(y[tr].mean() - y[te])))
        erros_modelo.append(em)
        erros_base.append(eb)
        print('  %4d | %16d | %20.4f | %13.4f'
              % (k, len(set(grupos[te].tolist())), em, eb))

    em = float(np.mean(erros_modelo))
    eb = float(np.mean(erros_base))
    ganho = 100.0 * (eb - em) / max(1e-9, eb)
    print()
    print('  erro medio FORA DA AMOSTRA : %.4f' % em)
    print('  erro de prever a MEDIA     : %.4f' % eb)
    print('  o modelo erra %.1f%% menos que a media' % ganho)
    if ganho < 5.0:
        print('  => NAO APRENDEU. O Q nao distingue acao boa de ruim ainda.')
    else:
        print('  => APRENDEU a ordenar acao. Proximo: ligar e medir no motor.')

    modelo = novo().fit(X, y)
    bundle = {
        'modelo': modelo,
        'tipo': 'q',
        'n_alvos': int(len(X)),
        'n_features': int(X.shape[1]),
        'n_lideres': int(n_lideres),
        'erro_fora_amostra': em,
        'erro_da_media': eb,
        'ganho_pct': ganho,
        'dataset': args.dataset,
        'lideres': sorted(set(grupos.tolist())),
    }
    import joblib
    saida = RAIZ / args.out
    saida.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, saida)
    print('  modelo Q -> %s' % saida)
    print('  alvos por lider: %s ...' % Counter(grupos.tolist()).most_common(4))
    print()
    print('  ISTO E ERRO DE PREVISAO, NAO E GANHO NO MOTOR. O que decide se o Q')
    print('  substitui a arvore e a medicao no jogo: velocidade E se ele escolhe')
    print('  a mesma acao que o professor escolheria.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
