"""
treinar_policy.py -- treina a POLITICA de imitacao (PASSO 2 do roteiro do
bloco 653) sobre o dataset de `build_policy_dataset.py`.

A PERGUNTA QUE ESTE SCRIPT RESPONDE
-----------------------------------
"Um modelo que olha o ESTADO consegue ranquear as acoes do humano melhor
que o score estatico que o motor usa hoje?"

E a pergunta certa porque as 7+ tentativas anteriores de imitacao
falharam por usar sinal SEM estado (bloco 653). Se um modelo COM estado
tambem nao bater o score atual, a hipotese do roteiro cai e isso precisa
ser sabido -- e um achado negativo valioso, nao um fracasso a esconder.

DISCIPLINA DE MEDICAO (nao negociavel neste projeto)
----------------------------------------------------
- **Split por PARTIDA** (`game_id`), nunca por decisao: decisoes do mesmo
  jogo sao fortemente correlacionadas (mesma mao, mesmo board evoluindo);
  split por decisao infla o resultado de teste de forma grosseira.
- **Baseline no MESMO split**: o score estatico do motor ranqueando as
  mesmas candidatas. Sem isso, um numero de teste alto nao diz se o
  modelo e melhor que o que ja existe.
- O risco de overfitting nos MESMOS logs que tambem validam
  `decision_quality_full.py` ja foi levantado e aceito pelo usuario como
  conhecido (nota do topo do HANDOFF, 22/08). Por isso o numero que este
  script reporta como resultado e SEMPRE o de TESTE.

METRICA PRINCIPAL: `play top-1`
-------------------------------
Entre as candidatas `play` de cada decisao, a de maior score do ranqueador
e uma carta que o humano JOGOU naquele turno? E o proxy mais proximo da
metrica `play` de `decision_quality_full.py` (que o usuario quer levar de
~28% pra 85/90%), medivel sem rodar a partida inteira -- entao serve pra
iterar rapido antes de gastar uma medicao completa.

LIMITACAO herdada do dataset (declarada, nao contornada): o rotulo e
"esta acao esta no CONJUNTO que o humano fez neste turno", nao alinhamento
decisao-a-decisao. Um `play top-1` alto aqui NAO garante o mesmo numero em
`decision_quality_full.py` -- garante que o ranqueador aponta pra carta
certa, que e condicao necessaria, nao suficiente.

Uso:
    python treinar_policy.py [--dataset metrics/policy_dataset.jsonl]
                             [--out metrics/policy_train_report.json] [--seed 42]
"""
import argparse
import json
import os
from collections import defaultdict

import joblib
import numpy as np

from optcg_engine.decision_engine import load_cards_db
from optcg_engine.policy import (state_base_features, action_features,
                                count_features)

STATE_NUM = ['life', 'opp_life', 'hand', 'opp_hand', 'field', 'opp_field',
             'don_available', 'don_rested', 'opp_lethal_threat', 'n_candidates']
STATE_CAT = ['priority', 'posture', 'phase', 'profile']
KINDS = ['play', 'attack', 'activate', 'attach_don', 'pass']


def _carregar(path):
    return [json.loads(l) for l in open(path, encoding='utf-8')]


def _vocab(rows):
    cats = {k: sorted({str((r.get('state_cat') or {}).get(k)) for r in rows})
            for k in STATE_CAT}
    lideres = sorted({r['leader'] for r in rows})
    return cats, lideres


def _featurize(rows, cats, lideres, cards_db):
    """Uma linha por PAR (decisao, candidata). Features = estado + acao."""
    X, y, grupos, meta = [], [], [], []
    for gi, r in enumerate(rows):
        st = r.get('state') or {}
        stc = r.get('state_cat') or {}
        # FONTE UNICA: mesma featurizacao que o motor usa em runtime
        # (optcg_engine/policy.py) -- ver REGRA_SEM_DUPLICACAO aplicada a ML.
        spec = {'state_num': STATE_NUM, 'state_cat': STATE_CAT,
                'cats': cats, 'lideres': lideres, 'kinds': KINDS}
        ctx = dict(st)
        ctx.update(stc)
        base = state_base_features(ctx, r['leader'], spec)

        for c in r['candidates']:
            info = cards_db.get(c.get('code')) or {}
            feat = action_features(base, c.get('kind'), c.get('score'), info, spec)
            X.append(feat)
            y.append(1 if c.get('humano_fez') else 0)
            grupos.append(gi)
            meta.append({'kind': c.get('kind'), 'code': c.get('code'),
                         'score': c.get('score'), 'game_id': r['game_id'],
                         'leader': r['leader']})
    return np.array(X, dtype=np.float32), np.array(y), np.array(grupos), meta


