"""Por que a candidata CERTA perde, quando ela esta no shortlist?

O oraculo (bloco 697) mostrou que em 80,3% dos turnos a carta do humano
esta no shortlist e MESMO ASSIM perde. Duas causas possiveis, com
conserto OPOSTO:
  (a) perde por POUCO  -> resolucao: ruido de simulacao domina
  (b) perde por MUITO  -> a funcao de valor esta confiantemente errada

E uma terceira, que o log deixa medir: a busca cara INVERTE o que o score
estatico ja acertava?
"""
import json, os, sys
from collections import Counter
import pandas as pd

sys.path.insert(0, '.')
from audit_real_losses import audit_one_game, hist_action_kind
from optcg_engine.decision_engine import load_cards_db
from decision_quality_vs_human import find_all_human_logs

cards_db = load_cards_db('cards_rows.csv')
df = pd.read_csv('decklists_raw.csv')
urls = df.groupby('deck_url')['deck_name'].first()

comp = 0                      # comparacoes validas
est_certo = 0                 # score ESTATICO preferia a carta do humano
margens = []
amostras = Counter()

for pf, human, lider, _g in find_all_human_logs():
    path = os.path.join('logs', pf)
    try:
        raw = json.load(open(path, encoding='utf-8'))
        rep = audit_one_game(path, human, cards_db, df, urls,
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
        if not hum:
            continue
        for r in t['decisions']:
            ch = r.get('chosen') or {}
            if ch.get('kind') == 'play' and (ch.get('card') or {}).get('code') in hum:
                continue                     # ja escolheu certo nesta decisao
            cands = [c for c in (r.get('candidates') or [])
                     if c.get('kind') == 'play'
                     and (c.get('card') or {}).get('code') in hum]
            if not cands or ch.get('simulated_value') is None:
                continue
            melhor = max(cands, key=lambda c: c.get('simulated_value') or -1e9)
            if melhor.get('simulated_value') is None:
                continue
            comp += 1
            amostras[ch.get('simulated_samples')] += 1
            d_est = (melhor.get('score') or 0) - (ch.get('score') or 0)
            d_sim = melhor['simulated_value'] - ch['simulated_value']
            margens.append(d_sim)
            if d_est > 0:
                est_certo += 1

margens.sort()
n = len(margens)
print(f'\n{comp} decisoes onde a carta do humano ESTAVA no shortlist e perdeu\n')
print(f'  >> score ESTATICO ja preferia a carta do humano, e a BUSCA a derrubou:'
      f' {est_certo:5} ({est_certo/comp*100:5.1f}%)')
print('     (unica comparacao nao-tautologica -- ver docstring)')
print(f'\n  amostras da simulacao na escolhida: '
      f'{dict(amostras.most_common(6))}')
print(f'\n  margem de valor simulado (escolhida - humano); negativo = perdeu:')
for q, r in ((0.10,'p10'),(0.25,'p25'),(0.50,'MEDIANA'),(0.75,'p75'),(0.90,'p90')):
    print(f'    {r:8} {margens[int(n*q)]:+9.1f}')
perto = sum(1 for m in margens if abs(m) <= 20)
print(f'\n  perdeu por margem <= 20 (ruido plausivel): {perto} ({perto/n*100:.1f}%)')
