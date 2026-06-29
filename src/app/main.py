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
import uuid

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from langgraph.checkpoint.memory import MemorySaver

from app.agent import build_agent

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)

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
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"error": "question is required"}), 400
    # A thread_id labels the conversation; reuse it across turns to keep memory.
    thread_id = data.get("thread_id") or str(uuid.uuid4())
    try:
        result = get_agent().invoke(
            {"messages": [("user", question)]},
            config={"configurable": {"thread_id": thread_id}},
        )
        answer = result["messages"][-1].content
        return jsonify({"answer": answer, "thread_id": thread_id})
    except Exception as exc:
        log.exception("Agent failed")
        return jsonify({"error": str(exc)}), 500


def main() -> None:
    port = int(os.environ.get("PORT", 5003))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
