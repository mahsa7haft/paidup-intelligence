# One image, many roles (ADR 014): the default CMD serves the /ask API; the
# ingestion cron reuses this image with e.g. `python -m app.ingest_all`.
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Install dependencies before copying the code so source edits don't
# invalidate the (slow) dependency layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app/src

# Shell form so Railway's $PORT is expanded. Agent requests hold the worker for
# the whole think->tool loop (30s-2min), hence threads for concurrency and a
# generous timeout rather than extra workers.
CMD ["sh", "-c", "gunicorn --workers 1 --threads 8 --timeout 300 --bind 0.0.0.0:${PORT:-5003} app.main:app"]
