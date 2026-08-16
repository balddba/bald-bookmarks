"""Admin console API routes."""

from fastapi import APIRouter, Request

from bald_bookmarks.api.deps import DriverDep, SchedulerDep, SettingsDep
from bald_bookmarks.config import Settings
from bald_bookmarks.db.abc import DatabaseDriver
from bald_bookmarks.db.migrate import describe_schema
from bald_bookmarks.domain.admin import (
    AdminConfig,
    AdminSnapshot,
    SchedulerStatus,
    SchemaStatus,
)
from bald_bookmarks.domain.bookmarks import BookmarkThumbnailUpdate, ThumbnailStatus
from bald_bookmarks.domain.jobs import Job, JobExecutionResult, JobStatus
from bald_bookmarks.services.thumbnail_jobs import enqueue_thumbnail_capture

router = APIRouter(prefix="/api/admin", tags=["admin"])

_QUEUED_STATUSES = {JobStatus.PENDING, JobStatus.RUNNING}


def public_config(settings: Settings) -> AdminConfig:
    """Build a sanitized settings view that never includes secrets.

    Args:
        settings (Settings): Application settings.

    Returns:
        AdminConfig: Public configuration fields.
    """
    return AdminConfig(
        db_driver=settings.db_driver,
        oracle_user=settings.oracle_user,
        oracle_dsn=settings.oracle_dsn,
        oracle_password_set=bool(settings.oracle_password),
        job_poll_seconds=settings.job_poll_seconds,
        job_max_attempts=settings.job_max_attempts,
        media_root=str(settings.media_root),
        thumbnails_dir=str(settings.thumbnails_dir),
        cors_origins=list(settings.cors_origins),
        thumbnail_viewport_width=settings.thumbnail_viewport_width,
        thumbnail_viewport_height=settings.thumbnail_viewport_height,
        thumbnail_timeout_ms=settings.thumbnail_timeout_ms,
        thumbnail_no_sandbox=settings.thumbnail_no_sandbox,
    )


def _schema_status(settings: Settings, driver: DatabaseDriver) -> SchemaStatus:
    """Read the deployed Alembic revision and compare it with local heads.

    Args:
        settings (Settings): Application settings.
        driver (DatabaseDriver): Database driver.

    Returns:
        SchemaStatus: Schema inspection result.
    """
    current_revision: str | None = None
    current_error: str | None = None
    try:
        current_revision = driver.alembic_revision()
    except Exception as exc:  # noqa: BLE001
        current_error = str(exc)
    return describe_schema(
        settings,
        current_revision,
        current_error=current_error,
    )


def _split_jobs(jobs: list[Job]) -> tuple[list[Job], list[Job]]:
    """Partition jobs into queued work and terminal history.

    Args:
        jobs (list[Job]): Recent jobs newest first.

    Returns:
        tuple[list[Job], list[Job]]: Queued jobs, then history.
    """
    queued = [job for job in jobs if job.status in _QUEUED_STATUSES]
    history = [job for job in jobs if job.status not in _QUEUED_STATUSES]
    return queued, history


@router.get("", response_model=AdminSnapshot)
def get_admin_snapshot(
    request: Request,
    settings: SettingsDep,
    driver: DriverDep,
    scheduler: SchedulerDep,
) -> AdminSnapshot:
    """Return configuration, schema, health, and job state.

    Args:
        request (Request): Current request (for app metadata).
        settings (SettingsDep): Application settings.
        driver (DriverDep): Database driver.
        scheduler (SchedulerDep): Background job scheduler.

    Returns:
        AdminSnapshot: Combined admin console payload.
    """
    queued_jobs, job_history = _split_jobs(driver.list_jobs(limit=100))
    return AdminSnapshot(
        app_title=request.app.title,
        app_version=request.app.version,
        config=public_config(settings),
        alembic=_schema_status(settings, driver),
        database=driver.health_check(),
        scheduler=SchedulerStatus(
            running=scheduler.is_running(),
            poll_seconds=settings.job_poll_seconds,
            registered_job_types=scheduler.registry.registered_types(),
        ),
        queued_jobs=queued_jobs,
        job_history=job_history,
    )


@router.post("/jobs/regenerate-thumbnails", response_model=JobExecutionResult)
def regenerate_all_thumbnails(
    settings: SettingsDep,
    driver: DriverDep,
) -> JobExecutionResult:
    """Enqueue thumbnail capture for every bookmark.

    Resets each bookmark's thumbnail status to pending and queues a
    thumbnail.capture job for the scheduler to process.

    Args:
        settings (SettingsDep): Application settings.
        driver (DriverDep): Database driver.

    Returns:
        JobExecutionResult: Count of bookmarks and jobs enqueued.
    """
    bookmarks = driver.list_bookmarks()
    for bookmark in bookmarks:
        driver.update_bookmark_thumbnail(
            bookmark.id,
            BookmarkThumbnailUpdate(
                thumbnail_status=ThumbnailStatus.PENDING,
                thumbnail_path=None,
                thumbnail_updated_at=None,
            ),
        )
        enqueue_thumbnail_capture(driver, bookmark.id, settings)
    return JobExecutionResult(
        job_type="thumbnail.capture",
        jobs_enqueued=len(bookmarks),
        bookmark_count=len(bookmarks),
    )
