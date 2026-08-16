"""Job domain and API models."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class JobStatus(StrEnum):
    """Lifecycle status for background jobs."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ThumbnailCapturePayload(BaseModel):
    """Payload for thumbnail.capture jobs.

    Attributes:
        bookmark_id (int): Bookmark to capture a preview for.
    """

    model_config = ConfigDict(extra="forbid")

    bookmark_id: int


class JobEnqueue(BaseModel):
    """Payload for enqueueing a background job.

    Attributes:
        job_type (str): Registered handler key (e.g. thumbnail.capture).
        payload_json (str): JSON-encoded handler payload.
        scheduled_at (datetime | None): When the job becomes eligible.
        max_attempts (int | None): Override for max attempts.
    """

    model_config = ConfigDict(extra="forbid")

    job_type: str = Field(min_length=1, max_length=128)
    payload_json: str = Field(min_length=2)
    scheduled_at: datetime | None = None
    max_attempts: int | None = Field(default=None, ge=1)


class JobExecutionResult(BaseModel):
    """Outcome of an admin-triggered bulk job enqueue.

    Attributes:
        job_type (str): Registered handler key that was enqueued.
        jobs_enqueued (int): Number of jobs created.
        bookmark_count (int): Bookmarks included in the operation.
    """

    model_config = ConfigDict(extra="forbid")

    job_type: str
    jobs_enqueued: int
    bookmark_count: int


class Job(BaseModel):
    """Persisted background job entity.

    Attributes:
        id (int): Primary key.
        job_type (str): Registered handler key.
        payload_json (str): JSON-encoded handler payload.
        status (JobStatus): Current lifecycle status.
        attempts (int): Number of execution attempts so far.
        max_attempts (int): Attempts allowed before permanent failure.
        scheduled_at (datetime): Eligibility timestamp.
        started_at (datetime | None): When the current/last run started.
        finished_at (datetime | None): When the job finished.
        last_error (str | None): Last failure message.
        created_at (datetime): Creation timestamp.
        updated_at (datetime): Last update timestamp.
    """

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: int
    job_type: str
    payload_json: str
    status: JobStatus
    attempts: int
    max_attempts: int
    scheduled_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime
