"""Duelo: BUSCA do nucleo Rust (fase B) x motor Python atual.

Um lado escolhe a jogada principal pela busca (`GameState.busca_rust`); o resto
das decisoes (escolhas internas, defesa) continua no motor Python dos dois lados.
Partidas em PARES: mesmos decks e mesma semente, trocando o lado da busca --
assim deck e quem comeca nao pesam no placar.

Uso: python duelo_busca.py --pares 10 --seed 7000 --iteracoes 2000 --turnos 6
"""
import argparse
import json
import random
import sys
import time

import optcg_core
import paridade_nucleo as P
from optcg_engine import decision_engine as de


MOTIVOS_TOT = {}


def partida(seed: int, lado_busca: str, cfg: dict):
    dl = P._load_deck_list()
    rng = random.Random(seed)
    ia, ib = rng.sample(range(len(dl)), 2)
    random.seed(seed)
    m = de.OPTCGMatch(dl[ia][1], dl[ib][1])
    m.setup()
    optcg_core.carrega_cartas(json.dumps(P.tabela_de_cartas(m)))
    busca = m.state_a if lado_busca == 'A' else m.state_b
    busca.busca_rust = dict(cfg)
    for n in range(m.MAX_TURNS * 2):
        p = (m.state_a if m.state_a.is_first else m.state_b) if n % 2 == 0 \
            else (m.state_b if m.state_a.is_first else m.state_a)
        o = m.state_b if p is m.state_a else m.state_a
        r = m.play_turn(p, o)
        if r:
            MOTIVOS_TOT.update({k: MOTIVOS_TOT.get(k, 0) + v for k, v in busca.busca_rust.get('_motivos', {}).items()})
            return r, busca.busca_rust.get('_estat', []), dl[ia][0], dl[ib][0]
    MOTIVOS_TOT.update({k: MOTIVOS_TOT.get(k, 0) + v for k, v in busca.busca_rust.get('_motivos', {}).items()})
    return None, busca.busca_rust.get('_estat', []), dl[ia][0], dl[ib][0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pares', type=int, default=10)
    ap.add_argument('--seed', type=int, default=7000)
    ap.add_argument('--iteracoes', type=int, default=2000)
    ap.add_argument('--turnos', type=int, default=6)
    ap.add_argument('--c', type=float, default=0.7)
    ap.add_argument('--sem-valor', action='store_true', help='folhas pela nota simples (sem a rede)')
    ap.add_argument('--rede', default='', help='rede politica+valor da fase C (JSON do rede_pv.py)')
    ap.add_argument('--defesa-rede', action='store_true', help='na simulacao, o defensor bloqueia/counter pela rede')
    a = ap.parse_args()
    cfg = {'iteracoes': a.iteracoes, 'turnos': a.turnos, 'c': a.c, 'semente': a.seed}
    if not a.sem_valor:
        # folhas da busca avaliadas pela rede de valor do motor (`win_prob`)
        from optcg_engine import value_net as V
        optcg_core.carrega_valor(json.dumps(V.exporta_para_nucleo()))
    if a.rede:
        optcg_core.carrega_rede(1, open(a.rede).read())
        cfg['rede'] = 1
        cfg['defesa_rede'] = a.defesa_rede
    placar = {'busca': 0, 'python': 0, 'empate': 0}
    t_busca, n_busca, fora, its = 0.0, 0, 0, 0
    t0 = time.time()
    for i in range(a.pares):
        for lado in ('A', 'B'):
            v, est, da, db = partida(a.seed + i, lado, cfg)
            if v is None or v not in ('A', 'B'):
                placar['empate'] += 1
                res = 'empate'
            elif v == lado:
                placar['busca'] += 1
                res = 'BUSCA'
            else:
                placar['python'] += 1
                res = 'python'
            t_busca += sum(x[0] for x in est)
            n_busca += len(est)
            fora += sum(x[1] for x in est)
            its += sum(x[2] for x in est)
            print(f'seed {a.seed + i} busca={lado} ({da} x {db}): venceu {res}', flush=True)
    jog = placar['busca'] + placar['python']
    print(f"\nPLACAR busca {placar['busca']} x {placar['python']} python (empates {placar['empate']}) "
          f"= {100 * placar['busca'] / max(jog, 1):.0f}% para a busca")
    print(f'decisoes da busca: {n_busca}, {t_busca / max(n_busca, 1):.2f}s cada; '
          f'simulacoes fora do nucleo: {100 * fora / max(its, 1):.0f}%; total {time.time() - t0:.0f}s')
    for k, v in sorted(MOTIVOS_TOT.items(), key=lambda x: -x[1])[:20]:
        print(f'   fora do nucleo: {k} ({v})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
