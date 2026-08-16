"""Bookmark API routes."""

from fastapi import APIRouter, HTTPException, Query, status

from bald_bookmarks.api.deps import DriverDep, SettingsDep
from bald_bookmarks.db.exceptions import NotFoundError
from bald_bookmarks.domain.bookmarks import (
    Bookmark,
    BookmarkCreate,
    BookmarkThumbnailUpdate,
    BookmarkUpdate,
    ThumbnailStatus,
)
from bald_bookmarks.services.thumbnail_jobs import enqueue_thumbnail_capture
from bald_bookmarks.services.url_metadata import (
    UrlMetadataError,
    UrlMetadataRequest,
    UrlMetadataResponse,
    fetch_url_metadata,
)

router = APIRouter(prefix="/api/bookmarks", tags=["bookmarks"])


@router.get("", response_model=list[Bookmark])
def list_bookmarks(
    driver: DriverDep,
    folder_id: int | None = Query(default=None),
    q: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    unfiled_only: bool = Query(default=False),
) -> list[Bookmark]:
    """List bookmarks with optional filters.

    Args:
        driver (DriverDep): Database driver.
        folder_id (int | None): Restrict to folder.
        q (str | None): Search text.
        tag (str | None): Tag name filter.
        unfiled_only (bool): Only unfiled bookmarks.

    Returns:
        list[Bookmark]: Matching bookmarks.
    """
    return driver.list_bookmarks(
        folder_id=folder_id,
        q=q,
        tag=tag,
        unfiled_only=unfiled_only,
    )


@router.post("/url-preview", response_model=UrlMetadataResponse)
def preview_bookmark_url(payload: UrlMetadataRequest) -> UrlMetadataResponse:
    """Fetch page title and description for a bookmark URL.

    Used by the create/edit form when the URL field loses focus.

    Args:
        payload (UrlMetadataRequest): URL to inspect.

    Returns:
        UrlMetadataResponse: Extracted metadata for the page.
    """
    try:
        return fetch_url_metadata(payload.url)
    except UrlMetadataError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.message,
        ) from exc


@router.get("/{bookmark_id}", response_model=Bookmark)
def get_bookmark(bookmark_id: int, driver: DriverDep) -> Bookmark:
    """Fetch a bookmark.

    Args:
        bookmark_id (int): Bookmark primary key.
        driver (DriverDep): Database driver.

    Returns:
        Bookmark: Matching bookmark.
    """
    try:
        return driver.get_bookmark(bookmark_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post("", response_model=Bookmark, status_code=status.HTTP_201_CREATED)
def create_bookmark(
    payload: BookmarkCreate,
    driver: DriverDep,
    settings: SettingsDep,
) -> Bookmark:
    """Create a bookmark and enqueue thumbnail capture.

    Args:
        payload (BookmarkCreate): Creation payload.
        driver (DriverDep): Database driver.
        settings (SettingsDep): Application settings.

    Returns:
        Bookmark: Created bookmark.
    """
    try:
        bookmark = driver.create_bookmark(payload)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    enqueue_thumbnail_capture(driver, bookmark.id, settings)
    return bookmark


@router.patch("/{bookmark_id}", response_model=Bookmark)
def update_bookmark(
    bookmark_id: int,
    payload: BookmarkUpdate,
    driver: DriverDep,
    settings: SettingsDep,
) -> Bookmark:
    """Update a bookmark and re-queue thumbnail when URL changes.

    Args:
        bookmark_id (int): Bookmark primary key.
        payload (BookmarkUpdate): Update payload.
        driver (DriverDep): Database driver.
        settings (SettingsDep): Application settings.

    Returns:
        Bookmark: Updated bookmark.
    """
    try:
        current = driver.get_bookmark(bookmark_id)
        updated = driver.update_bookmark(bookmark_id, payload)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    updates = payload.model_dump(exclude_unset=True)
    if "url" in updates and updates["url"] != current.url:
        driver.update_bookmark_thumbnail(
            bookmark_id,
            BookmarkThumbnailUpdate(
                thumbnail_status=ThumbnailStatus.PENDING,
                thumbnail_path=None,
                thumbnail_updated_at=None,
            ),
        )
        enqueue_thumbnail_capture(driver, bookmark_id, settings)
        updated = driver.get_bookmark(bookmark_id)
    return updated


@router.delete("/{bookmark_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bookmark(bookmark_id: int, driver: DriverDep) -> None:
    """Delete a bookmark.

    Args:
        bookmark_id (int): Bookmark primary key.
        driver (DriverDep): Database driver.
    """
    try:
        driver.delete_bookmark(bookmark_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post("/{bookmark_id}/thumbnail/refresh", response_model=Bookmark)
def refresh_thumbnail(
    bookmark_id: int,
    driver: DriverDep,
    settings: SettingsDep,
) -> Bookmark:
    """Re-queue thumbnail capture for a bookmark.

    Args:
        bookmark_id (int): Bookmark primary key.
        driver (DriverDep): Database driver.
        settings (SettingsDep): Application settings.

    Returns:
        Bookmark: Bookmark with pending thumbnail status.
    """
    try:
        driver.get_bookmark(bookmark_id)
        bookmark = driver.update_bookmark_thumbnail(
            bookmark_id,
            BookmarkThumbnailUpdate(
                thumbnail_status=ThumbnailStatus.PENDING,
                thumbnail_path=None,
                thumbnail_updated_at=None,
            ),
        )
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    enqueue_thumbnail_capture(driver, bookmark_id, settings)
    return bookmark
