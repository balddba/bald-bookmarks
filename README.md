<p align="center">
  <img src="frontend/public/logo.png" alt="Bald Bookmarks Logo" width="160" />
</p>

<h1 align="center">Bald Bookmarks</h1>

<p align="center">
  Single-user bookmark manager with nested folder hierarchies, tagging, Playwright-powered page preview thumbnails, and a pluggable multi-database architecture supporting Oracle, PostgreSQL, MySQL, and SQLite.
</p>

---

## Stack

- **Backend**: Python 3.13+, FastAPI, Granian (ASGI), Pydantic v2, Alembic, Playwright (Chromium), Loguru
- **Frontend**: React 19, Vite, Tailwind CSS v4, HeroUI v3, React Router v7
- **Database Support**: SQLite, PostgreSQL, MySQL, and Oracle Database via a unified `DatabaseDriver` ABC

---

## Features

- **Nested Folder Hierarchies**: Organize bookmarks with unlimited nesting depth, quick folder navigation, and bookmark counters.
- **Tagging System**: Add, filter, and manage tags across all bookmarks.
- **Page Preview Thumbnails**: Background capture jobs powered by headless Chromium (Playwright) store visual website thumbnails.
- **Pluggable Multi-DB Architecture**: Easily switch between SQLite, PostgreSQL, MySQL, and Oracle Database using standard configuration.
- **Integrated Admin Console**: Monitor server health, Alembic schema migration status, active background scheduler, job queue/history, and trigger bulk thumbnail regeneration.
- **Automated Migrations**: Automatic Alembic schema upgrades on startup across all supported database drivers.

---

## Quickstart with Docker

### Standard Stack

```bash
cp .env.example .env
docker compose up --build
```

### Pre-Seeded Demo Stack

Run the stack pre-populated with sample categories, bookmarks, and preview metadata:

```bash
docker compose -f docker-compose.demo.yaml up --build
```

### Access URLs

- **Web UI**: [http://localhost:8080](http://localhost:8080) (Nginx reverse proxies `/api` and `/media` requests to the backend)
- **API Direct**: [http://localhost:8081](http://localhost:8081) (or `http://localhost:8000` when running locally)
- **Interactive API Docs (Swagger)**: [http://localhost:8081/docs](http://localhost:8081/docs)

---

## Local Development Setup

### 1. Prerequisites

- Python 3.13+
- [`uv`](https://github.com/astral-sh/uv) package manager
- Node.js 18+ & `npm`

### 2. Backend Setup

```bash
# Install Python dependencies
uv sync --group dev

# Install Playwright Chromium browser binary for page previews
uv run playwright install chromium

# Create local environment configuration
cp .env.example .env

# Apply database migrations to the configured database
uv run alembic upgrade head
```

#### Optional: Generate Demo SQLite Database
To generate or reset a populated `demo.db` locally:

```bash
uv run python scripts/create_demo_db.py
```

### 3. Run the Backend API

```bash
export PYTHONPATH=backend
uv run granian --interface asgi --host 127.0.0.1 --port 8000 --reload bald_bookmarks.main:app
```

### 4. Run the Frontend Development Server

```bash
cd frontend
npm install
npm run dev
```

The frontend dev server runs at [http://localhost:5173](http://localhost:5173) and proxies `/api` requests to `http://127.0.0.1:8000`.

---

## Configuration Reference

Key settings configurable via environment variables or `.env`:

| Setting | Default | Description |
| --- | --- | --- |
| `DB_DRIVER` | `sqlite` | Database engine (`sqlite`, `postgres`, `mysql`, `oracle`) |
| `SQLITE_PATH` | `backend/bald_bookmarks/data/bookmarks.db` | Path to SQLite database file |
| `POSTGRES_HOST` / `POSTGRES_PORT` / `...` | `localhost:5432` | PostgreSQL credentials & database |
| `MYSQL_HOST` / `MYSQL_PORT` / `...` | `localhost:3306` | MySQL credentials & database |
| `ORACLE_USER` / `ORACLE_DSN` / `...` | `localhost:1521/FREEPDB1` | Oracle Database credentials & DSN |
| `JOB_POLL_SECONDS` | `5` | Background scheduler polling frequency in seconds |
| `JOB_MAX_ATTEMPTS` | `3` | Maximum retry attempts for failed background jobs |
| `MEDIA_ROOT` | `backend/bald_bookmarks/media` | Directory where captured thumbnail images are stored |
| `THUMBNAIL_VIEWPORT_WIDTH` / `HEIGHT` | `1280` / `720` | Playwright viewport dimensions for thumbnails |
| `THUMBNAIL_NO_SANDBOX` | `false` (`true` in Docker) | Disable Playwright Chromium sandbox if needed |

---

## Testing & Quality Gates

### Run Test Suite

```bash
# Run pytest suite
uv run pytest

# Test all database drivers (requires Docker / live DB instances)
uv run python scripts/run_database_tests.py
# Or specify targeted engines:
# uv run python scripts/run_database_tests.py --engines sqlite postgres
```

Per-engine helper compose files live under `compose/` (`compose/postgres.yml`, `compose/mysql.yml`, `compose/oracle.yml`, `compose/sqlite.yml`) to spin up individual testing databases.

### Linting & Formatting

Code style is enforced with [Ruff](https://github.com/astral-sh/ruff):

```bash
# Check code for lint errors
uv run --with ruff ruff check backend tests scripts

# Format python files
uv run --with ruff ruff format backend tests scripts
```
