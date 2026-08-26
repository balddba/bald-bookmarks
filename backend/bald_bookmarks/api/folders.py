"""Folder API routes."""

from fastapi import APIRouter, HTTPException, Query, status

from bald_bookmarks.api.deps import DriverDep
from bald_bookmarks.db.exceptions import ConflictError, NotFoundError, ValidationError
from bald_bookmarks.domain.folders import (
    Folder,
    FolderCreate,
    FolderTreeNode,
    FolderUpdate,
)

router = APIRouter(prefix="/api/folders", tags=["folders"])


@router.get("/tree")
def get_folder_tree(driver: DriverDep) -> list[FolderTreeNode]:
    """Return the nested folder hierarchy.

    Args:
        driver (DriverDep): Database driver.

    Returns:
        list[FolderTreeNode]: Root nodes with children.
    """
    return driver.get_folder_tree()


@router.get("/{folder_id}")
def get_folder(folder_id: int, driver: DriverDep) -> Folder:
    """Fetch a single folder.

    Args:
        folder_id (int): Folder primary key.
        driver (DriverDep): Database driver.

    Returns:
        Folder: Matching folder.

    Raises:
        HTTPException: If the folder is not found.
    """
    try:
        return driver.get_folder(folder_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.get("/{folder_id}/children")
def list_children(folder_id: int, driver: DriverDep) -> list[Folder]:
    """List direct children of a folder.

    Args:
        folder_id (int): Folder primary key.
        driver (DriverDep): Database driver.

    Returns:
        list[Folder]: Child folders.

    Raises:
        HTTPException: If the parent folder is not found.
    """
    try:
        driver.get_folder(folder_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return driver.list_folder_children(folder_id)


@router.get("")
def list_root_folders(driver: DriverDep) -> list[Folder]:
    """List root folders.

    Args:
        driver (DriverDep): Database driver.

    Returns:
        list[Folder]: Root folders.
    """
    return driver.list_folder_children(None)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_folder(payload: FolderCreate, driver: DriverDep) -> Folder:
    """Create a folder.

    Args:
        payload (FolderCreate): Creation payload.
        driver (DriverDep): Database driver.

    Returns:
        Folder: Created folder.

    Raises:
        HTTPException: If the specified parent folder is not found.
    """
    try:
        return driver.create_folder(payload)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.patch("/{folder_id}")
def update_folder(
    folder_id: int,
    payload: FolderUpdate,
    driver: DriverDep,
) -> Folder:
    """Update a folder.

    Args:
        folder_id (int): Folder primary key.
        payload (FolderUpdate): Update payload.
        driver (DriverDep): Database driver.

    Returns:
        Folder: Updated folder.

    Raises:
        HTTPException: If folder is not found or move creates a cycle.
    """
    try:
        return driver.update_folder(folder_id, payload)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.delete("/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_folder(
    folder_id: int,
    driver: DriverDep,
    recursive: bool = Query(default=False),
) -> None:
    """Delete a folder.

    Args:
        folder_id (int): Folder primary key.
        driver (DriverDep): Database driver.
        recursive (bool): Delete descendants and bookmarks when True.

    Raises:
        HTTPException: If folder is not found or has contents without recursive=True.
    """
    try:
        driver.delete_folder(folder_id, recursive=recursive)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
