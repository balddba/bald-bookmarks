# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

COPY pyproject.toml uv.lock README.md ./
COPY backend ./backend

RUN uv sync --frozen --no-dev

FROM python:3.13-slim-bookworm AS runtime

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend \
    MEDIA_ROOT=/data/media \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PATH="/app/.venv/bin:$PATH"

COPY --from=builder /app/.venv /app/.venv

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && playwright install-deps chromium \
    && playwright install chromium \
    && useradd --create-home --uid 10001 appuser \
    && mkdir -p /data/media/thumbnails \
    && chown -R appuser:appuser /data /app /ms-playwright \
    && rm -rf /var/lib/apt/lists/*

COPY --chown=appuser:appuser backend ./backend
COPY --chown=appuser:appuser alembic ./alembic
COPY --chown=appuser:appuser alembic.ini ./alembic.ini
COPY --chown=appuser:appuser pyproject.toml README.md ./

USER appuser

EXPOSE 8000

CMD ["granian", "--interface", "asgi", "--host", "0.0.0.0", "--port", "8000", "bald_bookmarks.main:app"]
