#!/usr/bin/env python3
"""Preserva o combat log mais recente e gera o relatorio da sessao em 1 comando.

Tambem e chamado automaticamente pelo engine_server quando recebe `outcome`.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
DEFAULT_AUTOSAVED = Path(
    os.environ.get(
        "OPTCGSIM_AUTOSAVED_DIR",
        r"E:\Games\OnePieceSimulador\Builds_Windows\CombatLogs\AutoSaved",
    )
)


def _latest_log(directory: Path, max_age_seconds: int = 1800) -> Path:
    candidates = [p for p in directory.glob("*.log") if p.is_file()]
    if not candidates:
        raise FileNotFoundError(f"nenhum .log encontrado em {directory}")
    latest = max(candidates, key=lambda p: p.stat().st_mtime)
    age = time.time() - latest.stat().st_mtime
    if age > max_age_seconds:
        raise FileNotFoundError(
            f"log mais recente tem {age / 60:.0f} min; recusado para nao associar partida antiga: {latest}"
        )
    return latest


def _wait_stable(path: Path, attempts: int = 12, interval: float = 1.0) -> None:
    previous = -1
    stable = 0
    for _ in range(attempts):
        size = path.stat().st_size
        stable = stable + 1 if size == previous else 0
        if stable >= 2:
            return
        previous = size
        time.sleep(interval)
    raise TimeoutError(f"combat log ainda esta sendo gravado: {path}")


def collect_latest(decision_log: Path, autosaved_dir: Path = DEFAULT_AUTOSAVED,
                   match_id: str = "") -> dict:
    combat_log = _latest_log(autosaved_dir)
    _wait_stable(combat_log)
    if not decision_log.exists():
        raise FileNotFoundError(f"decision log ausente: {decision_log}")

    stamp = datetime.now().strftime("%Y-%m-%dT%H.%M.%S")
    output_dir = ROOT / "metrics" / "live_runs"
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"live_{stamp}.json"

    parse_cmd = [sys.executable, str(ROOT / "parse_combat_log.py"),
                 str(combat_log), "--add-to-db"]
    report_cmd = [sys.executable, str(ROOT / "bot_efficiency_report.py"),
                  "--decision-log", str(decision_log),
                  "--json", str(report_path)]
    parsed = subprocess.run(parse_cmd, cwd=ROOT, text=True, capture_output=True)
    if parsed.returncode:
        raise RuntimeError(f"parse_combat_log falhou: {parsed.stderr or parsed.stdout}")
    reported = subprocess.run(report_cmd, cwd=ROOT, text=True, capture_output=True)
    if reported.returncode:
        raise RuntimeError(f"bot_efficiency_report falhou: {reported.stderr or reported.stdout}")

    receipt = {
        "schema": 1,
        "match_id": match_id or None,
        "combat_log": str(combat_log),
        "decision_log": str(decision_log),
        "report": str(report_path),
        "collected_at": stamp,
    }
    receipt_path = output_dir / f"receipt_{stamp}.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
    receipt["receipt"] = str(receipt_path)
    return receipt


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--decision-log", type=Path,
                    help="default: JSONL mais recente do engine_server")
    ap.add_argument("--autosaved-dir", type=Path, default=DEFAULT_AUTOSAVED)
    args = ap.parse_args()
    decision_log = args.decision_log
    if decision_log is None:
        logs = list((REPO / "BOT" / "engine_server" / "logs" / "decisions").glob("*.jsonl"))
        if not logs:
            raise FileNotFoundError("nenhum decision JSONL encontrado")
        decision_log = max(logs, key=lambda p: p.stat().st_mtime)
    result = collect_latest(decision_log, args.autosaved_dir)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
