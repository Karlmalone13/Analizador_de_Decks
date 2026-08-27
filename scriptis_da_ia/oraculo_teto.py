"""ORACULO: qual o TETO do `play` que a arquitetura atual consegue expressar?

Pergunta que decide o rumo do projeto (bloco 697): "da pra chegar a 85%
ajustando configuracao, ou o gap e estrutural?". Ninguem tinha medido.

Mede TRES niveis no mesmo turno, diretamente comparaveis entre si:

  1. REAL          -- o conjunto que o motor de fato jogou.
  2. ORACULO-BUSCA -- se o motor escolhesse PERFEITAMENTE dentro do
                      shortlist que ele mesmo montou (`candidates`).
                      Teto do que ajustar a FUNCAO DE VALOR alcanca.
  3. ORACULO-GERACAO -- se escolhesse perfeitamente dentro de TUDO que
                      gerou como acao legal (`all_actions`), ou seja, se
                      o corte do shortlist tambem fosse perfeito.
                      Teto do que ajustar QUALQUER peso alcanca.

O que sobra acima de (3) e o que a arquitetura NAO consegue expressar de
jeito nenhum: a carta nunca virou acao legal. Nenhum tuning alcanca isso.

LIMITE HONESTO do metodo: os niveis 2 e 3 usam CONTINENCIA (o conjunto do
humano esta contido no que estava disponivel?). Ignora se o motor teria
DON/sequencia pra executar todas -- entao sao TETOS OTIMISTAS, o real
alcancavel e menor. Isso favorece a conclusao "da pra chegar la", entao
se mesmo assim o numero for baixo, a conclusao e solida.
"""
import json
import os
import sys
from collections import Counter, defaultdict

import pandas as pd

sys.path.insert(0, '.')
from audit_real_losses import audit_one_game, hist_action_kind
from optcg_engine.decision_engine import load_cards_db
from decision_quality_vs_human import find_all_human_logs

cards_db = load_cards_db('cards_rows.csv')
df_raw = pd.read_csv('decklists_raw.csv')
urls = df_raw.groupby('deck_url')['deck_name'].first()

real = busca = geracao = tot = 0
por_lider = defaultdict(lambda: [0, 0, 0, 0])   # real, busca, geracao, n
falta = Counter()

for pf, human, lider, _g in find_all_human_logs():
    path = os.path.join('logs', pf)
    try:
        raw = json.load(open(path, encoding='utf-8'))
        rep = audit_one_game(path, human, cards_db, df_raw, urls,
                             capture_candidates=True)
    except Exception:
        continue
    if rep.get('error'):
        continue
    rb = {(t['turn'], t['player']): t for t in raw['turns']}

    for t in rep.get('turnos', []):
        if 'decisions' not in t:
            continue
        raw_t = rb.get((t['turn'], human))
        if not raw_t:
            continue
        hum = {a['card'] for a in (raw_t.get('actions') or [])
               if a.get('card') and hist_action_kind(a, cards_db) == 'play'}
        motor = {(r.get('chosen') or {}).get('card', {}).get('code')
                 for r in t['decisions']
                 if (r.get('chosen') or {}).get('kind') == 'play'}
        motor.discard(None)
        if not hum and not motor:
            continue                      # turno sem dado de play

        cand = {(c.get('card') or {}).get('code')
                for r in t['decisions'] for c in (r.get('candidates') or [])
                if c.get('kind') == 'play'}
        todas = {a.get('code')
                 for r in t['decisions'] for a in (r.get('all_actions') or [])
                 if a.get('kind') == 'play'}
        cand.discard(None); todas.discard(None)

        tot += 1
        p = por_lider[t.get('leader') or lider]
        p[3] += 1
        if hum == motor:
            real += 1; p[0] += 1
        if hum <= cand:
            busca += 1; p[1] += 1
        if hum <= todas:
            geracao += 1; p[2] += 1
        else:
            for c in hum - todas:
                falta[c] += 1

print(f'\n{tot} turnos\n')
print(f'  1. REAL (motor escolheu)          {real:5}  {real/tot*100:5.1f}%')
print(f'  2. ORACULO-BUSCA (shortlist)      {busca:5}  {busca/tot*100:5.1f}%')
print(f'  3. ORACULO-GERACAO (tudo gerado)  {geracao:5}  {geracao/tot*100:5.1f}%')
print(f'\n  ganho possivel ajustando VALOR   (2-1): {(busca-real)/tot*100:+5.1f}pp')
print(f'  ganho possivel ajustando CORTE   (3-2): {(geracao-busca)/tot*100:+5.1f}pp')
print(f'  INALCANCAVEL por tuning        (100-3): {(tot-geracao)/tot*100:5.1f}pp')

print('\n--- por lider (>=8 turnos) ---')
print(f'  {"lider":12}{"real":>8}{"busca":>8}{"geracao":>9}{"n":>6}')
for lid, (a, b, c, n) in sorted(por_lider.items(), key=lambda x: -x[1][3]):
    if n >= 8:
        print(f'  {lid:12}{a/n*100:7.1f}%{b/n*100:7.1f}%{c/n*100:8.1f}%{n:6}')

print('\n--- cartas que o humano jogou e NUNCA viraram acao legal ---')
for c, n in falta.most_common(15):
    print(f'  {c}  {n}x')
