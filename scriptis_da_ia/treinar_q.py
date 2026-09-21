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
modelo que decorou lider passa e quebra no deck novo. NAO reduzir isso por
velocidade -- discutido explicitamente com o usuario 19/09/2026: jogar bem nao
e "ganhar a partida", e extrair o melhor do deck que se tem, e um modelo que so
aprendeu "este lider costuma vencer" erraria isso silenciosamente. O corte por
velocidade tem que vir de OUTRO lugar (ver abaixo), nunca de tirar o holdout.

## AS-IS que motivou a mudanca de 19/09/2026 (bloco 878)

Medido isolado: ler+parsear o corpus inteiro (721k linhas) custa 22s: **1,5%**
do tempo de "treina" no ciclo (1451s). O resto e o `MLPRegressor.fit()` --
210,6s pra UM fit em ~577k linhas. E o codigo fazia **6 fits completos**: 5
(GroupKFold) + 1 final no corpus inteiro (`modelo = novo().fit(X, y)`, o que
realmente vai pro `.joblib`). Os folds de validacao NUNCA viram modelo de
producao -- so medem generalizacao -- entao nao precisam ver o corpus
INTEIRO pra isso. Duas mudancas, nenhuma delas mexendo no holdout por lider:

1. `--folds` cai de 5 pra 2 (o MINIMO que ainda garante "testado em lider
   nao visto") -- 5 fits de validacao viram 2.
2. `--amostra-validacao` (default 200.000): os folds rodam numa AMOSTRA do
   corpus, nao no corpus inteiro. O modelo FINAL (o que e salvo) continua
   treinando no corpus INTEIRO, sem amostragem -- a amostra e so pra medir
   generalizacao mais barato.

Ganho estimado (nao ainda remedido com AS-IS formal): ~1451s -> ~350-400s.

## Relatorio POR LIDER individual (achado no mesmo pedido)

Ate aqui o relatorio so mostrava erro/concordancia POR FOLD (uma MISTURA de
varios lideres, ja que cada fold segura ~n_lideres/folds lideres de uma vez)
e POR FAMILIA de acao -- nunca por lider individual, embora a lista de
lideres ja estivesse salva no bundle sem uso nenhum. E exatamente o tipo de
agregado que o projeto ja proibe em outras ferramentas (regra "nenhum
resultado agregado vale sem o recorte POR LIDER", `decision_quality_full.py`
ja obrigado a mostrar isso). Um lider especifico podia estar generalizando
mal e sumir na media do fold. Corrigido: cada lider so aparece no fold em
que foi held-out, entao da pra tabular por lider sem custo extra de treino.

## Filtro por CRITERIO DE ROTULO (`--modo`, 20/09/2026) -- HIPOTESE TESTADA E DERRUBADA

O corpus mistura dois criterios de rotulo: 'bootstrap' (o proprio modelo
avaliando o estado que a candidata produz -- linhas antigas nao tem o campo
`modo`, mas o bloco 877 ja mediu que 100% delas sao bootstrap) e 'busca'
(professor independente, simula de verdade). A hipotese inicial era que
misturar os dois contamina o alvo -- erro fora da amostra SUBIU 6 ciclos
seguidos (0,0498 -> 0,0581) enquanto a fracao 'busca' crescia.

**MEDIDO E DERRUBADO no mesmo dia**: um Q treinado SO com 'busca' (95k linhas,
alguns lideres com so 35-104 decisoes de validacao) perdeu **0x9** (11
empates) contra o Q treinado com o corpus INTEIRO misturado, em duelo real
(espelho pareado, `treino_continuo.duelar_sprt`) -- nao so pior em metrica
estatica, pior JOGANDO. O corpus 'busca' ainda nao tem volume suficiente pra
treinar sozinho; misturar com 'bootstrap' hoje ajuda mais do que atrapalha,
mesmo que o criterio nao seja o mesmo. **Default volta a ser 'todos'** -- o
flag fica pra quando o volume de 'busca' crescer o bastante pra re-testar
(o campo `modo` grava certo desde o bloco 877, entao a comparacao pode ser
refeita a qualquer momento sem precisar gerar dado novo).

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
    ap.add_argument('--folds', type=int, default=2,
                    help='GroupKFold por lider. MINIMO 2 (garante lider nunca '
                         'visto no treino) -- default ate 19/09 era 5, cortado '
                         'pro minimo que ainda cumpre a garantia (bloco 878, '
                         'AS-IS: cada fold a mais e outro fit completo, ~210s '
                         'em ~577k linhas)')
    ap.add_argument('--amostra-validacao', dest='amostra_validacao', type=int,
                    default=200_000,
                    help='os FOLDS de validacao rodam nesta amostra do corpus, '
                         'nao no corpus inteiro -- o modelo FINAL salvo sempre '
                         've tudo (bloco 878). 0 desliga a amostragem (usa o '
                         'corpus inteiro tambem na validacao, comportamento '
                         'antigo).')
    ap.add_argument('--modelo', choices=('rede', 'arvores'), default='rede',
                    help='REDE por default desde o bloco 800: medido em 120 mil '
                         'alvos, ela erra 18%% MENOS que as 300 arvores (0,0554 '
                         'x 0,0676) e a previsao custa 0,100 ms contra 8,47 -- '
                         '85x. Nao ha troca entre qualidade e velocidade aqui.')
    ap.add_argument('--modo', choices=('busca', 'bootstrap', 'todos'),
                    default='todos',
                    help='qual CRITERIO DE ROTULO usar pra treinar (ver '
                         'docstring do modulo). Linha sem o campo `modo` conta '
                         'como \'bootstrap\'. Default \'todos\' -- \'busca\' '
                         'sozinho foi testado em duelo real e PERDEU 0x9 '
                         '(20/09/2026), corpus ainda pequeno demais.')
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
    n_lidas = n_filtradas_modo = 0
    with caminho.open(encoding='utf-8') as fh:
        for linha in fh:
            linha = linha.strip()
            if not linha:
                continue
            d = json.loads(linha)
            n_lidas += 1
            modo = d.get('modo') or 'bootstrap'
            if args.modo != 'todos' and modo != args.modo:
                n_filtradas_modo += 1
                continue
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

    print()
    print('  corpus: %d linhas lidas | %d descartadas pelo filtro --modo=%s '
          '(%d restantes)' % (n_lidas, n_filtradas_modo, args.modo, len(X)))

    if len(X) < 500:
        raise SystemExit('corpus pequeno demais (%d alvos) -- gere mais antes, '
                         'ou use --modo todos/bootstrap se \'busca\' ainda nao '
                         'acumulou volume' % len(X))
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

    # AMOSTRA SO PRA VALIDACAO (bloco 878) -- os folds nunca viram o modelo
    # salvo (esse treina no X/y INTEIROS mais abaixo), entao nao precisam do
    # corpus inteiro pra medir generalizacao. Semente FIXA (reprodutivel).
    if args.amostra_validacao and len(X) > args.amostra_validacao:
        idx_val = np.random.RandomState(0).choice(
            len(X), size=args.amostra_validacao, replace=False)
        idx_val.sort()  # mantem a ordem original (decisoes agrupadas)
        Xv, yv, gruposv = X[idx_val], y[idx_val], grupos[idx_val]
        decisoesv = decisoes[idx_val]
        escolhidasv = escolhidas[idx_val]
        familiasv = familias[idx_val]
        print('  validacao rodando numa amostra de %d (o modelo final treina '
              'nos %d inteiros)' % (len(Xv), len(X)))
    else:
        Xv, yv, gruposv = X, y, grupos
        decisoesv, escolhidasv, familiasv = decisoes, escolhidas, familias
    n_lideres_val = len(set(gruposv.tolist()))

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

    folds = min(args.folds, n_lideres_val)
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
    # POR LIDER individual (bloco 878) -- cada lider so aparece no fold em
    # que foi held-out, entao acumula direto sem custo extra de treino.
    # erro_lider: lider -> lista de |erro| das linhas dele; conc_lider: lider
    # -> [acertos, total] de concordancia, mesmo formato de conc_fam.
    erro_lider = {}
    conc_lider = {}
    # CONTROLE QUE PODE FALHAR (regra do projeto): escolher no ACASO entre as
    # candidatas da decisao. Com ~4,8 candidatas isso ja da ~21%, entao a
    # concordancia sozinha nao diz nada -- o que informa e a distancia ate aqui.
    conc_acaso = 0.0
    gkf = GroupKFold(n_splits=folds)
    print()
    print('  fold | lideres no teste | erro medio do MODELO | erro da MEDIA')
    for k, (tr, te) in enumerate(gkf.split(Xv, yv, gruposv), 1):
        m = novo().fit(Xv[tr], yv[tr])
        pred = m.predict(Xv[te])
        em = float(np.mean(np.abs(pred - yv[te])))
        eb = float(np.mean(np.abs(yv[tr].mean() - yv[te])))
        erros_modelo.append(em)
        erros_base.append(eb)

        for pos, i in enumerate(te):
            erro_lider.setdefault(gruposv[i], []).append(abs(pred[pos] - yv[i]))

        # so as decisoes do fold de TESTE, e so as que tem id e escolhida
        grupos_dec = {}
        for pos, i in enumerate(te):
            dec = decisoesv[i]
            if dec.endswith('|None') or dec.startswith('None|'):
                continue
            grupos_dec.setdefault(dec, []).append((pos, i))
        for dec, itens in grupos_dec.items():
            if len(itens) < 2:
                continue          # decisao de uma candidata so nao decide nada
            alvo_prof = [i for _p, i in itens if escolhidasv[i]]
            if len(alvo_prof) != 1:
                continue          # sem professor marcado, nao ha o que comparar
            melhor = max(itens, key=lambda t: pred[t[0]])[1]
            acertou = (melhor == alvo_prof[0])
            conc_ok += 1 if acertou else 0
            conc_acaso += 1.0 / len(itens)
            conc_tot += 1
            fam = familiasv[alvo_prof[0]]
            d2 = conc_fam.setdefault(fam, [0, 0])
            d2[1] += 1
            d2[0] += 1 if acertou else 0
            lid = gruposv[alvo_prof[0]]
            d3 = conc_lider.setdefault(lid, [0, 0])
            d3[1] += 1
            d3[0] += 1 if acertou else 0
        print('  %4d | %16d | %20.4f | %13.4f'
              % (k, len(set(gruposv[te].tolist())), em, eb))

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

    # POR LIDER individual (bloco 878) -- ate aqui o relatorio so mostrava
    # fold (mistura varios lideres) e familia; um lider especifico podia
    # generalizar mal e sumir na media. Ordenado por volume de decisoes,
    # mesma convencao de `decision_quality_full.py`.
    por_lider = {}
    for lid in set(list(erro_lider.keys()) + list(conc_lider.keys())):
        erros = erro_lider.get(lid, [])
        ok, tot = conc_lider.get(lid, [0, 0])
        por_lider[lid] = {
            'erro_medio': round(float(np.mean(erros)), 4) if erros else None,
            'n_alvos': len(erros),
            'concordancia_pct': round(100.0 * ok / tot, 1) if tot else None,
            'decisoes': tot,
        }
    if por_lider:
        print()
        print('  POR LIDER (validacao, cada lider held-out em 1 fold):')
        print('    %-14s %10s %12s %14s %10s'
              % ('lider', 'alvos', 'erro medio', 'concordancia', 'decisoes'))
        for lid, d in sorted(por_lider.items(), key=lambda kv: -kv[1]['decisoes']):
            erro_txt = '%.4f' % d['erro_medio'] if d['erro_medio'] is not None else '?'
            conc_txt = ('%.1f%%' % d['concordancia_pct']
                       if d['concordancia_pct'] is not None else '?')
            print('    %-14s %10d %12s %14s %10d'
                  % (lid, d['n_alvos'], erro_txt, conc_txt, d['decisoes']))

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
        'por_lider': por_lider,
        'amostra_validacao': int(len(Xv)),
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
