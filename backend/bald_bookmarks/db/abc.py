"""Abstract database driver interface."""

from abc import ABC, abstractmethod

from bald_bookmarks.domain.admin import DatabaseHealth
from bald_bookmarks.domain.bookmarks import (
    Bookmark,
    BookmarkCreate,
    BookmarkThumbnailUpdate,
    BookmarkUpdate,
)
from bald_bookmarks.domain.folders import (
    Folder,
    FolderCreate,
    FolderTreeNode,
    FolderUpdate,
)
from bald_bookmarks.domain.jobs import Job, JobEnqueue
from bald_bookmarks.domain.tags import Tag, TagCreate


class DatabaseDriver(ABC):
    """Abstract persistence interface for Bald Bookmarks.

    Concrete drivers implement Oracle (or future engines) while routers and
    job handlers depend only on this ABC and Pydantic models.
    """

    @abstractmethod
    def connect(self) -> None:
        """Open connections or pools required by the driver."""

    @abstractmethod
    def close(self) -> None:
        """Close connections or pools owned by the driver."""

    @abstractmethod
    def health_check(self) -> DatabaseHealth:
        """Probe database connectivity.

        Returns:
            DatabaseHealth: Probe result including latency when measured.
        """

    @abstractmethod
    def alembic_revision(self) -> str | None:
        """Return the deployed Alembic revision when the driver stores one.

        Returns:
            str | None: version_num from alembic_version, or None.
        """

    def __enter__(self) -> "DatabaseDriver":
        """Connect and return the driver for context-manager use.

        Returns:
            DatabaseDriver: Connected driver instance.
        """
        self.connect()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        """Close the driver when leaving a context manager.

        Args:
            exc_type (object): Exception type if raised.
            exc (object): Exception instance if raised.
            tb (object): Traceback if raised.
        """
        self.close()

    # --- Folders ---

    @abstractmethod
    def create_folder(self, payload: FolderCreate) -> Folder:
        """Create a folder.

        Args:
            payload (FolderCreate): Folder creation payload.

        Returns:
            Folder: Created folder.
        """

    @abstractmethod
    def get_folder(self, folder_id: int) -> Folder:
        """Fetch a folder by id.

        Args:
            folder_id (int): Folder primary key.

        Returns:
            Folder: Matching folder.

        Raises:
            NotFoundError: If the folder does not exist.
        """

    @abstractmethod
    def list_folder_children(self, parent_id: int | None) -> list[Folder]:
        """List direct children of a folder (or root when parent_id is None).

        Args:
            parent_id (int | None): Parent folder id, or None for roots.

        Returns:
            list[Folder]: Child folders sorted by sort_order then name.
        """

    @abstractmethod
    def get_folder_tree(self) -> list[FolderTreeNode]:
        """Build the full nested folder tree.

        Returns:
            list[FolderTreeNode]: Root nodes with nested children.
        """

    @abstractmethod
    def update_folder(self, folder_id: int, payload: FolderUpdate) -> Folder:
        """Update folder fields.

        Args:
            folder_id (int): Folder primary key.
            payload (FolderUpdate): Fields to update.

        Returns:
            Folder: Updated folder.

        Raises:
            NotFoundError: If the folder does not exist.
            ValidationError: If a move would create a cycle.
        """

    @abstractmethod
    def delete_folder(self, folder_id: int, *, recursive: bool = False) -> None:
        """Delete a folder.

        Args:
            folder_id (int): Folder primary key.
            recursive (bool): When True, delete descendants and bookmarks.

        Raises:
            NotFoundError: If the folder does not exist.
            ConflictError: If non-recursive delete finds children or bookmarks.
        """

    # --- Bookmarks ---

    @abstractmethod
    def create_bookmark(self, payload: BookmarkCreate) -> Bookmark:
        """Create a bookmark and attach tags.

        Args:
            payload (BookmarkCreate): Bookmark creation payload.

        Returns:
            Bookmark: Created bookmark with tags.
        """

    @abstractmethod
    def get_bookmark(self, bookmark_id: int) -> Bookmark:
        """Fetch a bookmark by id.

        Args:
            bookmark_id (int): Bookmark primary key.

        Returns:
            Bookmark: Matching bookmark with tags.

        Raises:
            NotFoundError: If the bookmark does not exist.
        """

    @abstractmethod
    def list_bookmarks(
        self,
        *,
        folder_id: int | None = None,
        q: str | None = None,
        tag: str | None = None,
        unfiled_only: bool = False,
    ) -> list[Bookmark]:
        """List bookmarks with optional filters.

        Args:
            folder_id (int | None): Restrict to this folder when set.
            q (str | None): Case-insensitive title/url/description filter.
            tag (str | None): Restrict to bookmarks with this tag name.
            unfiled_only (bool): When True, only bookmarks with no folder.

        Returns:
            list[Bookmark]: Matching bookmarks.
        """

    @abstractmethod
    def update_bookmark(self, bookmark_id: int, payload: BookmarkUpdate) -> Bookmark:
        """Update bookmark fields and optional tag set.

        Args:
            bookmark_id (int): Bookmark primary key.
            payload (BookmarkUpdate): Fields to update.

        Returns:
            Bookmark: Updated bookmark.

        Raises:
            NotFoundError: If the bookmark does not exist.
        """

    @abstractmethod
    def delete_bookmark(self, bookmark_id: int) -> None:
        """Delete a bookmark and its tag links.

        Args:
            bookmark_id (int): Bookmark primary key.

        Raises:
            NotFoundError: If the bookmark does not exist.
        """

    @abstractmethod
    def update_bookmark_thumbnail(
        self,
        bookmark_id: int,
        payload: BookmarkThumbnailUpdate,
    ) -> Bookmark:
        """Update thumbnail status and path for a bookmark.

        Args:
            bookmark_id (int): Bookmark primary key.
            payload (BookmarkThumbnailUpdate): Thumbnail fields.

        Returns:
            Bookmark: Updated bookmark.

        Raises:
            NotFoundError: If the bookmark does not exist.
        """

    # --- Tags ---

    @abstractmethod
    def list_tags(self) -> list[Tag]:
        """List all tags.

        Returns:
            list[Tag]: Tags sorted by name.
        """

    @abstractmethod
    def create_tag(self, payload: TagCreate) -> Tag:
        """Create a tag.

        Args:
            payload (TagCreate): Tag creation payload.

        Returns:
            Tag: Created tag.

        Raises:
            ConflictError: If the tag name already exists.
        """

    @abstractmethod
    def delete_tag(self, tag_id: int) -> None:
        """Delete a tag and detach it from bookmarks.

        Args:
            tag_id (int): Tag primary key.

        Raises:
            NotFoundError: If the tag does not exist.
        """

    # --- Jobs ---

    @abstractmethod
    def enqueue_job(self, payload: JobEnqueue) -> Job:
        """Enqueue a background job.

        Args:
            payload (JobEnqueue): Job enqueue payload.

        Returns:
            Job: Created pending job.
        """

    @abstractmethod
    def claim_next_job(self) -> Job | None:
        """Atomically claim the next eligible pending job.

        Returns:
            Job | None: Claimed running job, or None if none eligible.
        """

    @abstractmethod
    def mark_job_succeeded(self, job_id: int) -> Job:
        """Mark a job as succeeded.

        Args:
            job_id (int): Job primary key.

        Returns:
            Job: Updated job.

        Raises:
            NotFoundError: If the job does not exist.
        """

    @abstractmethod
    def mark_job_failed(
        self,
        job_id: int,
        error: str,
        *,
        retry: bool,
        scheduled_at: object | None = None,
    ) -> Job:
        """Mark a job failed or re-queue it for retry.

        Args:
            job_id (int): Job primary key.
            error (str): Failure message.
            retry (bool): When True, set status pending with future schedule.
            scheduled_at (object | None): Retry eligibility timestamp.

        Returns:
            Job: Updated job.

        Raises:
            NotFoundError: If the job does not exist.
        """

    @abstractmethod
    def list_jobs(self, *, limit: int = 100) -> list[Job]:
        """List recent jobs newest first.

        Args:
            limit (int): Maximum rows to return.

        Returns:
            list[Job]: Job rows.
        """

    @abstractmethod
    def get_job(self, job_id: int) -> Job:
        """Fetch a job by id.

        Args:
            job_id (int): Job primary key.

        Returns:
            Job: Matching job.

        Raises:
            NotFoundError: If the job does not exist.
        """
