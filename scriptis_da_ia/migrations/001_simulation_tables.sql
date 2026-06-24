-- migrations/001_simulation_tables.sql
-- ============================================================================
-- Sistema de Simulacao de Partidas (Turn Planner + Opponent Reading)
-- Cria as 3 tabelas necessarias para as 3 analises:
--   1. Deck do usuario contra meta       (simulation_jobs + meta_decklists)
--   2. Deck do usuario contra deck colado (simulation_jobs, deck_b inline)
--   3. Deck do usuario contra seus proprios decks (simulation_jobs + user_decks)
--
-- Rodar no SQL Editor do Supabase, na ordem em que aparecem neste arquivo.
-- ============================================================================

-- Extensao necessaria para gen_random_uuid() (geralmente ja vem habilitada
-- por padrao no Supabase, mas garante caso nao esteja).
CREATE EXTENSION IF NOT EXISTS pgcrypto;


-- ============================================================================
-- 1) simulation_jobs
-- Controla o ciclo de vida de cada pedido de simulacao (padrao fila +
-- polling: o cliente HTTP nunca espera o trabalho pesado terminar).
-- ============================================================================
CREATE TABLE IF NOT EXISTS simulation_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID,                              -- dono do job (FK logica para auth.users, sem FK fisica por simplicidade)
    analysis_type   TEXT NOT NULL CHECK (analysis_type IN ('meta', 'custom_opponent', 'own_decks')),
    status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'done', 'error')),

    deck_a          JSONB NOT NULL,                    -- decklist do usuario: [{"code": "OP15-001", "qty": 4}, ...]
    deck_b          JSONB,                              -- decklist do oponente (custom_opponent / own_decks). NULL quando analysis_type='meta'.
    meta_filter     JSONB,                              -- filtros para 'meta' (ex: {"is_current_meta": true, "set_codes": ["OP-13","OP-14"]})

    n_simulations   INT NOT NULL DEFAULT 10,            -- partidas por matchup (Monte Carlo)
    n_meta_decks    INT,                                 -- quantos decks do meta rodar contra (so para analysis_type='meta')

    progress        INT NOT NULL DEFAULT 0,             -- simulacoes concluidas (para barra de progresso real)
    total_steps     INT,                                 -- total esperado: n_simulations (custom/own) ou n_simulations*n_meta_decks (meta)

    result          JSONB,                               -- resultado final (taxa de vitoria, breakdown por matchup, etc)
    error_message   TEXT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Consulta mais comum: "meus jobs, mais recentes primeiro"
CREATE INDEX IF NOT EXISTS idx_simulation_jobs_user_created
    ON simulation_jobs (user_id, created_at DESC);

-- Consulta do worker: "jobs pendentes para processar"
CREATE INDEX IF NOT EXISTS idx_simulation_jobs_status
    ON simulation_jobs (status)
    WHERE status IN ('pending', 'running');


-- ============================================================================
-- 2) meta_decklists
-- Decklists do meta (atual e historico) para a Analise 1. Populamento e
-- trabalho futuro -- a tabela nasce vazia, pronta para receber dados.
-- ============================================================================
CREATE TABLE IF NOT EXISTS meta_decklists (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,                      -- ex: "Red Zoro OP-13 Regional Winner"
    leader_code     TEXT NOT NULL,                      -- ex: "OP13-001"
    set_code        TEXT,                                -- edicao de origem, para filtrar atual/historico (ex: "OP-13")
    cards           JSONB NOT NULL,                      -- [{"code": "OP13-042", "qty": 4}, ...] -- SEM o leader, so o resto do deck (50 cartas)
    source_url      TEXT,                                -- de onde veio (Limitless, etc), para auditoria
    is_current_meta BOOLEAN NOT NULL DEFAULT true,       -- permite filtrar "meta atual" vs "historico" nas consultas
    win_rate        NUMERIC,                              -- taxa de vitoria conhecida da lista original (se disponivel), so referencia
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_meta_decklists_current
    ON meta_decklists (is_current_meta, leader_code);

CREATE INDEX IF NOT EXISTS idx_meta_decklists_set
    ON meta_decklists (set_code);


-- ============================================================================
-- 3) user_decks
-- Decks salvos do proprio usuario, para a Analise 3 (deck vs deck, ambos
-- do usuario) e tambem como origem possivel do deck_a em qualquer analise.
-- ============================================================================
CREATE TABLE IF NOT EXISTS user_decks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL,
    name            TEXT NOT NULL,
    leader_code     TEXT NOT NULL,
    cards           JSONB NOT NULL,                      -- [{"code": "...", "qty": N}, ...]
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_user_decks_user
    ON user_decks (user_id, created_at DESC);


-- ============================================================================
-- Trigger generico para manter updated_at sincronizado em UPDATE
-- ============================================================================
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_simulation_jobs_updated_at ON simulation_jobs;
CREATE TRIGGER trg_simulation_jobs_updated_at
    BEFORE UPDATE ON simulation_jobs
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_user_decks_updated_at ON user_decks;
CREATE TRIGGER trg_user_decks_updated_at
    BEFORE UPDATE ON user_decks
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();