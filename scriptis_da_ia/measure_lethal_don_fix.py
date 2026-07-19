"""
measure_lethal_don_fix.py -- medicao PAREADA (mesmo gauntlet, mesma seed,
tudo igual exceto FIX_LETHAL_DON_ALLOCATION) do fix de 19/07 registrado em
GUIA_AUDITORIA_DECISOES.md secao 8. Mesma metodologia de tune_weights.py
(self-play deterministico, PYTHONHASHSEED=0, criterio MAXIMIN sem-regressao),
mas comparando a flag em vez de pesos de evaluate_state_v2 -- os dois lados
usam a MESMA regua (v2, producao atual), so a alocacao de DON em LETHAL muda.

Uso:
    python measure_lethal_don_fix.py --n 30 --seed 1
    python measure_lethal_don_fix.py --gauntlet Krieg Kid "Barba Negra BY"
"""
from __future__ import annotations
import argparse
import os
import random
import subprocess
import sys
from pathlib import Path

if os.environ.get('PYTHONHASHSEED') != '0':
    os.environ['PYTHONHASHSEED'] = '0'
    raise SystemExit(subprocess.call([sys.executable] + sys.argv))

sys.path.insert(0, str(Path(__file__).parent))
from optcg_engine import decision_engine as de
from optcg_engine.sim_bridge import load_sim_deck
from optcg_engine.decision_engine import OPTCGMatch


def _play_one(deck_a, deck_b):
    m = OPTCGMatch(deck_a, deck_b)
    m.setup()
    winner = None
    turns_played = 0
    for turn_num in range(m.MAX_TURNS * 2):
        p = (m.state_a if m.state_a.is_first else m.state_b) if turn_num % 2 == 0 \
            else (m.state_b if m.state_a.is_first else m.state_a)
        opp = m.state_b if p is m.state_a else m.state_a
        r = m.play_turn(p, opp)
        turns_played = turn_num + 1
        if r:
            winner = r
            break
    return winner, turns_played


def run_gauntlet_side(deck_imu, decks_opp: dict, gauntlet, n, seed, flag_value):
    de.FIX_LETHAL_DON_ALLOCATION = flag_value
    out = {}
    for name in gauntlet:
        random.seed(seed)
        wins = 0.0
        turns_total = 0
        for _ in range(n):
            winner, turns = _play_one(deck_imu, decks_opp[name])
            turns_total += turns
            if winner == 'A':
                wins += 1
            elif winner is None:
                wins += 0.5
        out[name] = {'winrate': wins / n, 'avg_turns': turns_total / n}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--n', type=int, default=30)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--gauntlet', nargs='*', default=['Krieg', 'Kid', 'Barba Negra BY'])
    ap.add_argument('--mc', type=int, default=4,
                    help='amostras Monte Carlo do Turn Planner (4 acelera; 6 e a validacao final)')
    args = ap.parse_args()

    de.PLANNER_MC_SAMPLES = args.mc
    print(f"[measure] MC={de.PLANNER_MC_SAMPLES} n={args.n} seed={args.seed} "
          f"gauntlet={args.gauntlet}", flush=True)

    deck_imu = load_sim_deck('Imu')
    decks_opp = {name: load_sim_deck(name) for name in args.gauntlet}

    before = run_gauntlet_side(deck_imu, decks_opp, args.gauntlet, args.n, args.seed, False)
    print(f"[FIX OFF] {before}", flush=True)
    after = run_gauntlet_side(deck_imu, decks_opp, args.gauntlet, args.n, args.seed, True)
    print(f"[FIX ON ] {after}", flush=True)

    print("\n=== comparacao pareada (mesma seed, mesmo gauntlet) ===")
    margens = []
    for name in args.gauntlet:
        wr_b, wr_a = before[name]['winrate'], after[name]['winrate']
        t_b, t_a = before[name]['avg_turns'], after[name]['avg_turns']
        margem = wr_a - wr_b
        margens.append(margem)
        print(f"{name:20s} winrate {wr_b:.3f} -> {wr_a:.3f}  (delta {margem:+.3f})   "
              f"turnos_medios {t_b:.1f} -> {t_a:.1f}")

    maximin = min(margens)
    print(f"\nmaximin da margem de winrate (min sobre matchups): {maximin:+.3f}")
    if maximin < 0:
        print("REGRESSAO detectada em pelo menos 1 matchup -- NAO aceitar o fix como está.")
    elif maximin == 0 and all(m == 0 for m in margens):
        print("Empate exato em todos os matchups -- sem evidencia de ganho nem de regressao "
              "nesta amostra (aumentar --n antes de decidir).")
    else:
        print("Sem regressao em nenhum matchup (maximin >= 0).")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
