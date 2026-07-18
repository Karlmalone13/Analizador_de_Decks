#!/usr/bin/env python3
"""Compara dois relatorios do proxy sem misturar execucao e estrategia."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

HIGHER_IS_BETTER = {
    "execution_success_pct": True,
    "legal_actions_coverage_pct": True,
    "chosen_score_coverage_pct": True,
    "state_after_coverage_pct": True,
    "counterfactual_coverage_pct": True,
    "outcome_coverage_pct": True,
    "mean_counterfactual_regret": False,
}


def _latest_live(report: dict) -> dict:
    logs = report.get("decision_logs") or []
    return logs[-1] if logs else {}


def compare_reports(before: dict, after: dict) -> dict:
    a, b = _latest_live(before), _latest_live(after)
    compatibility = []
    if before.get("manifest") != after.get("manifest"):
        compatibility.append("manifest diferente")
    if before.get("bootstrap_seed") != after.get("bootstrap_seed"):
        compatibility.append("bootstrap_seed diferente")
    commits_a = set((a.get("commit_consistency") or {}).get("commits") or [])
    commits_b = set((b.get("commit_consistency") or {}).get("commits") or [])
    if not a or not b:
        compatibility.append("um dos relatorios nao possui decision_logs")

    metrics = {}
    for name, higher in HIGHER_IS_BETTER.items():
        old, new = a.get(name), b.get(name)
        if old is None or new is None:
            metrics[name] = {"before": old, "after": new, "delta": None,
                             "verdict": "unavailable"}
            continue
        delta = round(float(new) - float(old), 3)
        improved = delta > 0 if higher else delta < 0
        regressed = delta < 0 if higher else delta > 0
        metrics[name] = {"before": old, "after": new, "delta": delta,
                         "verdict": "improved" if improved else
                                    "regressed" if regressed else "unchanged"}

    latency_a, latency_b = a.get("latency_ms") or {}, b.get("latency_ms") or {}
    for name in ("mean", "p95", "max", "timeout_pct"):
        old, new = latency_a.get(name), latency_b.get(name)
        key = f"latency_{name}"
        if old is None or new is None:
            metrics[key] = {"before": old, "after": new, "delta": None,
                            "verdict": "unavailable"}
        else:
            delta = round(float(new) - float(old), 3)
            metrics[key] = {"before": old, "after": new, "delta": delta,
                            "verdict": "improved" if delta < 0 else
                                       "regressed" if delta > 0 else "unchanged"}

    return {
        "schema": 1,
        "compatible": not compatibility,
        "compatibility_warnings": compatibility,
        "before_commits": sorted(commits_a),
        "after_commits": sorted(commits_b),
        "metrics": metrics,
        "regressions": [name for name, value in metrics.items()
                        if value["verdict"] == "regressed"],
        "note": "comparacao causal exige mesmos snapshots ou seeds/decks; este diff nao inventa causalidade",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("before", type=Path)
    ap.add_argument("after", type=Path)
    ap.add_argument("--json", dest="output", type=Path)
    args = ap.parse_args()
    result = compare_reports(json.loads(args.before.read_text(encoding="utf-8")),
                             json.loads(args.after.read_text(encoding="utf-8")))
    rendered = json.dumps(result, indent=2, ensure_ascii=False)
    print(rendered)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 1 if result["regressions"] or not result["compatible"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
