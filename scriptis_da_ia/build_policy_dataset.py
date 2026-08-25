"""
build_policy_dataset.py -- monta o dataset ROTULADO pra imitacao-por-
POLITICA (PASSO 2 do roteiro do bloco 653).

CONTEXTO / POR QUE ESTE ARQUIVO EXISTE
--------------------------------------
As 7+ tentativas anteriores de fazer o motor jogar como o humano (blocos
641-649, 663, 676, 677) falharam TODAS pela mesma causa, ja diagnosticada
no bloco 653: usam uma estatistica MARGINAL e SEM CONTEXTO ("quantas
vezes este lider fez este token") e a injetam como BONUS dentro de uma
funcao de valor que ja tem termos fortes de dano/board. Sinal sem estado
nao discrimina decisao que DEPENDE do estado.

O bloco 653 tambem mediu os 2 fatos que tornam a imitacao por POLITICA
viavel (e que separam este projeto de "imitar uma populacao diversa"):
  (a) o alvo e DETERMINISTICO -- mesmo jogador, mesma mao, mesmo board:
      mesmo conjunto de cartas jogado em 76 de 76 casos;
  (b) o banco e essencialmente UM JOGADOR (70,9% dos turnos).
Ou seja: e um problema de aprendizado supervisionado sobre uma politica
unica e consistente, nao de modelar diversidade humana.

O QUE FALTAVA E AGORA EXISTE
----------------------------
Pra treinar uma politica e preciso, POR DECISAO: o conjunto de acoes
LEGAIS naquele instante + qual delas o humano escolheu. O conjunto de
acoes legais so passou a ser observavel no bloco 676, quando
`_log_turn_planner_decision` ganhou o campo `all_actions` (lista COMPLETA
de acoes geradas, antes de qualquer corte de shortlist). Antes disso o
log so guardava os top-8 candidatos, o que tornava impossivel montar o
alvo de forma honesta.

O QUE ESTE SCRIPT PRODUZ
------------------------
Um JSONL, uma linha por DECISAO, com:
  - `features`: estado do jogo no instante da decisao (do `context` do
    decision_log, que o motor ja grava) + features da ACAO candidata;
  - `candidates`: as acoes legais (kind + codigo + score estatico);
  - `label`: qual acao o HUMANO tomou naquele ponto (ou 'pass'/None
    quando o humano nao tomou mais nenhuma acao daquele tipo no turno).

LIMITACAO HONESTA, declarada de saida: o log do humano da a SEQUENCIA de
acoes do turno, nao um alinhamento decisao-a-decisao com as decisoes que
o motor simulado tomou (o motor pode divergir na 1a decisao e a partir
dai estar num estado diferente do humano). Por isso o rotulo aqui e
"esta acao esta no CONJUNTO de acoes que o humano tomou neste turno" --
uma aproximacao deliberada, e a mesma granularidade que
`decision_quality_full.py` ja usa pra medir `play` (conjunto de cartas
jogadas no turno). Nao inventa alinhamento que o dado nao tem.

SPLIT: por PARTIDA (`game_id`), nunca por decisao -- decisoes do mesmo
jogo sao correlacionadas, e o risco de overfitting nos MESMOS logs que
tambem validam `decision_quality_full.py` ja foi levantado e aceito pelo
usuario (nota do topo do HANDOFF, 22/08) como conhecido, o que exige o
split ser honesto.

Uso:
    python build_policy_dataset.py --out metrics/policy_dataset.jsonl [--limit N]
"""
import argparse
import json
import os

import pandas as pd

from audit_real_losses import audit_one_game, hist_action_kind
from optcg_engine.decision_engine import load_cards_db

LOGS_DIR = 'logs'
INDEX_PATH = os.path.join(LOGS_DIR, 'index.json')

# Campos do `context` do decision_log que descrevem o ESTADO (nao a acao).
# Sao os mesmos que o motor ja grava por decisao -- nao inventa feature
# nova aqui, pra que o modelo treine exatamente sobre o que o motor
# enxerga na hora de decidir (se treinasse sobre mais que isso, nao
# daria pra aplicar a politica em producao).
CONTEXT_FEATURES = [
    'life', 'opp_life', 'hand', 'opp_hand', 'field', 'opp_field',
    'don_available', 'don_rested', 'opp_lethal_threat', 'n_candidates',
    # bloco 682: COMPOSICAO da mao/campo, nao so contagens -- ver
    # `_decision_context` em decision_engine.py.
    'hand_cost_min', 'hand_cost_max', 'hand_cost_avg', 'hand_pagaveis',
    'hand_counter_total', 'hand_blockers', 'hand_triggers',
    'hand_power_max', 'hand_eventos',
    'board_power_total', 'opp_board_power_total',
]
CONTEXT_CATEGORICAL = ['priority', 'posture', 'phase', 'profile']


