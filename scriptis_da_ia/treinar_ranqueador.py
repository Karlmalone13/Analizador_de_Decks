"""FASE 2 do plano do bloco 702: ranqueador APRENDIDO, deck-agnostico.

O PROBLEMA, na sua forma minima
-------------------------------
O oraculo (bloco 697/703) reduziu o gap a isto: **as candidatas certas
ja estao na lista; basta ordena-las**. Um re-ranqueador puro tem teto de
94,6% (`fast_eval.py`) contra os 28,6% de hoje. E problema de
aprendizado supervisionado com rotulo pronto (a escolha do humano).

RESTRICAO INEGOCIAVEL -- "qualquer deck que o usuario montar"
-------------------------------------------------------------
**NENHUM codigo de carta ou de lider entra como feature.** So
PROPRIEDADES (custo, poder, counter, blocker/rush/trigger, tipo, cor,
relacao com o estado). O codigo da carta e usado APENAS pra CONSULTAR
essas propriedades no banco -- nunca como entrada do modelo.

Motivo: com identidade, o modelo memoriza "com o lider X jogue a carta Y"
e quebra no 1o deck novo -- **pior que hoje**, ja que a funcao escrita a
mao e deck-agnostica por construcao.

**A tentativa reprovada do bloco 683 violava isto**: `policy.py:98` tinha
one-hot de LIDER, e o split era por PARTIDA -- com o mesmo lider dos dois
lados, aquela validacao **nunca poderia detectar** falha de
generalizacao pra deck novo. Ver `REPROVADOS.md`.

VALIDACAO: split por LIDER
--------------------------
Treina num conjunto de lideres, valida em lideres que o modelo NUNCA viu.
Mede literalmente "joga um deck pro qual nao foi treinado". O numero que
importa e o da VALIDACAO, nunca o do treino.

LIMITE HERDADO do avaliador rapido (ler antes de comemorar)
------------------------------------------------------------
Offline o estado nao se atualiza conforme o modelo escolhe diferente --
isto E o *distribution shift*. O numero daqui e OTIMISTA e serve pra
FILTRAR hipotese; a decisao final e sempre `decision_quality_full.py`.
"""
from __future__ import annotations

import argparse
import json
import os

import numpy as np
import pandas as pd

from fast_eval import (agrupa_por_turno, avalia, carrega, faz_oraculo,
                       rank_estatico, rank_motor, split_por_lider)

AQUI = os.path.dirname(os.path.abspath(__file__))


def props_das_cartas() -> dict:
    """Propriedades por codigo -- consulta, NAO feature de identidade.

    Usa `load_cards_db`/`get_card_effects` do PROPRIO motor em vez de
    reparsear `cards_rows.csv` (regra do projeto: nao reinventar). A 1a
    versao lia o CSV na mao e quebrou em `card_power` com texto -- o CSV
    tem 803 linhas de carta DON sem poder/custo e ao menos uma anomalia
    de conteudo. O carregador do motor ja normaliza tudo isso, e garante
    que o modelo veja EXATAMENTE as mesmas propriedades que o motor ve.
    """
    from optcg_engine.decision_engine import load_cards_db, get_card_effects
    db = load_cards_db(os.path.join(AQUI, 'cards_rows.csv'))
    out = {}
    for cod, c in db.items():
        gat = set((get_card_effects(cod).get('effects') or
                   get_card_effects(cod) or {}).keys())
        tipo = str(c.get('type') or '').upper()
        out[cod] = {
            'cost': float(c.get('cost') or 0),
            'power': float(c.get('power') or 0) / 1000.0,
            'counter': float(c.get('counter') or 0) / 1000.0,
            'is_char': 1.0 if tipo == 'CHARACTER' else 0.0,
            'is_event': 1.0 if tipo == 'EVENT' else 0.0,
            'is_stage': 1.0 if tipo == 'STAGE' else 0.0,
            'blocker': 1.0 if c.get('has_blocker') else 0.0,
            'rush': 1.0 if c.get('has_rush') else 0.0,
            'trigger': 1.0 if c.get('has_trigger') else 0.0,
            'banish': 1.0 if c.get('has_banish') else 0.0,
            'double_attack': 1.0 if c.get('has_double_attack') else 0.0,
            'n_gatilhos': float(len(gat)),
            'tem_on_play': 1.0 if 'on_play' in gat else 0.0,
            'tem_activate': 1.0 if 'activate_main' in gat else 0.0,
            'tem_when_atk': 1.0 if 'when_attacking' in gat else 0.0,
            'tem_counter_ef': 1.0 if 'counter' in gat else 0.0,
        }
    return out


