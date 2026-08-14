"""Folder domain and API models."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class FolderCreate(BaseModel):
    """Payload for creating a folder.

    Attributes:
        name (str): Folder display name.
        parent_id (int | None): Parent folder id, or None for root.
        sort_order (int): Relative sort position among siblings.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    parent_id: int | None = None
    sort_order: int = 0


class FolderUpdate(BaseModel):
    """Payload for updating a folder.

    Attributes:
        name (str | None): New display name.
        parent_id (int | None): New parent folder id.
        sort_order (int | None): New sort position.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    parent_id: int | None = None
    sort_order: int | None = None


class Folder(BaseModel):
    """Persisted folder entity.

    Attributes:
        id (int): Primary key.
        name (str): Folder display name.
        parent_id (int | None): Parent folder id, or None for root.
        sort_order (int): Relative sort position among siblings.
        created_at (datetime): Creation timestamp.
        updated_at (datetime): Last update timestamp.
        bookmark_count (int): Bookmarks filed directly in this folder.
    """

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: int
    name: str
    parent_id: int | None
    sort_order: int
    created_at: datetime
    updated_at: datetime
    bookmark_count: int = 0


class FolderTreeNode(BaseModel):
    """Folder node with nested children for tree responses.

    Attributes:
        id (int): Primary key.
        name (str): Folder display name.
        parent_id (int | None): Parent folder id, or None for root.
        sort_order (int): Relative sort position among siblings.
        created_at (datetime): Creation timestamp.
        updated_at (datetime): Last update timestamp.
        bookmark_count (int): Bookmarks filed directly in this folder.
        children (list[FolderTreeNode]): Nested child folders.
    """

    model_config = ConfigDict(extra="forbid")

    id: int
    name: str
    parent_id: int | None
    sort_order: int
    created_at: datetime
    updated_at: datetime
    bookmark_count: int = 0
    children: list["FolderTreeNode"] = Field(default_factory=list)
