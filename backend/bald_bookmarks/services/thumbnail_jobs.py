"""Thumbnail capture job enqueue helpers."""

from bald_bookmarks.config import Settings
from bald_bookmarks.db.abc import DatabaseDriver
from bald_bookmarks.domain.jobs import JobEnqueue, ThumbnailCapturePayload


def enqueue_thumbnail_capture(
    driver: DatabaseDriver,
    bookmark_id: int,
    settings: Settings,
) -> None:
    """Enqueue a thumbnail.capture job for a bookmark.

    Args:
        driver (DatabaseDriver): Database driver.
        bookmark_id (int): Bookmark primary key.
        settings (Settings): Application settings.
    """
    payload = ThumbnailCapturePayload(bookmark_id=bookmark_id)
    driver.enqueue_job(
        JobEnqueue(
            job_type="thumbnail.capture",
            payload_json=payload.model_dump_json(),
            max_attempts=settings.job_max_attempts,
        )
    )
