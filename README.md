# Bald Bookmarks

Single-user bookmark manager with nested folders, tags, Playwright page-preview thumbnails, and an Oracle-ready database ABC.

## Stack

- Backend: FastAPI + Granian, Pydantic models, `DatabaseDriver` ABC (`oracle` / `memory`), Alembic
- Frontend: React + Vite + Tailwind v4 + HeroUI v3

## Docker

```bash
cp .env.example .env
docker compose up --build
```

- App UI: http://localhost:8080 (nginx proxies `/api` and `/media` to the API)
- API direct: http://localhost:8000
- Default `DB_DRIVER=memory`; set Oracle vars in `.env` for Oracle
- Oracle schema is applied with Alembic on API startup
- Thumbnail files persist in the `media_data` volume

## Setup

```bash
uv sync --group dev
uv run playwright install chromium
cp .env.example .env
# edit Oracle settings, or set DB_DRIVER=memory for local API without Oracle
uv run alembic upgrade head   # Oracle only; also runs automatically on API startup
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
uv run --with ruff ruff check backend tests
uv run --with ruff ruff format backend tests
```
