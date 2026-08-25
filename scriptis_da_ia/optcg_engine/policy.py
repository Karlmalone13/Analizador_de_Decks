"""
policy.py -- politica de imitacao aprendida dos logs humanos (PASSO 2 do
roteiro do bloco 653), carregada em runtime pelo motor.

FONTE UNICA DE FEATURES
-----------------------
Este modulo e importado TANTO por `treinar_policy.py` (que treina) QUANTO
por `decision_engine.py` (que aplica). A construcao de features vive aqui
e SO aqui -- duplicar a featurizacao entre treino e runtime e a forma
classica de o modelo receber, em producao, um vetor diferente do que viu
no treino, e falhar silenciosamente (nao levanta erro, so decide mal).
E a mesma `REGRA_SEM_DUPLICACAO.md` do projeto aplicada a ML.

DOIS MODELOS, DOIS PROBLEMAS DISTINTOS (medidos 25/08)
------------------------------------------------------
1. `ranker`  -- QUAL carta jogar. Score atual do motor: AUC 0,702;
   modelo com estado: 0,848 (teste, split por partida).
2. `counter` -- QUANTAS cartas jogar no turno. O motor acerta a contagem
   em 58,3% dos turnos; o modelo, 65,6%. Isso e um TETO DURO da metrica
   `play` (que exige o CONJUNTO do turno bater exato): com a contagem
   errada, o conjunto nao bate por melhor que seja a selecao.

DEGRADACAO GRACIOSA: sem o arquivo do modelo, `load_policy()` devolve
None e o motor segue com o comportamento de sempre. O modelo e um
artefato opcional, nao uma dependencia dura.
"""
from __future__ import annotations

import os

MODEL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          'metrics', 'policy_train_report.joblib')

_CACHE: dict = {}


def load_policy(path: str | None = None):
    """Carrega (com cache) o bundle de modelos. None se indisponivel --
    sem sklearn/joblib instalados, ou sem arquivo treinado ainda."""
    p = path or MODEL_PATH
    if p in _CACHE:
        return _CACHE[p]
    bundle = None
    try:
        if os.path.exists(p):
            import joblib
            bundle = joblib.load(p)
    except Exception:
        bundle = None      # nunca derruba o motor por causa do modelo
    _CACHE[p] = bundle
    return bundle


def state_base_features(ctx: dict, leader_code: str, spec: dict) -> list:
    """Parte do vetor que descreve o ESTADO (comum a todas as candidatas
    da mesma decisao). `ctx` e o MESMO dict que
    `_log_turn_planner_decision` grava em `context` -- de proposito: o
    modelo so pode usar o que o motor enxerga na hora de decidir."""
    feat = [float(ctx.get(k) or 0) for k in spec['state_num']]
    for k in spec['state_cat']:
        v = str(ctx.get(k))
        feat += [1.0 if v == opt else 0.0 for opt in spec['cats'][k]]
    feat += [1.0 if leader_code == L else 0.0 for L in spec['lideres']]
    return feat


def action_features(base: list, kind: str, score: float, info: dict,
                    spec: dict) -> list:
    """Vetor completo de uma CANDIDATA = estado + descricao da acao."""
    feat = list(base)
    feat += [1.0 if kind == k else 0.0 for k in spec['kinds']]
    feat.append(float(score or 0.0))
    feat.append(float(info.get('cost') or 0))
    feat.append(float(info.get('power') or 0) / 1000.0)
    feat.append(float(info.get('counter') or 0) / 1000.0)
    feat.append(1.0 if info.get('has_blocker') else 0.0)
    feat.append(1.0 if info.get('has_rush') else 0.0)
    feat.append(1.0 if info.get('has_trigger') else 0.0)
    return feat


def count_features(base: list, custos_play: list, don_available: float) -> list:
    """Vetor do modelo de CONTAGEM = estado + composicao de custos da mao.

    Sem a composicao o modelo so via o TAMANHO da mao e ficava cego
    (60,7%, quase empatado com os 58,3% do motor); com ela vai a 65,6%.
    `cabem` (quantas cartas cabem no DON pegando das mais baratas pras
    mais caras) e o teto FISICO de quantas cartas o turno comporta."""
    custos = sorted(float(c or 0) for c in custos_play)
    don = float(don_available or 0)
    cabem = 0
    acc = 0.0
    for cst in custos:
        if acc + cst <= don:
            acc += cst
            cabem += 1
        else:
            break
    return list(base) + [
        float(len(custos)),
        float(cabem),
        custos[0] if custos else 0.0,
        custos[-1] if custos else 0.0,
        (sum(custos) / len(custos)) if custos else 0.0,
        don - acc,
    ]
