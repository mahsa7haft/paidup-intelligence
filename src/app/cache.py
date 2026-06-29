"""
L1 answer cache (Redis) — exact normalised-text match.

We deliberately do NOT do semantic (L2) caching. In this domain, topically-similar
questions need DIFFERENT answers ("oil" vs "gas" funded MPs; "Labour" vs "Conservative"
donors score ~0.93–0.95 cosine but are not interchangeable). Caching on question
similarity would risk serving the wrong answer, and the safe threshold sits so high it
barely fires beyond exact matches anyway — while still paying an embedding call on
every miss. See ADR 016. For guaranteed-instant popular questions, PRECOMPUTE (warm
this cache ahead of time) rather than guessing via similarity.

Graceful: if Redis is unavailable, lookups miss and stores no-op — never breaks /ask.
Only first-turn questions are cached (follow-ups depend on conversation context).
"""

import hashlib
import logging
import os

log = logging.getLogger(__name__)

TTL_SECONDS = 24 * 3600   # cached answers live 24h

_redis = None


def _normalise(question: str) -> str:
    return " ".join(question.lower().split())


def _key(question: str) -> str:
    return "qcache:" + hashlib.sha256(_normalise(question).encode()).hexdigest()


def _get_redis():
    """Lazy Redis client. Returns None if unavailable (cache then disabled)."""
    global _redis
    if _redis is None:
        try:
            import redis
            url = os.environ.get("REDIS_URL", "redis://localhost:6379")
            client = redis.from_url(url, decode_responses=True, socket_connect_timeout=2)
            client.ping()
            _redis = client
        except Exception as exc:
            log.warning("Redis unavailable, cache disabled: %s", exc)
            _redis = False  # sentinel: tried and failed
    return _redis or None


def lookup(question: str) -> tuple[str | None, str | None]:
    """Return (answer, "L1") on an exact cache hit, else (None, None)."""
    try:
        r = _get_redis()
        if r is not None:
            hit = r.get(_key(question))
            if hit:
                return hit, "L1"
    except Exception as exc:
        log.warning("Cache lookup failed: %s", exc)
    return None, None


def store(question: str, answer: str) -> None:
    """Cache an answer under the normalised question, with a TTL."""
    try:
        r = _get_redis()
        if r is not None:
            r.setex(_key(question), TTL_SECONDS, answer)
    except Exception as exc:
        log.warning("Cache store failed: %s", exc)