def _play_top1(scores, y, grupos, meta):
    """Entre as candidatas `play` de cada decisao, a de MAIOR score do
    ranqueador e uma que o humano jogou? Devolve (acertos, decisoes)."""
    por_dec = defaultdict(list)
    for i, g in enumerate(grupos):
        if meta[i]['kind'] == 'play':
            por_dec[g].append(i)
    ok = tot = 0
    for g, idxs in por_dec.items():
        if not any(y[i] for i in idxs):
            continue   # humano nao jogou nada elegivel aqui -- nada a acertar
        tot += 1
        melhor = max(idxs, key=lambda i: scores[i])
        ok += int(y[melhor] == 1)
    return ok, tot



def _featurize_count(rows, cats, lideres, cards_db):
    """Dataset do modelo de CONTAGEM: uma linha por TURNO.

    Alvo: QUANTAS cartas o humano jogou naquele turno (0,1,2,3+). E o
    segundo gargalo, medido 25/08 e ate entao nunca atacado: o motor joga
    o MESMO NUMERO de cartas que o humano em apenas **52,7%** dos turnos
    (25,0% joga mais, 22,3% menos). Como a metrica `play` exige que o
    CONJUNTO bata exato, isso e um TETO DURO -- mesmo com selecao de
    carta perfeita, o conjunto nao pode bater em mais de 52,7% dos
    turnos. Ranquear melhor QUAL carta (o outro modelo) nao resolve
    isto; sao dois problemas distintos.

    Features: o estado no INICIO do turno (1a decisao) + lider. Nao usa
    nada que dependa do que o motor decidiu depois -- senao a politica
    seria inaplicavel em producao, onde a contagem precisa ser decidida
    ANTES de jogar.
    """
    por_turno = defaultdict(list)
    for r in rows:
        por_turno[(r['game_id'], r['turn'])].append(r)

    X, y, jogos = [], [], []
    for (gid, _turno), decs in por_turno.items():
        primeiro = decs[0]
        st = primeiro.get('state') or {}
        stc = primeiro.get('state_cat') or {}
        spec = {'state_num': STATE_NUM, 'state_cat': STATE_CAT,
                'cats': cats, 'lideres': lideres, 'kinds': KINDS}
        ctx = dict(st)
        ctx.update(stc)
        base = state_base_features(ctx, primeiro['leader'], spec)

        # Features de COMPOSICAO DA MAO (achado 25/08): sem elas o modelo
        # so via o TAMANHO da mao, e quantas cartas cabem no turno depende
        # dos CUSTOS delas -- o modelo ficava praticamente cego (60,7% x
        # 58,3% do motor, +2,4pp). As candidatas `play` da 1a decisao SAO
        # as cartas jogaveis com seus custos, e estao disponiveis no motor
        # em runtime no mesmo ponto -- entao a politica continua aplicavel.
        custos = [float((cards_db.get(c.get('code')) or {}).get('cost') or 0)
                  for c in primeiro['candidates'] if c['kind'] == 'play']
        feat = count_features(base, custos, st.get('don_available'))

        humano = {c['code'] for d in decs for c in d['candidates']
                  if c['kind'] == 'play' and c['humano_fez']}
        motor = sum(1 for d in decs if d['motor_escolheu']['kind'] == 'play')
        X.append(feat)
        y.append(min(len(humano), 3))     # 3+ agrupado (cauda rala)
        jogos.append((gid, min(motor, 3)))
    return np.array(X, dtype=np.float32), np.array(y), jogos


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dataset', default='metrics/policy_dataset.jsonl')
    ap.add_argument('--out', default='metrics/policy_train_report.json')
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--test-frac', type=float, default=0.25)
    args = ap.parse_args()

    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import roc_auc_score

    rows = _carregar(args.dataset)
    cards_db = load_cards_db('cards_rows.csv')
    cats, lideres = _vocab(rows)
    X, y, grupos, meta = _featurize(rows, cats, lideres, cards_db)

    # SPLIT POR PARTIDA -- ver docstring. Decisao do mesmo jogo NUNCA cai
    # dos dois lados.
    jogos = sorted({m['game_id'] for m in meta})
    rng = np.random.default_rng(args.seed)
    rng.shuffle(jogos)
    n_test = max(1, int(len(jogos) * args.test_frac))
    jogos_test = set(jogos[:n_test])
    is_test = np.array([m['game_id'] in jogos_test for m in meta])

    print(f'{len(rows)} decisoes | {len(jogos)} partidas | {X.shape[0]} pares '
          f'| {X.shape[1]} features')
    print(f'split por PARTIDA: {len(jogos)-n_test} treino / {n_test} teste '
          f'({is_test.sum()} pares de teste)')

    modelo = HistGradientBoostingClassifier(
        max_iter=300, learning_rate=0.08, max_depth=6,
        random_state=args.seed)
    modelo.fit(X[~is_test], y[~is_test])

    p_test = modelo.predict_proba(X[is_test])[:, 1]
    p_train = modelo.predict_proba(X[~is_test])[:, 1]

    y_test, g_test = y[is_test], grupos[is_test]
    m_test = [m for m, t in zip(meta, is_test) if t]
    s_test = np.array([m['score'] or 0.0 for m in m_test])

    auc_test = roc_auc_score(y_test, p_test)
    auc_train = roc_auc_score(y[~is_test], p_train)
    auc_score = roc_auc_score(y_test, s_test)

    ok_mod, tot = _play_top1(p_test, y_test, g_test, m_test)
    ok_base, tot_b = _play_top1(s_test, y_test, g_test, m_test)

    print()
    print('=' * 62)
    print('RESULTADO (numeros de TESTE -- partidas nunca vistas no treino)')
    print('=' * 62)
    print(f'AUC par-a-par   modelo: {auc_test:.3f}   '
          f'(treino {auc_train:.3f} -- gap grande = overfit)')
    print(f'AUC par-a-par   score estatico do motor (baseline): {auc_score:.3f}')
    print()
    print(f'play top-1  MODELO           : {ok_mod}/{tot} ({ok_mod/max(tot,1)*100:.1f}%)')
    print(f'play top-1  SCORE (hoje)     : {ok_base}/{tot_b} ({ok_base/max(tot_b,1)*100:.1f}%)')
    delta = (ok_mod - ok_base) / max(tot, 1) * 100
    print(f'delta                        : {delta:+.1f}pp')


    # ── MODELO DE CONTAGEM (quantas cartas jogar) ────────────────────────
    Xc, yc, jogos_c = _featurize_count(rows, cats, lideres, cards_db)
    is_test_c = np.array([g in jogos_test for g, _ in jogos_c])
    modelo_count = HistGradientBoostingClassifier(
        max_iter=200, learning_rate=0.08, max_depth=4, l2_regularization=1.0,
        random_state=args.seed)
    modelo_count.fit(Xc[~is_test_c], yc[~is_test_c])
    pred_c = modelo_count.predict(Xc[is_test_c])
    real_c = yc[is_test_c]
    motor_c = np.array([m for _, m in jogos_c])[is_test_c]
    acc_modelo = float((pred_c == real_c).mean())
    acc_motor = float((motor_c == real_c).mean())

    print()
    print(f'CONTAGEM (quantas cartas jogar) -- {len(real_c)} turnos de teste')
    print(f'  acerto MODELO : {acc_modelo*100:.1f}%')
    print(f'  acerto MOTOR  : {acc_motor*100:.1f}%   (o teto duro de hoje)')
    print(f'  delta         : {(acc_modelo-acc_motor)*100:+.1f}pp')

    # ── SERIALIZACAO (o motor precisa carregar isto em runtime) ──────────
    modelo_path = args.out.replace('.json', '.joblib')
    joblib.dump({
        'ranker': modelo, 'counter': modelo_count,
        'cats': cats, 'lideres': lideres,
        'state_num': STATE_NUM, 'state_cat': STATE_CAT, 'kinds': KINDS,
    }, modelo_path)
    print(f'\nmodelos serializados em {modelo_path}')

    os.makedirs(os.path.dirname(args.out) or '.', exist_ok=True)
    json.dump({
        'auc_test': auc_test, 'auc_train': auc_train, 'auc_baseline': auc_score,
        'play_top1_modelo': [ok_mod, tot],
        'play_top1_score': [ok_base, tot_b],
        'count_acc_modelo': acc_modelo, 'count_acc_motor': acc_motor,
        'n_decisoes': len(rows), 'n_jogos': len(jogos), 'seed': args.seed,
    }, open(args.out, 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
    print(f'\nresumo salvo em {args.out}')


if __name__ == '__main__':
    main()
