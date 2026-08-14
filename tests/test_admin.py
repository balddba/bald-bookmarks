"""Tests for the admin console API and related helpers."""

from pathlib import Path

from fastapi.testclient import TestClient

from bald_bookmarks.config import Settings
from bald_bookmarks.db.memory import MemoryDriver
from bald_bookmarks.db.migrate import describe_schema
from bald_bookmarks.db.oracle.driver import OracleDriver
from bald_bookmarks.domain.jobs import JobEnqueue, JobStatus
from bald_bookmarks.main import create_app


def test_memory_health_check_connected() -> None:
    """Connected memory driver reports a healthy probe."""
    driver = MemoryDriver()
    assert driver.health_check().ok is False
    driver.connect()
    health = driver.health_check()
    assert health.ok is True
    assert health.driver == "memory"
    assert health.latency_ms == 0.0
    assert driver.alembic_revision() is None
    driver.close()
    assert driver.health_check().ok is False


def test_oracle_health_check_without_pool() -> None:
    """Oracle health check fails closed when the pool has not been opened."""
    driver = OracleDriver(
        Settings(
            db_driver="oracle",
            oracle_user="bookmarks",
            oracle_password="secret",
            oracle_dsn="localhost:1521/xepdb1",
        )
    )
    health = driver.health_check()
    assert health.ok is False
    assert health.driver == "oracle"
    assert "not open" in health.message


def test_describe_schema_reads_local_heads() -> None:
    """Local Alembic scripts expose the current head revision."""
    status = describe_schema(Settings(db_driver="memory"), current_revision=None)
    assert status.applicable is False
    assert status.current_revision is None
    assert status.is_current is None
    assert "0002_description_varchar" in status.head_revisions
    revisions = [item.revision for item in status.revisions]
    assert revisions[0] == "0002_description_varchar"
    assert "0001_initial" in revisions


def test_describe_schema_marks_oracle_current() -> None:
    """Oracle deployments match when the DB revision is a local head."""
    settings = Settings(
        db_driver="oracle",
        oracle_user="bookmarks",
        oracle_password="secret",
        oracle_dsn="localhost:1521/xepdb1",
    )
    status = describe_schema(settings, current_revision="0002_description_varchar")
    assert status.applicable is True
    assert status.is_current is True
    behind = describe_schema(settings, current_revision="0001_initial")
    assert behind.is_current is False


def test_describe_schema_missing_ini(tmp_path: Path) -> None:
    """Missing alembic.ini is reported on the schema status."""
    status = describe_schema(
        Settings(db_driver="memory"),
        current_revision=None,
        alembic_root=tmp_path,
    )
    assert status.error is not None
    assert "alembic.ini" in status.error


def test_admin_snapshot_redacts_password(tmp_path: Path) -> None:
    """Admin payload includes config and never echoes the Oracle password."""
    secret = "super-secret-password"
    settings = Settings(
        db_driver="memory",
        oracle_user="bookmarks",
        oracle_password=secret,
        oracle_dsn="db.example.net:1521/lab",
        media_root=tmp_path / "media",
        job_poll_seconds=0.05,
        job_max_attempts=3,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.get("/api/admin")
    assert response.status_code == 200
    assert secret not in response.text
    body = response.json()
    assert body["app_title"] == "Bald Bookmarks"
    assert body["config"]["db_driver"] == "memory"
    assert body["config"]["oracle_user"] == "bookmarks"
    assert body["config"]["oracle_dsn"] == "db.example.net:1521/lab"
    assert body["config"]["oracle_password_set"] is True
    assert "oracle_password" not in body["config"]
    assert body["database"]["ok"] is True
    assert body["database"]["driver"] == "memory"
    assert body["alembic"]["applicable"] is False
    assert "0002_description_varchar" in body["alembic"]["head_revisions"]
    assert body["alembic"]["current_revision"] is None
    assert body["scheduler"]["running"] is True
    assert "thumbnail.capture" in body["scheduler"]["registered_job_types"]
    assert body["queued_jobs"] == []
    assert body["job_history"] == []


def test_admin_snapshot_splits_queued_and_history(client: TestClient) -> None:
    """Pending jobs appear under queued; terminal jobs appear in history."""
    created = client.post(
        "/api/bookmarks",
        json={"title": "Example", "url": "https://example.com/admin"},
    )
    assert created.status_code == 201
    snapshot = client.get("/api/admin").json()
    combined = snapshot["queued_jobs"] + snapshot["job_history"]
    assert any(job["job_type"] == "thumbnail.capture" for job in combined)
    assert all(
        job["status"] in {JobStatus.PENDING, JobStatus.RUNNING}
        for job in snapshot["queued_jobs"]
    )
    assert all(
        job["status"] not in {JobStatus.PENDING, JobStatus.RUNNING}
        for job in snapshot["job_history"]
    )


def test_admin_history_includes_failed_job() -> None:
    """A failed job is listed in history, not the scheduled queue."""
    driver = MemoryDriver()
    driver.connect()
    job = driver.enqueue_job(
        JobEnqueue(job_type="thumbnail.capture", payload_json='{"bookmark_id": 1}')
    )
    driver.mark_job_failed(job.id, "boom", retry=False)
    queued = [
        item
        for item in driver.list_jobs()
        if item.status in {JobStatus.PENDING, JobStatus.RUNNING}
    ]
    history = [
        item
        for item in driver.list_jobs()
        if item.status not in {JobStatus.PENDING, JobStatus.RUNNING}
    ]
    assert queued == []
    assert history[0].id == job.id
    assert history[0].status == JobStatus.FAILED
    driver.close()