PROP_KEYS = ['cost', 'power', 'counter', 'is_char', 'is_event', 'is_stage',
             'blocker', 'rush', 'trigger', 'banish', 'double_attack',
             'n_gatilhos', 'tem_on_play', 'tem_activate', 'tem_when_atk',
             'tem_counter_ef']
ESTADO_NUM = ['life', 'opp_life', 'hand', 'opp_hand', 'field', 'opp_field',
              'don_available', 'don_rested', 'opp_lethal_threat',
              'n_candidates', 'hand_cost_min', 'hand_cost_max',
              'hand_cost_avg', 'hand_pagaveis', 'hand_counter_total',
              'hand_blockers', 'hand_triggers', 'hand_power_max',
              'hand_eventos', 'board_power_total', 'opp_board_power_total']
CATS = {'priority': None, 'posture': None, 'phase': None, 'profile': None}
KINDS = ['play', 'activate', 'attach_don', 'attack']


def descobre_categorias(linhas):
    for k in CATS:
        CATS[k] = sorted({str((d.get('state_cat') or {}).get(k)) for d in linhas})


def vetor(d, cand, props) -> list:
    st = d.get('state') or {}
    sc = d.get('state_cat') or {}
    f = [float(st.get(k) or 0) for k in ESTADO_NUM]
    for k, opts in CATS.items():
        v = str(sc.get(k))
        f += [1.0 if v == o else 0.0 for o in opts]
    f += [1.0 if cand['kind'] == k else 0.0 for k in KINDS]
    f.append(float(cand.get('score') or 0.0) / 100.0)
    p = props.get(cand.get('code')) or {}
    f += [float(p.get(k, 0.0)) for k in PROP_KEYS]
    # relacao acao x estado (nao e identidade: e interacao de propriedades)
    don = float(st.get('don_available') or 0)
    f.append(1.0 if p.get('cost', 99) <= don else 0.0)
    f.append(don - float(p.get('cost', 0)))
    return f


def monta(turnos, props, so_play=True):
    """Monta o dataset. `so_play=True` restringe as candidatas a `play`.

    POR QUE (achado da 1a iteracao, bloco 704): treinando sobre TODAS as
    candidatas, **51,1% ficam rotuladas positivas** -- o rotulo e "esta
    acao esta no CONJUNTO do turno do humano", nao "o humano escolheu
    esta acao NESTA decisao" (limitacao honesta ja declarada em
    `build_policy_dataset.py`: o log humano nao da alinhamento
    decisao-a-decisao). Com metade positiva o argmax nao discrimina, e o
    modelo escolhia `attach_don`/`attack` deixando o conjunto de `play`
    VAZIO -- resultado 20,3% na validacao, PIOR que o baseline (21,3%) e
    pior que ele proprio no treino (20,8% x 30,7%).

    O oraculo usa os MESMOS rotulos e chega a 94,6%: a informacao basta,
    o que estava errado era a regra de decisao. Restringir a `play`
    transforma o problema no que ele de fato e -- "esta carta esta entre
    as que o humano jogou neste turno?" -- e deixa as demais decisoes com
    o motor, isolando a ordenacao.
    """
    X, y, grupo = [], [], []
    for t in turnos:
        for d in t['decisoes']:
            for c in d['candidates']:
                if so_play and c['kind'] != 'play':
                    continue
                X.append(vetor(d, c, props))
                y.append(1 if c.get('humano_fez') else 0)
                grupo.append(t['leader'])
    return np.array(X, dtype=np.float32), np.array(y), grupo


