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
DB_ROOT = ROOT / "logs"
DB_INDEX = DB_ROOT / "index.json"
# Achado 19/07 (leitura do decompilado GameplayLogicScript.cs): o jogo tem
# DUAS gravacoes diferentes. `CombatLogs/AutoSaved/` (SaveMyLogLines) e um
# autosave continuo que corta ANTES do desfecho -- confirmado em 5/5 logs do
# bot que chegaram perto do fim (ver HANDOFF bloco 285). `CombatLogs/` (pasta
# pai, sem AutoSaved) e onde DownloadLogLines() escreve o log CHEIO, incluindo
# as linhas "Downloaded the Combat Log!"/"GameOver". BotDriver.cs agora chama
# gls.DownloadLogLines() direto no GameOver (nao precisa clicar o botao na
# UI) -- por isso a pasta default mudou daqui pra frente. Mantem o nome da
# env var por compatibilidade (quem ja tinha ela setada testando AutoSaved
# pode apontar pra qualquer uma das duas).
DEFAULT_AUTOSAVED = Path(
    os.environ.get(
        "OPTCGSIM_AUTOSAVED_DIR",
        r"E:\Games\OnePieceSimulador\Builds_Windows\CombatLogs",
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


def _validate_bank_entry(combat_log: Path, index: list, db_root: Path = DB_ROOT) -> tuple[dict, str]:
    entry = next((item for item in reversed(index) if item.get("id") == combat_log.stem), None)
    if entry is None:
        raise RuntimeError(f"parser terminou sem registrar id={combat_log.stem} no index")
    required = [entry.get("log_file"), entry.get("parsed_file")]
    required.extend((entry.get("deck_files") or {}).values())
    missing = [rel for rel in required if not rel or not (db_root / rel).is_file()]
    if missing:
        raise RuntimeError(f"entrada existe, mas artefatos do banco estao ausentes: {missing}")
    canonical_stem = Path(entry["log_file"]).stem
    if "_x_" not in canonical_stem or not canonical_stem.endswith(f"_{combat_log.stem}"):
        raise RuntimeError(f"nome fora do padrao Lider-Cores_x_Lider-Cores_timestamp: {canonical_stem}")
    return entry, canonical_stem


def _apply_winner(index: list, entry_id: str, result: str,
                  bot_seat: str = "p1") -> None:
    """Preenche o 'winner' do index a partir do resultado da telemetria.

    O combat log baixado pelo jogo e cortado antes das linhas finais
    (Downloaded the Combat Log!/GameOver) -- parse_combat_log.py nao tem
    como saber quem venceu so pelo texto. O resultado do /outcome e da
    perspectiva do BOT; `bot_seat` diz em qual assento do log o bot estava
    ("p1" = label [You], "p2" = [Opponent]). A versao anterior assumia
    bot=p1 SEMPRE e invertia o vencedor quando o bot controlava o outro
    lado (achado real 22/07: Kid x Katakuri, bot=Katakuri=[Opponent]
    perdeu 6-0 e o index registrou winner=p2).
    """
    if result not in {"win", "loss"}:
        return
    if bot_seat not in {"p1", "p2"}:
        bot_seat = "p1"
    opp_seat = "p2" if bot_seat == "p1" else "p1"
    for item in index:
        if item.get("id") == entry_id:
            item["winner"] = bot_seat if result == "win" else opp_seat
            return


def collect_latest(decision_log: Path, autosaved_dir: Path = DEFAULT_AUTOSAVED,
                   match_id: str = "", result: str = "",
                   bot_seat: str = "p1") -> dict:
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

    # Nao confia apenas no exit code: confirma a entrada e todos os artefatos
    # usando o schema/nome oficial produzido por parse_combat_log.add_to_db.
    index = json.loads(DB_INDEX.read_text(encoding="utf-8")) if DB_INDEX.exists() else []
    bank_entry, canonical_stem = _validate_bank_entry(combat_log, index)
    if result:
        _apply_winner(index, bank_entry["id"], result, bot_seat=bot_seat)
        DB_INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
        bank_entry = next(item for item in index if item.get("id") == bank_entry["id"])
    reported = subprocess.run(report_cmd, cwd=ROOT, text=True, capture_output=True)
    if reported.returncode:
        raise RuntimeError(f"bot_efficiency_report falhou: {reported.stderr or reported.stdout}")

    receipt = {
        "schema": 1,
        "match_id": match_id or None,
        "combat_log": str(combat_log),
        "decision_log": str(decision_log),
        "report": str(report_path),
        "bank_entry_id": bank_entry["id"],
        "bank_log": str(DB_ROOT / bank_entry["log_file"]),
        "bank_parsed": str(DB_ROOT / bank_entry["parsed_file"]),
        "bank_decks": [str(DB_ROOT / rel) for rel in (bank_entry.get("deck_files") or {}).values()],
        "canonical_name": canonical_stem,
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
    ap.add_argument("--result", choices=("win", "loss"),
                    help="resultado do bot, se conhecido (fallback manual sem /outcome)")
    args = ap.parse_args()
    decision_log = args.decision_log
    if decision_log is None:
        logs = list((REPO / "BOT" / "engine_server" / "logs" / "decisions").glob("*.jsonl"))
        if not logs:
            raise FileNotFoundError("nenhum decision JSONL encontrado")
        decision_log = max(logs, key=lambda p: p.stat().st_mtime)
    receipt = collect_latest(decision_log, args.autosaved_dir, result=args.result or "")
    print(json.dumps(receipt, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
