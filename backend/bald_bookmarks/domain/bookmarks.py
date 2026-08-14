"""Bookmark domain and API models."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from bald_bookmarks.domain.tags import Tag

DESCRIPTION_MAX_LENGTH = 256


class ThumbnailStatus(StrEnum):
    """Lifecycle status for bookmark preview thumbnails."""

    NONE = "none"
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class BookmarkCreate(BaseModel):
    """Payload for creating a bookmark.

    Attributes:
        title (str): Bookmark title.
        url (str): Bookmark URL.
        description (str | None): Optional description.
        folder_id (int | None): Containing folder id, or None if unfiled.
        tag_names (list[str]): Tag names to attach on create.
    """

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=512)
    url: str = Field(min_length=1, max_length=2048)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)
    folder_id: int | None = None
    tag_names: list[str] = Field(default_factory=list)


class BookmarkUpdate(BaseModel):
    """Payload for updating a bookmark.

    Attributes:
        title (str | None): New title.
        url (str | None): New URL.
        description (str | None): New description.
        folder_id (int | None): New folder id.
        tag_names (list[str] | None): Replacement tag set when provided.
    """

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=512)
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)
    folder_id: int | None = None
    tag_names: list[str] | None = None


class Bookmark(BaseModel):
    """Persisted bookmark entity.

    Attributes:
        id (int): Primary key.
        title (str): Bookmark title.
        url (str): Bookmark URL.
        description (str | None): Optional description.
        folder_id (int | None): Containing folder id, or None if unfiled.
        thumbnail_status (ThumbnailStatus): Preview generation status.
        thumbnail_path (str | None): Relative media path when ready.
        thumbnail_updated_at (datetime | None): Last thumbnail update time.
        created_at (datetime): Creation timestamp.
        updated_at (datetime): Last update timestamp.
        tags (list[Tag]): Attached tags.
    """

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: int
    title: str
    url: str
    description: str | None
    folder_id: int | None
    thumbnail_status: ThumbnailStatus
    thumbnail_path: str | None
    thumbnail_updated_at: datetime | None
    created_at: datetime
    updated_at: datetime
    tags: list[Tag] = Field(default_factory=list)


class BookmarkThumbnailUpdate(BaseModel):
    """Internal payload for updating thumbnail fields.

    Attributes:
        thumbnail_status (ThumbnailStatus): New status.
        thumbnail_path (str | None): Relative media path.
        thumbnail_updated_at (datetime | None): Update timestamp.
    """

    model_config = ConfigDict(extra="forbid")

    thumbnail_status: ThumbnailStatus
    thumbnail_path: str | None = None
    thumbnail_updated_at: datetime | None = None
