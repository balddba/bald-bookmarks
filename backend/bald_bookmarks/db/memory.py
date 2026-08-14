"""In-memory DatabaseDriver for tests and local development without Oracle."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import Lock

from bald_bookmarks.db.abc import DatabaseDriver
from bald_bookmarks.db.exceptions import ConflictError, NotFoundError, ValidationError
from bald_bookmarks.domain.admin import DatabaseHealth
from bald_bookmarks.domain.bookmarks import (
    Bookmark,
    BookmarkCreate,
    BookmarkThumbnailUpdate,
    BookmarkUpdate,
    ThumbnailStatus,
)
from bald_bookmarks.domain.folders import (
    Folder,
    FolderCreate,
    FolderTreeNode,
    FolderUpdate,
)
from bald_bookmarks.domain.jobs import Job, JobEnqueue, JobStatus
from bald_bookmarks.domain.tags import Tag, TagCreate, normalize_tag_name


def _utcnow() -> datetime:
    """Return the current UTC timestamp.

    Returns:
        datetime: Aware UTC datetime.
    """
    return datetime.now(UTC)


class MemoryDriver(DatabaseDriver):
    """Thread-safe in-memory driver implementing DatabaseDriver."""

    def __init__(self, *, default_max_attempts: int = 3) -> None:
        """Initialize empty stores.

        Args:
            default_max_attempts (int): Default job retry limit.
        """
        self._default_max_attempts = default_max_attempts
        self._lock = Lock()
        self._folders: dict[int, Folder] = {}
        self._bookmarks: dict[int, Bookmark] = {}
        self._tags: dict[int, Tag] = {}
        self._jobs: dict[int, Job] = {}
        self._next_ids = {
            "folder": 1,
            "bookmark": 1,
            "tag": 1,
            "job": 1,
        }
        self._connected = False

    def connect(self) -> None:
        """Mark the driver as connected."""
        self._connected = True

    def close(self) -> None:
        """Mark the driver as closed."""
        self._connected = False

    def health_check(self) -> DatabaseHealth:
        """Report whether the in-memory driver is connected.

        Returns:
            DatabaseHealth: Probe result for the memory driver.
        """
        if self._connected:
            return DatabaseHealth(
                ok=True,
                driver="memory",
                latency_ms=0.0,
                message="In-memory driver is connected",
            )
        return DatabaseHealth(
            ok=False,
            driver="memory",
            latency_ms=None,
            message="In-memory driver is not connected",
        )

    def alembic_revision(self) -> str | None:
        """Return None because the memory driver does not persist Alembic state.

        Returns:
            None: Always None.
        """
        return None

    def _require_connected(self) -> None:
        """Raise if the driver is not connected.

        Raises:
            RuntimeError: If connect was not called.
        """
        if not self._connected:
            raise RuntimeError("MemoryDriver is not connected")

    def _next_id(self, kind: str) -> int:
        """Allocate the next synthetic primary key.

        Args:
            kind (str): Entity kind key in _next_ids.

        Returns:
            int: Next id value.
        """
        value = self._next_ids[kind]
        self._next_ids[kind] = value + 1
        return value

    def _get_or_create_tag(self, name: str) -> Tag:
        """Return an existing tag or create one for the normalized name.

        Args:
            name (str): Raw or normalized tag name.

        Returns:
            Tag: Matching tag.
        """
        normalized = normalize_tag_name(name)
        for tag in self._tags.values():
            if tag.name == normalized:
                return tag
        now = _utcnow()
        tag = Tag(id=self._next_id("tag"), name=normalized, created_at=now)
        self._tags[tag.id] = tag
        return tag

    def _folder_descendants(self, folder_id: int) -> set[int]:
        """Collect descendant folder ids.

        Args:
            folder_id (int): Ancestor folder id.

        Returns:
            set[int]: Descendant ids (excluding folder_id).
        """
        children = {
            child.id for child in self._folders.values() if child.parent_id == folder_id
        }
        result = set(children)
        for child_id in children:
            result |= self._folder_descendants(child_id)
        return result

    def create_folder(self, payload: FolderCreate) -> Folder:
        """Create a folder.

        Args:
            payload (FolderCreate): Folder creation payload.

        Returns:
            Folder: Created folder.

        Raises:
            NotFoundError: If parent_id does not exist.
        """
        self._require_connected()
        with self._lock:
            if payload.parent_id is not None and payload.parent_id not in self._folders:
                raise NotFoundError(f"Folder {payload.parent_id} not found")
            now = _utcnow()
            folder = Folder(
                id=self._next_id("folder"),
                name=payload.name,
                parent_id=payload.parent_id,
                sort_order=payload.sort_order,
                created_at=now,
                updated_at=now,
            )
            self._folders[folder.id] = folder
            return folder

    def get_folder(self, folder_id: int) -> Folder:
        """Fetch a folder by id.

        Args:
            folder_id (int): Folder primary key.

        Returns:
            Folder: Matching folder.

        Raises:
            NotFoundError: If the folder does not exist.
        """
        self._require_connected()
        with self._lock:
            folder = self._folders.get(folder_id)
            if folder is None:
                raise NotFoundError(f"Folder {folder_id} not found")
            return folder.model_copy(
                update={"bookmark_count": self._direct_bookmark_count(folder_id)}
            )

    def _direct_bookmark_count(self, folder_id: int) -> int:
        """Count bookmarks filed directly in a folder.

        Args:
            folder_id (int): Folder primary key.

        Returns:
            int: Number of bookmarks with this folder_id.
        """
        return sum(
            1
            for bookmark in self._bookmarks.values()
            if bookmark.folder_id == folder_id
        )

    def list_folder_children(self, parent_id: int | None) -> list[Folder]:
        """List direct children of a folder.

        Args:
            parent_id (int | None): Parent folder id, or None for roots.

        Returns:
            list[Folder]: Child folders.
        """
        self._require_connected()
        with self._lock:
            children = [
                folder
                for folder in self._folders.values()
                if folder.parent_id == parent_id
            ]
            return sorted(
                (
                    folder.model_copy(
                        update={
                            "bookmark_count": self._direct_bookmark_count(folder.id)
                        }
                    )
                    for folder in children
                ),
                key=lambda item: (item.sort_order, item.name.lower()),
            )

    def get_folder_tree(self) -> list[FolderTreeNode]:
        """Build the full nested folder tree.

        Returns:
            list[FolderTreeNode]: Root nodes with nested children.
        """
        self._require_connected()
        with self._lock:
            by_parent: dict[int | None, list[Folder]] = {}
            for folder in self._folders.values():
                by_parent.setdefault(folder.parent_id, []).append(folder)

            def build(parent_id: int | None) -> list[FolderTreeNode]:
                nodes: list[FolderTreeNode] = []
                children = sorted(
                    by_parent.get(parent_id, []),
                    key=lambda item: (item.sort_order, item.name.lower()),
                )
                for child in children:
                    nodes.append(
                        FolderTreeNode(
                            id=child.id,
                            name=child.name,
                            parent_id=child.parent_id,
                            sort_order=child.sort_order,
                            created_at=child.created_at,
                            updated_at=child.updated_at,
                            bookmark_count=self._direct_bookmark_count(child.id),
                            children=build(child.id),
                        )
                    )
                return nodes

            return build(None)

    def update_folder(self, folder_id: int, payload: FolderUpdate) -> Folder:
        """Update folder fields.

        Args:
            folder_id (int): Folder primary key.
            payload (FolderUpdate): Fields to update.

        Returns:
            Folder: Updated folder.

        Raises:
            NotFoundError: If the folder or new parent does not exist.
            ValidationError: If a move would create a cycle.
        """
        self._require_connected()
        with self._lock:
            folder = self._folders.get(folder_id)
            if folder is None:
                raise NotFoundError(f"Folder {folder_id} not found")
            data = folder.model_dump()
            updates = payload.model_dump(exclude_unset=True)
            if "parent_id" in updates:
                new_parent = updates["parent_id"]
                if new_parent is not None:
                    if new_parent not in self._folders:
                        raise NotFoundError(f"Folder {new_parent} not found")
                    if (
                        new_parent == folder_id
                        or new_parent in self._folder_descendants(folder_id)
                    ):
                        raise ValidationError("Cannot move a folder under itself")
            data.update(updates)
            data["updated_at"] = _utcnow()
            updated = Folder.model_validate(data)
            self._folders[folder_id] = updated
            return updated

    def delete_folder(self, folder_id: int, *, recursive: bool = False) -> None:
        """Delete a folder.

        Args:
            folder_id (int): Folder primary key.
            recursive (bool): When True, delete descendants and bookmarks.

        Raises:
            NotFoundError: If the folder does not exist.
            ConflictError: If non-recursive delete finds children or bookmarks.
        """
        self._require_connected()
        with self._lock:
            if folder_id not in self._folders:
                raise NotFoundError(f"Folder {folder_id} not found")
            children = [
                folder
                for folder in self._folders.values()
                if folder.parent_id == folder_id
            ]
            bookmarks = [
                bookmark
                for bookmark in self._bookmarks.values()
                if bookmark.folder_id == folder_id
            ]
            if not recursive and (children or bookmarks):
                raise ConflictError(
                    "Folder is not empty; pass recursive=true to delete contents"
                )
            targets = {folder_id} | self._folder_descendants(folder_id)
            bookmark_ids = [
                bookmark.id
                for bookmark in self._bookmarks.values()
                if bookmark.folder_id in targets
            ]
            for bookmark_id in bookmark_ids:
                del self._bookmarks[bookmark_id]
            for target_id in targets:
                del self._folders[target_id]

    def create_bookmark(self, payload: BookmarkCreate) -> Bookmark:
        """Create a bookmark and attach tags.

        Args:
            payload (BookmarkCreate): Bookmark creation payload.

        Returns:
            Bookmark: Created bookmark with tags.

        Raises:
            NotFoundError: If folder_id does not exist.
        """
        self._require_connected()
        with self._lock:
            if payload.folder_id is not None and payload.folder_id not in self._folders:
                raise NotFoundError(f"Folder {payload.folder_id} not found")
            now = _utcnow()
            tags = [self._get_or_create_tag(name) for name in payload.tag_names]
            bookmark = Bookmark(
                id=self._next_id("bookmark"),
                title=payload.title,
                url=payload.url,
                description=payload.description,
                folder_id=payload.folder_id,
                thumbnail_status=ThumbnailStatus.PENDING,
                thumbnail_path=None,
                thumbnail_updated_at=None,
                created_at=now,
                updated_at=now,
                tags=tags,
            )
            self._bookmarks[bookmark.id] = bookmark
            return bookmark

    def get_bookmark(self, bookmark_id: int) -> Bookmark:
        """Fetch a bookmark by id.

        Args:
            bookmark_id (int): Bookmark primary key.

        Returns:
            Bookmark: Matching bookmark.

        Raises:
            NotFoundError: If the bookmark does not exist.
        """
        self._require_connected()
        with self._lock:
            bookmark = self._bookmarks.get(bookmark_id)
            if bookmark is None:
                raise NotFoundError(f"Bookmark {bookmark_id} not found")
            return bookmark

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
        self._require_connected()
        with self._lock:
            results = list(self._bookmarks.values())
            if unfiled_only:
                results = [item for item in results if item.folder_id is None]
            elif folder_id is not None:
                results = [item for item in results if item.folder_id == folder_id]
            if q:
                needle = q.lower()
                results = [
                    item
                    for item in results
                    if needle in item.title.lower()
                    or needle in item.url.lower()
                    or (item.description and needle in item.description.lower())
                ]
            if tag:
                normalized = normalize_tag_name(tag)
                results = [
                    item
                    for item in results
                    if any(existing.name == normalized for existing in item.tags)
                ]
            return sorted(results, key=lambda item: item.created_at, reverse=True)

    def update_bookmark(self, bookmark_id: int, payload: BookmarkUpdate) -> Bookmark:
        """Update bookmark fields and optional tag set.

        Args:
            bookmark_id (int): Bookmark primary key.
            payload (BookmarkUpdate): Fields to update.

        Returns:
            Bookmark: Updated bookmark.

        Raises:
            NotFoundError: If the bookmark or folder does not exist.
        """
        self._require_connected()
        with self._lock:
            bookmark = self._bookmarks.get(bookmark_id)
            if bookmark is None:
                raise NotFoundError(f"Bookmark {bookmark_id} not found")
            data = bookmark.model_dump()
            updates = payload.model_dump(exclude_unset=True)
            tag_names = updates.pop("tag_names", None)
            if "folder_id" in updates and updates["folder_id"] is not None:
                if updates["folder_id"] not in self._folders:
                    raise NotFoundError(f"Folder {updates['folder_id']} not found")
            data.update(updates)
            if tag_names is not None:
                data["tags"] = [
                    self._get_or_create_tag(name).model_dump() for name in tag_names
                ]
            data["updated_at"] = _utcnow()
            updated = Bookmark.model_validate(data)
            self._bookmarks[bookmark_id] = updated
            return updated

    def delete_bookmark(self, bookmark_id: int) -> None:
        """Delete a bookmark.

        Args:
            bookmark_id (int): Bookmark primary key.

        Raises:
            NotFoundError: If the bookmark does not exist.
        """
        self._require_connected()
        with self._lock:
            if bookmark_id not in self._bookmarks:
                raise NotFoundError(f"Bookmark {bookmark_id} not found")
            del self._bookmarks[bookmark_id]

    def update_bookmark_thumbnail(
        self,
        bookmark_id: int,
        payload: BookmarkThumbnailUpdate,
    ) -> Bookmark:
        """Update thumbnail fields for a bookmark.

        Args:
            bookmark_id (int): Bookmark primary key.
            payload (BookmarkThumbnailUpdate): Thumbnail fields.

        Returns:
            Bookmark: Updated bookmark.

        Raises:
            NotFoundError: If the bookmark does not exist.
        """
        self._require_connected()
        with self._lock:
            bookmark = self._bookmarks.get(bookmark_id)
            if bookmark is None:
                raise NotFoundError(f"Bookmark {bookmark_id} not found")
            data = bookmark.model_dump()
            data.update(payload.model_dump())
            data["updated_at"] = _utcnow()
            updated = Bookmark.model_validate(data)
            self._bookmarks[bookmark_id] = updated
            return updated

    def list_tags(self) -> list[Tag]:
        """List all tags.

        Returns:
            list[Tag]: Tags sorted by name.
        """
        self._require_connected()
        with self._lock:
            return sorted(self._tags.values(), key=lambda item: item.name)

    def create_tag(self, payload: TagCreate) -> Tag:
        """Create a tag.

        Args:
            payload (TagCreate): Tag creation payload.

        Returns:
            Tag: Created tag.

        Raises:
            ConflictError: If the tag name already exists.
        """
        self._require_connected()
        with self._lock:
            for tag in self._tags.values():
                if tag.name == payload.name:
                    raise ConflictError(f"Tag '{payload.name}' already exists")
            tag = Tag(id=self._next_id("tag"), name=payload.name, created_at=_utcnow())
            self._tags[tag.id] = tag
            return tag

    def delete_tag(self, tag_id: int) -> None:
        """Delete a tag and detach it from bookmarks.

        Args:
            tag_id (int): Tag primary key.

        Raises:
            NotFoundError: If the tag does not exist.
        """
        self._require_connected()
        with self._lock:
            if tag_id not in self._tags:
                raise NotFoundError(f"Tag {tag_id} not found")
            del self._tags[tag_id]
            for bookmark_id, bookmark in list(self._bookmarks.items()):
                remaining = [tag for tag in bookmark.tags if tag.id != tag_id]
                if len(remaining) != len(bookmark.tags):
                    data = bookmark.model_dump()
                    data["tags"] = [tag.model_dump() for tag in remaining]
                    data["updated_at"] = _utcnow()
                    self._bookmarks[bookmark_id] = Bookmark.model_validate(data)

    def enqueue_job(self, payload: JobEnqueue) -> Job:
        """Enqueue a background job.

        Args:
            payload (JobEnqueue): Job enqueue payload.

        Returns:
            Job: Created pending job.
        """
        self._require_connected()
        with self._lock:
            now = _utcnow()
            job = Job(
                id=self._next_id("job"),
                job_type=payload.job_type,
                payload_json=payload.payload_json,
                status=JobStatus.PENDING,
                attempts=0,
                max_attempts=payload.max_attempts or self._default_max_attempts,
                scheduled_at=payload.scheduled_at or now,
                started_at=None,
                finished_at=None,
                last_error=None,
                created_at=now,
                updated_at=now,
            )
            self._jobs[job.id] = job
            return job

    def claim_next_job(self) -> Job | None:
        """Atomically claim the next eligible pending job.

        Returns:
            Job | None: Claimed running job, or None if none eligible.
        """
        self._require_connected()
        with self._lock:
            now = _utcnow()
            eligible = [
                job
                for job in self._jobs.values()
                if job.status == JobStatus.PENDING and job.scheduled_at <= now
            ]
            if not eligible:
                return None
            job = sorted(eligible, key=lambda item: (item.scheduled_at, item.id))[0]
            updated = job.model_copy(
                update={
                    "status": JobStatus.RUNNING,
                    "attempts": job.attempts + 1,
                    "started_at": now,
                    "updated_at": now,
                }
            )
            self._jobs[job.id] = updated
            return updated

    def mark_job_succeeded(self, job_id: int) -> Job:
        """Mark a job as succeeded.

        Args:
            job_id (int): Job primary key.

        Returns:
            Job: Updated job.

        Raises:
            NotFoundError: If the job does not exist.
        """
        self._require_connected()
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise NotFoundError(f"Job {job_id} not found")
            now = _utcnow()
            updated = job.model_copy(
                update={
                    "status": JobStatus.SUCCEEDED,
                    "finished_at": now,
                    "updated_at": now,
                    "last_error": None,
                }
            )
            self._jobs[job_id] = updated
            return updated

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
        self._require_connected()
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise NotFoundError(f"Job {job_id} not found")
            now = _utcnow()
            if retry:
                retry_at = (
                    scheduled_at
                    if isinstance(scheduled_at, datetime)
                    else now + timedelta(seconds=2**job.attempts)
                )
                updated = job.model_copy(
                    update={
                        "status": JobStatus.PENDING,
                        "scheduled_at": retry_at,
                        "finished_at": None,
                        "last_error": error,
                        "updated_at": now,
                    }
                )
            else:
                updated = job.model_copy(
                    update={
                        "status": JobStatus.FAILED,
                        "finished_at": now,
                        "last_error": error,
                        "updated_at": now,
                    }
                )
            self._jobs[job_id] = updated
            return updated

    def list_jobs(self, *, limit: int = 100) -> list[Job]:
        """List recent jobs newest first.

        Args:
            limit (int): Maximum rows to return.

        Returns:
            list[Job]: Job rows.
        """
        self._require_connected()
        with self._lock:
            jobs = sorted(
                self._jobs.values(),
                key=lambda item: item.created_at,
                reverse=True,
            )
            return jobs[:limit]

    def get_job(self, job_id: int) -> Job:
        """Fetch a job by id.

        Args:
            job_id (int): Job primary key.

        Returns:
            Job: Matching job.

        Raises:
            NotFoundError: If the job does not exist.
        """
        self._require_connected()
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise NotFoundError(f"Job {job_id} not found")
            return job
