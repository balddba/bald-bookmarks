"""Job API routes."""

from fastapi import APIRouter, HTTPException, Query, status

from bald_bookmarks.api.deps import DriverDep
from bald_bookmarks.db.exceptions import NotFoundError
from bald_bookmarks.domain.jobs import Job

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("")
def list_jobs(
    driver: DriverDep,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[Job]:
    """List recent background jobs.

    Args:
        driver (DriverDep): Database driver.
        limit (int): Maximum rows to return.

    Returns:
        list[Job]: Recent jobs.
    """
    return driver.list_jobs(limit=limit)


@router.get("/{job_id}")
def get_job(job_id: int, driver: DriverDep) -> Job:
    """Fetch a background job.

    Args:
        job_id (int): Job primary key.
        driver (DriverDep): Database driver.

    Returns:
        Job: Matching job.

    Raises:
        HTTPException: If the job is not found.
    """
    try:
        return driver.get_job(job_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
