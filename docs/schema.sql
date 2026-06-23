-- Full schema for a fresh intelligence-postgres instance.
-- Run this once on a new database before starting any ingestion.
--
-- Usage:
--   psql "postgresql://..." -f docs/schema.sql

-- Enable pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- ── Vector tables ──────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS interests_vectors (
    id           SERIAL PRIMARY KEY,
    source_id    TEXT NOT NULL UNIQUE,
    mp_id        INTEGER NOT NULL,
    mp_name      TEXT NOT NULL,
    category     TEXT,
    content      TEXT NOT NULL,
    metadata     JSONB,
    embedding    VECTOR(1536),
    content_hash TEXT
);

CREATE TABLE IF NOT EXISTS party_donations_vectors (
    id            SERIAL PRIMARY KEY,
    source_id     TEXT NOT NULL UNIQUE,
    party_name    TEXT NOT NULL,
    donor_name    TEXT NOT NULL,
    amount        NUMERIC,
    donation_date DATE,
    content       TEXT NOT NULL,
    metadata      JSONB,
    embedding     VECTOR(1536),
    content_hash  TEXT
);

CREATE TABLE IF NOT EXISTS votes_vectors (
    id           SERIAL PRIMARY KEY,
    source_id    TEXT NOT NULL UNIQUE,
    mp_id        INTEGER NOT NULL,
    mp_name      TEXT NOT NULL,
    division_id  INTEGER,
    vote         TEXT,
    vote_date    DATE,
    content      TEXT NOT NULL,
    metadata     JSONB,
    embedding    VECTOR(1536),
    content_hash TEXT
);

CREATE TABLE IF NOT EXISTS appg_vectors (
    id           SERIAL PRIMARY KEY,
    source_id    TEXT NOT NULL UNIQUE,
    mp_id        INTEGER NOT NULL,
    mp_name      TEXT NOT NULL,
    appg_name    TEXT NOT NULL,
    role         TEXT,
    content      TEXT NOT NULL,
    metadata     JSONB,
    embedding    VECTOR(1536),
    content_hash TEXT
);

-- ── Ingestion audit log ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS ingest_runs (
    id              SERIAL      PRIMARY KEY,
    script          TEXT        NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL,
    finished_at     TIMESTAMPTZ,
    last_updated_at TIMESTAMPTZ,
    status          TEXT        NOT NULL DEFAULT 'running',
    embedded        INT         NOT NULL DEFAULT 0,
    skipped         INT         NOT NULL DEFAULT 0,
    errors          INT         NOT NULL DEFAULT 0,
    notes           TEXT        NOT NULL DEFAULT ''
);

-- ── IVFFlat indexes ────────────────────────────────────────────────────────────
-- DO NOT run these on an empty database.
-- Build indexes AFTER ingestion is complete — centroids are learned from real data.
-- Check disk before running: need 3x the table size free as temporary workspace.
-- See ADR 011 for disk requirements.
--
-- Run order: votes first (largest table), then others.
-- Check disk between each: SELECT pg_size_pretty(pg_database_size(current_database()));
--
-- SET maintenance_work_mem = '512MB';
--
-- CREATE INDEX idx_votes_embedding_ivfflat
--   ON votes_vectors USING ivfflat (embedding vector_cosine_ops) WITH (lists = 200);
--
-- CREATE INDEX idx_interests_embedding_ivfflat
--   ON interests_vectors USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
--
-- CREATE INDEX idx_party_donations_embedding_ivfflat
--   ON party_donations_vectors USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
--
-- CREATE INDEX idx_appg_embedding_ivfflat
--   ON appg_vectors USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
