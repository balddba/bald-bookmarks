"""Unit tests for the PostgreSQL DatabaseDriver."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import psycopg
import pytest

from bald_bookmarks.config import Settings
from bald_bookmarks.db.exceptions import ConflictError, NotFoundError
from bald_bookmarks.db.postgres.driver import PostgresDriver
from bald_bookmarks.domain.jobs import Job, JobStatus
from bald_bookmarks.domain.tags import TagCreate


def _postgres_settings() -> Settings:
    """Build PostgreSQL settings that do not require a live database.

    Returns:
        Settings: Validated PostgreSQL driver settings.
    """
    return Settings(
        db_driver="postgres",
        postgres_host="localhost",
        postgres_user="bookmarks",
        postgres_password="secret",
        postgres_database="bald_bookmarks",
    )


def _postgres_driver_with_cursor() -> tuple[PostgresDriver, MagicMock, MagicMock]:
    """Build a PostgresDriver whose pool yields a mocked connection.

    Returns:
        tuple[PostgresDriver, MagicMock, MagicMock]: Driver, connection, and cursor.
    """
    driver = PostgresDriver(_postgres_settings())
    conn = MagicMock()
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.__exit__.return_value = None
    conn.cursor.return_value = cursor
    conn.__enter__.return_value = conn
    conn.__exit__.return_value = None
    driver._pool = MagicMock()
    driver._pool.connection.return_value = conn
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


def test_health_check_without_pool() -> None:
    """Health check fails closed when the pool has not been opened."""
    driver = PostgresDriver(_postgres_settings())
    health = driver.health_check()
    assert health.ok is False
    assert health.driver == "postgres"
    assert "not open" in health.message


def test_connect_without_settings_raises() -> None:
    """Connect fails fast when PostgreSQL fields are missing."""
    settings = Settings(db_driver="sqlite")
    driver = PostgresDriver(settings)
    with pytest.raises(ValueError, match="PostgreSQL connection settings"):
        driver.connect()


def test_insert_id_uses_returning() -> None:
    """PostgreSQL inserts read the generated id from RETURNING."""
    driver, _conn, cursor = _postgres_driver_with_cursor()
    cursor.fetchone.return_value = (42,)
    inserted = driver._insert_id(
        cursor,
        "INSERT INTO tags (name, created_at) VALUES (%(name)s, %(created_at)s)",
        {"name": "news", "created_at": datetime.now(UTC)},
    )
    assert inserted == 42
    sql = cursor.execute.call_args.args[0]
    assert "RETURNING id" in sql


def test_claim_next_job_sql_uses_skip_locked() -> None:
    """Claim SQL locks a single eligible row without blocking other workers."""
    driver, _conn, cursor = _postgres_driver_with_cursor()
    cursor.fetchone.return_value = None
    assert driver.claim_next_job() is None
    sql = cursor.execute.call_args.args[0]
    assert "FOR UPDATE SKIP LOCKED" in sql.upper()
    assert "LIMIT 1" in sql.upper()


def test_claim_next_job_returns_none_when_queue_empty() -> None:
    """An empty eligible queue rolls back and returns None."""
    driver, conn, cursor = _postgres_driver_with_cursor()
    cursor.fetchone.return_value = None
    assert driver.claim_next_job() is None
    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()


def test_claim_next_job_returns_updated_job() -> None:
    """A matching pending row is claimed and reloaded."""
    driver, conn, cursor = _postgres_driver_with_cursor()
    cursor.fetchone.return_value = (7,)
    job = _running_job(7)
    with patch.object(driver, "get_job", return_value=job) as get_job:
        claimed = driver.claim_next_job()
    assert claimed is job
    get_job.assert_called_once_with(7)
    conn.commit.assert_called_once()
    update_sql = cursor.execute.call_args_list[1].args[0]
    assert "UPDATE jobs" in update_sql


def test_claim_next_job_reraises_database_error() -> None:
    """PostgreSQL errors during claim are rolled back and re-raised."""
    driver, conn, cursor = _postgres_driver_with_cursor()
    cursor.execute.side_effect = psycopg.Error("deadlock")
    with pytest.raises(psycopg.Error, match="deadlock"):
        driver.claim_next_job()
    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()


def test_get_folder_raises_not_found() -> None:
    """Missing folders raise NotFoundError."""
    driver, _conn, cursor = _postgres_driver_with_cursor()
    cursor.fetchone.return_value = None
    with pytest.raises(NotFoundError, match="Folder 99 not found"):
        driver.get_folder(99)


def test_create_tag_conflict() -> None:
    """Duplicate tag names raise ConflictError."""
    driver, _conn, cursor = _postgres_driver_with_cursor()
    cursor.fetchone.return_value = (1,)
    with pytest.raises(ConflictError, match="already exists"):
        driver.create_tag(TagCreate(name="news"))


def test_folder_descendants_uses_recursive_cte() -> None:
    """Folder descendant lookup uses a recursive CTE instead of CONNECT BY."""
    driver, conn, cursor = _postgres_driver_with_cursor()
    cursor.fetchall.return_value = [(2,), (3,)]
    descendants = driver._folder_descendants(conn, 1)
    assert descendants == {2, 3}
    sql = cursor.execute.call_args.args[0]
    assert "WITH RECURSIVE" in sql.upper()
    assert "CONNECT BY" not in sql.upper()
