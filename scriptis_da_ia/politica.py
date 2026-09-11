"""REDE DE POLITICA: coleta + a medicao que decide se vale a pena. Bloco 772.

IDEIA: em vez de o ML ESCOLHER a jogada (rede de valor, reprovada 3x -- ver
bloco 771), ele PODA o shortlist: das ~10,7 candidatas por decisao, mantem
as N mais promissoras e a busca cara avalia so essas.

ASSIMETRIA DE ERRO, que e a razao de tentar: a rede de valor COMPETE com a
busca -- se erra, o bot joga errado. A politica ALIMENTA a busca -- se erra,
a busca ainda avalia as sobreviventes. Errar sai barato.

ROTULO: qual candidata a BUSCA COMPLETA escolheu. Isto e DESTILACAO DE
BUSCA, nao imitacao de humano -- a imitacao de humano e o que caiu por
*distribution shift* nos blocos 680-683 (`REPROVADOS.md`).

A MEDICAO QUE DECIDE, e ela e OFFLINE (nenhuma partida de duelo):

    com que frequencia a jogada que a busca escolheu sobrevive ao corte?

Se for ~97% com N=4, podamos de 10,7 pra 4 perdendo 3%. Se for 70%, o
caminho morre aqui, em minutos, em vez de uma hora de duelo.

BASELINE HONESTO, incluido de proposito: o score ESTATICO que o motor ja
calcula tambem ordena as candidatas. **Se ele sozinho ja der uma taxa alta,
nao precisamos de ML nenhum pra podar** -- e isso mataria a ideia, o que e
exatamente o que um teste honesto tem que poder fazer.

Uso:
  python politica.py --coletar --n 40 --workers 2
  python politica.py --medir
"""
from __future__ import annotations
import argparse
import json
import random
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parent
SAIDA = RAIZ / 'metrics' / 'politica_dataset.jsonl'

# Campos numericos que `_descreve_candidata` produz, na ordem em que viram
# colunas. `kind` e categorico e entra como one-hot logo abaixo.
CAND_NUM = ('score', 'don', 'cost', 'power', 'counter', 'blocker', 'rush')
CAND_KIND = ('play', 'attack', 'attach_don', 'activate', 'pass')


def _uma_partida(task):
    i, seed, eps = task
    from gerar_selfplay_dataset import _load_deck_list
    from optcg_engine.decision_engine import OPTCGMatch

    dl = _load_deck_list()
    rng = random.Random(seed)
    ia, ib = rng.sample(range(len(dl)), 2)
    random.seed(seed)
    try:
        m = OPTCGMatch(dl[ia][1], dl[ib][1])
        m.setup()
    except Exception:
        return []
    m._pol_captura = []
    if eps:
        m._explora_eps = eps
    lider = {'A': dl[ia][0], 'B': dl[ib][0]}
    try:
        for t in range(m.MAX_TURNS * 2):
            p = (m.state_a if m.state_a.is_first else m.state_b) if t % 2 == 0 \
                else (m.state_b if m.state_a.is_first else m.state_a)
            opp = m.state_b if p is m.state_a else m.state_a
            if m.play_turn(p, opp):
                break
    except Exception:
        return []
    saida = []
    for d in (m._pol_captura or []):
        d['match'] = i
        d['leader'] = lider['A']
        saida.append(d)
    return saida


def coletar(n, workers, seed, eps):
    tasks = [(i, seed * 1_000_003 + i, eps) for i in range(n)]
    tudo = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for r in ex.map(_uma_partida, tasks):
            tudo.extend(r)
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    with open(SAIDA, 'w', encoding='utf-8') as f:
        for d in tudo:
            f.write(json.dumps(d) + '\n')
    cands = [len(d['cands']) for d in tudo]
    print('{:,} decisoes de {} partidas -> {}'.format(len(tudo), n, SAIDA.name))
    if cands:
        print('candidatas por decisao: media {:.1f} | min {} | max {}'.format(
            sum(cands) / len(cands), min(cands), max(cands)))


def _linha(feats, cand):
    kind = cand.get('kind')
    return (list(feats)
            + [float(cand.get(k, 0) or 0) for k in CAND_NUM]
            + [1.0 if kind == k else 0.0 for k in CAND_KIND])


def medir(topn_lista=(2, 3, 4, 5, 6)):
    from sklearn.ensemble import HistGradientBoostingClassifier
    dados = [json.loads(l) for l in open(SAIDA, encoding='utf-8') if l.strip()]
    if not dados:
        raise SystemExit('sem dados -- rode --coletar primeiro')

    lideres = sorted({d['leader'] for d in dados})
    rng = np.random.RandomState(42)
    rng.shuffle(lideres)
    teste = set(lideres[:max(1, len(lideres) // 4)])
    tr = [d for d in dados if d['leader'] not in teste]
    te = [d for d in dados if d['leader'] in teste]
    print('decisoes: {:,} treino | {:,} TESTE ({} lideres nunca vistos)'
          .format(len(tr), len(te), len(teste)))

    X, y = [], []
    for d in tr:
        for j, c in enumerate(d['cands']):
            X.append(_linha(d['feats'], c))
            y.append(1 if j == d['escolhida'] else 0)
    modelo = HistGradientBoostingClassifier(
        max_iter=300, learning_rate=0.05, max_depth=4,
        min_samples_leaf=40, early_stopping=True,
        validation_fraction=0.15, random_state=0).fit(np.array(X), np.array(y))

    print('')
    print('A MEDICAO QUE DECIDE -- a jogada da busca SOBREVIVE ao corte?')
    print('{:>6}{:>14}{:>18}{:>14}'.format(
        'top-N', 'POLITICA', 'score estatico', 'sorteio'))
    n_dec = len(te)
    for N in topn_lista:
        ok_pol = ok_est = ok_rnd = 0
        for d in te:
            m = len(d['cands'])
            alvo = d['escolhida']
            if m <= N:
                ok_pol += 1; ok_est += 1; ok_rnd += 1
                continue
            p = modelo.predict_proba(
                np.array([_linha(d['feats'], c) for c in d['cands']]))[:, 1]
            if alvo in set(np.argsort(-p)[:N]):
                ok_pol += 1
            est = np.array([float(c.get('score', 0) or 0) for c in d['cands']])
            if alvo in set(np.argsort(-est)[:N]):
                ok_est += 1
            ok_rnd += N / m
        print('{:>6}{:>13.1%}{:>17.1%}{:>14.1%}'.format(
            N, ok_pol / n_dec, ok_est / n_dec, ok_rnd / n_dec))
    print('')
    print('LEITURA: se o "score estatico" ja der taxa alta, NAO precisamos de')
    print('ML pra podar -- bastaria cortar pelo score, e a ideia morre aqui.')
    print('A politica so se justifica se ganhar dele por margem real.')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--coletar', action='store_true')
    ap.add_argument('--medir', action='store_true')
    ap.add_argument('--n', type=int, default=40)
    ap.add_argument('--workers', type=int, default=2)
    ap.add_argument('--seed', type=int, default=4242)
    ap.add_argument('--explorar', type=float, default=0.15)
    a = ap.parse_args()
    if a.coletar:
        coletar(a.n, a.workers, a.seed, a.explorar)
    if a.medir:
        medir()
    if not (a.coletar or a.medir):
        ap.error('use --coletar e/ou --medir')


if __name__ == '__main__':
    main()
