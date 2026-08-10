"""
baseline_metrics.py
===================
Bateria determinística de métricas motor-vs-motor — o MARCO-ZERO do plano
PLANO_AVALIACAO_E_BUSCA.md (item 0). Roda ANTES de cada etapa e DEPOIS;
uma etapa só é "feita" se o winrate não regride e as métricas de
passividade movem na direção certa.

Determinístico: auto-relança com PYTHONHASHSEED=0 (mesma seed -> mesmas
partidas, ver audit_antipatterns.py). Comparar dois runs com a mesma
--seed é comparação limpa (só o efeito da mudança de código aparece).

Métricas por LADO (A e B), com foco no lado auditado (A = deck-a):
  winrate            — vitórias de A / total (empate conta meio)
  atk/turno          — agressividade bruta
  % ataque no líder  — pressão real de dano (vs trocar no board)
  dano feito         — hits no líder adversário
  DON anexado/ataque — margem investida (seco vs pesado)
  counters gastos    — economia de mão na defesa
  turnos até fim     — velocidade da partida

Uso:
  python baseline_metrics.py                        # Imu vs Teach BY, 50 jogos
  python baseline_metrics.py --n 50 --seed 1
  python baseline_metrics.py --deck-a Imu --deck-b "Krieg RG"
  python baseline_metrics.py --json out.json        # salva pra diff entre etapas
  python baseline_metrics.py --workers 4            # paraleliza (achado 10/08)

Paralelismo: cada partida e independente -- `--workers N` roda N partidas em
processos separados via ProcessPoolExecutor (mesmo padrao ja validado em
audit_replay.py/gauntlet_matchup.py). Nota de reprodutibilidade: a versao
sequencial antiga avançava um UNICO `random` global entre as N partidas (a
seed efetiva da partida i dependia de quantas chamadas de random.* as
partidas 0..i-1 ja tinham feito) -- isso nao e reproduzivel entre processos,
entao cada partida agora usa sua PROPRIA seed derivada de `--seed`+indice
(`args.seed * 1_000_003 + i`), igual sequencial ou paralelo. `--seed`
continua determinístico (mesmo seed = mesmas N partidas), só a composição
exata de cada partida individual muda em relação ao comportamento antigo.
"""
from __future__ import annotations
import argparse
import json
import os
import random
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

# Reprodutibilidade real (ver audit_antipatterns.py): PYTHONHASHSEED precisa
# existir antes do interpretador subir — relança se não estiver fixo.
if os.environ.get('PYTHONHASHSEED') != '0':
    os.environ['PYTHONHASHSEED'] = '0'
    raise SystemExit(subprocess.call([sys.executable] + sys.argv))

sys.path.insert(0, str(Path(__file__).parent))
from optcg_engine.sim_bridge import load_sim_deck
from optcg_engine.decision_engine import OPTCGMatch


def _side_stats() -> dict:
    return {'wins': 0.0, 'atk': 0, 'atk_leader': 0, 'dmg': 0,
            'don_attached': 0, 'counters': 0, 'turnos_proprios': 0}


def _play_one_match(deck_a, deck_b, seed: int, side_a_v2: dict | None = None) -> dict:
    """Roda 1 partida instrumentada do ZERO (sem mutar estado compartilhado) e
    devolve um resultado bruto -- pode rodar em processo separado sem
    coordenacao. `_accumulate` (abaixo) faz a mesma soma que antes vivia
    inline dentro do loop de `run_match`."""
    random.seed(seed)
    match = OPTCGMatch(deck_a, deck_b)
    match.setup()
    match.replay_log = []
    if side_a_v2 is not None:
        match.state_a.use_eval_v2 = True
        match.state_a.eval_weights = side_a_v2
        match.state_b.use_eval_v2 = False

    turnos = 0
    winner = None
    turnos_proprios_a = 0
    turnos_proprios_b = 0
    for turn_num in range(match.MAX_TURNS * 2):
        p = (match.state_a if match.state_a.is_first else match.state_b) \
            if turn_num % 2 == 0 \
            else (match.state_b if match.state_a.is_first else match.state_a)
        opp = match.state_b if p is match.state_a else match.state_a
        if p is match.state_a:
            turnos_proprios_a += 1
        else:
            turnos_proprios_b += 1
        result = match.play_turn(p, opp)
        turnos += 1
        if result:
            winner = result
            break

    return {
        'winner': winner,
        'turnos': turnos,
        'turnos_proprios_a': turnos_proprios_a,
        'turnos_proprios_b': turnos_proprios_b,
        'replay_log': match.replay_log,
        'counters_a': match.state_a.counters_used,
        'counters_b': match.state_b.counters_used,
    }


