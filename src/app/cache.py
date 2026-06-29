"""
Two-level cache for agent answers.

  L1  Redis      — exact question match. Instant.
  L2  Postgres   — semantic match (pgvector cosine over past questions).

Both layers degrade gracefully: if Redis is down or embedding fails, we log and fall
through to the agent. The cache must never break /ask.

Only standalone (first-turn) questions are cached — follow-ups depend on conversation
context and would be wrong to serve from a text-keyed cache.
"""

import hashlib
import logging
import os

import psycopg2
from pgvector.psycopg2 import register_vector

from app.embeddings import embed_query

log = logging.getLogger(__name__)

L1_TTL_SECONDS = 24 * 3600      # Redis exact-match entries live 24h
L2_MAX_AGE_DAYS = 7             # semantic entries considered for 7 days
L2_SIMILARITY_THRESHOLD = 0.95  # how close a past question must be to count as a hit

_redis = None
_table_ready = False


# ── normalisation / keys ─────────────────────────────────────────────────────────

def _normalise(question: str) -> str:
    return " ".join(question.lower().split())


def _l1_key(question: str) -> str:
    return "qcache:" + hashlib.sha256(_normalise(question).encode()).hexdigest()


# ── connections ──────────────────────────────────────────────────────────────────

def _get_redis():
    """Lazy Redis client. Returns None if unavailable (L1 then disabled)."""
    global _redis
    if _redis is None:
        try:
            import redis
            url = os.environ.get("REDIS_URL", "redis://localhost:6379")
            client = redis.from_url(url, decode_responses=True, socket_connect_timeout=2)
            client.ping()
            _redis = client
        except Exception as exc:
            log.warning("Redis unavailable, L1 cache disabled: %s", exc)
            _redis = False  # sentinel: tried and failed
    return _redis or None


def _write_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    return url.replace("postgres://", "postgresql://", 1)


def _pg_connect():
    conn = psycopg2.connect(_write_url())
    register_vector(conn)
    return conn


def _ensure_table(conn) -> None:
    global _table_ready
    if _table_ready:
        return
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS query_cache (
                id         SERIAL PRIMARY KEY,
                question   TEXT NOT NULL,
                embedding  VECTOR(1536),
                answer     TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
    conn.commit()
    _table_ready = True


# ── public API ───────────────────────────────────────────────────────────────────

def lookup(question: str) -> tuple[str | None, str | None]:
    """Return (answer, layer) on a cache hit, else (None, None)."""
    # L1 — exact match (whole block guarded; cache must never break /ask)
    try:
        r = _get_redis()
        if r is not None:
            hit = r.get(_l1_key(question))
            if hit:
                return hit, "L1"
    except Exception as exc:
        log.warning("L1 lookup failed: %s", exc)

    # L2 — semantic match
    try:
        embedding = embed_query(question)
        vec = "[" + ",".join(str(float(x)) for x in embedding) + "]"
        conn = _pg_connect()
        try:
            _ensure_table(conn)
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT answer, 1 - (embedding <=> %s::vector) AS similarity
                    FROM query_cache
                    WHERE created_at > NOW() - INTERVAL '{L2_MAX_AGE_DAYS} days'
                    ORDER BY embedding <=> %s::vector
                    LIMIT 1
                    """,
                    (vec, vec),
                )
                row = cur.fetchone()
            if row and row[1] is not None and row[1] >= L2_SIMILARITY_THRESHOLD:
                answer = row[0]
                _l1_store(question, answer)  # promote to L1 for next time
                return answer, "L2"
        finally:
            conn.close()
    except Exception as exc:
        log.warning("L2 lookup failed: %s", exc)

    return None, None


def store(question: str, answer: str) -> None:
    """Store an answer in both cache layers. Embeds once, reuses for L1 + L2."""
    _l1_store(question, answer)
    try:
        embedding = embed_query(question)
        conn = _pg_connect()
        try:
            _ensure_table(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO query_cache (question, embedding, answer) VALUES (%s, %s, %s)",
                    (question, embedding, answer),
                )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        log.warning("L2 store failed: %s", exc)


def _l1_store(question: str, answer: str) -> None:
    r = _get_redis()
    if r is None:
        return
    try:
        r.setex(_l1_key(question), L1_TTL_SECONDS, answer)
    except Exception as exc:
        log.warning("L1 store failed: %s", exc)
