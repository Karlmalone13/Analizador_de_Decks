"""
db.py — Camada de acesso ao Postgres (Supabase)
================================================
Conexão direta via asyncpg (sem ORM) com o banco criado pela migration
migrations/001_simulation_tables.sql. Usa DATABASE_URL do ambiente.

Mantém esta camada fina: só CRUD nas 3 tabelas (simulation_jobs,
meta_decklists, user_decks). Lógica de simulação fica em outro módulo
(simulation_worker.py), que importa daqui só o necessário para ler/escrever
o estado do job.
"""
import json
import os
from typing import Any, Optional
from uuid import UUID

import asyncpg

_DATABASE_URL = os.environ.get("DATABASE_URL")

_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    """
    Pool de conexões compartilhado pela aplicação inteira. Criado de forma
    lazy (na primeira chamada) porque a criação do pool é async e o FastAPI
    sobe o app antes de qualquer event loop estar disponível para isso no
    import-time.
    """
    global _pool
    if _pool is None:
        if not _DATABASE_URL:
            raise RuntimeError(
                "DATABASE_URL não está definida no ambiente. "
                "Configure a connection string do Postgres (Supabase) "
                "como variável de ambiente antes de usar qualquer função deste módulo."
            )
        _pool = await asyncpg.create_pool(
            _DATABASE_URL,
            min_size=1,
            max_size=10,
            # a simulação roda em BackgroundTasks no mesmo processo da API;
            # um teto baixo evita esgotar conexões do Supabase (free tier
            # tem limite de conexões simultâneas baixo).
        )
    return _pool


