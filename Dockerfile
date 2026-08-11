FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

# Dependencies first, in their own layer — this only re-runs when the
# lock file changes, so code edits rebuild in seconds.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

RUN useradd --create-home --uid 1000 appuser && chown -R appuser /app
USER appuser

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]