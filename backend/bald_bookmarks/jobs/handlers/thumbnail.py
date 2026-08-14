"""thumbnail.capture job handler using Playwright page previews."""

from datetime import UTC, datetime
from pathlib import Path

from loguru import logger

from bald_bookmarks.config import Settings
from bald_bookmarks.db.abc import DatabaseDriver
from bald_bookmarks.domain.bookmarks import BookmarkThumbnailUpdate, ThumbnailStatus
from bald_bookmarks.domain.jobs import Job, ThumbnailCapturePayload
from bald_bookmarks.services.page_preview import capture_page_preview


def handle_thumbnail_capture(
    driver: DatabaseDriver,
    job: Job,
    settings: object,
) -> None:
    """Capture a page preview thumbnail for a bookmark.

    Validates ThumbnailCapturePayload, marks the bookmark processing, renders
    the bookmark URL with Playwright into media/thumbnails, then marks the
    thumbnail ready. On failure the bookmark is marked failed before re-raising
    so the scheduler can retry.

    Args:
        driver (DatabaseDriver): Persistence driver.
        job (Job): Claimed job row.
        settings (object): Application Settings instance.

    Raises:
        ValueError: If settings is not a Settings instance.
        Exception: Propagates capture failures for scheduler retry logic.
    """
    if not isinstance(settings, Settings):
        raise ValueError("thumbnail handler requires Settings")
    payload = ThumbnailCapturePayload.model_validate_json(job.payload_json)
    bookmark = driver.get_bookmark(payload.bookmark_id)
    logger.info(
        "Capturing page preview for bookmark_id={} url={}",
        bookmark.id,
        bookmark.url,
    )
    driver.update_bookmark_thumbnail(
        bookmark.id,
        BookmarkThumbnailUpdate(thumbnail_status=ThumbnailStatus.PROCESSING),
    )
    thumbnails_dir = settings.thumbnails_dir
    thumbnails_dir.mkdir(parents=True, exist_ok=True)
    relative_path = f"thumbnails/{bookmark.id}.png"
    target = thumbnails_dir / f"{bookmark.id}.png"
    try:
        capture_page_preview(
            bookmark.url,
            target,
            viewport_width=settings.thumbnail_viewport_width,
            viewport_height=settings.thumbnail_viewport_height,
            timeout_ms=settings.thumbnail_timeout_ms,
            no_sandbox=_should_disable_sandbox(settings),
        )
    except Exception as exc:
        logger.warning(
            "Page preview failed bookmark_id={} error={}",
            bookmark.id,
            exc,
        )
        driver.update_bookmark_thumbnail(
            bookmark.id,
            BookmarkThumbnailUpdate(
                thumbnail_status=ThumbnailStatus.FAILED,
                thumbnail_path=None,
                thumbnail_updated_at=datetime.now(UTC),
            ),
        )
        raise

    driver.update_bookmark_thumbnail(
        bookmark.id,
        BookmarkThumbnailUpdate(
            thumbnail_status=ThumbnailStatus.READY,
            thumbnail_path=relative_path,
            thumbnail_updated_at=datetime.now(UTC),
        ),
    )


def _should_disable_sandbox(settings: Settings) -> bool:
    """Decide whether Chromium should launch without the sandbox.

    Args:
        settings (Settings): Application settings.

    Returns:
        bool: True when THUMBNAIL_NO_SANDBOX is set or running in Docker.
    """
    if settings.thumbnail_no_sandbox:
        return True
    return Path("/.dockerenv").exists()
