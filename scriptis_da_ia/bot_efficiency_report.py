#!/usr/bin/env python3
"""Relatorio reproduzivel de eficiencia observavel em combat logs.

Exemplos:
    python bot_efficiency_report.py
    python bot_efficiency_report.py --json metrics/report.json
    python bot_efficiency_report.py --proxy baseline_imu_vs_teach.json
    python bot_efficiency_report.py --manifest metrics/meus_cohorts.json
"""
from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent
PARSED_ROOT = ROOT / "logs" / "parsed"
DEFAULT_MANIFEST = ROOT / "metrics" / "bot_efficiency_cohorts.json"
EXPECTED_SNAPSHOT_FIELDS = ("hand", "board", "trash", "life")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _player_leader(data: dict, player: str) -> dict:
    for slot in ("p1", "p2"):
        info = data.get("meta", {}).get("players", {}).get(slot, {})
        if info.get("name") == player:
            return info.get("leader", {})
    return {}


def _opponent_player(data: dict, player: str) -> str | None:
    names = [data.get("meta", {}).get("players", {}).get(s, {}).get("name")
             for s in ("p1", "p2")]
    return next((name for name in names if name and name != player), None)


def _is_leader_target(target: Any, leader: dict) -> bool:
    if isinstance(target, dict):
        return target.get("type") == "LEADER" or target.get("code") == leader.get("code")
    text = str(target or "").lower()
    code = str(leader.get("code") or "").lower()
    name = str(leader.get("name") or "").lower()
    return bool((code and code in text) or (name and name in text))


def _match_stats(data: dict, player: str, expected_leader: str, file_name: str) -> dict:
    own_leader = _player_leader(data, player)
    if own_leader.get("code") != expected_leader:
        raise ValueError(
            f"{file_name}: {player} usa {own_leader.get('code')!r}, esperado {expected_leader!r}"
        )
    opponent = _opponent_player(data, player)
    if not opponent:
        raise ValueError(f"{file_name}: oponente nao encontrado")
    opp_leader = _player_leader(data, opponent)

    turns = data.get("turns", [])
    own_turns = [turn for turn in turns if turn.get("player") == player]
    attacks: list[dict] = []
    attaches = 0
    passive_turns = 0
    first_attack_turn = None
    for own_index, turn in enumerate(own_turns, start=1):
        turn_attacks = [a for a in turn.get("actions", []) if a.get("type") == "attack"]
        attacks.extend(turn_attacks)
        attaches += sum(int(a.get("amount") or 0) for a in turn.get("actions", [])
                        if a.get("type") == "attach_don")
        if turn_attacks and first_attack_turn is None:
            first_attack_turn = turn.get("turn")
        if own_index >= 2 and not turn_attacks:
            passive_turns += 1

    snapshot_turns = 0
    snapshot_fields_present = 0
    snapshot_fields_expected = len(turns) * 2 * len(EXPECTED_SNAPSHOT_FIELDS)
    for turn in turns:
        snap = turn.get("snapshot") or {}
        if snap:
            snapshot_turns += 1
        for side in (player, opponent):
            state = snap.get(side, {})
            snapshot_fields_present += sum(field in state for field in EXPECTED_SNAPSHOT_FIELDS)

    leader_hits = [a for a in attacks
                   if _is_leader_target(a.get("target"), opp_leader)
                   and a.get("result") == "hit"]
    return {
        "file": file_name,
        "games": 1,
        "turns": len(turns),
        "own_turns": len(own_turns),
        "attacks": len(attacks),
        "leader_attacks": sum(_is_leader_target(a.get("target"), opp_leader) for a in attacks),
        # O parser marca hit sem quantidade quando o log nao emite "hit for N".
        # Contra lider isso vale ao menos 1 vida; preserva Double Attack quando N>1.
        "damage": sum(max(1, int(a.get("damage") or 0)) for a in leader_hits),
        "counters_forced": sum(len(a.get("countered_by") or []) for a in attacks),
        "passive_turns": passive_turns,
        "first_attack_turn_sum": int(first_attack_turn or 0),
        "games_with_attack": int(first_attack_turn is not None),
        "attach_don_observed": attaches,
        "snapshot_turns": snapshot_turns,
        "snapshot_fields_present": snapshot_fields_present,
        "snapshot_fields_expected": snapshot_fields_expected,
    }


def _sum_matches(matches: list[dict]) -> dict:
    keys = [k for k in matches[0] if k != "file"] if matches else []
    return {key: sum(float(m[key]) for m in matches) for key in keys}


def _ratio(n: float, d: float, scale: float = 1.0) -> float | None:
    return scale * n / d if d else None


