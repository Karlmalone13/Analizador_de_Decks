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

from optcg_engine.value_net import FEATURE_NAMES, FEATURE_NAMES_RICAS, MODEL_PATH

DATASET_DEFAULT = 'metrics/selfplay_dataset.jsonl'


def carregar(caminho: str):
    X, y, grupos = [], [], []
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
            grupos.append(d.get('leader') or '?')
    return X, y, grupos


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dataset', default=DATASET_DEFAULT)
    ap.add_argument('--folds', type=int, default=5)
    ap.add_argument('--out', default=MODEL_PATH)
    ap.add_argument('--features', choices=('basicas', 'ricas'), default='basicas',
                    help='basicas = as 32 originais (so contagens e agregados); '
                         'ricas = 32 + 17 de QUALIDADE do board (poder maximo, '
                         'DON anexado, rush/double/unblockable/banish, quantos '
                         'personagens TEM efeito). Default basicas pra nao mudar '
                         'comportamento sem medicao (bloco 764)')
    args = ap.parse_args()

    import numpy as np
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import GroupKFold

    X, y, grupos = carregar(args.dataset)
    if not X:
        raise SystemExit(f'dataset vazio ou sem rotulo: {args.dataset}')
    X = np.array(X, dtype=float)
    y = np.array(y, dtype=int)
    grupos = np.array(grupos)

    n_lideres = len(set(grupos))
    # O dataset novo grava o SUPERCONJUNTO rico (49); o antigo tem 32.
    # Aqui se recorta o que o modelo vai enxergar -- assim o MESMO corpus
    # treina os dois lados do A/B e a comparacao isola a VISAO (bloco 764).
    nomes = FEATURE_NAMES_RICAS if args.features == 'ricas' else FEATURE_NAMES
    if X.shape[1] == len(FEATURE_NAMES_RICAS):
        idx = [FEATURE_NAMES_RICAS.index(n) for n in nomes]
        X = X[:, idx]
    elif X.shape[1] == len(FEATURE_NAMES):
        if args.features == 'ricas':
            raise SystemExit(
                'ERRO: --features ricas exige dataset com as 49 (este tem 32). '
                'Re-gere com gerar_selfplay_dataset.py.')
    else:
        raise SystemExit(f'ERRO: dataset tem {X.shape[1]} features; '
                         f'esperado {len(FEATURE_NAMES)} ou '
                         f'{len(FEATURE_NAMES_RICAS)}. Re-gere.')
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
        return HistGradientBoostingClassifier(
            max_iter=200, learning_rate=0.06, max_depth=4,
            min_samples_leaf=40, l2_regularization=1.0,
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
        m = novo_modelo().fit(X[i_tr], y[i_tr])
        a_tr = roc_auc_score(y[i_tr], m.predict_proba(X[i_tr])[:, 1])
        a_te = roc_auc_score(y[i_te], m.predict_proba(X[i_te])[:, 1])
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
    bundle = {
        'modelo': modelo,
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
