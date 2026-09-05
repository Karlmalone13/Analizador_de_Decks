-- migrations/002_add_cancelled_status.sql
-- ============================================================================
-- Adiciona 'cancelled' aos status permitidos de simulation_jobs (pedido do
-- usuario, 05/09/2026 -- botao de cancelar uma simulacao em andamento no
-- front). O CHECK original (001_simulation_tables.sql) so permitia
-- 'pending'/'running'/'done'/'error'; sem esta migration, `db.cancel_job()`
-- falharia com violacao de constraint.
--
-- Rodar no SQL Editor do Supabase, uma vez.
-- ============================================================================

ALTER TABLE simulation_jobs
    DROP CONSTRAINT IF EXISTS simulation_jobs_status_check;

ALTER TABLE simulation_jobs
    ADD CONSTRAINT simulation_jobs_status_check
    CHECK (status IN ('pending', 'running', 'done', 'error', 'cancelled'));
