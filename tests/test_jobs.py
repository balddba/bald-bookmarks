"""Unit tests for SQLiteDriver CRUD and thumbnail job handling."""

from pathlib import Path
from unittest.mock import patch

import pytest

from bald_bookmarks.config import Settings
from bald_bookmarks.db.exceptions import ConflictError, NotFoundError, ValidationError
from bald_bookmarks.db.sqlite.driver import SQLiteDriver
from bald_bookmarks.domain.bookmarks import BookmarkCreate
from bald_bookmarks.domain.folders import FolderCreate, FolderUpdate
from bald_bookmarks.domain.jobs import JobEnqueue, ThumbnailCapturePayload
from bald_bookmarks.domain.tags import TagCreate
from bald_bookmarks.jobs.handlers.thumbnail import handle_thumbnail_capture
from bald_bookmarks.jobs.registry import build_default_registry
from bald_bookmarks.jobs.scheduler import JobScheduler
from bald_bookmarks.services.page_preview import PagePreviewError


def test_folder_cycle_validation(driver: SQLiteDriver) -> None:
    """Reject moves that would create a folder cycle.

    Args:
        driver (SQLiteDriver): SQLite driver fixture.
    """
    root = driver.create_folder(FolderCreate(name="Root"))
    child = driver.create_folder(FolderCreate(name="Child", parent_id=root.id))
    with pytest.raises(ValidationError):
        driver.update_folder(root.id, FolderUpdate(parent_id=child.id))


def test_recursive_folder_delete_removes_nested_contents(
    driver: SQLiteDriver,
) -> None:
    """Recursive delete removes descendant folders and bookmarks.

    Args:
        driver (SQLiteDriver): SQLite driver fixture.
    """
    root = driver.create_folder(FolderCreate(name="Root"))
    child = driver.create_folder(FolderCreate(name="Child", parent_id=root.id))
    driver.create_bookmark(
        BookmarkCreate(
            title="Root page",
            url="https://example.com/root",
            folder_id=root.id,
        )
    )
    driver.create_bookmark(
        BookmarkCreate(
            title="Child page",
            url="https://example.com/child",
            folder_id=child.id,
        )
    )
    driver.delete_folder(root.id, recursive=True)
    assert driver.get_folder_tree() == []
    assert driver.list_bookmarks() == []


def test_tag_conflict(driver: SQLiteDriver) -> None:
    """Creating a duplicate tag raises ConflictError.

    Args:
        driver (SQLiteDriver): SQLite driver fixture.
    """
    driver.create_tag(TagCreate(name="Ops"))
    with pytest.raises(ConflictError):
        driver.create_tag(TagCreate(name="ops"))


def test_missing_entities(driver: SQLiteDriver) -> None:
    """Missing entity lookups raise NotFoundError.

    Args:
        driver (SQLiteDriver): SQLite driver fixture.
    """
    with pytest.raises(NotFoundError):
        driver.get_folder(999)
    with pytest.raises(NotFoundError):
        driver.get_bookmark(999)
    with pytest.raises(NotFoundError):
        driver.get_job(999)