async def close_pool():
    """Chamar no shutdown do FastAPI (lifespan) para fechar conexões limpo."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


# ─────────────────────────────────────────────────────────────────────────
# simulation_jobs
# ─────────────────────────────────────────────────────────────────────────

async def create_job(
    analysis_type: str,
    deck_a: list[dict],
    deck_b: Optional[list[dict]] = None,
    meta_filter: Optional[dict] = None,
    n_simulations: int = 10,
    n_meta_decks: Optional[int] = None,
    total_steps: Optional[int] = None,
    user_id: Optional[str] = None,
) -> str:
    """Insere um novo job com status='pending' e devolve o id (str UUID)."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO simulation_jobs
            (user_id, analysis_type, deck_a, deck_b, meta_filter,
             n_simulations, n_meta_decks, total_steps)
        VALUES ($1, $2, $3::jsonb, $4::jsonb, $5::jsonb, $6, $7, $8)
        RETURNING id
        """,
        UUID(user_id) if user_id else None,
        analysis_type,
        json.dumps(deck_a),
        json.dumps(deck_b) if deck_b is not None else None,
        json.dumps(meta_filter) if meta_filter is not None else None,
        n_simulations,
        n_meta_decks,
        total_steps,
    )
    return str(row["id"])


async def get_job(job_id: str) -> Optional[dict]:
    """Devolve o job como dict (campos JSONB já decodificados), ou None se não existir."""
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM simulation_jobs WHERE id = $1", UUID(job_id)
    )
    if row is None:
        return None
    return _job_row_to_dict(row)


async def update_job_progress(job_id: str, progress: int, status: str = "running"):
    pool = await get_pool()
    await pool.execute(
        "UPDATE simulation_jobs SET progress = $1, status = $2 WHERE id = $3",
        progress, status, UUID(job_id),
    )


async def finish_job(job_id: str, result: dict):
    pool = await get_pool()
    await pool.execute(
        "UPDATE simulation_jobs SET status = 'done', result = $1::jsonb, progress = total_steps WHERE id = $2",
        json.dumps(result), UUID(job_id),
    )


async def fail_job(job_id: str, error_message: str):
    pool = await get_pool()
    await pool.execute(
        "UPDATE simulation_jobs SET status = 'error', error_message = $1 WHERE id = $2",
        error_message, UUID(job_id),
    )


def _job_row_to_dict(row: asyncpg.Record) -> dict:
    d = dict(row)
    d["id"] = str(d["id"])
    if d.get("user_id"):
        d["user_id"] = str(d["user_id"])
    for jsonb_field in ("deck_a", "deck_b", "meta_filter", "result"):
        if d.get(jsonb_field) is not None and isinstance(d[jsonb_field], str):
            d[jsonb_field] = json.loads(d[jsonb_field])
    for ts_field in ("created_at", "updated_at"):
        if d.get(ts_field) is not None:
            d[ts_field] = d[ts_field].isoformat()
    return d


# ─────────────────────────────────────────────────────────────────────────
# meta_decklists
# ─────────────────────────────────────────────────────────────────────────

async def list_meta_decklists(
    is_current_meta: Optional[bool] = None,
    set_codes: Optional[list[str]] = None,
    limit: int = 20,
) -> list[dict]:
    """
    Lista decklists do meta para a Análise 1. Filtros são opcionais e
    combináveis. `limit` aplica o teto de 20 decklists acordado para a
    primeira versão da Análise 1 (evitar custo computacional descontrolado).
    """
    pool = await get_pool()
    conditions = []
    params: list[Any] = []

    if is_current_meta is not None:
        params.append(is_current_meta)
        conditions.append(f"is_current_meta = ${len(params)}")
    if set_codes:
        params.append(set_codes)
        conditions.append(f"set_code = ANY(${len(params)})")

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)
    query = f"""
        SELECT id, name, leader_code, set_code, cards, source_url, is_current_meta, win_rate
        FROM meta_decklists
        {where_clause}
        ORDER BY created_at DESC
        LIMIT ${len(params)}
    """
    rows = await pool.fetch(query, *params)
    out = []
    for r in rows:
        d = dict(r)
        d["id"] = str(d["id"])
        if isinstance(d.get("cards"), str):
            d["cards"] = json.loads(d["cards"])
        out.append(d)
    return out


async def insert_meta_decklist(
    name: str,
    leader_code: str,
    cards: list[dict],
    set_code: Optional[str] = None,
    source_url: Optional[str] = None,
    is_current_meta: bool = True,
    win_rate: Optional[float] = None,
) -> str:
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO meta_decklists
            (name, leader_code, set_code, cards, source_url, is_current_meta, win_rate)
        VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7)
        RETURNING id
        """,
        name, leader_code, set_code, json.dumps(cards), source_url, is_current_meta, win_rate,
    )
    return str(row["id"])


# ─────────────────────────────────────────────────────────────────────────
# user_decks
# ─────────────────────────────────────────────────────────────────────────

async def list_user_decks(user_id: str) -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT id, name, leader_code, cards, created_at FROM user_decks WHERE user_id = $1 ORDER BY created_at DESC",
        UUID(user_id),
    )
    out = []
    for r in rows:
        d = dict(r)
        d["id"] = str(d["id"])
        if isinstance(d.get("cards"), str):
            d["cards"] = json.loads(d["cards"])
        d["created_at"] = d["created_at"].isoformat()
        out.append(d)
    return out


async def get_user_deck(deck_id: str) -> Optional[dict]:
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT id, user_id, name, leader_code, cards FROM user_decks WHERE id = $1",
        UUID(deck_id),
    )
    if row is None:
        return None
    d = dict(row)
    d["id"] = str(d["id"])
    d["user_id"] = str(d["user_id"])
    if isinstance(d.get("cards"), str):
        d["cards"] = json.loads(d["cards"])
    return d


async def insert_user_deck(user_id: str, name: str, leader_code: str, cards: list[dict]) -> str:
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO user_decks (user_id, name, leader_code, cards)
        VALUES ($1, $2, $3, $4::jsonb)
        RETURNING id
        """,
        UUID(user_id), name, leader_code, json.dumps(cards),
    )
    return str(row["id"])