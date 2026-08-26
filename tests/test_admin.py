"""Tests for the admin console API and related helpers."""

from pathlib import Path

from fastapi.testclient import TestClient

from bald_bookmarks.config import Settings
from bald_bookmarks.db.migrate import describe_schema
from bald_bookmarks.db.mysql.driver import MySQLDriver
from bald_bookmarks.db.oracle.driver import OracleDriver
from bald_bookmarks.db.postgres.driver import PostgresDriver
from bald_bookmarks.db.sqlite.driver import SQLiteDriver
from bald_bookmarks.domain.jobs import JobEnqueue, JobStatus
from bald_bookmarks.main import create_app


def test_sqlite_health_check_connected(tmp_path: Path) -> None:
    """Connected SQLite driver reports a healthy probe.

    Args:
        tmp_path (Path): Pytest temporary directory.
    """
    driver = SQLiteDriver(
        Settings(db_driver="sqlite", sqlite_path=tmp_path / "bookmarks.db")
    )
    assert driver.health_check().ok is False
    driver.connect()
    health = driver.health_check()
    assert health.ok is True
    assert health.driver == "sqlite"
    assert health.latency_ms is not None
    driver.close()
    assert driver.health_check().ok is False


def test_postgres_health_check_without_pool() -> None:
    """PostgreSQL health check fails closed when the pool has not been opened."""
    driver = PostgresDriver(
        Settings(
            db_driver="postgres",
            postgres_host="localhost",
            postgres_user="bookmarks",
            postgres_password="secret",
            postgres_database="bald_bookmarks",
        )
    )
    health = driver.health_check()
    assert health.ok is False
    assert health.driver == "postgres"
    assert "not open" in health.message


def test_mysql_health_check_without_pool() -> None:
    """MySQL health check fails closed when the pool has not been opened."""
    driver = MySQLDriver(
        Settings(
            db_driver="mysql",
            mysql_host="localhost",
            mysql_user="bookmarks",
            mysql_password="secret",
            mysql_database="bald_bookmarks",
        )
    )
    health = driver.health_check()
    assert health.ok is False
    assert health.driver == "mysql"
    assert "not open" in health.message


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
    status = describe_schema(Settings(db_driver="sqlite"), current_revision=None)
    assert status.applicable is True
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


def test_describe_schema_marks_postgres_current() -> None:
    """PostgreSQL deployments match when the DB revision is a local head."""
    settings = Settings(
        db_driver="postgres",
        postgres_host="localhost",
        postgres_user="bookmarks",
        postgres_password="secret",
        postgres_database="bald_bookmarks",
    )
    status = describe_schema(settings, current_revision="0002_description_varchar")
    assert status.applicable is True
    assert status.is_current is True


def test_describe_schema_missing_ini(tmp_path: Path) -> None:
    """Missing alembic.ini is reported on the schema status.

    Args:
        tmp_path (Path): Pytest temporary directory.
    """
    status = describe_schema(
        Settings(db_driver="sqlite"),
        current_revision=None,
        alembic_root=tmp_path,
    )
    assert status.error is not None
    assert "alembic.ini" in status.error


def test_admin_snapshot_redacts_password(tmp_path: Path) -> None:
    """Admin payload includes config and never echoes the Oracle password.

    Args:
        tmp_path (Path): Pytest temporary directory.
    """
    secret = "super-secret-password"
    settings = Settings(
        db_driver="sqlite",
        sqlite_path=tmp_path / "bookmarks.db",
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
    assert body["config"]["db_driver"] == "sqlite"
    assert body["config"]["sqlite_path"] == str(tmp_path / "bookmarks.db")
    assert body["config"]["oracle_user"] == "bookmarks"
    assert body["config"]["oracle_dsn"] == "db.example.net:1521/lab"
    assert body["config"]["oracle_password_set"] is True
    assert "oracle_password" not in body["config"]
    assert "postgres_password" not in body["config"]
    assert "mysql_password" not in body["config"]
    assert body["database"]["ok"] is True
    assert body["database"]["driver"] == "sqlite"
    assert body["alembic"]["applicable"] is True
    assert "0002_description_varchar" in body["alembic"]["head_revisions"]
    assert body["alembic"]["current_revision"] == "0002_description_varchar"
    assert body["scheduler"]["running"] is True
    assert "thumbnail.capture" in body["scheduler"]["registered_job_types"]
    assert body["queued_jobs"] == []
    assert body["job_history"] == []


def test_admin_snapshot_splits_queued_and_history(client: TestClient) -> None:
    """Pending jobs appear under queued; terminal jobs appear in history.

    Args:
        client (TestClient): Test client instance.
    """
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


def test_admin_history_includes_failed_job(driver: object) -> None:
    """A failed job is listed in history, not the scheduled queue.

    Args:
        driver (object): Pytest fixture providing database driver.
    """
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


def test_admin_regenerate_all_thumbnails(client: TestClient) -> None:
    """Bulk thumbnail regeneration enqueues one job per bookmark.

    Args:
        client (TestClient): Test client instance.
    """
    client.post(
        "/api/bookmarks",
        json={"title": "One", "url": "https://example.com/one"},
    )
    client.post(
        "/api/bookmarks",
        json={"title": "Two", "url": "https://example.com/two"},
    )

    response = client.post("/api/admin/jobs/regenerate-thumbnails")
    assert response.status_code == 200
    body = response.json()
    assert body["job_type"] == "thumbnail.capture"
    assert body["bookmark_count"] == 2
    assert body["jobs_enqueued"] == 2

    snapshot = client.get("/api/admin").json()
    thumbnail_jobs = [
        job for job in snapshot["queued_jobs"] if job["job_type"] == "thumbnail.capture"
    ]
    assert len(thumbnail_jobs) >= 2


def test_admin_regenerate_all_thumbnails_empty(client: TestClient) -> None:
    """Bulk regeneration with no bookmarks enqueues zero jobs.

    Args:
        client (TestClient): Test client instance.
    """
    response = client.post("/api/admin/jobs/regenerate-thumbnails")
    assert response.status_code == 200
    body = response.json()
    assert body["jobs_enqueued"] == 0
    assert body["bookmark_count"] == 0
