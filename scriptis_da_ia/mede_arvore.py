"""AS-IS do custo da arvore do turno (bloco 973, `_arvore_q`).

Joga as MESMAS partidas (mesmas seeds, mesmos decks) duas vezes: sem a arvore
e com a arvore nos dois lados. Mede segundos por partida, decisoes que passaram
pela arvore, nos expandidos, transposicoes reusadas e quantas vezes a arvore
trocou a escolha do Q. Nao mede FORCA -- isso e o portao.

    python mede_arvore.py --partidas 6 --seed 973
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import time

os.environ.setdefault('OMP_NUM_THREADS', '1')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from optcg_engine import decision_engine as de  # noqa: E402
from optcg_engine.decision_engine import OPTCGMatch  # noqa: E402
from gerar_selfplay_dataset import _load_deck_list  # noqa: E402


def joga(seed: int, arvore: bool) -> dict:
    de._EM_SIMULACAO['on'] = False
    deck_list = _load_deck_list()
    rng = random.Random(seed)
    ia, ib = rng.sample(range(len(deck_list)), 2)
    random.seed(seed)
    m = OPTCGMatch(deck_list[ia][1], deck_list[ib][1])
    m.setup()
    for s in (m.state_a, m.state_b):
        s.arvore_q = arvore
    t0 = time.perf_counter()
    vencedor, erro = None, None
    try:
        for n in range(m.MAX_TURNS * 2):
            p = (m.state_a if m.state_a.is_first else m.state_b) if n % 2 == 0 \
                else (m.state_b if m.state_a.is_first else m.state_a)
            opp = m.state_b if p is m.state_a else m.state_a
            r = m.play_turn(p, opp)
            if r:
                vencedor = r
                break
    except Exception as e:  # registra, nao esconde
        erro = f'{type(e).__name__}: {e}'
    return {'seg': time.perf_counter() - t0, 'vencedor': vencedor, 'erro': erro,
            'lideres': (deck_list[ia][0], deck_list[ib][0])}


def assinatura(partidas: int, seed: int) -> int:
    """Uma linha por partida com tudo que a arvore decidiu: vencedor, turnos,
    decisoes, nos, transposicoes, trocas e escolhas por familia. Otimizacao de
    velocidade tem que reproduzir estas linhas EXATAMENTE."""
    import json
    t0 = time.perf_counter()
    for i in range(partidas):
        antes = json.loads(json.dumps(de._ARVORE_STATS, default=str))
        r = joga(seed + i, True)
        d = {k: de._ARVORE_STATS[k] - antes.get(k, 0) for k in ('decisoes', 'nos', 'hits', 'mudou')}
        ef = {f: [v[0] - (antes.get('efeitos', {}).get(f, [0, 0])[0]),
                  v[1] - (antes.get('efeitos', {}).get(f, [0, 0])[1])]
              for f, v in sorted(de._ARVORE_STATS.get('efeitos', {}).items())}
        print('ASSIN', seed + i, r['vencedor'], r['erro'], json.dumps(d, sort_keys=True),
              json.dumps(ef, sort_keys=True), flush=True)
    print(f'tempo {time.perf_counter() - t0:.1f}s; arvore {de._ARVORE_STATS["seg"]:.1f}s')
    return 0


def perfil(partidas: int, seed: int) -> int:
    """AS-IS de ONDE a arvore gasta o tempo: cProfile ligado so dentro de
    `_arvore_q`, nas mesmas seeds."""
    import cProfile
    import pstats
    pr = cProfile.Profile()
    orig = de.OPTCGMatch._arvore_q

    def _com_perfil(self, *x, **k):
        pr.enable()
        try:
            return orig(self, *x, **k)
        finally:
            pr.disable()
    de.OPTCGMatch._arvore_q = _com_perfil
    t0 = time.perf_counter()
    for i in range(partidas):
        joga(seed + i, True)
    print(f'{partidas} partidas em {time.perf_counter() - t0:.1f}s; arvore '
          f'{de._ARVORE_STATS["seg"]:.1f}s em {de._ARVORE_STATS["decisoes"]} decisoes')
    st = pstats.Stats(pr)
    st.sort_stats('cumulative').print_stats(35)
    st.sort_stats('tottime').print_stats(25)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--partidas', type=int, default=6)
    ap.add_argument('--seed', type=int, default=973)
    ap.add_argument('--assinatura', action='store_true',
                    help='so com a arvore; imprime a assinatura de cada partida '
                         '(otimizacao tem que manter IDENTICA)')
    ap.add_argument('--perfil', action='store_true',
                    help='so com a arvore; perfil (cProfile) restrito a ela')
    a = ap.parse_args()
    if a.perfil:
        return perfil(a.partidas, a.seed)
    if a.assinatura:
        return assinatura(a.partidas, a.seed)
    tot = {False: 0.0, True: 0.0}
    for i in range(a.partidas):
        s = a.seed + i
        de._Q_FALLBACK.clear()
        sem = joga(s, False)
        fb_sem = dict(de._Q_FALLBACK)
        de._Q_FALLBACK.clear()
        antes = dict(de._ARVORE_STATS)
        com = joga(s, True)
        fb_com = dict(de._Q_FALLBACK)
        st = {k: de._ARVORE_STATS[k] - antes[k] for k in antes if isinstance(antes[k], (int, float))}
        tot[False] += sem['seg']
        tot[True] += com['seg']
        print(f'seed {s} {com["lideres"]}: sem {sem["seg"]:.1f}s  com {com["seg"]:.1f}s  '
              f'| decisoes {st["decisoes"]}  nos {st["nos"]}  hits {st["hits"]}  '
              f'mudou {st["mudou"]}  arvore {st["seg"]:.1f}s  fallback sem {fb_sem} com {fb_com}'
              + (f'  ERRO sem: {sem["erro"]}' if sem['erro'] else '')
              + (f'  ERRO com: {com["erro"]}' if com['erro'] else ''), flush=True)
    S = de._ARVORE_STATS
    print(f'\nTOTAL: sem {tot[False]:.1f}s  com {tot[True]:.1f}s  '
          f'-> {tot[True] / max(tot[False], 1e-9):.2f}x')
    if S['decisoes']:
        print(f'arvore: {S["seg"] / S["decisoes"] * 1000:.0f} ms/decisao, '
              f'{S["nos"] / S["decisoes"]:.1f} nos/decisao, '
              f'hits {S["hits"]}, mudou {S["mudou"]}/{S["decisoes"]} '
              f'({100 * S["mudou"] / S["decisoes"]:.0f}%)')
    print({k: v for k, v in S.items()})
    G = de._ARVORE_GAPS
    if G:
        print('\ndistancia pra melhor nota do Q -> ramos | escolhidos pela arvore')
        for lo, hi in [(0, 1e-9), (1e-9, .01), (.01, .02), (.02, .03), (.03, .05),
                       (.05, .08), (.08, .12), (.12, .2), (.2, 9)]:
            b = [e for g, e in G if lo <= g < hi] if lo else [e for g, e in G if g < hi]
            if b:
                print(f'  [{lo:.2f}, {hi:.2f}): {len(b):5d} | {sum(b):4d} ({100*sum(b)/len(b):.0f}%)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
