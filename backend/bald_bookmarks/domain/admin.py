"""Admin console models for runtime inspection."""

from pydantic import BaseModel, ConfigDict, Field

from bald_bookmarks.domain.jobs import Job


class AdminConfig(BaseModel):
    """Sanitized runtime configuration (secrets omitted).

    Attributes:
        db_driver (str): Database driver name (oracle or memory).
        oracle_user (str | None): Oracle username when configured.
        oracle_dsn (str | None): Oracle Easy Connect or TNS DSN.
        oracle_password_set (bool): True when a password is present.
        job_poll_seconds (float): Seconds between job poll cycles.
        job_max_attempts (int): Max attempts before a job is failed.
        media_root (str): Root directory for thumbnail media files.
        thumbnails_dir (str): Resolved thumbnail directory.
        cors_origins (list[str]): Allowed browser origins for CORS.
        thumbnail_viewport_width (int): Screenshot viewport width in pixels.
        thumbnail_viewport_height (int): Screenshot viewport height in pixels.
        thumbnail_timeout_ms (int): Page navigation timeout for previews.
        thumbnail_no_sandbox (bool): Launch Chromium without the sandbox.
    """

    model_config = ConfigDict(extra="forbid")

    db_driver: str
    oracle_user: str | None
    oracle_dsn: str | None
    oracle_password_set: bool
    job_poll_seconds: float
    job_max_attempts: int
    media_root: str
    thumbnails_dir: str
    cors_origins: list[str]
    thumbnail_viewport_width: int
    thumbnail_viewport_height: int
    thumbnail_timeout_ms: int
    thumbnail_no_sandbox: bool


class SchemaRevision(BaseModel):
    """One Alembic revision from the local script directory.

    Attributes:
        revision (str): Revision identifier.
        down_revision (str | None): Parent revision identifier.
        doc (str | None): First line of the revision docstring.
    """

    model_config = ConfigDict(extra="forbid")

    revision: str
    down_revision: str | None
    doc: str | None


class SchemaStatus(BaseModel):
    """Deployed Alembic revision compared with local heads.

    Attributes:
        applicable (bool): True when the Oracle driver applies migrations.
        current_revision (str | None): Revision stored in alembic_version.
        head_revisions (list[str]): Head revision ids from local scripts.
        is_current (bool | None): True when current matches a local head.
        revisions (list[SchemaRevision]): Local revision chain, newest first.
        error (str | None): Inspection error message when lookup failed.
    """

    model_config = ConfigDict(extra="forbid")

    applicable: bool
    current_revision: str | None
    head_revisions: list[str] = Field(default_factory=list)
    is_current: bool | None
    revisions: list[SchemaRevision] = Field(default_factory=list)
    error: str | None = None


class DatabaseHealth(BaseModel):
    """Result of a database connectivity probe.

    Attributes:
        ok (bool): True when the probe succeeded.
        driver (str): Driver name that performed the probe.
        latency_ms (float | None): Probe duration in milliseconds.
        message (str): Human-readable probe outcome.
    """

    model_config = ConfigDict(extra="forbid")

    ok: bool
    driver: str
    latency_ms: float | None
    message: str


class SchedulerStatus(BaseModel):
    """In-process job scheduler state.

    Attributes:
        running (bool): True when the poll loop task is active.
        poll_seconds (float): Configured seconds between idle polls.
        registered_job_types (list[str]): Handler keys in the registry.
    """

    model_config = ConfigDict(extra="forbid")

    running: bool
    poll_seconds: float
    registered_job_types: list[str]


class AdminSnapshot(BaseModel):
    """Combined payload for the admin console.

    Attributes:
        app_title (str): FastAPI application title.
        app_version (str): FastAPI application version.
        config (AdminConfig): Sanitized settings.
        alembic (SchemaStatus): Alembic deployment status.
        database (DatabaseHealth): Connectivity probe result.
        scheduler (SchedulerStatus): Background scheduler status.
        queued_jobs (list[Job]): Pending and running jobs.
        job_history (list[Job]): Terminal job rows newest first.
    """

    model_config = ConfigDict(extra="forbid")

    app_title: str
    app_version: str
    config: AdminConfig
    alembic: SchemaStatus
    database: DatabaseHealth
    scheduler: SchedulerStatus
    queued_jobs: list[Job]
    job_history: list[Job]
