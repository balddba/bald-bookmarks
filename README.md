# Bald Bookmarks

Single-user bookmark manager with nested folders, tags, Playwright page-preview thumbnails, and a `DatabaseDriver` ABC with Oracle, PostgreSQL, MySQL, and SQLite implementations.

## Stack

- Backend: FastAPI + Granian, Pydantic models, `DatabaseDriver` ABC (`oracle` / `postgres` / `mysql` / `sqlite`), Alembic
- Frontend: React + Vite + Tailwind v4 + HeroUI v3

## Docker

```bash
cp .env.example .env
docker compose up --build
```

To run with the pre-seeded demo database:

```bash
docker compose -f docker-compose.demo.yaml up --build
```


- App UI: http://localhost:8080 (nginx proxies `/api` and `/media` to the API)
- API direct: http://localhost:8000
- Default `DB_DRIVER=sqlite`; set Oracle, PostgreSQL, or MySQL vars in `.env` for another engine
- Relational schema is applied with Alembic on API startup
- Thumbnail files persist in the `media_data` volume

## Setup

```bash
uv sync --group dev
uv run playwright install chromium
cp .env.example .env
# edit Oracle / PostgreSQL / MySQL / SQLite settings
uv run alembic upgrade head   # also runs automatically on API startup
```

Page previews are captured by the `thumbnail.capture` job via headless Chromium. In Docker, `THUMBNAIL_NO_SANDBOX=true` is set by default.

## Run API

```bash
export PYTHONPATH=backend
uv run granian --interface asgi --host 127.0.0.1 --port 8000 --reload bald_bookmarks.main:app
```

## Run frontend

```bash
cd frontend
npm install
npm run dev
```

## Tests

```bash
uv run pytest
uv run python scripts/run_database_tests.py
# optional: uv run python scripts/run_database_tests.py --engines sqlite postgres
uv run --with ruff ruff check backend tests scripts
uv run --with ruff ruff format backend tests scripts
```

Per-engine compose files live under `compose/` and use placeholder credentials (`changeme`). They are not the application stack; use `docker-compose.yml` for that.