def _accumulate(raw: dict, sa: dict, sb: dict) -> None:
    """Soma o resultado bruto de 1 partida nos totais acumulados -- mesma
    logica que `run_match` fazia inline, extraida pra rodar no processo
    PRINCIPAL depois de coletar resultados (sequenciais ou paralelos)."""
    winner = raw['winner']
    if winner == 'A':   sa['wins'] += 1
    elif winner == 'B': sb['wins'] += 1
    else:               sa['wins'] += 0.5; sb['wins'] += 0.5

    sa['turnos_proprios'] += raw['turnos_proprios_a']
    sb['turnos_proprios'] += raw['turnos_proprios_b']

    for e in raw['replay_log']:
        side = sa if e.get('player') == 'A' else sb
        if e.get('type') == 'attack':
            side['atk'] += 1
            side['don_attached'] += e.get('attached_don', 0)
            tgt = e.get('target') or {}
            if tgt.get('type') == 'LEADER':
                side['atk_leader'] += 1
        elif e.get('type') == 'life_damage':
            side['dmg'] += 1

    sa['counters'] += raw['counters_a']
    sb['counters'] += raw['counters_b']


def run_match(deck_a, deck_b, sa: dict, sb: dict, side_a_v2: dict | None = None) -> int:
    """Compatibilidade com chamadores existentes (ex: outros scripts que
    importam esta funcao) -- roda 1 partida com o `random` global JA
    posicionado pelo chamador (nao deriva seed propria) e acumula direto,
    igual ao comportamento original. `main()` abaixo usa `_play_one_match`/
    `_accumulate` separados pra poder paralelizar."""
    match = OPTCGMatch(deck_a, deck_b)
    match.setup()
    match.replay_log = []
    if side_a_v2 is not None:
        match.state_a.use_eval_v2 = True
        match.state_a.eval_weights = side_a_v2
        match.state_b.use_eval_v2 = False

    turnos = 0
    winner = None
    for turn_num in range(match.MAX_TURNS * 2):
        p = (match.state_a if match.state_a.is_first else match.state_b) \
            if turn_num % 2 == 0 \
            else (match.state_b if match.state_a.is_first else match.state_a)
        opp = match.state_b if p is match.state_a else match.state_a
        (sa if p is match.state_a else sb)['turnos_proprios'] += 1
        result = match.play_turn(p, opp)
        turnos += 1
        if result:
            winner = result
            break

    if winner == 'A':   sa['wins'] += 1
    elif winner == 'B': sb['wins'] += 1
    else:               sa['wins'] += 0.5; sb['wins'] += 0.5

    for e in match.replay_log:
        side = sa if e.get('player') == 'A' else sb
        if e.get('type') == 'attack':
            side['atk'] += 1
            side['don_attached'] += e.get('attached_don', 0)
            tgt = e.get('target') or {}
            if tgt.get('type') == 'LEADER':
                side['atk_leader'] += 1
        elif e.get('type') == 'life_damage':
            side['dmg'] += 1

    sa['counters'] += match.state_a.counters_used
    sb['counters'] += match.state_b.counters_used
    return turnos


def _worker_task(task):
    deck_a_name, deck_b_name, seed, side_a_v2 = task
    deck_a = load_sim_deck(deck_a_name)
    deck_b = load_sim_deck(deck_b_name)
    return _play_one_match(deck_a, deck_b, seed, side_a_v2=side_a_v2)


