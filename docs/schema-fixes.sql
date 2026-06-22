-- Schema fixes to apply on Railway Postgres
-- Run after the initial table creation from issue #1

-- 1. Add content_hash to all four tables (needed for smart re-embed)
ALTER TABLE interests_vectors       ADD COLUMN IF NOT EXISTS content_hash TEXT;
ALTER TABLE party_donations_vectors ADD COLUMN IF NOT EXISTS content_hash TEXT;
ALTER TABLE votes_vectors           ADD COLUMN IF NOT EXISTS content_hash TEXT;
ALTER TABLE appg_vectors            ADD COLUMN IF NOT EXISTS content_hash TEXT;

-- 2. Replace the votes_vectors IVFFlat index with correct lists size
--    ~500k rows → lists ≈ sqrt(500000) ≈ 700
DROP INDEX IF EXISTS idx_votes_embedding_ivfflat;
CREATE INDEX IF NOT EXISTS idx_votes_embedding_ivfflat
  ON votes_vectors USING ivfflat (embedding vector_cosine_ops) WITH (lists = 700);

-- 3. Ingestion run audit log
CREATE TABLE IF NOT EXISTS ingest_runs (
    id          SERIAL      PRIMARY KEY,
    script      TEXT        NOT NULL,
    started_at  TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    status      TEXT        NOT NULL DEFAULT 'running',  -- running | success | error
    embedded    INT         NOT NULL DEFAULT 0,
    skipped     INT         NOT NULL DEFAULT 0,
    errors      INT         NOT NULL DEFAULT 0,
    notes       TEXT        NOT NULL DEFAULT ''
);

-- NOTE: All IVFFlat indexes should be dropped and recreated after the first
-- data load, because centroids are learned from existing rows. Empty-table
-- indexes have no meaningful centroids. Run this after initial ingestion:
--
--   DROP INDEX idx_interests_embedding_ivfflat;
--   DROP INDEX idx_party_donations_embedding_ivfflat;
--   DROP INDEX idx_votes_embedding_ivfflat;
--   DROP INDEX idx_appg_embedding_ivfflat;
--
--   CREATE INDEX idx_interests_embedding_ivfflat
--     ON interests_vectors USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
--   CREATE INDEX idx_party_donations_embedding_ivfflat
--     ON party_donations_vectors USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
--   CREATE INDEX idx_votes_embedding_ivfflat
--     ON votes_vectors USING ivfflat (embedding vector_cosine_ops) WITH (lists = 700);
--   CREATE INDEX idx_appg_embedding_ivfflat
--     ON appg_vectors USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
