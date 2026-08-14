"""Unit tests for Oracle job claim SQL."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import oracledb
import pytest

from bald_bookmarks.config import Settings
from bald_bookmarks.db.oracle.driver import OracleDriver
from bald_bookmarks.domain.jobs import Job, JobStatus


def _oracle_driver_with_cursor() -> tuple[OracleDriver, MagicMock, MagicMock]:
    """Build an OracleDriver whose pool yields a mocked connection.

    Returns:
        tuple[OracleDriver, MagicMock, MagicMock]: Driver, connection, and cursor.
    """
    settings = Settings(
        db_driver="oracle",
        oracle_user="bookmarks",
        oracle_password="secret",
        oracle_dsn="localhost:1521/lab",
    )
    driver = OracleDriver(settings)
    conn = MagicMock()
    cursor = MagicMock()
    claimed_id = MagicMock()
    cursor.var.return_value = claimed_id
    conn.cursor.return_value = cursor
    conn.__enter__.return_value = conn
    conn.__exit__.return_value = None
    driver._pool = MagicMock()
    driver._pool.acquire.return_value = conn
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


def test_claim_next_job_sql_updates_base_table() -> None:
    """Claim SQL must not use FOR UPDATE on an inline view (ORA-02014)."""
    driver, _conn, cursor = _oracle_driver_with_cursor()
    cursor.rowcount = 0
    cursor.var.return_value.getvalue.return_value = []
    assert driver.claim_next_job() is None
    sql = cursor.execute.call_args.args[0]
    assert "FOR UPDATE" not in sql.upper()
    assert "UPDATE jobs" in sql
    assert "ROWNUM = 1" in sql
    assert "RETURNING id INTO :id" in sql


def test_claim_next_job_returns_none_when_queue_empty() -> None:
    """An empty eligible queue rolls back and returns None."""
    driver, conn, cursor = _oracle_driver_with_cursor()
    cursor.rowcount = 0
    cursor.var.return_value.getvalue.return_value = []
    assert driver.claim_next_job() is None
    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()


def test_claim_next_job_returns_updated_job() -> None:
    """A matching pending row is claimed and reloaded."""
    driver, conn, cursor = _oracle_driver_with_cursor()
    cursor.rowcount = 1
    cursor.var.return_value.getvalue.return_value = [7]
    job = _running_job(7)
    with patch.object(driver, "get_job", return_value=job) as get_job:
        claimed = driver.claim_next_job()
    assert claimed is job
    get_job.assert_called_once_with(7)
    conn.commit.assert_called_once()


def test_claim_next_job_reraises_database_error() -> None:
    """Oracle errors during claim are rolled back and re-raised."""
    driver, conn, cursor = _oracle_driver_with_cursor()
    cursor.execute.side_effect = oracledb.DatabaseError("ORA-02014")
    with pytest.raises(oracledb.DatabaseError, match="ORA-02014"):
        driver.claim_next_job()
    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()
