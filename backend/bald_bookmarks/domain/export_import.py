"""Domain models for bookmark backup export and import."""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ExportFormat(StrEnum):
    """Supported export and import serialization formats."""

    JSON = "json"
    HTML = "html"


class ExportBookmark(BaseModel):
    """Bookmark entity shape for export and import payloads.

    Attributes:
        title (str): Bookmark display title.
        url (str): Bookmark web destination URL.
        description (str | None): Optional bookmark notes or description.
        created_at (datetime | None): Optional creation timestamp.
        tags (list[str]): Attached tag names.
    """

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=512)
    url: str = Field(min_length=1, max_length=2048)
    description: str | None = Field(default=None, max_length=256)
    created_at: datetime | None = None
    tags: list[str] = Field(default_factory=list)


class ExportFolder(BaseModel):
    """Folder node hierarchy shape for export and import payloads.

    Attributes:
        name (str): Folder display name.
        sort_order (int): Sibling sort position.
        folders (list[ExportFolder]): Nested child folders.
        bookmarks (list[ExportBookmark]): Bookmarks filed inside this folder.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    sort_order: int = 0
    folders: list["ExportFolder"] = Field(default_factory=list)
    bookmarks: list[ExportBookmark] = Field(default_factory=list)


class ExportBackup(BaseModel):
    """Top-level container for a complete bookmark library backup.

    Attributes:
        version (int): Backup schema version.
        exported_at (datetime): Timestamp when the backup was generated.
        folders (list[ExportFolder]): Root folders with nested hierarchies.
        bookmarks (list[ExportBookmark]): Unfiled bookmarks at the library root.
    """

    model_config = ConfigDict(extra="forbid")

    version: int = 1
    exported_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=UTC),
    )
    folders: list[ExportFolder] = Field(default_factory=list)
    bookmarks: list[ExportBookmark] = Field(default_factory=list)


class ImportRequest(BaseModel):
    """Optional JSON payload envelope for bookmark import requests.

    Attributes:
        content (str | None): Raw JSON or Netscape HTML content string.
        backup (ExportBackup | None): Structured backup payload.
        target_folder_id (int | None): Destination folder id, or None for root.
        skip_existing (bool): Whether to skip bookmarks with matching URLs.
        enqueue_thumbnails (bool): Whether to queue background thumbnail jobs.
    """

    model_config = ConfigDict(extra="forbid")

    content: str | None = None
    backup: ExportBackup | None = None
    target_folder_id: int | None = None
    skip_existing: bool = True
    enqueue_thumbnails: bool = True


class ImportResult(BaseModel):
    """Summary statistics describing an executed import operation.

    Attributes:
        folders_created (int): Number of folders created.
        bookmarks_created (int): Number of bookmarks created.
        bookmarks_skipped (int): Number of skipped duplicate bookmarks.
        tags_created (int): Number of distinct tags attached.
        errors (list[str]): Warning and error messages encountered.
    """

    model_config = ConfigDict(extra="forbid")

    folders_created: int = 0
    bookmarks_created: int = 0
    bookmarks_skipped: int = 0
    tags_created: int = 0
    errors: list[str] = Field(default_factory=list)
