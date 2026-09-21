"""
treinar_value.py
================
Treina a funcao de valor por auto-jogo (`optcg_engine/value_net.py`) a
partir do dataset de `gerar_selfplay_dataset.py`.

Decisao do usuario (08/09/2026): caminho HIBRIDO, atras de flag.

VALIDACAO: GroupKFold POR LIDER -- inegociavel
----------------------------------------------
O modelo e validado em lideres que ele NAO viu no treino. Isso nao e
capricho estatistico: e a correcao direta de dois defeitos ja pagos caro
neste projeto.

  - Bloco 702: `policy.py` tinha one-hot de LIDER com split POR PARTIDA.
    Aquela validacao **nunca poderia** detectar falha de generalizacao pra
    deck novo -- o modelo decorava o lider e a validacao aplaudia.
  - Bloco 705 -> 706: uma selecao de conjunto aprendida saiu **+4,8pp** em
    UM split de 9 lideres e foi comemorada; sob GroupKFold por lider (30
    lideres) virou **-0,2pp**. O resultado foi RETRATADO.

Por isso o numero que este script reporta como principal e o FORA DA
AMOSTRA por lider, e ele imprime o recorte por fold. Um AUC de treino alto
com validacao colada em 0,5 significa que o modelo decorou -- e o projeto
ja viu exatamente isso acontecer (bloco 706: regularizar fechou o treino
de 85,5% pra 47,9% **sem mover a validacao**).

O QUE UM RESULTADO BOM AQUI *NAO* PROVA
---------------------------------------
AUC fora da amostra alto significa que o modelo ordena estados melhor que
o acaso. **Nao** significa que ligar `VALUE_NET_WEIGHT` melhora o motor --
essa e a licao mais cara dos blocos 680-683, onde o ranqueador tinha AUC
0,851 (contra 0,702 do motor) e MESMO ASSIM piorava a metrica quando
ligado no laco de decisao. So o A/B com a flag ligada, medido por
`decision_quality_full.py --all` COM recorte por lider, decide.

Uso:
  python treinar_value.py
  python treinar_value.py --dataset metrics/selfplay_dataset.jsonl --folds 5
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from optcg_engine.value_net import (FEATURE_NAMES, FEATURE_NAMES_RICAS,
                                    FEATURE_NAMES_V3,
                                    FEATURE_NAMES_ALUNO, MODEL_PATH)

DATASET_DEFAULT = 'metrics/selfplay_dataset.jsonl'


def carregar(caminho: str):
    X, y, grupos, alvo = [], [], [], []
    with open(caminho, encoding='utf-8') as fh:
        for linha in fh:
            linha = linha.strip()
            if not linha:
                continue
            d = json.loads(linha)
            if 'win' not in d or 'feats' not in d:
                continue
            X.append(d['feats'])
            y.append(int(d['win']))
            # `alvo` (bloco 783, Fase 1): retorno de n passos gerado por
            # `rotulo_professor.py`. Ausente nos corpora antigos -- cai no
            # proprio `win`, entao nada quebra.
            alvo.append(float(d.get('alvo', d['win'])))
            grupos.append(d.get('leader') or '?')
    return X, y, grupos, alvo


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dataset', default=DATASET_DEFAULT)
    ap.add_argument('--folds', type=int, default=5)
    ap.add_argument('--com-quantil', dest='com_quantil', action='store_true',
                    help='REPROVADO no bloco 793 (quantil de alvo binario = [0,1] sempre). '
                         'Mantido so pra reproduzir a medicao.')
    ap.add_argument('--out', default=MODEL_PATH)
    ap.add_argument('--alvo', choices=('win', 'professor'), default='win',
                    help="win = o rotulo binario da partida (o de sempre). "
                         "professor = o alvo continuo de n passos gerado por "
                         "`rotulo_professor.py` (Fase 1, bloco 783). Medido: "
                         "com `win`, 100%% da variacao do rotulo vem da PARTIDA "
                         "e 0,0000 vem da posicao -- os ~18,5 estados de uma "
                         "partida levam a MESMA etiqueta, entao o modelo nao "
                         "tem como aprender qualidade de jogada. Com `professor` "
                         "a variancia dentro da partida vai a 0,0076 e os "
                         "valores distintos de 2 pra 20. Treina REGRESSOR.")
    ap.add_argument('--features', choices=('basicas', 'ricas', 'v3', 'aluno'), default='basicas',
                    help='basicas = as 32 originais (so contagens e agregados); '
                         'ricas = 32 + 17 de QUALIDADE do board (poder maximo, '
                         'DON anexado, rush/double/unblockable/banish, quantos '
                         'personagens TEM efeito). Default basicas pra nao mudar '
                         'comportamento sem medicao (bloco 764)')
    ap.add_argument('--modelo', choices=('arvores', 'rede'), default='arvores',
                    help='arvores = HistGradientBoosting* (default -- comportamento '
                         'antigo, nao muda quem ja chama este script sem passar a '
                         'flag). rede = Pipeline(StandardScaler, MLPRegressor/'
                         'Classifier), a mesma arquitetura NNUE-style ja usada em '
                         'treinar_q.py. Achado 21/09/2026: value_net_aluno.joblib '
                         '(arvores) era ~27%% do tempo de uma partida de self-play '
                         '(predictor.py:predict do sklearn) -- rede e acelerada por '
                         '`_forward_rapido` (value_net.py, 3,1x medido) e ja errou '
                         '18%% menos que arvores num corpus comparavel '
                         '(treinar_q.py, bloco 800).')
    args = ap.parse_args()

    import numpy as np
    from sklearn.ensemble import (HistGradientBoostingClassifier,
                                  HistGradientBoostingRegressor)
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import GroupKFold

    X, y, grupos, alvo = carregar(args.dataset)
    if not X:
        raise SystemExit(f'dataset vazio ou sem rotulo: {args.dataset}')
    X = np.array(X, dtype=float)
    y = np.array(y, dtype=int)
    grupos = np.array(grupos)
    alvo = np.array(alvo, dtype=float)

    n_lideres = len(set(grupos))
    # O dataset novo grava o SUPERCONJUNTO rico (49); o antigo tem 32.
    # Aqui se recorta o que o modelo vai enxergar -- assim o MESMO corpus
    # treina os dois lados do A/B e a comparacao isola a VISAO (bloco 764).
    nomes = {'basicas': FEATURE_NAMES, 'ricas': FEATURE_NAMES_RICAS,
             'v3': FEATURE_NAMES_V3,
             # `aluno` (Fase 2, bloco 783): V3 menos `counter_hand_opp`, a
             # unica das 78 que exige ver a MAO do oponente. Treinado com
             # ela, o modelo aprende padroes ancorados num numero que nao
             # existe na hora de jogar.
             'aluno': FEATURE_NAMES_ALUNO}[args.features]
    # O dataset grava o SUPERCONJUNTO mais recente; aqui se recorta o que o
    # modelo vai enxergar. Assim o MESMO corpus treina todos os lados do A/B
    # e a comparacao isola a VISAO, nao o volume (bloco 764/766).
    larguras = {len(FEATURE_NAMES): FEATURE_NAMES,
                len(FEATURE_NAMES_RICAS): FEATURE_NAMES_RICAS,
                len(FEATURE_NAMES_V3): FEATURE_NAMES_V3,
                len(FEATURE_NAMES_ALUNO): FEATURE_NAMES_ALUNO}
    if X.shape[1] not in larguras:
        raise SystemExit(f'ERRO: dataset tem {X.shape[1]} features; esperado '
                         f'{sorted(larguras)}. Re-gere.')
    do_dataset = larguras[X.shape[1]]
    faltando = [n for n in nomes if n not in do_dataset]
    if faltando:
        raise SystemExit(
            f'ERRO: --features {args.features} exige {len(nomes)} colunas, mas o '
            f'dataset ({X.shape[1]}) nao tem {len(faltando)} delas '
            f'(ex: {faltando[:3]}). Re-gere com gerar_selfplay_dataset.py.')
    X = X[:, [do_dataset.index(n) for n in nomes]]
    print(f'[value] {len(X)} estados | {n_lideres} lideres | '
          f'{len(nomes)} features ({args.features}) | positivos {y.mean():.1%}')

    folds = min(args.folds, n_lideres)
    if folds < 2:
        raise SystemExit(f'GroupKFold por lider precisa de >=2 lideres, '
                         f'o dataset tem {n_lideres}. Gere mais partidas '
                         f'(--decks maior em gerar_selfplay_dataset.py).')
    if folds < args.folds:
        print(f'  aviso: folds reduzido pra {folds} (so ha {n_lideres} lideres)')

    def novo_modelo():
        if args.modelo == 'rede':
            # REDE LEVE (NNUE-style), mesma arquitetura de `treinar_q.py`
            # (bloco 800) -- so entra com `--modelo rede` explicito, nunca
            # muda quem ja chama este script sem passar a flag.
            from sklearn.neural_network import MLPClassifier, MLPRegressor
            from sklearn.pipeline import make_pipeline
            from sklearn.preprocessing import StandardScaler
            Cls = (MLPRegressor if args.alvo == 'professor' else MLPClassifier)
            return make_pipeline(
                StandardScaler(),
                Cls(hidden_layer_sizes=(64, 32), activation='relu',
                    solver='adam', learning_rate_init=3e-3, max_iter=60,
                    early_stopping=True, n_iter_no_change=5, random_state=0))
        # Hiperparametros BUSCADOS (bloco 771), nao mais fixos no chute.
        # Medido em lideres nunca vistos: AUC fora da amostra 0,7761 ->
        # 0,7985, e o vao treino-teste caiu de 0,201 pra 0,087 -- o modelo
        # decorava. `early_stopping` + arvore rasa + folha grande sao o que
        # segura o sobre-ajuste com corpus pequeno.
        # Alvo continuo (professor) => REGRESSOR. Mesmos hiperparametros,
        # pra a comparacao isolar o ALVO e nao a capacidade do modelo.
        # max_iter=200 (era 300, ate 21/09/2026): a curva de val_score do
        # treino nunca platoa (early_stopping nao dispara antes de 300 --
        # continua melhorando ate o teto), mas o ganho marginal fica pequeno
        # (200->300 custa 0,0098 de AUC no corpus todo pra ~46% mais tempo
        # de inferencia). predictor.py:predict do sklearn era ~46% do tempo
        # de uma partida de self-play (as_is.py, bloco 21/09). Trade-off
        # aceito pelo usuario: 1% de AUC por mais velocidade, recuperavel
        # com mais volume de self-play (o proprio motivo da troca).
        cls = (HistGradientBoostingRegressor if args.alvo == 'professor'
               else HistGradientBoostingClassifier)
        return cls(
            max_iter=200, learning_rate=0.02, max_depth=3,
            min_samples_leaf=60, early_stopping=True, validation_fraction=0.15,
            l2_regularization=1.0,
            random_state=0)

    # ── Validacao FORA DA AMOSTRA, por lider ────────────────────────────
    aucs_val, aucs_tr = [], []
    gkf = GroupKFold(n_splits=folds)
    print(f'\n  fold | lideres no teste | AUC treino | AUC fora da amostra')
    print(f'  -----+------------------+------------+--------------------')
    for k, (i_tr, i_te) in enumerate(gkf.split(X, y, grupos), 1):
        if len(set(y[i_te])) < 2:
            print(f'   {k:2d}  | {len(set(grupos[i_te])):2d}               '
                  f' |     --     | fold sem as duas classes, pulado')
            continue
        # TREINA no alvo escolhido; AVALIA sempre contra o resultado REAL
        # (`y`), pra o AUC continuar comparavel com todas as medicoes
        # anteriores -- trocar a regua junto com o alvo tornaria a
        # comparacao inutil.
        m = novo_modelo().fit(X[i_tr], alvo[i_tr])
        def _p(Z):
            return (m.predict_proba(Z)[:, 1] if hasattr(m, 'predict_proba')
                    else m.predict(Z))
        a_tr = roc_auc_score(y[i_tr], _p(X[i_tr]))
        a_te = roc_auc_score(y[i_te], _p(X[i_te]))
        aucs_tr.append(a_tr)
        aucs_val.append(a_te)
        print(f'   {k:2d}  | {len(set(grupos[i_te])):2d}                '
              f'|   {a_tr:.4f}   |       {a_te:.4f}')

    if not aucs_val:
        raise SystemExit('nenhum fold valido -- dataset pequeno ou desbalanceado demais')

    auc_val = float(np.mean(aucs_val))
    auc_tr = float(np.mean(aucs_tr))
    print(f'\n  AUC treino (media):          {auc_tr:.4f}')
    print(f'  AUC FORA DA AMOSTRA (media): {auc_val:.4f}   <- o numero que vale')
    print(f'  gap treino-validacao:        {auc_tr - auc_val:+.4f}'
          f'   (gap grande = decorou lider, ver bloco 706)')

    if auc_val < 0.55:
        print('\n  ATENCAO: fora da amostra abaixo de 0,55 -- o modelo mal '
              'ordena melhor que o acaso.\n  NAO ligar VALUE_NET_WEIGHT '
              'com este modelo; gere mais partidas antes.')

    # ── Modelo final (treinado em tudo) ─────────────────────────────────
    modelo = novo_modelo().fit(X, y)

    # ── INCERTEZA: duas cabecas de QUANTIL no MESMO modelo (bloco 793) ───
    # Pedido do usuario, depois de me ver comparar duas estimativas PONTUAIS
    # pra decidir a defesa: *"porque vc esta fazendo elas decidirem em
    # probabilidade de vitoria se eu te dei uma lista de metodos?"* -- e a
    # linha da lista dele que resolve isto e o Processo Gaussiano, que
    # entrega a INCERTEZA junto da previsao.
    #
    # Por que quantil e nao GPR: GPR e O(n^3) e o corpus tem dezenas de
    # milhares de estados. E, principalmente, porque ele tambem perguntou
    # *"porque diversos modelos?"* -- um segundo modelo ao lado seria a
    # regua concorrente que `REGRA_SEM_DUPLICACAO` proibe. As cabecas de
    # quantil NAO decidem nada: quem decide continua sendo `modelo`. Elas so
    # dizem QUAO LARGO e o erro dele, no mesmo arquivo e sobre as mesmas
    # features.
    q_baixo = q_alto = None
    if False:   # REPROVADO no bloco 793 -- ver REPROVADOS.md e o --com-quantil abaixo
        from sklearn.ensemble import HistGradientBoostingRegressor as _HGR

        def _quantil(q):
            return _HGR(loss='quantile', quantile=q,
                        max_iter=300, learning_rate=0.02, max_depth=3,
                        min_samples_leaf=60, early_stopping=True,
                        validation_fraction=0.15, l2_regularization=1.0,
                        random_state=0).fit(X, y)

        print('  treinando as cabecas de INCERTEZA (quantis 10% e 90%)...')
        q_baixo, q_alto = _quantil(0.10), _quantil(0.90)

    bundle = {
        'modelo': modelo,
        'familia': args.modelo,
        'modelo_q10': q_baixo,
        'modelo_q90': q_alto,
        'feature_names': list(nomes),
        'auc_fora_amostra': auc_val,
        'auc_treino': auc_tr,
        'n_estados': int(len(X)),
        'n_lideres': int(n_lideres),
        'folds': folds,
        'lideres': sorted(set(grupos.tolist())),
        'dataset': args.dataset,
    }
    import joblib
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, args.out)
    print(f'\n  modelo -> {args.out}')
    print(f'  estados por lider: {Counter(grupos.tolist()).most_common(5)} ...')
    print('\n  PROXIMO PASSO OBRIGATORIO: isto e AUC, nao e ganho no motor.')
    print('  Blocos 680-683: AUC 0,851 e MESMO ASSIM piorou ligado no laco.')
    print('  Medir com A/B real:')
    print('    OPTCG_K_VALUE_NET_WEIGHT=200 python decision_quality_full.py --all')
    print('  e comparar contra o default (peso 0), COM recorte por lider.')


if __name__ == '__main__':
    main()
