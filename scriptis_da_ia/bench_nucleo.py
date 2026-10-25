"""Velocidade do simulador no nucleo Rust (PLANO_MOTOR_FORTE: o motor Python faz
~200 jogadas/s; a busca forte precisa de 10^5+).

Monta o estado inicial de partidas reais (mesmos decks e sorteio do teste de
paridade), joga N partidas inteiras SO no Rust a partir dele, com politica
aleatoria nas jogadas e nas escolhas internas, e mede jogadas por segundo.

Uso: python bench_nucleo.py --partidas 5 --seed 1000 --n 200
"""
import argparse
import json
import random
import sys
import time

import optcg_core
import paridade_nucleo as P
from optcg_engine import decision_engine as de
from optcg_engine import estado_canonico as ec


def estado_inicial(seed: int):
    dl = P._load_deck_list()
    rng = random.Random(seed)
    ia, ib = rng.sample(range(len(dl)), 2)
    random.seed(seed)
    m = de.OPTCGMatch(dl[ia][1], dl[ib][1])
    m.setup()
    optcg_core.carrega_cartas(json.dumps(P.tabela_de_cartas(m)))
    p = m.state_a if m.state_a.is_first else m.state_b
    o = m.state_b if p is m.state_a else m.state_a
    de.marca_publicas(p)
    de.marca_publicas(o)
    return ec.canonico(p, o)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--partidas', type=int, default=5, help='estados iniciais (decks) diferentes')
    ap.add_argument('--seed', type=int, default=1000)
    ap.add_argument('--n', type=int, default=200, help='partidas simuladas por estado inicial')
    ap.add_argument('--max-turnos', type=int, default=30)
    a = ap.parse_args()
    tot = {'jogadas': 0, 'segundos': 0.0, 'partidas': 0, 'limite': 0, 'v': 0}
    ns = {}
    for i in range(a.partidas):
        e = estado_inicial(a.seed + i)
        r = json.loads(optcg_core.simula_partidas(json.dumps(e), 0, a.n, a.seed + i, a.max_turnos))
        tot['jogadas'] += r['jogadas']
        tot['segundos'] += r['segundos']
        tot['partidas'] += r['partidas']
        tot['limite'] += r['limite']
        tot['v'] += r['vitorias_ativo'] + r['vitorias_outro']
        for k, v in r['nao_suportado'].items():
            ns[k] = ns.get(k, 0) + v
        print(f"seed {a.seed + i}: {r['partidas']} partidas, {r['jogadas']} jogadas em {r['segundos']:.3f}s "
              f"| venceu {r['vitorias_ativo']}/{r['vitorias_outro']} | limite {r['limite']} "
              f"| fora do nucleo {sum(r['nao_suportado'].values())}")
    jps = tot['jogadas'] / max(tot['segundos'], 1e-9)
    print(f"\nTOTAL: {tot['jogadas']} jogadas em {tot['segundos']:.2f}s = {jps:,.0f} jogadas/s "
          f"({tot['partidas'] / max(tot['segundos'], 1e-9):,.0f} partidas/s)")
    print(f"terminadas {tot['v']} | limite de turnos {tot['limite']} | fora do nucleo {sum(ns.values())}")
    for k, v in sorted(ns.items(), key=lambda x: -x[1])[:15]:
        print(f'   fora do nucleo: {k} ({v})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