def faz_rank_modelo(modelo, props, limiar=0.5):
    """Politica: joga a melhor candidata `play` se a confianca passar do
    limiar; caso contrario faz o que o motor faria. Nao repete carta ja
    jogada no turno (mesmo cuidado do oraculo, bloco 703)."""
    ja, ultimo = set(), [None]

    def rank(cands, d):
        chave = (d['game_id'], d['turn'])
        if ultimo[0] != chave:
            ja.clear()
            ultimo[0] = chave
        plays = [c for c in cands
                 if c['kind'] == 'play' and c.get('code') not in ja]
        if plays:
            V = np.array([vetor(d, c, props) for c in plays], dtype=np.float32)
            s = modelo.predict_proba(V)[:, 1]
            i = int(np.argmax(s))
            if s[i] >= limiar:
                ja.add(plays[i]['code'])
                return plays[i]
        return rank_motor(cands, d)
    return rank


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--frac-val', type=float, default=0.3)
    ap.add_argument('--seed', type=int, default=13)
    a = ap.parse_args()

    linhas = carrega()
    descobre_categorias(linhas)
    props = props_das_cartas()
    turnos = agrupa_por_turno(linhas)
    tr, va, lid_val = split_por_lider(turnos, a.frac_val, a.seed)

    Xtr, ytr, _ = monta(tr, props)
    print(f'treino: {len(tr)} turnos, {len(Xtr)} candidatas, '
          f'{ytr.sum()} positivas ({ytr.mean()*100:.1f}%)')
    print(f'validacao: {len(va)} turnos em {len(lid_val)} lideres NUNCA vistos')
    print(f'  {sorted(lid_val)}')
    print(f'  features: {Xtr.shape[1]} (ZERO de identidade de carta/lider)')

    from sklearn.ensemble import HistGradientBoostingClassifier
    m = HistGradientBoostingClassifier(
        max_iter=300, learning_rate=0.06, max_depth=6,
        l2_regularization=1.0, random_state=a.seed)
    m.fit(Xtr, ytr)

    print('\n--- varredura de limiar (o avaliador rapido paga aqui) ---')
    print(f'  {"limiar":>8}{"treino":>10}{"VALIDACAO":>12}')
    melhor = (None, -1)
    for lim in (0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90):
        vtr = avalia(tr, faz_rank_modelo(m, props, lim))['play']
        vva = avalia(va, faz_rank_modelo(m, props, lim))['play']
        print(f'  {lim:8.2f}{vtr*100:9.1f}%{vva*100:11.1f}%')
        if vva > melhor[1]:
            melhor = (lim, vva)
    print(f'  melhor limiar na validacao: {melhor[0]:.2f}')
    rank_m = faz_rank_modelo(m, props, melhor[0])
    print('\n' + '=' * 62)
    print(f'{"ranqueador":28}{"TREINO":>10}{"VALIDACAO":>14}')
    print('=' * 62)
    for nome, fn in (('motor real (baseline)', rank_motor),
                     ('score estatico', rank_estatico),
                     ('MODELO aprendido', rank_m),
                     ('oraculo (teto)', None)):
        f_tr = faz_oraculo() if fn is None else fn
        f_va = faz_oraculo() if fn is None else fn
        r1 = avalia(tr, f_tr)
        r2 = avalia(va, f_va)
        print(f'{nome:28}{r1["play"]*100:9.1f}%{r2["play"]*100:13.1f}%')

    r = avalia(va, rank_m)
    b = avalia(va, rank_motor)
    print(f'\n--- POR LIDER na validacao (decks nunca vistos) ---')
    print(f'  {"lider":12}{"baseline":>10}{"modelo":>9}{"delta":>9}{"n":>6}')
    for lid in sorted(r['por_lider']):
        tx, n = r['por_lider'][lid]
        bx = b['por_lider'].get(lid, (0, 0))[0]
        print(f'  {lid:12}{bx*100:9.1f}%{tx*100:8.1f}%{(tx-bx)*100:+8.1f}pp{n:6}')


if __name__ == '__main__':
    main()
