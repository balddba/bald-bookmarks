"""Bookmark API routes."""

import json
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from bald_bookmarks.api.deps import DriverDep, SettingsDep
from bald_bookmarks.db.exceptions import NotFoundError
from bald_bookmarks.domain.bookmarks import (
    Bookmark,
    BookmarkCreate,
    BookmarkThumbnailUpdate,
    BookmarkUpdate,
    ThumbnailStatus,
)
from bald_bookmarks.domain.export_import import (
    ExportFormat,
    ImportRequest,
    ImportResult,
)
from bald_bookmarks.services.export_import import BookmarkBackupService
from bald_bookmarks.services.thumbnail_jobs import enqueue_thumbnail_capture
from bald_bookmarks.services.url_metadata import (
    UrlMetadataError,
    UrlMetadataRequest,
    UrlMetadataResponse,
    fetch_url_metadata,
)

router = APIRouter(prefix="/api/bookmarks", tags=["bookmarks"])


@router.get("")
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


@router.post("/url-preview")
def preview_bookmark_url(payload: UrlMetadataRequest) -> UrlMetadataResponse:
    """Fetch page title and description for a bookmark URL.

    Used by the create/edit form when the URL field loses focus.

    Args:
        payload (UrlMetadataRequest): URL to inspect.

    Returns:
        UrlMetadataResponse: Extracted metadata for the page.

    Raises:
        HTTPException: If fetching URL metadata fails.
    """
    try:
        return fetch_url_metadata(payload.url)
    except UrlMetadataError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.message,
        ) from exc


@router.get("/export")
def export_bookmarks(
    driver: DriverDep,
    settings: SettingsDep,
    format: ExportFormat = Query(default=ExportFormat.JSON),
    folder_id: int | None = Query(default=None),
) -> Response:
    """Export bookmarks and folders as JSON backup or Netscape HTML.

    Args:
        driver (DriverDep): Database driver.
        settings (SettingsDep): Application settings.
        format (ExportFormat): Export serialization format (json or html).
        folder_id (int | None): Optional folder id scope.

    Returns:
        Response: Downloadable file response with attachment headers.

    Raises:
        HTTPException: If the specified folder is not found.
    """
    service = BookmarkBackupService(driver=driver, settings=settings)
    try:
        now_str = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
        if format == ExportFormat.HTML:
            html_content = service.export_html(folder_id=folder_id)
            filename = f"bald-bookmarks-{now_str}.html"
            return Response(
                content=html_content,
                media_type="text/html; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        backup = service.export_backup(folder_id=folder_id)
        json_content = backup.model_dump_json(indent=2)
        filename = f"bald-bookmarks-backup-{now_str}.json"
        return Response(
            content=json_content,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post("/import", status_code=status.HTTP_200_OK)
async def import_bookmarks(
    request: Request,
    driver: DriverDep,
    settings: SettingsDep,
    target_folder_id: int | None = Query(default=None),
    skip_existing: bool = Query(default=True),
    enqueue_thumbnails: bool = Query(default=True),
) -> ImportResult:
    """Import bookmarks and folders from a JSON backup or Netscape HTML file.

    Accepts raw file content, raw JSON, or an ImportRequest JSON body.

    Args:
        request (Request): Incoming HTTP request.
        driver (DriverDep): Database driver.
        settings (SettingsDep): Application settings.
        target_folder_id (int | None): Optional target folder id.
        skip_existing (bool): Whether to skip duplicate bookmark URLs.
        enqueue_thumbnails (bool): Whether to enqueue thumbnail jobs.

    Returns:
        ImportResult: Summary of imported folders, bookmarks, and tags.

    Raises:
        HTTPException: If the input is empty, invalid, or target folder missing.
    """
    body_bytes = await request.body()
    if not body_bytes.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Import payload is empty",
        )

    text = body_bytes.decode("utf-8", errors="replace")
    service = BookmarkBackupService(driver=driver, settings=settings)

    trimmed = text.strip()
    if trimmed.startswith("{"):
        try:
            parsed_json = json.loads(trimmed)
            if isinstance(parsed_json, dict) and "content" in parsed_json:
                req = ImportRequest.model_validate(parsed_json)
                effective_target = (
                    req.target_folder_id
                    if req.target_folder_id is not None
                    else target_folder_id
                )
                effective_skip = (
                    req.skip_existing
                    if req.skip_existing is not None
                    else skip_existing
                )
                effective_thumb = (
                    req.enqueue_thumbnails
                    if req.enqueue_thumbnails is not None
                    else enqueue_thumbnails
                )
                if req.backup is not None:
                    try:
                        return service.import_backup(
                            backup=req.backup,
                            target_folder_id=effective_target,
                            skip_existing=effective_skip,
                            enqueue_thumbnails=effective_thumb,
                        )
                    except NotFoundError as exc:
                        raise HTTPException(
                            status_code=status.HTTP_404_NOT_FOUND,
                            detail=str(exc),
                        ) from exc
                if req.content is not None:
                    text = req.content
                    target_folder_id = effective_target
                    skip_existing = effective_skip
                    enqueue_thumbnails = effective_thumb
        except Exception:  # noqa: BLE001
            pass

    try:
        return service.import_text(
            text=text,
            target_folder_id=target_folder_id,
            skip_existing=skip_existing,
            enqueue_thumbnails=enqueue_thumbnails,
        )
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/{bookmark_id}")
def get_bookmark(bookmark_id: int, driver: DriverDep) -> Bookmark:
    """Fetch a bookmark.

    Args:
        bookmark_id (int): Bookmark primary key.
        driver (DriverDep): Database driver.

    Returns:
        Bookmark: Matching bookmark.

    Raises:
        HTTPException: If the bookmark is not found.
    """
    try:
        return driver.get_bookmark(bookmark_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post("", status_code=status.HTTP_201_CREATED)
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

    Raises:
        HTTPException: If the specified folder is not found.
    """
    try:
        bookmark = driver.create_bookmark(payload)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    enqueue_thumbnail_capture(driver, bookmark.id, settings)
    return bookmark


@router.patch("/{bookmark_id}")
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

    Raises:
        HTTPException: If the bookmark or folder is not found.
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

    Raises:
        HTTPException: If the bookmark is not found.
    """
    try:
        driver.delete_bookmark(bookmark_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post("/{bookmark_id}/thumbnail/refresh")
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

    Raises:
        HTTPException: If the bookmark is not found.
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
