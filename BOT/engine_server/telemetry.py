"""Telemetria JSONL append-only para decisoes do bot ao vivo."""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = Path(__file__).resolve().parent / "logs" / "decisions"
LOG_DIR.mkdir(parents=True, exist_ok=True)
SESSION_ID = dt.datetime.now().strftime("%Y-%m-%dT%H.%M.%S")
PATH = LOG_DIR / f"decisions_{SESSION_ID}.jsonl"
_LOCK = threading.Lock()


def _commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
            stderr=subprocess.DEVNULL, timeout=2,
        ).strip()
    except Exception:
        return "unknown"


COMMIT = _commit()


def _modelo() -> str | None:
    """Hash do Q em uso (bloco 913, INSTRUCAO_MESTRA item 21): responde "qual
    modelo produziu este jogo?". `geracoes.id_do_hash` traduz pra geracao."""
    try:
        import hashlib
        caminho = ROOT / 'scriptis_da_ia' / 'metrics' / 'q_net.joblib'
        return hashlib.sha256(caminho.read_bytes()).hexdigest()[:12]
    except Exception:
        return None


MODELO = _modelo()


def new_decision_id() -> str:
    return uuid.uuid4().hex


def write_event(event: str, decision_id: str, **payload: Any) -> None:
    record = {
        "schema": 1,
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "session_id": SESSION_ID,
        "commit": COMMIT,
        "modelo": MODELO,
        "event": event,
        "decision_id": decision_id,
        **payload,
    }
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    with _LOCK:
        with PATH.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

