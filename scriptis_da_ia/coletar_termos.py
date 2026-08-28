"""Coleta os vetores de TERMO por candidata (passada cara, feita 1 vez).

Com `OPTCG_TERMOS=1` o motor grava, por candidata, o vetor de termos de
`_evaluate_state_v2` + o residuo (alinhamento humano e atalho de linha
vencedora). Reconstrucao verificada **EXATA em 477/477 candidatas**:

    valor_simulado = soma_k  termo_k * W[k]  +  residuo

Logo, avaliar um vetor de pesos NOVO e um produto escalar -- **sem
re-simular**. E isso que torna a busca CONJUNTA sobre os 17 pesos viavel.

Saida: `metrics/termos_dataset.jsonl`, uma linha por DECISAO.
"""
import argparse, json, os, sys
os.environ['OPTCG_TERMOS'] = '1'
sys.path.insert(0, '.')
import pandas as pd
from audit_real_losses import audit_one_game, hist_action_kind
from optcg_engine.decision_engine import load_cards_db
from decision_quality_vs_human import find_all_human_logs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='metrics/termos_dataset.jsonl')
    ap.add_argument('--limit', type=int, default=None)
    a = ap.parse_args()
    db = load_cards_db('cards_rows.csv')
    df = pd.read_csv('decklists_raw.csv')
    urls = df.groupby('deck_url')['deck_name'].first()
    n = 0
    with open(a.out, 'w', encoding='utf-8') as fh:
        for i, (pf, hum, lider, _g) in enumerate(find_all_human_logs()):
            if a.limit and i >= a.limit:
                break
            path = os.path.join('logs', pf)
            try:
                raw = json.load(open(path, encoding='utf-8'))
                rep = audit_one_game(path, hum, db, df, urls,
                                     capture_candidates=True)
            except Exception:
                continue
            if rep.get('error'):
                continue
            rb = {(t['turn'], t['player']): t for t in raw['turns']}
            for t in rep.get('turnos', []):
                if 'decisions' not in t:
                    continue
                raw_t = rb.get((t['turn'], hum))
                if not raw_t:
                    continue
                humano = {x['card'] for x in (raw_t.get('actions') or [])
                          if x.get('card')
                          and hist_action_kind(x, db) == 'play'}
                for d in t['decisions']:
                    cands = []
                    for c in (d.get('candidates') or []):
                        tv = c.get('termos')
                        if not tv:
                            continue
                        cands.append({
                            'kind': c.get('kind'),
                            'code': (c.get('card') or {}).get('code'),
                            'termos': tv['termos'], 'residuo': tv['residuo'],
                            'humano_fez': (c.get('kind') == 'play' and
                                           (c.get('card') or {}).get('code') in humano)})
                    if not cands:
                        continue
                    ch = d.get('chosen') or {}
                    fh.write(json.dumps({
                        'game_id': f"{os.path.basename(pf)}_{hum}",
                        'leader': t.get('leader') or lider, 'turn': t['turn'],
                        'humano': sorted(humano), 'candidates': cands,
                        'motor': {'kind': ch.get('kind'),
                                  'code': (ch.get('card') or {}).get('code')},
                    }, ensure_ascii=False) + '\n')
                    n += 1
            print(f'  {i+1} logs, {n} decisoes', flush=True)
    print(f'\n{n} decisoes gravadas em {a.out}')


if __name__ == '__main__':
    main()