def test_thumbnail_handler_writes_preview(
    driver: SQLiteDriver,
    tmp_path: Path,
) -> None:
    """Thumbnail handler writes a PNG and marks the bookmark ready.

    Args:
        driver (SQLiteDriver): SQLite driver fixture.
        tmp_path (Path): Pytest temporary directory.
    """
    bookmark = driver.create_bookmark(
        BookmarkCreate(title="Site", url="https://example.com")
    )
    settings = Settings(
        db_driver="sqlite",
        sqlite_path=tmp_path / "bookmarks.db",
        media_root=tmp_path / "media",
    )
    job = driver.enqueue_job(
        JobEnqueue(
            job_type="thumbnail.capture",
            payload_json=ThumbnailCapturePayload(
                bookmark_id=bookmark.id
            ).model_dump_json(),
        )
    )
    claimed = driver.claim_next_job()
    assert claimed is not None
    assert claimed.id == job.id

    def _fake_capture(url: str, destination: Path, **_: object) -> Path:
        """Write a tiny PNG for the mocked capture.

        Args:
            url (str): Bookmark URL (unused).
            destination (Path): Output path.
            **_ (object): Ignored capture options.

        Returns:
            Path: Written destination path.
        """
        _ = url
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
            b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        return destination

    with patch(
        "bald_bookmarks.jobs.handlers.thumbnail.capture_page_preview",
        side_effect=_fake_capture,
    ):
        handle_thumbnail_capture(driver, claimed, settings)
    updated = driver.get_bookmark(bookmark.id)
    assert updated.thumbnail_status.value == "ready"
    assert updated.thumbnail_path == f"thumbnails/{bookmark.id}.png"
    assert (settings.thumbnails_dir / f"{bookmark.id}.png").is_file()
    driver.mark_job_succeeded(claimed.id)
    assert driver.get_job(claimed.id).status.value == "succeeded"


def test_thumbnail_handler_marks_failed_on_error(
    driver: SQLiteDriver,
    tmp_path: Path,
) -> None:
    """Capture failures mark the bookmark thumbnail as failed.

    Args:
        driver (SQLiteDriver): SQLite driver fixture.
        tmp_path (Path): Pytest temporary directory.
    """
    bookmark = driver.create_bookmark(
        BookmarkCreate(title="Broken", url="https://example.com/missing")
    )
    settings = Settings(
        db_driver="sqlite",
        sqlite_path=tmp_path / "bookmarks.db",
        media_root=tmp_path / "media",
    )
    driver.enqueue_job(
        JobEnqueue(
            job_type="thumbnail.capture",
            payload_json=ThumbnailCapturePayload(
                bookmark_id=bookmark.id
            ).model_dump_json(),
        )
    )
    claimed = driver.claim_next_job()
    assert claimed is not None
    with (
        patch(
            "bald_bookmarks.jobs.handlers.thumbnail.capture_page_preview",
            side_effect=PagePreviewError("boom"),
        ),
        pytest.raises(PagePreviewError),
    ):
        handle_thumbnail_capture(driver, claimed, settings)
    updated = driver.get_bookmark(bookmark.id)
    assert updated.thumbnail_status.value == "failed"
    assert updated.thumbnail_path is None


def test_scheduler_processes_thumbnail_job(
    driver: SQLiteDriver,
    tmp_path: Path,
) -> None:
    """Scheduler claims and completes a thumbnail job.

    Args:
        driver (SQLiteDriver): SQLite driver fixture.
        tmp_path (Path): Pytest temporary directory.
    """
    settings = Settings(
        db_driver="sqlite",
        sqlite_path=tmp_path / "bookmarks.db",
        media_root=tmp_path / "media",
        job_poll_seconds=0.01,
    )
    bookmark = driver.create_bookmark(
        BookmarkCreate(title="Queued", url="https://queued.test")
    )
    driver.enqueue_job(
        JobEnqueue(
            job_type="thumbnail.capture",
            payload_json=ThumbnailCapturePayload(
                bookmark_id=bookmark.id
            ).model_dump_json(),
        )
    )

    def _fake_capture(url: str, destination: Path, **_: object) -> Path:
        """Write a tiny PNG for the mocked capture.

        Args:
            url (str): Bookmark URL (unused).
            destination (Path): Output path.
            **_ (object): Ignored capture options.

        Returns:
            Path: Written destination path.
        """
        _ = url
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
            b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        return destination

    with patch(
        "bald_bookmarks.jobs.handlers.thumbnail.capture_page_preview",
        side_effect=_fake_capture,
    ):
        scheduler = JobScheduler(driver, build_default_registry(), settings)
        processed = scheduler._process_one()
    assert processed is True
    assert driver.get_bookmark(bookmark.id).thumbnail_status.value == "ready"
    jobs = driver.list_jobs()
    assert jobs[0].status.value == "succeeded"
