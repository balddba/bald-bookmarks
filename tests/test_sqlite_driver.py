"""Unit tests for the SQLite DatabaseDriver."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from bald_bookmarks.config import Settings
from bald_bookmarks.db.exceptions import ConflictError, NotFoundError
from bald_bookmarks.db.sqlite.driver import SQLiteDriver
from bald_bookmarks.domain.jobs import Job, JobStatus
from bald_bookmarks.domain.tags import TagCreate


def _sqlite_settings() -> Settings:
    """Build SQLite settings that do not require a live database.

    Returns:
        Settings: Validated SQLite driver settings.
    """
    return Settings(db_driver="sqlite")


def _sqlite_driver_with_cursor() -> tuple[SQLiteDriver, MagicMock, MagicMock]:
    """Build a SQLiteDriver whose connection yields a mocked cursor.

    Returns:
        tuple[SQLiteDriver, MagicMock, MagicMock]: Driver, connection, and cursor.
    """
    driver = SQLiteDriver(_sqlite_settings())
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    driver._conn = conn
    return driver, conn, cursor


def _running_job(job_id: int = 7) -> Job:
    """Return a claimed job fixture.

    Args:
        job_id (int): Job primary key.

    Returns:
        Job: Running job.
    """
    now = datetime.now(UTC)
    return Job(
        id=job_id,
        job_type="thumbnail.capture",
        payload_json='{"bookmark_id": 1}',
        status=JobStatus.RUNNING,
        attempts=1,
        max_attempts=3,
        scheduled_at=now,
        started_at=now,
        finished_at=None,
        last_error=None,
        created_at=now,
        updated_at=now,
    )


def test_health_check_without_connection() -> None:
    """Health check fails closed when the connection has not been opened."""
    driver = SQLiteDriver(_sqlite_settings())
    health = driver.health_check()
    assert health.ok is False
    assert health.driver == "sqlite"
    assert "not open" in health.message


def test_insert_id_uses_returning() -> None:
    """SQLite inserts read the generated id from RETURNING."""
    driver, _conn, cursor = _sqlite_driver_with_cursor()
    cursor.fetchone.return_value = (42,)
    inserted = driver._insert_id(
        cursor,
        "INSERT INTO tags (name, created_at) VALUES (:name, :created_at)",
        {"name": "news", "created_at": datetime.now(UTC)},
    )
    assert inserted == 42
    sql = cursor.execute.call_args.args[0]
    assert "RETURNING id" in sql


def test_claim_next_job_sql_updates_base_table() -> None:
    """Claim SQL uses a single UPDATE...RETURNING without SKIP LOCKED."""
    driver, _conn, cursor = _sqlite_driver_with_cursor()
    cursor.fetchone.return_value = None
    assert driver.claim_next_job() is None
    sql = cursor.execute.call_args.args[0]
    assert "FOR UPDATE" not in sql.upper()
    assert "UPDATE jobs" in sql
    assert "RETURNING id" in sql
    assert "LIMIT 1" in sql.upper()


def test_claim_next_job_returns_none_when_queue_empty() -> None:
    """An empty eligible queue rolls back and returns None."""
    driver, conn, cursor = _sqlite_driver_with_cursor()
    cursor.fetchone.return_value = None
    assert driver.claim_next_job() is None
    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()


def test_claim_next_job_returns_updated_job() -> None:
    """A matching pending row is claimed and reloaded."""
    driver, conn, cursor = _sqlite_driver_with_cursor()
    cursor.fetchone.return_value = (7,)
    job = _running_job(7)
    with patch.object(driver, "get_job", return_value=job) as get_job:
        claimed = driver.claim_next_job()
    assert claimed is job
    get_job.assert_called_once_with(7)
    conn.commit.assert_called_once()


def test_get_folder_raises_not_found() -> None:
    """Missing folders raise NotFoundError."""
    driver, _conn, cursor = _sqlite_driver_with_cursor()
    cursor.fetchone.return_value = None
    with pytest.raises(NotFoundError, match="Folder 99 not found"):
        driver.get_folder(99)


def test_create_tag_conflict() -> None:
    """Duplicate tag names raise ConflictError."""
    driver, _conn, cursor = _sqlite_driver_with_cursor()
    cursor.fetchone.return_value = (1,)
    with pytest.raises(ConflictError, match="already exists"):
        driver.create_tag(TagCreate(name="news"))


def test_folder_descendants_uses_recursive_cte() -> None:
    """Folder descendant lookup uses a recursive CTE instead of CONNECT BY."""
    driver, conn, cursor = _sqlite_driver_with_cursor()
    cursor.fetchall.return_value = [(2,), (3,)]
    descendants = driver._folder_descendants(conn, 1)
    assert descendants == {2, 3}
    sql = cursor.execute.call_args.args[0]
    assert "WITH RECURSIVE" in sql.upper()
    assert "CONNECT BY" not in sql.upper()
