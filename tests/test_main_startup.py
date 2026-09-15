"""Application startup behavior tests."""

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bald_bookmarks import main
from bald_bookmarks.config import Settings


def test_default_app_builder_raises_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid runtime configuration fails fast by default."""

    def raise_config_error(settings: Settings | None = None) -> FastAPI:
        raise RuntimeError("bad config")

    monkeypatch.delenv("BALD_BOOKMARKS_IMPORT_FALLBACK_SQLITE", raising=False)
    monkeypatch.setattr(main, "create_app", raise_config_error)

    with pytest.raises(RuntimeError, match="bad config"):
        main._build_default_app()


def test_default_app_builder_can_use_explicit_sqlite_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Import-only tooling can opt into the SQLite fallback."""
    seen_settings: list[Settings | None] = []

    def create_or_record(settings: Settings | None = None) -> FastAPI:
        seen_settings.append(settings)
        if settings is None:
            raise RuntimeError("bad config")
        return FastAPI()

    monkeypatch.setenv("BALD_BOOKMARKS_IMPORT_FALLBACK_SQLITE", "true")
    monkeypatch.setattr(main, "create_app", create_or_record)

    app = main._build_default_app()

    assert isinstance(app, FastAPI)
    assert seen_settings[0] is None
    fallback_settings = seen_settings[1]
    assert fallback_settings is not None
    assert fallback_settings.normalized_driver == "sqlite"
    assert fallback_settings.sqlite_path == Path(
        "backend/bald_bookmarks/data/bookmarks.db"
    )


def test_lifespan_logs_startup_failures(tmp_path: Path) -> None:
    """Startup exceptions are written to container logs before the app exits."""
    settings = Settings(
        db_driver="sqlite",
        sqlite_path=tmp_path / "bookmarks.db",
        media_root=tmp_path / "media",
    )
    app = main.create_app(settings)

    with (
        patch("bald_bookmarks.main.upgrade_schema", side_effect=RuntimeError("boom")),
        patch("bald_bookmarks.main.logger.exception") as logged,
        pytest.raises(RuntimeError, match="boom"),
    ):
        with TestClient(app):
            pass

    logged.assert_called_once_with("Bald Bookmarks API startup failed")