METRICS: dict[str, Callable[[dict], float | None]] = {
    "atk_por_turno": lambda s: _ratio(s["attacks"], s["own_turns"]),
    "pct_atk_lider": lambda s: _ratio(s["leader_attacks"], s["attacks"], 100),
    "dano_por_jogo": lambda s: _ratio(s["damage"], s["games"]),
    "counters_arrancados_por_jogo": lambda s: _ratio(s["counters_forced"], s["games"]),
    "turnos_passivos_por_jogo": lambda s: _ratio(s["passive_turns"], s["games"]),
    "primeiro_ataque_turno_medio": lambda s: _ratio(s["first_attack_turn_sum"], s["games_with_attack"]),
    "don_observado_por_ataque": lambda s: _ratio(s["attach_don_observed"], s["attacks"]),
    "snapshot_coverage_pct": lambda s: _ratio(s["snapshot_turns"], s["turns"], 100),
    "snapshot_completeness_pct": lambda s: _ratio(
        s["snapshot_fields_present"], s["snapshot_fields_expected"], 100
    ),
}


def _round(value: float | None) -> float | None:
    return None if value is None or not math.isfinite(value) else round(value, 3)


def _bootstrap(matches: list[dict], metric: Callable[[dict], float | None],
               samples: int, rng: random.Random) -> list[float]:
    if not matches:
        return []
    values = []
    for _ in range(samples):
        picked = [matches[rng.randrange(len(matches))] for _ in matches]
        value = metric(_sum_matches(picked))
        if value is not None and math.isfinite(value):
            values.append(value)
    return sorted(values)


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    index = (len(values) - 1) * q
    lo, hi = math.floor(index), math.ceil(index)
    if lo == hi:
        return values[lo]
    return values[lo] * (hi - index) + values[hi] * (index - lo)


def analyze_cohort(cohort: dict, parsed_root: Path, samples: int, seed: int) -> dict:
    matches = []
    for item in cohort.get("matches", []):
        path = parsed_root / item["file"]
        if not path.exists():
            raise FileNotFoundError(f"arquivo do cohort ausente: {path}")
        matches.append(_match_stats(
            _load_json(path), item["player"], cohort["leader_code"], item["file"]
        ))
    total = _sum_matches(matches)
    rng = random.Random(seed)
    metrics = {}
    for name, fn in METRICS.items():
        boot = _bootstrap(matches, fn, samples, rng)
        metrics[name] = {
            "value": _round(fn(total)),
            "ci95": [_round(_percentile(boot, 0.025)), _round(_percentile(boot, 0.975))],
        }
    return {
        "label": cohort["label"],
        "leader_code": cohort["leader_code"],
        "n_games": len(matches),
        "metrics": metrics,
        "availability": {
            "state_fidelity": None,
            "decision_quality": None,
            "execution_success": None,
            "reason": "combat logs atuais nao tem verdade do DTO, snapshot pre-acao ou action_id confirmado",
        },
        "warnings": [
            "DON observado pode subcontar attaches do bot via reflection",
            "intervalos com menos de 20 partidas sao exploratorios",
        ],
        "matches": matches,
    }


def _proxy(path: Path, side: str) -> dict:
    data = _load_json(path)
    stats = data.get(side, {})
    return {
        "source": str(path),
        "side": side,
        "n_games": data.get("n"),
        "seed": data.get("seed"),
        "deck_a": data.get("deck_a"),
        "deck_b": data.get("deck_b"),
        "metrics": stats,
        "warning": "proxy motor-vs-motor; nao mede DTO, bridge, visao ou clique",
    }


def _fmt_metric(metric: dict) -> str:
    value = metric["value"]
    lo, hi = metric["ci95"]
    if value is None:
        return "n/d"
    return f"{value:.3f} (IC95% {lo:.3f}..{hi:.3f})"


def print_report(report: dict) -> None:
    print("=== EFICIENCIA OBSERVAVEL DO BOT ===")
    for cohort in report["cohorts"]:
        print(f"\n[{cohort['label']}] n={cohort['n_games']}")
        for name, metric in cohort["metrics"].items():
            print(f"  {name:34s} {_fmt_metric(metric)}")
        print("  state_fidelity/decision/execution: n/d (telemetria ausente)")
    for proxy in report.get("proxies", []):
        print(f"\n[proxy] {proxy['source']} lado={proxy['side']} n={proxy['n_games']}")
        for name, value in proxy["metrics"].items():
            print(f"  {name:34s} {value}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--parsed-root", type=Path, default=PARSED_ROOT)
    ap.add_argument("--bootstrap", type=int, default=5000)
    ap.add_argument("--seed", type=int, default=20260717)
    ap.add_argument("--proxy", action="append", type=Path, default=[])
    ap.add_argument("--proxy-side", choices=("A", "B"), default="A")
    ap.add_argument("--json", dest="json_out", type=Path)
    args = ap.parse_args()

    manifest = _load_json(args.manifest)
    if manifest.get("schema") != 1:
        raise ValueError("manifest schema deve ser 1")
    report = {
        "schema": 1,
        "manifest": str(args.manifest),
        "bootstrap_samples": args.bootstrap,
        "bootstrap_seed": args.seed,
        "cohorts": [
            analyze_cohort(c, args.parsed_root, args.bootstrap, args.seed + i)
            for i, c in enumerate(manifest.get("cohorts", []))
        ],
        "proxies": [_proxy(path, args.proxy_side) for path in args.proxy],
    }
    print_report(report)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                                 encoding="utf-8")
        print(f"\nSalvo em {args.json_out}")


if __name__ == "__main__":
    main()
