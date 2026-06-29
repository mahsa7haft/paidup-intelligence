"""
Seed the LOCAL docker-compose database with a handful of sample interest records
(with real embeddings) so the MCP search tools have something to find.

DEV ONLY. Hard-coded to the local docker-compose DB and guarded against ever
pointing at a remote host — so it can never touch production.

Run:
    PYTHONPATH=src uv run python scripts/seed_local.py
"""

import hashlib
import json
import sys

import psycopg2
from dotenv import load_dotenv
from pgvector.psycopg2 import register_vector

# Load .env only for OPENAI_API_KEY — we deliberately do NOT use its DATABASE_URL.
load_dotenv()

LOCAL_URL = "postgresql://intelligence:localdev@localhost:5433/intelligence"

# Safety guard: refuse to run against anything that isn't local.
if not ("localhost" in LOCAL_URL or "127.0.0.1" in LOCAL_URL):
    sys.exit("REFUSING: seed target is not local — this script only seeds the local DB.")

from app.embeddings import embed_query  # noqa: E402  (after env load)

# A few semantically varied interests so similarity search is demonstrable.
SAMPLES = [
    (101, "Jane Smith",  "Donation",     "MP Jane Smith (Labour) received £10,000 from Green Energy Ltd, a renewable energy company, as a donation."),
    (102, "John Doe",    "Gift",         "MP John Doe (Conservative) received £5,000 from British Petroleum, an oil and gas company, as a gift."),
    (103, "Alice Brown", "Hospitality",  "MP Alice Brown (Liberal Democrat) received free tickets to the Wimbledon tennis championships from the All England Club."),
    (104, "Bob White",   "Employment",   "MP Bob White (Labour) holds a paid directorship at a fintech banking startup, earning £20,000 per year."),
    (105, "Carol Green", "Donation",     "MP Carol Green (Green Party) received £2,000 from a community wind farm cooperative supporting clean energy."),
]


def main() -> None:
    conn = psycopg2.connect(LOCAL_URL)
    register_vector(conn)
    inserted = 0
    with conn.cursor() as cur:
        for mp_id, mp_name, category, content in SAMPLES:
            source_id = f"seed_interest_{mp_id}"
            embedding = embed_query(content)
            content_hash = hashlib.sha256(content.encode()).hexdigest()
            cur.execute(
                """
                INSERT INTO interests_vectors
                    (source_id, mp_id, mp_name, category, content, metadata, embedding, content_hash)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (source_id) DO UPDATE SET
                    content = EXCLUDED.content, embedding = EXCLUDED.embedding
                """,
                (source_id, mp_id, mp_name, category, content, json.dumps({}), embedding, content_hash),
            )
            inserted += 1
            print(f"  seeded {source_id}: {mp_name} ({category})")
    conn.commit()
    conn.close()
    print(f"\nDone. {inserted} interest records in the local DB.")


if __name__ == "__main__":
    main()
