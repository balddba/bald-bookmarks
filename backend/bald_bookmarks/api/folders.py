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


@router.get("/tree", response_model=list[FolderTreeNode])
def get_folder_tree(driver: DriverDep) -> list[FolderTreeNode]:
    """Return the nested folder hierarchy.

    Args:
        driver (DriverDep): Database driver.

    Returns:
        list[FolderTreeNode]: Root nodes with children.
    """
    return driver.get_folder_tree()


@router.get("/{folder_id}", response_model=Folder)
def get_folder(folder_id: int, driver: DriverDep) -> Folder:
    """Fetch a single folder.

    Args:
        folder_id (int): Folder primary key.
        driver (DriverDep): Database driver.

    Returns:
        Folder: Matching folder.
    """
    try:
        return driver.get_folder(folder_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.get("/{folder_id}/children", response_model=list[Folder])
def list_children(folder_id: int, driver: DriverDep) -> list[Folder]:
    """List direct children of a folder.

    Args:
        folder_id (int): Folder primary key.
        driver (DriverDep): Database driver.

    Returns:
        list[Folder]: Child folders.
    """
    try:
        driver.get_folder(folder_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return driver.list_folder_children(folder_id)


@router.get("", response_model=list[Folder])
def list_root_folders(driver: DriverDep) -> list[Folder]:
    """List root folders.

    Args:
        driver (DriverDep): Database driver.

    Returns:
        list[Folder]: Root folders.
    """
    return driver.list_folder_children(None)


@router.post("", response_model=Folder, status_code=status.HTTP_201_CREATED)
def create_folder(payload: FolderCreate, driver: DriverDep) -> Folder:
    """Create a folder.

    Args:
        payload (FolderCreate): Creation payload.
        driver (DriverDep): Database driver.

    Returns:
        Folder: Created folder.
    """
    try:
        return driver.create_folder(payload)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.patch("/{folder_id}", response_model=Folder)
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
