"""A busca DERRUBA o score estatico -- e acerta ou erra? Nos DOIS lados.

Corrige o vies de selecao do bloco 699/700: aquele diagnostico media so
as decisoes em que o motor JA TINHA ERRADO e concluiu que a busca
atrapalhava (45% das vezes o estatico ja tinha a carta certa). A ablacao
(bloco 700) REFUTOU: remover a busca custou -2,7pp. As vezes em que a
busca derruba o estatico e ACERTA nunca entraram na amostra.

Aqui a conta e feita no COMPLEMENTO tambem. Para cada decisao com dado:

  - `static_top`  = acao de maior `score` bruto em `all_actions`
                    (lista COMPLETA, antes de qualquer corte)
  - `chosen`      = o que o motor de fato executou apos a busca
  - derrubou?     = chosen != static_top
  - acertou?      = a carta e uma que o humano jogou neste turno

Reporta, separadamente, a taxa de acerto QUANDO derrubou e QUANDO
manteve -- e, dentro das derrubadas, quanto o `static_top` teria acertado.
Essa ultima comparacao e a unica que responde "a busca melhora ou piora
as decisoes em que ela intervem?".
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

st = Counter()

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
            todas = r.get('all_actions') or []
            ch = r.get('chosen') or {}
            if not todas or not ch:
                continue
            top = max(todas, key=lambda a: a.get('score') or -1e9)
            ch_cod = (ch.get('card') or {}).get('code')
            ch_ok = ch.get('kind') == 'play' and ch_cod in hum
            tp_ok = top.get('kind') == 'play' and top.get('code') in hum
            derrubou = not (ch.get('kind') == top.get('kind')
                            and ch_cod == top.get('code'))
            st['n'] += 1
            if derrubou:
                st['derrubou'] += 1
                st['derrubou_chosen_ok'] += ch_ok
                st['derrubou_static_ok'] += tp_ok
            else:
                st['manteve'] += 1
                st['manteve_ok'] += ch_ok

n, d, m = st['n'], st['derrubou'], st['manteve']
print(f'\n{n} decisoes (turnos em que o humano jogou algo)\n')
print(f'  a busca MANTEVE o topo estatico: {m:5} ({m/n*100:5.1f}%)')
print(f'     acerto: {st["manteve_ok"]/m*100:5.1f}%')
print(f'\n  a busca DERRUBOU o topo estatico: {d:5} ({d/n*100:5.1f}%)')
print(f'     acerto do que a busca ESCOLHEU : {st["derrubou_chosen_ok"]/d*100:5.1f}%'
      f'  ({st["derrubou_chosen_ok"]})')
print(f'     acerto do topo ESTATICO derrubado: {st["derrubou_static_ok"]/d*100:5.1f}%'
      f'  ({st["derrubou_static_ok"]})')
delta = (st['derrubou_chosen_ok'] - st['derrubou_static_ok']) / d * 100
print(f'\n  >> nas decisoes em que ela INTERVEM, a busca e {delta:+.1f}pp '
      f'{"MELHOR" if delta > 0 else "PIOR"} que o estatico')
