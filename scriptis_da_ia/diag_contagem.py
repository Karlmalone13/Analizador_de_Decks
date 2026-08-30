# -*- coding: utf-8 -*-
"""QUANTAS acoes o motor faz por turno, contra o humano (bloco 741).

Contagem e 39,2pp da perda de sequenciamento (bloco 734) -- a maior
fatia isolada. Mas TODOS os numeros de contagem do projeto (blocos 695 e
734) foram medidos no corpus ANTES do conserto de regua do bloco 739,
que descartava o ultimo turno de toda partida e apagava **24,6% das
anexacoes de DON e 15,2% dos ataques DO HUMANO**.

Como o que faltava era do lado humano, todo excesso do motor estava
INFLADO por construcao. Este script remede contra a regua corrigida,
separando o que antes vinha junto:

  - vies (media por turno) x dispersao (acerto exato por turno);
  - por TIPO de acao, nao so no agregado;
  - a distribuicao do erro (faz +1? +2? -1?), nao so a media.

So MEDE -- nao altera o motor.
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

TIPOS = ('play', 'activate', 'attach_don', 'attack')


def main(max_turnos=400):
    db = load_cards_db('cards_rows.csv')
    df = pd.read_csv('decklists_raw.csv')
    urls = df.groupby('deck_url')['deck_name'].first()

    def hk(a):
        t = a.get('type')
        return t if t in ('attack', 'attach_don') else hist_action_kind(a, db)

    n = 0
    soma_h = Counter()
    soma_m = Counter()
    exato_total = 0
    exato_por_tipo = Counter()
    erro_total = Counter()          # (motor - humano) no TOTAL de acoes
    erro_por_tipo = {t: Counter() for t in TIPOS}

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
            sh = [k for k in (hk(a) for a in (raw_t.get('actions') or [])) if k]
            sm = list(t.get('seq_kinds') or [])
            if not sm:
                sm = [k for k in ((r.get('chosen') or {}).get('kind')
                                  for r in t['decisions'])
                      if k in TIPOS]
            if len(sh) < 2 and len(sm) < 2:
                continue
            n += 1
            ch, cm = Counter(sh), Counter(sm)
            for k in TIPOS:
                soma_h[k] += ch[k]
                soma_m[k] += cm[k]
                d = cm[k] - ch[k]
                erro_por_tipo[k][max(-3, min(3, d))] += 1
                if d == 0:
                    exato_por_tipo[k] += 1
            dt = len(sm) - len(sh)
            erro_total[max(-3, min(3, dt))] += 1
            if dt == 0:
                exato_total += 1

    print(f'{n} turnos pareados\n')
    print('MEDIA DE ACOES POR TURNO')
    print(f'  {"tipo":12s} {"humano":>7s} {"motor":>7s} {"vies":>7s}'
          f'   {"acerto EXATO no turno":>22s}')
    for k in TIPOS:
        h, m = soma_h[k] / n, soma_m[k] / n
        print(f'  {k:12s} {h:7.2f} {m:7.2f} {m - h:+7.2f}'
              f'   {exato_por_tipo[k] / n * 100:21.1f}%')
    th, tm = sum(soma_h.values()) / n, sum(soma_m.values()) / n
    print(f'  {"TOTAL":12s} {th:7.2f} {tm:7.2f} {tm - th:+7.2f}'
          f'   {exato_total / n * 100:21.1f}%')

    def hist(c, titulo):
        print(f'\n{titulo}')
        for d in range(-3, 4):
            v = c.get(d, 0)
            rot = f'{d:+d}' if d not in (-3, 3) else (f'{d:+d} ou mais'
                                                      if d > 0 else f'{d:+d} ou menos')
            barra = '#' * int(v / max(1, n) * 60)
            print(f'  {rot:>12s} {v / max(n, 1) * 100:5.1f}%  {barra}')

    hist(erro_total, 'DISTRIBUICAO DO ERRO DE CONTAGEM (motor - humano), TOTAL')
    for k in TIPOS:
        hist(erro_por_tipo[k], f'  erro de contagem em `{k}`')


if __name__ == '__main__':
    main()
