"""Shared pytest fixtures."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bald_bookmarks.config import Settings
from bald_bookmarks.db.migrate import upgrade_schema
from bald_bookmarks.db.sqlite.driver import SQLiteDriver
from bald_bookmarks.main import create_app


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the --functional flag for live docker compose tests.

    Args:
        parser (pytest.Parser): Pytest command-line parser.
    """
    parser.addoption(
        "--functional",
        action="store_true",
        default=False,
        help="Start docker compose databases and run live driver tests.",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Register the functional marker.

    Args:
        config (pytest.Config): Pytest configuration.
    """
    config.addinivalue_line(
        "markers",
        "functional: live tests that start docker compose databases",
    )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Skip functional tests unless --functional is passed.

    Args:
        config (pytest.Config): Pytest configuration.
        items (list[pytest.Item]): Collected test items.
    """
    if config.getoption("--functional"):
        return
    skip_functional = pytest.mark.skip(
        reason="pass --functional to start docker compose databases"
    )
    for item in items:
        if "functional" in item.keywords:
            item.add_marker(skip_functional)


def sqlite_settings(tmp_path: Path, **overrides: object) -> Settings:
    """Build SQLite settings rooted in a temporary directory.

    Args:
        tmp_path (Path): Pytest temporary directory.
        **overrides (object): Extra Settings field values.

    Returns:
        Settings: Validated SQLite driver settings.
    """
    values: dict[str, object] = {
        "db_driver": "sqlite",
        "sqlite_path": tmp_path / "bookmarks.db",
        "media_root": tmp_path / "media",
        "job_poll_seconds": 0.05,
        "job_max_attempts": 3,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def driver(tmp_path: Path) -> Iterator[SQLiteDriver]:
    """Provide a connected SQLite driver with migrations applied.

    Args:
        tmp_path (Path): Pytest temporary directory.

    Yields:
        SQLiteDriver: Connected SQLite driver.
    """
    settings = sqlite_settings(tmp_path)
    upgrade_schema(settings)
    sqlite = SQLiteDriver(settings)
    sqlite.connect()
    yield sqlite
    sqlite.close()


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    """Build a TestClient backed by a temporary SQLite database.

    Args:
        tmp_path (Path): Pytest temporary directory.

    Yields:
        TestClient: Connected API client.
    """
    settings = sqlite_settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client
