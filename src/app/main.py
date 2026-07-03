"""
Flask server for the /ask interface.

Routes:
    GET  /         → the chat page
    GET  /health   → health check (Railway uses this)
    POST /ask      → { "question": "..." } → { "answer": "..." }

Run:
    PYTHONPATH=src uv run python -m app.main
    → http://localhost:5003
"""

import logging
import os
import time
import uuid
from collections import defaultdict

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from langgraph.checkpoint.memory import MemorySaver

from app import cache
from app.agent import RECURSION_LIMIT, build_agent

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)

# ── Rate limiting ────────────────────────────────────────────────────────────────
# Each /ask call is real LLM spend, and the endpoint is public. Cap questions per
# client per hour so a stranger (or a bot) can't run up the bill. In-memory and
# per-process — fine for a test launch; use Redis if we run multiple workers.
RATE_LIMIT_PER_HOUR = int(os.environ.get("RATE_LIMIT_PER_HOUR", "30"))  # 0 disables
_RATE_WINDOW = 3600
_hits: dict[str, list[float]] = defaultdict(list)


def _client_ip() -> str:
    # Railway/proxies put the real client first in X-Forwarded-For.
    fwd = request.headers.get("X-Forwarded-For", "")
    return fwd.split(",")[0].strip() if fwd else (request.remote_addr or "unknown")


def _rate_limited(ip: str) -> bool:
    if RATE_LIMIT_PER_HOUR <= 0:
        return False
    now = time.time()
    recent = [t for t in _hits[ip] if now - t < _RATE_WINDOW]
    _hits[ip] = recent
    if len(recent) >= RATE_LIMIT_PER_HOUR:
        return True
    recent.append(now)
    return False

# Compile the agent once with an in-memory checkpointer so conversations persist per
# thread_id across requests. MemorySaver is in-process (cleared on restart) — fine for
# now; swap for a Postgres checkpointer when we need durable history.
_agent = None


def get_agent():
    global _agent
    if _agent is None:
        log.info("Compiling agent…")
        _agent = build_agent(checkpointer=MemorySaver())
    return _agent


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/ask", methods=["POST"])
def ask_route():
    if _rate_limited(_client_ip()):
        return jsonify({"error": "Rate limit reached. Please try again later."}), 429

    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"error": "question is required"}), 400

    incoming_thread = data.get("thread_id")
    # Only first-turn questions are cacheable — follow-ups depend on conversation
    # context, so a text-keyed cache would serve wrong answers.
    is_first_turn = not incoming_thread
    if is_first_turn:
        cached, layer = cache.lookup(question)
        if cached is not None:
            log.info("Cache hit (%s)", layer)
            return jsonify({"answer": cached, "thread_id": str(uuid.uuid4()), "cached": layer})

    thread_id = incoming_thread or str(uuid.uuid4())
    try:
        result = get_agent().invoke(
            {"messages": [("user", question)]},
            config={"configurable": {"thread_id": thread_id}, "recursion_limit": RECURSION_LIMIT},
        )
        answer = result["messages"][-1].content
        if is_first_turn:
            cache.store(question, answer)
        return jsonify({"answer": answer, "thread_id": thread_id})
    except Exception as exc:
        log.exception("Agent failed")
        return jsonify({"error": str(exc)}), 500


def main() -> None:
    port = int(os.environ.get("PORT", 5003))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