def _human_actions_by_kind(turn, cards_db):
    """Conjunto de (kind, codigo) que o humano REALMENTE fez neste turno.

    Usa `hist_action_kind` -- o MESMO classificador de
    `decision_quality_full.py`/`audit_real_losses.py`, nao um segundo
    criterio (o log rotula EVENT jogado como 'activate', Stage ativada
    tambem, etc; ja houve bug real por usar `type` cru, bloco 650)."""
    out = set()
    for a in turn.get('actions', []) or []:
        code = a.get('card') or a.get('attacker_code') or a.get('to')
        if not code:
            continue
        t = a.get('type')
        if t == 'attack':
            out.add(('attack', a.get('attacker_code')))
        elif t == 'attach_don':
            out.add(('attach_don', a.get('to')))
        else:
            out.add((hist_action_kind(a, cards_db), code))
    return out


def _jobs(leader_filter=None):
    idx = json.load(open(INDEX_PATH, encoding='utf-8'))
    jobs = []
    for e in idx:
        p1, p2 = e.get('p1', {}), e.get('p2', {})
        if not p1.get('leader_code') or not p2.get('leader_code'):
            continue
        gid = e.get('id') or e.get('parsed_file', '?')
        bs = e.get('bot_side')
        if bs:
            hk = 'p2' if bs == 'p1' else 'p1'
            nome = (p2 if bs == 'p1' else p1).get('name')
            lider = e[hk]['leader_code']
            if nome and (not leader_filter or lider == leader_filter):
                jobs.append((e['parsed_file'], nome, lider, gid))
        else:
            for k in ('p1', 'p2'):
                side = e.get(k, {})
                if not side.get('name') or not side.get('leader_code'):
                    continue
                if leader_filter and side['leader_code'] != leader_filter:
                    continue
                jobs.append((e['parsed_file'], side['name'],
                             side['leader_code'], f'{gid}_{k}'))
    return jobs


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default='metrics/policy_dataset.jsonl')
    ap.add_argument('--leader')
    ap.add_argument('--limit', type=int, help='max de partidas (debug)')
    args = ap.parse_args()

    cards_db = load_cards_db('cards_rows.csv')
    df_raw = pd.read_csv('decklists_raw.csv')
    urls = df_raw.groupby('deck_url')['deck_name'].first()

    jobs = _jobs(args.leader)
    if args.limit:
        jobs = jobs[:args.limit]
    print(f'{len(jobs)} partida(s)/lado(s) a processar...')

    os.makedirs(os.path.dirname(args.out) or '.', exist_ok=True)
    n_dec = n_pos = 0
    jogos_ok = 0
    raw_cache = {}

    with open(args.out, 'w', encoding='utf-8') as fh:
        for parsed_file, human, lider, gid in jobs:
            path = os.path.join(LOGS_DIR, parsed_file)
            if path not in raw_cache:
                try:
                    raw_cache[path] = json.load(open(path, encoding='utf-8'))
                except Exception:
                    continue
            raw = raw_cache[path]
            try:
                rep = audit_one_game(path, human, cards_db, df_raw, urls,
                                     capture_candidates=True)
            except Exception:
                continue
            if rep.get('error'):
                continue
            jogos_ok += 1
            rb = {(t['turn'], t['player']): t for t in raw['turns']}

            for t in rep.get('turnos', []):
                if 'decisions' not in t:
                    continue
                raw_t = rb.get((t['turn'], human))
                if not raw_t:
                    continue
                humano = _human_actions_by_kind(raw_t, cards_db)

                for rec in t['decisions']:
                    ctx = rec.get('context') or {}
                    acoes = rec.get('all_actions') or []
                    if not acoes:
                        continue
                    escolhida = rec.get('chosen') or {}
                    cands = []
                    for a in acoes:
                        par = (a.get('kind'), a.get('code'))
                        cands.append({
                            'kind': a.get('kind'),
                            'code': a.get('code'),
                            'score': a.get('score'),
                            # ALVO: o humano fez esta (kind, codigo) neste turno?
                            'humano_fez': par in humano,
                        })
                    n_pos += sum(1 for c in cands if c['humano_fez'])
                    fh.write(json.dumps({
                        'game_id': gid,
                        'leader': lider,
                        'turn': t['turn'],
                        'state': {k: ctx.get(k) for k in CONTEXT_FEATURES},
                        'state_cat': {k: ctx.get(k) for k in CONTEXT_CATEGORICAL},
                        'candidates': cands,
                        'motor_escolheu': {
                            'kind': escolhida.get('kind'),
                            'code': (escolhida.get('card') or {}).get('code'),
                        },
                    }, ensure_ascii=False) + '\n')
                    n_dec += 1

    print(f'{jogos_ok} partidas processadas')
    print(f'{n_dec} decisoes gravadas em {args.out}')
    print(f'{n_pos} pares (acao candidata, humano_fez=True) -- exemplos positivos')


if __name__ == '__main__':
    main()
