"""Tag API routes."""

from fastapi import APIRouter, HTTPException, status

from bald_bookmarks.api.deps import DriverDep
from bald_bookmarks.db.exceptions import ConflictError, NotFoundError
from bald_bookmarks.domain.tags import Tag, TagCreate

router = APIRouter(prefix="/api/tags", tags=["tags"])


@router.get("", response_model=list[Tag])
def list_tags(driver: DriverDep) -> list[Tag]:
    """List all tags.

    Args:
        driver (DriverDep): Database driver.

    Returns:
        list[Tag]: Tags sorted by name.
    """
    return driver.list_tags()


@router.post("", response_model=Tag, status_code=status.HTTP_201_CREATED)
def create_tag(payload: TagCreate, driver: DriverDep) -> Tag:
    """Create a tag.

    Args:
        payload (TagCreate): Creation payload.
        driver (DriverDep): Database driver.

    Returns:
        Tag: Created tag.
    """
    try:
        return driver.create_tag(payload)
    except ConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tag(tag_id: int, driver: DriverDep) -> None:
    """Delete a tag.

    Args:
        tag_id (int): Tag primary key.
        driver (DriverDep): Database driver.
    """
    try:
        driver.delete_tag(tag_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
