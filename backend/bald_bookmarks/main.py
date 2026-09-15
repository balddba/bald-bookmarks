"""FastAPI application entrypoint."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger

from bald_bookmarks import __version__
from bald_bookmarks.api import admin, bookmarks, folders, jobs, tags
from bald_bookmarks.config import Settings, get_settings
from bald_bookmarks.db.factory import create_driver
from bald_bookmarks.db.migrate import upgrade_schema
from bald_bookmarks.jobs.registry import build_default_registry
from bald_bookmarks.jobs.scheduler import JobScheduler
from bald_bookmarks.sentry import init_sentry


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Apply schema migrations, connect, and start the job scheduler.

    Args:
        app (FastAPI): Application instance.

    Yields:
        None: Control while the app is running.
    """
    settings: Settings = app.state.settings
    driver = app.state.driver
    scheduler: JobScheduler = app.state.scheduler
    try:
        settings.thumbnails_dir.mkdir(parents=True, exist_ok=True)
        if settings.normalized_driver == "sqlite":
            settings.sqlite_db_path().parent.mkdir(parents=True, exist_ok=True)
        upgrade_schema(settings)
        driver.connect()
        await scheduler.start()
        logger.info("Bald Bookmarks API started db_driver={}", settings.db_driver)
    except Exception:
        logger.exception("Bald Bookmarks API startup failed")
        raise
    try:
        yield
    finally:
        await scheduler.stop()
        driver.close()
        logger.info("Bald Bookmarks API stopped")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application.

    Args:
        settings (Settings | None): Optional preloaded settings (tests).

    Returns:
        FastAPI: Configured application.
    """
    resolved = settings or get_settings()
    init_sentry(resolved)
    driver = create_driver(resolved)
    registry = build_default_registry()
    scheduler = JobScheduler(driver, registry, resolved)

    app = FastAPI(title="Bald Bookmarks", version=__version__, lifespan=lifespan)
    app.state.settings = resolved
    app.state.driver = driver
    app.state.scheduler = scheduler

    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(folders.router)
    app.include_router(bookmarks.router)
    app.include_router(tags.router)
    app.include_router(jobs.router)
    app.include_router(admin.router)

    media_root = Path(resolved.media_root)
    media_root.mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=str(media_root)), name="media")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        """Return a simple health payload.

        Returns:
            dict[str, str]: Status map.
        """
        return {"status": "ok"}

    return app


def _build_default_app() -> FastAPI:
    """Create the module-level app.

    A SQLite fallback can be enabled for import-oriented tooling by setting
    BALD_BOOKMARKS_IMPORT_FALLBACK_SQLITE=true. Normal runtime startup should
    fail fast when configuration is invalid instead of silently switching
    databases.

    Returns:
        FastAPI: Application instance.
    """
    try:
        return create_app()
    except Exception as exc:  # noqa: BLE001
        if os.getenv("BALD_BOOKMARKS_IMPORT_FALLBACK_SQLITE", "").lower() not in {
            "1",
            "true",
            "yes",
        }:
            raise
        logger.warning("Using SQLite driver fallback during app import: {}", exc)
        return create_app(
            Settings(
                DB_DRIVER="sqlite",
                SQLITE_PATH=Path("backend/bald_bookmarks/data/bookmarks.db"),
                MEDIA_ROOT=Path("backend/bald_bookmarks/media"),
            )
        )


app = _build_default_app()
