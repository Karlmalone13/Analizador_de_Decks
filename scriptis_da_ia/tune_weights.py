"""
tune_weights.py  —  Otimizador de pesos da evaluate_state_v2 (item 5, 1º corte)
==============================================================================
Acha um vetor de pesos onde a v2 (Imu) BATE a v1 no gauntlet inteiro, por
SELF-PLAY determinístico — sem hand-tuning (o whack-a-mole que estamos
matando). Coordinate-ascent simples a partir dos priors.

Setup por partida (como o sistema per-deck vai operar):
  - Lado A (Imu)      = v2 com os pesos-candidatos.
  - Lado B (oponente) = v1 (a régua atual em produção).
Objetivo = MAXIMIN da margem de winrate (min sobre matchups de
`winrate_v2 − winrate_v1_baseline`): força melhora SEM regredir nenhum
matchup. Empate desempatado pela soma das margens.

Determinístico: PYTHONHASHSEED=0 (auto-relança) + seed fixa. Comparar dois
runs é limpo. Vencedor salvo em eval_weights.json (o motor carrega no import).

Uso:
  python tune_weights.py                 # gauntlet padrão, ~poucos min
  python tune_weights.py --n 30 --iters 3
  python tune_weights.py --gauntlet Krieg Kid "Barba Negra BY"
"""
from __future__ import annotations
import argparse
import json
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

# winrate v1 de referência (baseline_metrics saved) — alvo a bater/não regredir
_V1 = {
    'Krieg': 0.38, 'Kid': 0.34, 'Barba Negra BY': 0.88,
}

# passo de busca por peso (fração multiplicativa) e limites sensatos
_TUNABLE = ['dmg', 'board_mine', 'board_opp', 'hand_first', 'counter_hand',
            'don_field', 'coverage', 'ax_trash', 'ax_reanim', 'ax_inversion',
            'life_mult']


def _imu_winrate(deck_imu, deck_opp, weights: dict, n: int, seed: int) -> float:
    """Winrate do Imu (A=v2+weights) vs oponente (B=v1), n jogos, seed fixa."""
    random.seed(seed)
    wins = 0.0
    for _ in range(n):
        m = OPTCGMatch(deck_imu, deck_opp)
        m.setup()
        # A = Imu com v2 + pesos candidatos; B = oponente com v1
        m.state_a.use_eval_v2 = True
        m.state_a.eval_weights = weights
        m.state_b.use_eval_v2 = False
        winner = None
        for turn_num in range(m.MAX_TURNS * 2):
            p = (m.state_a if m.state_a.is_first else m.state_b) if turn_num % 2 == 0 \
                else (m.state_b if m.state_a.is_first else m.state_a)
            opp = m.state_b if p is m.state_a else m.state_a
            r = m.play_turn(p, opp)
            if r:
                winner = r
                break
        if winner == 'A':   wins += 1
        elif winner is None: wins += 0.5
    return wins / n


def _score(weights, gauntlet, decks_imu, decks_opp, n, seed,
           beat_maximin=None) -> tuple[tuple, dict]:
    """
    (maximin da margem, soma) + winrates. maximin = min sobre matchups de
    (winrate − v1). EARLY-STOP: o objetivo é maximin; como maximin ≤ QUALQUER
    margem, assim que uma margem cai abaixo do `beat_maximin` atual o candidato
    já não pode vencer — aborta e economiza os matchups restantes. Avalia os
    matchups do MAIS DIFÍCIL pro mais fácil (menor v1 primeiro) pra o corte
    disparar cedo.
    """
    wr = {}
    ordem = sorted(gauntlet, key=lambda nm: _V1.get(nm, 0.5))
    for name in ordem:
        wr[name] = _imu_winrate(decks_imu, decks_opp[name], weights, n, seed)
        margem = wr[name] - _V1.get(name, 0.5)
        if beat_maximin is not None and margem <= beat_maximin:
            return (margem, -999.0), wr   # não vence — poda o resto
    margens = [wr[name] - _V1.get(name, 0.5) for name in gauntlet]
    return (min(margens), sum(margens)), wr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=30)
    ap.add_argument('--iters', type=int, default=3)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--gauntlet', nargs='*', default=['Krieg', 'Kid', 'Barba Negra BY'])
    ap.add_argument('--mc', type=int, default=4, help='amostras Monte Carlo na busca (6 no jogo real)')
    args = ap.parse_args()

    # amostragem Monte Carlo mais leve DURANTE a busca (acelera; validação
    # final volta a 6). Não muda a régua, só o custo por partida.
    de.PLANNER_MC_SAMPLES = args.mc
    print(f"[tuner] MC={de.PLANNER_MC_SAMPLES} n={args.n} gauntlet={args.gauntlet}")

    decks_imu = load_sim_deck('Imu')
    decks_opp = {name: load_sim_deck(name) for name in args.gauntlet}

    best = dict(de.EVAL_WEIGHTS)
    best_key, best_wr = _score(best, args.gauntlet, decks_imu, decks_opp, args.n, args.seed)
    print(f"PRIOR  maximin={best_key[0]:+.3f} soma={best_key[1]:+.3f}  {best_wr}", flush=True)

    for it in range(args.iters):
        melhorou = False
        for w in _TUNABLE:
            for fator in (1.5, 0.67):
                cand = dict(best)
                cand[w] = round(best[w] * fator, 4)
                # early-stop: só interessa quem SUPERA o maximin atual
                key, wr = _score(cand, args.gauntlet, decks_imu, decks_opp,
                                 args.n, args.seed, beat_maximin=best_key[0])
                if key > best_key:
                    best, best_key, best_wr = cand, key, wr
                    melhorou = True
                    print(f"  it{it} {w}×{fator}: maximin={key[0]:+.3f} "
                          f"soma={key[1]:+.3f}  {wr}", flush=True)
        if not melhorou:
            print(f"  it{it}: sem melhora — convergiu")
            break

    print(f"\nMELHOR maximin={best_key[0]:+.3f} soma={best_key[1]:+.3f}")
    print(f"winrates: {best_wr}")
    print(f"pesos:    {best}")

    # só salva se NÃO regride nenhum matchup (maximin >= 0)
    if best_key[0] >= -0.02:
        out = Path(__file__).parent / 'eval_weights.json'
        out.write_text(json.dumps(best, indent=2), encoding='utf-8')
        print(f"\n-> salvo em {out} (nenhuma regressão relevante). "
              f"Ligar USE_EVAL_V2=True e re-medir com baseline_metrics.")
    else:
        print(f"\n-> NÃO salvo: ainda regride (maximin {best_key[0]:+.3f}). "
              f"Sinal de que Imu precisa de matchup-awareness (item 3) "
              f"ou mais iterações/pesos.")


if __name__ == '__main__':
    main()