def _fmt(s: dict, n: int) -> dict:
    t = max(1, s['turnos_proprios'])
    a = max(1, s['atk'])
    return {
        'winrate':        round(s['wins'] / n, 3),
        'atk_por_turno':  round(s['atk'] / t, 2),
        'pct_atk_lider':  round(100 * s['atk_leader'] / a, 1),
        'dano_por_jogo':  round(s['dmg'] / n, 2),
        'don_por_atk':    round(s['don_attached'] / a, 2),
        # counters_used acumula PODER de counter (c.counter), não contagem
        'counter_power_por_jogo': round(s['counters'] / n, 0),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=50)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--deck-a', default='Imu')
    ap.add_argument('--deck-b', default='Barba Negra BY')
    ap.add_argument('--json', default='', help='salva o resumo em JSON pra diff entre etapas')
    ap.add_argument('--side-a-v2', action='store_true',
                    help='lado A usa evaluate_state_v2 + eval_weights.json; B fica v1 (deployment real)')
    ap.add_argument('--workers', type=int, default=1,
                    help='processos paralelos (1=sequencial, comportamento de sempre)')
    args = ap.parse_args()

    deck_a = load_sim_deck(args.deck_a)
    deck_b = load_sim_deck(args.deck_b)

    side_a_v2 = None
    if args.side_a_v2:
        import json as _json
        from optcg_engine import decision_engine as _de
        wpath = Path(__file__).parent / 'eval_weights.json'
        side_a_v2 = dict(_de.EVAL_WEIGHTS)
        if wpath.exists():
            side_a_v2.update({k: v for k, v in _json.loads(wpath.read_text()).items()
                              if k != '_meta'})
        print(f'[v2] lado A = evaluate_state_v2 tunado; lado B = v1')

    sa, sb = _side_stats(), _side_stats()
    turnos_total = 0

    # Mesma derivacao de seed por-partida (args.seed * 1_000_003 + i) nos
    # DOIS caminhos -- achado ao testar: usar `random.seed(args.seed)` uma
    # vez so (encadeado entre partidas, comportamento antigo) no sequencial
    # e a seed derivada no paralelo dava resultados DIFERENTES pro mesmo
    # --seed, quebrando a promessa de "--workers so muda o tempo, nao o
    # resultado". Unificado: `--workers 1` tambem usa `_play_one_match`/
    # `_accumulate` com seed por indice, entao trocar --workers e
    # reprodutivel (mesmo --seed = mesmos N resultados, sequencial ou nao).
    tasks = [(args.deck_a, args.deck_b, args.seed * 1_000_003 + i, side_a_v2)
             for i in range(args.n)]
    if args.workers <= 1:
        resultados_brutos = [_worker_task(t) for t in tasks]
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            resultados_brutos = list(ex.map(_worker_task, tasks))
    for raw in resultados_brutos:
        _accumulate(raw, sa, sb)
        turnos_total += raw['turnos']

    resA, resB = _fmt(sa, args.n), _fmt(sb, args.n)
    resumo = {
        'deck_a': args.deck_a, 'deck_b': args.deck_b,
        'n': args.n, 'seed': args.seed,
        'turnos_medios': round(turnos_total / args.n, 1),
        'A': resA, 'B': resB,
    }

    print(f"\n=== BASELINE: {args.deck_a} (A) vs {args.deck_b} (B) — "
          f"{args.n} jogos, seed={args.seed}, {resumo['turnos_medios']} turnos/jogo ===")
    cols = ['winrate', 'atk_por_turno', 'pct_atk_lider', 'dano_por_jogo',
            'don_por_atk', 'counter_power_por_jogo']
    print(f"  {'métrica':18s} {'A (' + args.deck_a[:10] + ')':>16s} {'B (' + args.deck_b[:10] + ')':>16s}")
    for c in cols:
        print(f"  {c:18s} {resA[c]:>16} {resB[c]:>16}")

    if args.json:
        Path(args.json).write_text(json.dumps(resumo, indent=2, ensure_ascii=False),
                                   encoding='utf-8')
        print(f"\n-> salvo em {args.json}")


if __name__ == '__main__':
    main()
