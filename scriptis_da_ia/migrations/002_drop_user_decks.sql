-- migrations/002_drop_user_decks.sql
-- ============================================================================
-- Remove a tabela user_decks, criada erroneamente na migration 001 antes de
-- se descobrir que o frontend Next.js já tem uma tabela `decks` própria,
-- em uso real (criação/edição/listagem de decks do usuário já acontece
-- nela via src/app/deck/page.tsx e src/app/meus-decks/page.tsx).
--
-- user_decks nunca foi populada em produção (nenhum código do frontend
-- escreve nela) -- é seguro remover sem risco de perda de dados.
--
-- A partir desta migration, qualquer funcionalidade Python que precise
-- ler decks salvos do usuário (Análise 3: deck vs deck, ambos do
-- usuário) usa a tabela `decks` diretamente, formato real:
--   decks(id, user_id, name, leader_id, cards, updated_at)
--   cards é uma STRING JSON (não JSONB) serializada pelo frontend:
--   {"leader": {...Card}, "cards": [{"card": {...Card}, "quantity": N}]}
--
-- Rodar no SQL Editor do Supabase.
-- ============================================================================

DROP TRIGGER IF EXISTS trg_user_decks_updated_at ON user_decks;
DROP TABLE IF EXISTS user_decks;