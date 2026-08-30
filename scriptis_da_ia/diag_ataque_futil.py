# -*- coding: utf-8 -*-
"""Os ataques a MAIS do motor sao FUTEIS ou LUCRATIVOS? (bloco 742)

O bloco 741 mediu, contra a regua corrigida, que o maior vies de
contagem e `attack`: motor 1,98 por turno x humano 1,66 (+0,32), e
ASSIMETRICO -- 33,2% dos turnos com ataque a mais contra 9,2% a menos.
A causa ficou NAO identificada (a hipotese do blocker foi refutada).

Esta e a pergunta que parte o espaco em dois:

  FUTEIS (bloqueados / counterados / 0 de dano)
      -> o motor erra a previsao de defesa do oponente.
         Alvo: modelo de oponente / avaliacao de counter.

  LUCRATIVOS (conectam e tiram vida)
      -> o humano recusa ataque que COMPENSA, por uma razao que o motor
         nao modela (guardar board, nao entregar trigger, montar o turno
         letal). Alvo: outro completamente.

Depende do `kind: attack_outcome` no decision_log (bloco 742) -- ate
entao o motor registrava a DECISAO de atacar e nunca o RESULTADO, que o
log humano sempre teve. So MEDE.
"""
import json
import os
import sys
from collections import Counter

import pandas as pd

sys.path.insert(0, '.')
from audit_real_losses import audit_one_game, hist_action_kind
from decision_quality_vs_human import find_all_human_logs
from optcg_engine.decision_engine import load_cards_db


def pct(a, b):
    return f'{a / b * 100:5.1f}%' if b else '    --'


def main(max_turnos=400):
    db = load_cards_db('cards_rows.csv')
    df = pd.read_csv('decklists_raw.csv')
    urls = df.groupby('deck_url')['deck_name'].first()

    n = 0
    # motor
    m_atk = m_futil = 0
    causa = Counter()
    # motor, separando por POSICAO do ataque dentro do turno
    pos_atk = Counter()
    pos_futil = Counter()
    # humano
    h_atk = h_futil = 0
    # turnos com EXCESSO
    exc_turnos = exc_extra = exc_extra_futil = 0
    exc_dano_extra = 0

    for pf, hum, lider, _g in find_all_human_logs():
        if n >= max_turnos:
            break
        path = os.path.join('logs', pf)
        try:
            raw = json.load(open(path, encoding='utf-8'))
            rep = audit_one_game(path, hum, db, df, urls, capture_candidates=True)
        except Exception:
            continue
        if rep.get('error'):
            continue
        rb = {(t['turn'], t['player']): t for t in raw['turns']}
        for t in rep.get('turnos', []):
            if n >= max_turnos or 'decisions' not in t:
                continue
            raw_t = rb.get((t['turn'], hum))
            if not raw_t:
                continue
            hatk = [a for a in (raw_t.get('actions') or [])
                    if a.get('type') == 'attack']
            matk = list(t.get('attack_outcomes') or [])
            if not hatk and not matk:
                continue
            n += 1

            for a in hatk:
                h_atk += 1
                if not (a.get('damage') or 0):
                    h_futil += 1

            for i, o in enumerate(matk):
                m_atk += 1
                futil = not (o.get('dano') or 0)
                # posicao: 1o, 2o, 3o+ ataque do turno
                chave = min(i + 1, 3)
                pos_atk[chave] += 1
                if futil:
                    m_futil += 1
                    pos_futil[chave] += 1
                    if o.get('blocked_by'):
                        causa['bloqueado'] += 1
                    elif (o.get('counter_add') or 0) > 0:
                        causa['counterado'] += 1
                    else:
                        causa['sem dano (outro)'] += 1

            # turnos em que o motor atacou MAIS
            if len(matk) > len(hatk):
                exc_turnos += 1
                k = len(matk) - len(hatk)
                # os `k` ULTIMOS ataques do turno sao a margem
                margem = matk[-k:]
                exc_extra += k
                for o in margem:
                    d = o.get('dano') or 0
                    exc_dano_extra += d
                    if not d:
                        exc_extra_futil += 1

    print(f'{n} turnos pareados\n')
    print('TAXA DE FUTILIDADE (ataque que NAO tira vida)')
    print(f'  humano  {h_futil:5d} / {h_atk:5d}   {pct(h_futil, h_atk)}')
    print(f'  motor   {m_futil:5d} / {m_atk:5d}   {pct(m_futil, m_atk)}')
    print()
    print('CAUSA da futilidade do motor')
    for k, v in causa.most_common():
        print(f'  {k:20s} {v:5d}   {pct(v, m_futil)} dos futeis')
    print()
    print('FUTILIDADE por POSICAO do ataque no turno (motor)')
    for k in (1, 2, 3):
        rot = f'{k}o ataque' if k < 3 else '3o+ ataque'
        print(f'  {rot:12s} {pos_futil[k]:5d} / {pos_atk[k]:5d}   '
              f'{pct(pos_futil[k], pos_atk[k])}')
    print()
    print('TURNOS EM QUE O MOTOR ATACOU MAIS QUE O HUMANO')
    print(f'  turnos                       {exc_turnos}')
    print(f'  ataques EXCEDENTES           {exc_extra}')
    print(f'  deles, FUTEIS                {exc_extra_futil}   '
          f'{pct(exc_extra_futil, exc_extra)}')
    print(f'  vida tirada pelos excedentes {exc_dano_extra}')


if __name__ == '__main__':
    main()
