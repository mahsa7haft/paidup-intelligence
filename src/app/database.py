"""
Read-only database access for the MCP / query layer.

The agent and MCP tools only ever SELECT, so this connects with the read-only role
when DATABASE_URL_READONLY is set (see ADR 013), falling back to DATABASE_URL for
local development. Ingestion uses its own write connections elsewhere.
"""

import os

import psycopg2
import psycopg2.extras
from pgvector.psycopg2 import register_vector

# Whitelist of searchable tables → the columns each tool returns.
# Whitelisting the table name keeps the f-string query safe from injection: callers
# can only ever name a key in this dict, never arbitrary SQL.
SEARCHABLE: dict[str, list[str]] = {
    "interests_vectors":       ["source_id", "mp_name", "category", "content", "metadata"],
    "party_donations_vectors": ["source_id", "party_name", "donor_name", "amount",
                                "donation_date", "content", "metadata"],
    "votes_vectors":           ["source_id", "mp_name", "vote", "vote_date", "content", "metadata"],
    "appg_vectors":            ["source_id", "mp_name", "appg_name", "role", "content", "metadata"],
}


def _read_url() -> str:
    """Prefer the read-only role; fall back to the main URL for local dev."""
    url = os.environ.get("DATABASE_URL_READONLY") or os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError("Neither DATABASE_URL_READONLY nor DATABASE_URL is set")
    return url.replace("postgres://", "postgresql://", 1)


def _connect():
    conn = psycopg2.connect(_read_url())
    register_vector(conn)  # teaches psycopg2 to send/receive pgvector's vector type
    return conn


def similarity_search(table: str, query_vector: list[float], k: int = 5) -> list[dict]:
    """
    Return the k rows in `table` most similar to `query_vector` by cosine distance.

    `<=>` is pgvector's cosine-distance operator (smaller = closer). We also return
    `similarity` = 1 - distance, so 1.0 is identical and 0.0 is unrelated.
    """
    if table not in SEARCHABLE:
        raise ValueError(f"Unknown table: {table!r}. Allowed: {sorted(SEARCHABLE)}")
    if k < 1:
        raise ValueError("k must be >= 1")

    columns = SEARCHABLE[table]
    col_sql = ", ".join(columns)
    # A Python list becomes a Postgres array (numeric[]); the <=> operator needs a
    # `vector`. Format the embedding as a vector literal and cast it explicitly.
    vec_literal = "[" + ",".join(str(float(x)) for x in query_vector) + "]"
    query = (
        f"SELECT {col_sql}, 1 - (embedding <=> %s::vector) AS similarity "
        f"FROM {table} "
        f"ORDER BY embedding <=> %s::vector "
        f"LIMIT %s"
    )

    conn = _connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, (vec_literal, vec_literal, k))
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()
