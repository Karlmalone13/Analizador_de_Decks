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
    ap.add_argument('--modelo', choices=('rede', 'arvores'), default='rede',
                    help='REDE por default desde o bloco 800: medido em 120 mil '
                         'alvos, ela erra 18%% MENOS que as 300 arvores (0,0554 '
                         'x 0,0676) e a previsao custa 0,100 ms contra 8,47 -- '
                         '85x. Nao ha troca entre qualidade e velocidade aqui.')
    args = ap.parse_args()

    import numpy as np
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.neural_network import MLPRegressor
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import make_pipeline
    from sklearn.model_selection import GroupKFold

    caminho = RAIZ / args.dataset
    X, y, grupos = [], [], []
    decisoes, escolhidas, familias = [], [], []
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
            # Quais linhas competiram na MESMA decisao, quem o professor
            # escolheu, e de que familia era a acao. Linhas antigas nao tem
            # `decisao` e ficam de fora da concordancia (nao do treino).
            decisoes.append((d.get('match'), d.get('decisao')))
            escolhidas.append(bool(d.get('escolhida')))
            familias.append(d.get('acao') or '?')

    if len(X) < 500:
        raise SystemExit('corpus pequeno demais (%d alvos) -- gere mais antes'
                         % len(X))
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    grupos = np.asarray(grupos)
    decisoes = np.asarray([('%s|%s' % dc) for dc in decisoes])
    escolhidas = np.asarray(escolhidas)
    familias = np.asarray(familias)
    n_lideres = len(set(grupos.tolist()))

    print()
    print('  alvos: %d | features: %d | lideres: %d'
          % (len(X), X.shape[1], n_lideres))
    print('  alvo: media %.3f | desvio %.3f | distintos %d'
          % (y.mean(), y.std(), len(set(np.round(y, 4).tolist()))))

    def novo():
        # REDE LEVE (NNUE-style), default desde o bloco 800. A previsao e duas
        # multiplicacoes de matriz -- 0,100 ms em numpy puro contra 8,47 ms das
        # 300 arvores percorridas em Python, e com erro 18% MENOR.
        #
        # O `--modelo arvores` fica pra reproduzir a comparacao, nao pra uso.
        if args.modelo == 'arvores':
            return HistGradientBoostingRegressor(
                max_iter=300, learning_rate=0.02, max_depth=3,
                min_samples_leaf=60, early_stopping=True,
                validation_fraction=0.15, l2_regularization=1.0, random_state=0)
        return make_pipeline(
            StandardScaler(),
            MLPRegressor(hidden_layer_sizes=(64, 32), activation='relu',
                         solver='adam', learning_rate_init=3e-3, max_iter=60,
                         early_stopping=True, n_iter_no_change=5,
                         random_state=0))

    folds = min(args.folds, n_lideres)
    if folds < 2:
        raise SystemExit('precisa de pelo menos 2 lideres pra validar por lider')

    # BASE DE COMPARACAO: prever sempre a media. Sem isto, um R2 qualquer
    # parece bom -- e a regra do projeto e ter um controle que pode falhar.
    erros_modelo, erros_base = [], []
    # CONCORDANCIA TOP-1: por decisao, o argmax do aluno bate a escolha do
    # professor? E o que decide se o Q substitui a arvore -- erro absoluto
    # mede o VALOR, e quem decide e o ARGMAX.
    conc_ok = conc_tot = 0
    conc_fam = {}
    # CONTROLE QUE PODE FALHAR (regra do projeto): escolher no ACASO entre as
    # candidatas da decisao. Com ~4,8 candidatas isso ja da ~21%, entao a
    # concordancia sozinha nao diz nada -- o que informa e a distancia ate aqui.
    conc_acaso = 0.0
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

        # so as decisoes do fold de TESTE, e so as que tem id e escolhida
        grupos_dec = {}
        for pos, i in enumerate(te):
            dec = decisoes[i]
            if dec.endswith('|None') or dec.startswith('None|'):
                continue
            grupos_dec.setdefault(dec, []).append((pos, i))
        for dec, itens in grupos_dec.items():
            if len(itens) < 2:
                continue          # decisao de uma candidata so nao decide nada
            alvo_prof = [i for _p, i in itens if escolhidas[i]]
            if len(alvo_prof) != 1:
                continue          # sem professor marcado, nao ha o que comparar
            melhor = max(itens, key=lambda t: pred[t[0]])[1]
            acertou = (melhor == alvo_prof[0])
            conc_ok += 1 if acertou else 0
            conc_acaso += 1.0 / len(itens)
            conc_tot += 1
            fam = familias[alvo_prof[0]]
            d2 = conc_fam.setdefault(fam, [0, 0])
            d2[1] += 1
            d2[0] += 1 if acertou else 0
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

    conc = (100.0 * conc_ok / conc_tot) if conc_tot else None
    print()
    if conc is None:
        print('  CONCORDANCIA TOP-1: sem amostra -- o corpus nao tem `decisao`/')
        print('  `escolhida` (linhas anteriores ao bloco 809). Gere um ciclo novo.')
    else:
        acaso = 100.0 * conc_acaso / conc_tot
        print('  CONCORDANCIA TOP-1 COM O PROFESSOR: %.1f%% (%d decisoes)'
              % (conc, conc_tot))
        print('     escolher no ACASO daria %.1f%%  ->  %+.1f pp acima do acaso'
              % (acaso, conc - acaso))
        print('     a mesma acao que a arvore escolheria, FORA DA AMOSTRA.')
        print('     E ISTO, nao o erro acima, que decide se o Q substitui a')
        print('     arvore: o motor escolhe por argmax, nao por valor.')
        if conc_fam:
            print()
            print('     por familia de acao:')
            for fam, (ok, tot) in sorted(conc_fam.items(), key=lambda kv: -kv[1][1]):
                print('       %-12s %5.1f%%  (%d decisoes)'
                      % (fam, 100.0 * ok / max(1, tot), tot))

    modelo = novo().fit(X, y)
    bundle = {
        'modelo': modelo,
        'tipo': 'q',
        'familia': args.modelo,
        'n_alvos': int(len(X)),
        'n_features': int(X.shape[1]),
        'n_lideres': int(n_lideres),
        'erro_fora_amostra': em,
        'concordancia_top1': conc,
        'concordancia_acaso': (100.0 * conc_acaso / conc_tot) if conc_tot else None,
        'concordancia_decisoes': conc_tot,
        'concordancia_por_familia': {k: {'acerto_pct': round(100.0 * v[0] / max(1, v[1]), 1),
                                         'decisoes': v[1]}
                                     for k, v in conc_fam.items()},
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
