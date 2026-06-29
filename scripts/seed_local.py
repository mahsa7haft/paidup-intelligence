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

# Party donations (Electoral Commission style) — party money, not personal.
SAMPLE_DONATIONS = [
    ("Labour",       "Green Energy Ltd",  50000, "2024-01-15", "The Labour Party received £50,000 from Green Energy Ltd, a renewable energy company."),
    ("Conservative", "British Petroleum", 100000, "2024-02-01", "The Conservative Party received £100,000 from British Petroleum, an oil and gas company."),
    ("Green Party",  "Wind Farm Co-op",   10000, "2024-03-01", "The Green Party received £10,000 from a community wind farm cooperative supporting clean energy."),
]

# Voting records.
SAMPLE_VOTES = [
    (101, "Jane Smith",  "Aye", "2024-04-01", "MP Jane Smith (Labour) voted Aye in favour of the Renewable Energy Investment Bill."),
    (102, "John Doe",    "No",  "2024-04-01", "MP John Doe (Conservative) voted No against the Renewable Energy Investment Bill."),
    (105, "Carol Green", "Aye", "2024-05-01", "MP Carol Green (Green Party) voted Aye in favour of declaring a Climate Emergency."),
]


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def main() -> None:
    conn = psycopg2.connect(LOCAL_URL)
    register_vector(conn)
    with conn.cursor() as cur:
        # interests
        for mp_id, mp_name, category, content in SAMPLES:
            source_id = f"seed_interest_{mp_id}"
            cur.execute(
                """
                INSERT INTO interests_vectors
                    (source_id, mp_id, mp_name, category, content, metadata, embedding, content_hash)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (source_id) DO UPDATE SET
                    content = EXCLUDED.content, embedding = EXCLUDED.embedding
                """,
                (source_id, mp_id, mp_name, category, content, json.dumps({}),
                 embed_query(content), _hash(content)),
            )
            print(f"  interest  {source_id}: {mp_name}")

        # party donations
        for i, (party, donor, amount, date, content) in enumerate(SAMPLE_DONATIONS, 1):
            source_id = f"seed_donation_{i}"
            cur.execute(
                """
                INSERT INTO party_donations_vectors
                    (source_id, party_name, donor_name, amount, donation_date, content, metadata, embedding, content_hash)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (source_id) DO UPDATE SET
                    content = EXCLUDED.content, embedding = EXCLUDED.embedding
                """,
                (source_id, party, donor, amount, date, content, json.dumps({}),
                 embed_query(content), _hash(content)),
            )
            print(f"  donation  {source_id}: {party} <- {donor}")

        # votes
        for mp_id, mp_name, vote, date, content in SAMPLE_VOTES:
            source_id = f"seed_vote_{mp_id}_{date}"
            cur.execute(
                """
                INSERT INTO votes_vectors
                    (source_id, mp_id, mp_name, vote, vote_date, content, metadata, embedding, content_hash)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (source_id) DO UPDATE SET
                    content = EXCLUDED.content, embedding = EXCLUDED.embedding
                """,
                (source_id, mp_id, mp_name, vote, date, content, json.dumps({}),
                 embed_query(content), _hash(content)),
            )
            print(f"  vote      {source_id}: {mp_name} {vote}")

    conn.commit()
    conn.close()
    print("\nDone. Seeded interests + party donations + votes into the local DB.")


if __name__ == "__main__":
    main()
