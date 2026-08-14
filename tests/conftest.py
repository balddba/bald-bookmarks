"""Shared pytest fixtures."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bald_bookmarks.config import Settings
from bald_bookmarks.main import create_app


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    """Build a TestClient backed by the memory driver.

    Args:
        tmp_path (Path): Pytest temporary directory.

    Yields:
        TestClient: Connected API client.
    """
    settings = Settings(
        db_driver="memory",
        media_root=tmp_path / "media",
        job_poll_seconds=0.05,
        job_max_attempts=3,
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client
