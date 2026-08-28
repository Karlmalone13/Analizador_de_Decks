"""ONDE exatamente a sequencia do motor diverge da do humano? (bloco 731)

Sequenciamento e a categoria de MAIOR VOLUME da metrica oficial -- 4.887
decisoes, 1/3 do total -- e esta em 36,4%. Pela regra de priorizacao
(volume x gap, `CLAUDE.md`), e o alvo mais caro do projeto.

O bloco 691 ja tinha medido o SINTOMA (o motor abre o turno com
`attach_don` 3,3x mais que o humano; `attack -> activate` e a transicao
mais comum dele, 4,3x). O que falta e onde a sequencia QUEBRA: qual par
de acoes o motor troca de ordem com mais frequencia, e quanto cada troca
custa no LCS.

So MEDE -- nao altera o motor (regra do bloco 730).
"""
import json, os, sys
from collections import Counter
import pandas as pd

sys.path.insert(0, '.')
from audit_real_losses import audit_one_game, hist_action_kind
from optcg_engine.decision_engine import load_cards_db
from decision_quality_vs_human import find_all_human_logs


def lcs(a, b):
    m = [[0]*(len(b)+1) for _ in range(len(a)+1)]
    for i in range(len(a)):
        for j in range(len(b)):
            m[i+1][j+1] = m[i][j]+1 if a[i] == b[j] else max(m[i][j+1], m[i+1][j])
    return m[len(a)][len(b)]


def main(max_turnos=400):
    db = load_cards_db('cards_rows.csv')
    df = pd.read_csv('decklists_raw.csv')
    urls = df.groupby('deck_url')['deck_name'].first()

    def hk(a):
        t = a.get('type')
        return t if t in ('attack', 'attach_don') else hist_action_kind(a, db)

    prim = Counter()
    perdas = Counter()       # qual acao do humano o motor NAO tem na ordem
    excesso = Counter()      # qual acao o motor faz e o humano nao
    pares_h, pares_m = Counter(), Counter()
    n = 0
    soma_lcs = soma_max = 0

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
            # bloco 732: usa `seq_kinds` (ordem real, com o DON de
            # COMBATE intercalado). A versao anterior lia so
            # `decisions`, que exclui `attach_don_for_attack` -- entao
            # comparava as anexacoes-que-habilitam-efeito do motor contra
            # TODAS as anexacoes do humano. Populacoes diferentes: era o
            # que produzia o "motor abre com attach_don 26,8% x 7,8%".
            sm = list(t.get('seq_kinds') or [])
            if not sm:
                sm = [k for k in ((r.get('chosen') or {}).get('kind')
                                  for r in t['decisions'])
                      if k in ('play', 'activate', 'attach_don', 'attack')]
            if len(sh) < 2 and len(sm) < 2:
                continue
            n += 1
            L = lcs(sh, sm)
            soma_lcs += L
            soma_max += max(len(sh), len(sm))
            if sh:
                prim[('humano', sh[0])] += 1
            if sm:
                prim[('motor', sm[0])] += 1
            ch, cm = Counter(sh), Counter(sm)
            for k in set(ch) | set(cm):
                d = cm[k] - ch[k]
                if d > 0:
                    excesso[k] += d
                elif d < 0:
                    perdas[k] += -d
            for a, b in zip(sh, sh[1:]):
                pares_h[(a, b)] += 1
            for a, b in zip(sm, sm[1:]):
                pares_m[(a, b)] += 1

    print(f'{n} turnos pareados | LCS agregado {soma_lcs}/{soma_max} = '
          f'{soma_lcs/soma_max*100:.1f}%\n')
    print('PRIMEIRA acao do turno:')
    for k in ('play', 'activate', 'attach_don', 'attack'):
        h = prim[('humano', k)]; m = prim[('motor', k)]
        print(f'  {k:12} humano {h/n*100:5.1f}%   motor {m/n*100:5.1f}%'
              f'   {"<-- motor faz MAIS" if m > h*1.5 else ""}')
    print(f'\nACOES QUE O MOTOR FAZ A MAIS (total no corpus):')
    for k, v in excesso.most_common():
        print(f'  {k:12} +{v}')
    print(f'ACOES QUE O MOTOR DEIXA DE FAZER:')
    for k, v in perdas.most_common():
        print(f'  {k:12} -{v}')
    print(f'\nTRANSICOES -- taxa por turno (motor / humano):')
    todas = set(pares_h) | set(pares_m)
    linhas = []
    for p in todas:
        h, m = pares_h[p]/n, pares_m[p]/n
        if max(h, m) < 0.05:
            continue
        linhas.append((abs(m-h), p, m, h))
    linhas.sort(reverse=True)
    for _, (a, b), m, h in linhas[:12]:
        r = f'{m/h:.1f}x' if h else 'so o motor'
        print(f'  {a:11}->{b:12} motor {m:5.2f}  humano {h:5.2f}   {r}')


if __name__ == '__main__':
    main()
