"""SQLite DatabaseDriver implementation using the stdlib sqlite3 module."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from threading import RLock
from time import perf_counter
from typing import Any

from loguru import logger

from bald_bookmarks.config import Settings
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

_DESCENDANTS_SQL = """
WITH RECURSIVE descendants AS (
    SELECT id FROM folders WHERE parent_id = :id
    UNION ALL
    SELECT f.id
    FROM folders f
    INNER JOIN descendants d ON f.parent_id = d.id
)
SELECT id FROM descendants
"""

_FOLDER_DELETE_ORDER_SQL = """
WITH RECURSIVE tree AS (
    SELECT id, 0 AS lvl FROM folders WHERE id = :id
    UNION ALL
    SELECT f.id, tree.lvl + 1
    FROM folders f
    INNER JOIN tree ON f.parent_id = tree.id
)
SELECT id FROM tree ORDER BY lvl DESC
"""

_CLAIM_NEXT_JOB_SQL = """
UPDATE jobs
SET status = :running,
    attempts = attempts + 1,
    started_at = :started_at,
    updated_at = :updated_at
WHERE id = (
    SELECT id
    FROM jobs
    WHERE status = :pending
      AND scheduled_at <= :now
    ORDER BY scheduled_at, id
    LIMIT 1
)
RETURNING id
"""


def _utcnow() -> datetime:
    """Return the current UTC timestamp.

    Returns:
        datetime: Aware UTC datetime.
    """
    return datetime.now(UTC)


def _adapt_datetime(value: datetime) -> str:
    """Serialize a datetime for SQLite storage.

    Args:
        value (datetime): Timestamp to store.

    Returns:
        str: ISO-8601 timestamp.
    """
    if value.tzinfo is None:
        return value.isoformat()
    return value.astimezone(UTC).isoformat()


def _parse_datetime(value: object) -> datetime:
    """Parse a SQLite timestamp into an aware UTC datetime.

    Args:
        value (object): Datetime instance or ISO-8601 string.

    Returns:
        datetime: Aware UTC datetime.

    Raises:
        TypeError: If value is not a datetime or string.
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    raise TypeError(f"Unsupported timestamp value: {type(value)!r}")


def _parse_datetime_opt(value: object) -> datetime | None:
    """Parse an optional SQLite timestamp.

    Args:
        value (object): Datetime, ISO-8601 string, or None.

    Returns:
        datetime | None: Aware UTC datetime, or None.
    """
    if value is None:
        return None
    return _parse_datetime(value)


def _convert_timestamp(raw: bytes) -> datetime:
    """Convert a SQLite DATETIME/TIMESTAMP column to datetime.

    Args:
        raw (bytes): Stored timestamp bytes.

    Returns:
        datetime: Aware UTC datetime.
    """
    return _parse_datetime(raw.decode())


sqlite3.register_adapter(datetime, _adapt_datetime)
sqlite3.register_converter("DATETIME", _convert_timestamp)
sqlite3.register_converter("TIMESTAMP", _convert_timestamp)


@contextmanager
def _cursor(conn: sqlite3.Connection) -> Iterator[sqlite3.Cursor]:
    """Open a cursor and close it when the block ends.

    Args:
        conn (sqlite3.Connection): Active connection.

    Yields:
        sqlite3.Cursor: Open cursor.
    """
    cursor = conn.cursor()
    try:
        yield cursor
    finally:
        cursor.close()


class SQLiteDriver(DatabaseDriver):
    """Persist Bald Bookmarks data with a stdlib sqlite3 connection."""

    def __init__(self, settings: Settings) -> None:
        """Store settings for connection creation.

        Args:
            settings (Settings): Application settings with the SQLite path.
        """
        self._settings = settings
        self._conn: sqlite3.Connection | None = None
        self._lock = RLock()

    def connect(self) -> None:
        """Open the SQLite database connection.

        Raises:
            ValueError: If the SQLite path is missing.
        """
        if self._conn is not None:
            return
        db_path = self._settings.sqlite_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            db_path,
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        logger.info("SQLite connection opened path={}", db_path)

    def close(self) -> None:
        """Close the SQLite connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
            logger.info("SQLite connection closed")

    def health_check(self) -> DatabaseHealth:
        """Run SELECT 1 against a pooled connection.

        Returns:
            DatabaseHealth: Probe result including latency when measured.
        """
        started = perf_counter()
        if self._conn is None:
            return DatabaseHealth(
                ok=False,
                driver="sqlite",
                latency_ms=None,
                message="SQLite connection is not open",
            )
        try:
            with self._acquire() as conn, _cursor(conn) as cursor:
                try:
                    cursor.execute("SELECT 1")
                    cursor.fetchone()
                except sqlite3.Error as exc:
                    latency_ms = round((perf_counter() - started) * 1000, 2)
                    logger.bind(path=str(self._settings.sqlite_path)).error(
                        "db_health_check_failed err={}", exc
                    )
                    return DatabaseHealth(
                        ok=False,
                        driver="sqlite",
                        latency_ms=latency_ms,
                        message=str(exc),
                    )
        except Exception as exc:  # noqa: BLE001
            latency_ms = round((perf_counter() - started) * 1000, 2)
            logger.bind(path=str(self._settings.sqlite_path)).error(
                "db_health_check_failed err={}", exc
            )
            return DatabaseHealth(
                ok=False,
                driver="sqlite",
                latency_ms=latency_ms,
                message=str(exc),
            )
        latency_ms = round((perf_counter() - started) * 1000, 2)
        return DatabaseHealth(
            ok=True,
            driver="sqlite",
            latency_ms=latency_ms,
            message="SELECT 1 succeeded",
        )

    def alembic_revision(self) -> str | None:
        """Read version_num from the Alembic version table.

        Returns:
            str | None: Deployed revision id, or None when the table is empty.

        Raises:
            sqlite3.Error: If alembic_version cannot be queried.
            RuntimeError: If the connection has not been opened.
        """
        with self._acquire() as conn, _cursor(conn) as cursor:
            try:
                cursor.execute("SELECT version_num FROM alembic_version")
                row = cursor.fetchone()
            except sqlite3.Error as exc:
                logger.bind(path=str(self._settings.sqlite_path)).error(
                    "alembic_revision_failed err={}", exc
                )
                raise
        if row is None:
            return None
        return str(row[0])

    @contextmanager
    def _acquire(self) -> Iterator[sqlite3.Connection]:
        """Yield the SQLite connection under the driver lock.

        Yields:
            sqlite3.Connection: Open connection.

        Raises:
            RuntimeError: If the connection has not been opened.
        """
        if self._conn is None:
            raise RuntimeError("SQLiteDriver is not connected")
        with self._lock:
            yield self._conn

    def _insert_id(
        self,
        cursor: sqlite3.Cursor,
        sql: str,
        params: dict[str, Any],
    ) -> int:
        """Insert a row and return the generated primary key.

        Args:
            cursor (sqlite3.Cursor): Active cursor.
            sql (str): INSERT statement without RETURNING.
            params (dict[str, Any]): Named bind values.

        Returns:
            int: Generated primary key.

        Raises:
            RuntimeError: If INSERT RETURNING yields no row.
        """
        returning_sql = f"{sql.rstrip().rstrip(';')} RETURNING id"
        cursor.execute(returning_sql, params)
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("INSERT did not return an id")
        return int(row[0])

    def _fetch_folder(self, conn: sqlite3.Connection, folder_id: int) -> Folder:
        """Load a folder row.

        Args:
            conn (sqlite3.Connection): Active connection.
            folder_id (int): Folder primary key.

        Returns:
            Folder: Matching folder.

        Raises:
            NotFoundError: If the folder does not exist.
        """
        with _cursor(conn) as cursor:
            cursor.execute(
                """
                SELECT f.id, f.parent_id, f.name, f.sort_order,
                       f.created_at, f.updated_at,
                       (SELECT COUNT(*)
                        FROM bookmarks b
                        WHERE b.folder_id = f.id) AS bookmark_count
                FROM folders f
                WHERE f.id = :id
                """,
                {"id": folder_id},
            )
            row = cursor.fetchone()
        if row is None:
            raise NotFoundError(f"Folder {folder_id} not found")
        return Folder(
            id=int(row[0]),
            parent_id=int(row[1]) if row[1] is not None else None,
            name=row[2],
            sort_order=int(row[3]),
            created_at=_parse_datetime(row[4]),
            updated_at=_parse_datetime(row[5]),
            bookmark_count=int(row[6]),
        )

    def _bookmark_counts(self, conn: sqlite3.Connection) -> dict[int, int]:
        """Load bookmark counts grouped by folder id.

        Args:
            conn (sqlite3.Connection): Active connection.

        Returns:
            dict[int, int]: Bookmark count keyed by folder id.
        """
        with _cursor(conn) as cursor:
            cursor.execute(
                """
                SELECT folder_id, COUNT(*)
                FROM bookmarks
                WHERE folder_id IS NOT NULL
                GROUP BY folder_id
                """
            )
            rows = cursor.fetchall()
        return {int(row[0]): int(row[1]) for row in rows}

    def _folder_descendants(
        self,
        conn: sqlite3.Connection,
        folder_id: int,
    ) -> set[int]:
        """Collect descendant folder ids via a recursive CTE.

        Args:
            conn (sqlite3.Connection): Active connection.
            folder_id (int): Ancestor folder id.

        Returns:
            set[int]: Descendant ids excluding folder_id.
        """
        with _cursor(conn) as cursor:
            cursor.execute(_DESCENDANTS_SQL, {"id": folder_id})
            rows = cursor.fetchall()
        return {int(row[0]) for row in rows}

    def _bookmark_tags(self, conn: sqlite3.Connection, bookmark_id: int) -> list[Tag]:
        """Load tags for a bookmark.

        Args:
            conn (sqlite3.Connection): Active connection.
            bookmark_id (int): Bookmark primary key.

        Returns:
            list[Tag]: Attached tags.
        """
        with _cursor(conn) as cursor:
            cursor.execute(
                """
                SELECT t.id, t.name, t.created_at
                FROM tags t
                JOIN bookmark_tags bt ON bt.tag_id = t.id
                WHERE bt.bookmark_id = :bookmark_id
                ORDER BY t.name
                """,
                {"bookmark_id": bookmark_id},
            )
            rows = cursor.fetchall()
        return [
            Tag(id=int(row[0]), name=row[1], created_at=_parse_datetime(row[2]))
            for row in rows
        ]

    def _row_to_bookmark(
        self,
        conn: sqlite3.Connection,
        row: tuple[Any, ...],
    ) -> Bookmark:
        """Map a bookmarks SELECT row to a Bookmark model.

        Args:
            conn (sqlite3.Connection): Active connection.
            row (tuple[Any, ...]): Selected columns.

        Returns:
            Bookmark: Domain bookmark with tags.
        """
        bookmark_id = int(row[0])
        return Bookmark(
            id=bookmark_id,
            folder_id=int(row[1]) if row[1] is not None else None,
            title=row[2],
            url=row[3],
            description=row[4],
            thumbnail_status=ThumbnailStatus(row[5]),
            thumbnail_path=row[6],
            thumbnail_updated_at=_parse_datetime_opt(row[7]),
            created_at=_parse_datetime(row[8]),
            updated_at=_parse_datetime(row[9]),
            tags=self._bookmark_tags(conn, bookmark_id),
        )

    def _fetch_bookmark(self, conn: sqlite3.Connection, bookmark_id: int) -> Bookmark:
        """Load a bookmark with tags.

        Args:
            conn (sqlite3.Connection): Active connection.
            bookmark_id (int): Bookmark primary key.

        Returns:
            Bookmark: Matching bookmark.

        Raises:
            NotFoundError: If the bookmark does not exist.
        """
        with _cursor(conn) as cursor:
            cursor.execute(
                """
                SELECT id, folder_id, title, url, description, thumbnail_status,
                       thumbnail_path, thumbnail_updated_at, created_at, updated_at
                FROM bookmarks
                WHERE id = :id
                """,
                {"id": bookmark_id},
            )
            row = cursor.fetchone()
        if row is None:
            raise NotFoundError(f"Bookmark {bookmark_id} not found")
        return self._row_to_bookmark(conn, row)

    def _get_or_create_tag(self, conn: sqlite3.Connection, name: str) -> Tag:
        """Return an existing tag or insert a new one.

        Args:
            conn (sqlite3.Connection): Active connection.
            name (str): Raw tag name.

        Returns:
            Tag: Matching tag.
        """
        normalized = normalize_tag_name(name)
        with _cursor(conn) as cursor:
            cursor.execute(
                "SELECT id, name, created_at FROM tags WHERE name = :name",
                {"name": normalized},
            )
            row = cursor.fetchone()
            if row is not None:
                return Tag(
                    id=int(row[0]), name=row[1], created_at=_parse_datetime(row[2])
                )
            created_at = _utcnow()
            tag_id = self._insert_id(
                cursor,
                "INSERT INTO tags (name, created_at) VALUES (:name, :created_at)",
                {"name": normalized, "created_at": created_at},
            )
        return Tag(id=tag_id, name=normalized, created_at=created_at)

    def _set_bookmark_tags(
        self,
        conn: sqlite3.Connection,
        bookmark_id: int,
        tag_names: list[str],
    ) -> None:
        """Replace bookmark tag links with the given names.

        Args:
            conn (sqlite3.Connection): Active connection.
            bookmark_id (int): Bookmark primary key.
            tag_names (list[str]): Desired tag names.
        """
        with _cursor(conn) as cursor:
            cursor.execute(
                "DELETE FROM bookmark_tags WHERE bookmark_id = :bookmark_id",
                {"bookmark_id": bookmark_id},
            )
            for name in tag_names:
                tag = self._get_or_create_tag(conn, name)
                cursor.execute(
                    """
                    INSERT INTO bookmark_tags (bookmark_id, tag_id)
                    VALUES (:bookmark_id, :tag_id)
                    """,
                    {"bookmark_id": bookmark_id, "tag_id": tag.id},
                )

    def _row_to_job(self, row: tuple[Any, ...]) -> Job:
        """Map a jobs SELECT row to a Job model.

        Args:
            row (tuple[Any, ...]): Selected columns.

        Returns:
            Job: Domain job.
        """
        return Job(
            id=int(row[0]),
            job_type=row[1],
            payload_json=str(row[2]),
            status=JobStatus(row[3]),
            attempts=int(row[4]),
            max_attempts=int(row[5]),
            scheduled_at=_parse_datetime(row[6]),
            started_at=_parse_datetime_opt(row[7]),
            finished_at=_parse_datetime_opt(row[8]),
            last_error=str(row[9]) if row[9] is not None else None,
            created_at=_parse_datetime(row[10]),
            updated_at=_parse_datetime(row[11]),
        )

    def create_folder(self, payload: FolderCreate) -> Folder:
        """Create a folder.

        Args:
            payload (FolderCreate): Folder creation payload.

        Returns:
            Folder: Created folder.

        Raises:
            NotFoundError: If parent_id does not exist.
        """
        now = _utcnow()
        with self._acquire() as conn:
            if payload.parent_id is not None:
                self._fetch_folder(conn, payload.parent_id)
            with _cursor(conn) as cursor:
                folder_id = self._insert_id(
                    cursor,
                    """
                    INSERT INTO folders (
                        parent_id, name, sort_order, created_at, updated_at
                    )
                    VALUES (
                        :parent_id, :name, :sort_order,
                        :created_at, :updated_at
                    )
                    """,
                    {
                        "parent_id": payload.parent_id,
                        "name": payload.name,
                        "sort_order": payload.sort_order,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
            conn.commit()
            return self._fetch_folder(conn, folder_id)

    def get_folder(self, folder_id: int) -> Folder:
        """Fetch a folder by id.

        Args:
            folder_id (int): Folder primary key.

        Returns:
            Folder: Matching folder.
        """
        with self._acquire() as conn:
            return self._fetch_folder(conn, folder_id)

    def list_folder_children(self, parent_id: int | None) -> list[Folder]:
        """List direct children of a folder.

        Args:
            parent_id (int | None): Parent folder id, or None for roots.

        Returns:
            list[Folder]: Child folders.
        """
        with self._acquire() as conn, _cursor(conn) as cursor:
            if parent_id is None:
                cursor.execute(
                    """
                    SELECT f.id, f.parent_id, f.name, f.sort_order,
                           f.created_at, f.updated_at,
                           (SELECT COUNT(*)
                            FROM bookmarks b
                            WHERE b.folder_id = f.id) AS bookmark_count
                    FROM folders f
                    WHERE f.parent_id IS NULL
                    ORDER BY f.sort_order, LOWER(f.name)
                    """
                )
            else:
                cursor.execute(
                    """
                    SELECT f.id, f.parent_id, f.name, f.sort_order,
                           f.created_at, f.updated_at,
                           (SELECT COUNT(*)
                            FROM bookmarks b
                            WHERE b.folder_id = f.id) AS bookmark_count
                    FROM folders f
                    WHERE f.parent_id = :parent_id
                    ORDER BY f.sort_order, LOWER(f.name)
                    """,
                    {"parent_id": parent_id},
                )
            rows = cursor.fetchall()
            return [
                Folder(
                    id=int(row[0]),
                    parent_id=int(row[1]) if row[1] is not None else None,
                    name=row[2],
                    sort_order=int(row[3]),
                    created_at=_parse_datetime(row[4]),
                    updated_at=_parse_datetime(row[5]),
                    bookmark_count=int(row[6]),
                )
                for row in rows
            ]

    def get_folder_tree(self) -> list[FolderTreeNode]:
        """Build the full nested folder tree.

        Returns:
            list[FolderTreeNode]: Root nodes with nested children.
        """
        with self._acquire() as conn, _cursor(conn) as cursor:
            cursor.execute(
                """
                SELECT id, parent_id, name, sort_order, created_at, updated_at
                FROM folders
                ORDER BY sort_order, LOWER(name)
                """
            )
            rows = cursor.fetchall()
            bookmark_counts = self._bookmark_counts(conn)
            folders = [
                Folder(
                    id=int(row[0]),
                    parent_id=int(row[1]) if row[1] is not None else None,
                    name=row[2],
                    sort_order=int(row[3]),
                    created_at=_parse_datetime(row[4]),
                    updated_at=_parse_datetime(row[5]),
                    bookmark_count=bookmark_counts.get(int(row[0]), 0),
                )
                for row in rows
            ]
            by_parent: dict[int | None, list[Folder]] = {}
            for folder in folders:
                by_parent.setdefault(folder.parent_id, []).append(folder)

            def build(parent_id: int | None) -> list[FolderTreeNode]:
                nodes: list[FolderTreeNode] = []
                for child in by_parent.get(parent_id, []):
                    nodes.append(
                        FolderTreeNode(
                            id=child.id,
                            name=child.name,
                            parent_id=child.parent_id,
                            sort_order=child.sort_order,
                            created_at=child.created_at,
                            updated_at=child.updated_at,
                            bookmark_count=child.bookmark_count,
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
        with self._acquire() as conn:
            current = self._fetch_folder(conn, folder_id)
            updates = payload.model_dump(exclude_unset=True)
            name = updates.get("name", current.name)
            parent_id = updates.get("parent_id", current.parent_id)
            sort_order = updates.get("sort_order", current.sort_order)
            if "parent_id" in updates and parent_id is not None:
                self._fetch_folder(conn, parent_id)
                if parent_id == folder_id or parent_id in self._folder_descendants(
                    conn,
                    folder_id,
                ):
                    raise ValidationError("Cannot move a folder under itself")
            with _cursor(conn) as cursor:
                cursor.execute(
                    """
                    UPDATE folders
                    SET name = :name,
                        parent_id = :parent_id,
                        sort_order = :sort_order,
                        updated_at = :updated_at
                    WHERE id = :id
                    """,
                    {
                        "name": name,
                        "parent_id": parent_id,
                        "sort_order": sort_order,
                        "updated_at": _utcnow(),
                        "id": folder_id,
                    },
                )
            conn.commit()
            return self._fetch_folder(conn, folder_id)

    def delete_folder(self, folder_id: int, *, recursive: bool = False) -> None:
        """Delete a folder.

        Args:
            folder_id (int): Folder primary key.
            recursive (bool): When True, delete descendants and bookmarks.

        Raises:
            NotFoundError: If the folder does not exist.
            ConflictError: If non-recursive delete finds children or bookmarks.
        """
        with self._acquire() as conn:
            self._fetch_folder(conn, folder_id)
            with _cursor(conn) as cursor:
                cursor.execute(
                    "SELECT COUNT(*) FROM folders WHERE parent_id = :id",
                    {"id": folder_id},
                )
                child_count = cursor.fetchone()[0]
                cursor.execute(
                    "SELECT COUNT(*) FROM bookmarks WHERE folder_id = :id",
                    {"id": folder_id},
                )
                bookmark_count = cursor.fetchone()[0]
                if not recursive and (child_count or bookmark_count):
                    raise ConflictError(
                        "Folder is not empty; pass recursive=true to delete contents"
                    )
                targets = {folder_id} | self._folder_descendants(conn, folder_id)
                for target_id in targets:
                    cursor.execute(
                        "SELECT id FROM bookmarks WHERE folder_id = :id",
                        {"id": target_id},
                    )
                    bookmark_ids = [int(row[0]) for row in cursor.fetchall()]
                    for bookmark_id in bookmark_ids:
                        cursor.execute(
                            "DELETE FROM bookmark_tags WHERE bookmark_id = :id",
                            {"id": bookmark_id},
                        )
                        cursor.execute(
                            "DELETE FROM bookmarks WHERE id = :id",
                            {"id": bookmark_id},
                        )
                try:
                    cursor.execute(_FOLDER_DELETE_ORDER_SQL, {"id": folder_id})
                    ordered = cursor.fetchall()
                except sqlite3.Error as exc:
                    logger.error("folder_delete_order_failed err={}", exc)
                    raise
                for row in ordered:
                    cursor.execute(
                        "DELETE FROM folders WHERE id = :id",
                        {"id": int(row[0])},
                    )
            conn.commit()

    def create_bookmark(self, payload: BookmarkCreate) -> Bookmark:
        """Create a bookmark and attach tags.

        Args:
            payload (BookmarkCreate): Bookmark creation payload.

        Returns:
            Bookmark: Created bookmark with tags.
        """
        now = _utcnow()
        with self._acquire() as conn:
            if payload.folder_id is not None:
                self._fetch_folder(conn, payload.folder_id)
            with _cursor(conn) as cursor:
                bookmark_id = self._insert_id(
                    cursor,
                    """
                    INSERT INTO bookmarks (
                        folder_id, title, url, description, thumbnail_status,
                        created_at, updated_at
                    )
                    VALUES (
                        :folder_id, :title, :url, :description,
                        :thumbnail_status, :created_at, :updated_at
                    )
                    """,
                    {
                        "folder_id": payload.folder_id,
                        "title": payload.title,
                        "url": payload.url,
                        "description": payload.description,
                        "thumbnail_status": ThumbnailStatus.PENDING.value,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
            self._set_bookmark_tags(conn, bookmark_id, payload.tag_names)
            conn.commit()
            return self._fetch_bookmark(conn, bookmark_id)

    def get_bookmark(self, bookmark_id: int) -> Bookmark:
        """Fetch a bookmark by id.

        Args:
            bookmark_id (int): Bookmark primary key.

        Returns:
            Bookmark: Matching bookmark.
        """
        with self._acquire() as conn:
            return self._fetch_bookmark(conn, bookmark_id)

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
        with self._acquire() as conn, _cursor(conn) as cursor:
            clauses: list[str] = []
            params: dict[str, Any] = {}
            if unfiled_only:
                clauses.append("b.folder_id IS NULL")
            elif folder_id is not None:
                clauses.append("b.folder_id = :folder_id")
                params["folder_id"] = folder_id
            if q:
                clauses.append(
                    "("
                    "LOWER(b.title) LIKE :q OR LOWER(b.url) LIKE :q "
                    "OR LOWER(COALESCE(b.description, '')) LIKE :q"
                    ")"
                )
                params["q"] = f"%{q.lower()}%"
            if tag:
                clauses.append(
                    "EXISTS ("
                    "SELECT 1 FROM bookmark_tags bt "
                    "JOIN tags t ON t.id = bt.tag_id "
                    "WHERE bt.bookmark_id = b.id AND t.name = :tag_name"
                    ")"
                )
                params["tag_name"] = normalize_tag_name(tag)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            sql = f"""
                SELECT b.id, b.folder_id, b.title, b.url, b.description,
                       b.thumbnail_status, b.thumbnail_path, b.thumbnail_updated_at,
                       b.created_at, b.updated_at
                FROM bookmarks b
                {where}
                ORDER BY b.created_at DESC
                """
            if params:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)
            rows = cursor.fetchall()
            return [self._row_to_bookmark(conn, row) for row in rows]

    def update_bookmark(self, bookmark_id: int, payload: BookmarkUpdate) -> Bookmark:
        """Update bookmark fields and optional tag set.

        Args:
            bookmark_id (int): Bookmark primary key.
            payload (BookmarkUpdate): Fields to update.

        Returns:
            Bookmark: Updated bookmark.
        """
        with self._acquire() as conn:
            current = self._fetch_bookmark(conn, bookmark_id)
            updates = payload.model_dump(exclude_unset=True)
            tag_names = updates.pop("tag_names", None)
            title = updates.get("title", current.title)
            url = updates.get("url", current.url)
            description = updates.get("description", current.description)
            folder_id = updates.get("folder_id", current.folder_id)
            if "folder_id" in updates and folder_id is not None:
                self._fetch_folder(conn, folder_id)
            with _cursor(conn) as cursor:
                cursor.execute(
                    """
                    UPDATE bookmarks
                    SET title = :title,
                        url = :url,
                        description = :description,
                        folder_id = :folder_id,
                        updated_at = :updated_at
                    WHERE id = :id
                    """,
                    {
                        "title": title,
                        "url": url,
                        "description": description,
                        "folder_id": folder_id,
                        "updated_at": _utcnow(),
                        "id": bookmark_id,
                    },
                )
            if tag_names is not None:
                self._set_bookmark_tags(conn, bookmark_id, tag_names)
            conn.commit()
            return self._fetch_bookmark(conn, bookmark_id)

    def delete_bookmark(self, bookmark_id: int) -> None:
        """Delete a bookmark and its tag links.

        Args:
            bookmark_id (int): Bookmark primary key.
        """
        with self._acquire() as conn:
            self._fetch_bookmark(conn, bookmark_id)
            with _cursor(conn) as cursor:
                cursor.execute(
                    "DELETE FROM bookmark_tags WHERE bookmark_id = :id",
                    {"id": bookmark_id},
                )
                cursor.execute(
                    "DELETE FROM bookmarks WHERE id = :id",
                    {"id": bookmark_id},
                )
            conn.commit()

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
        """
        with self._acquire() as conn:
            self._fetch_bookmark(conn, bookmark_id)
            with _cursor(conn) as cursor:
                cursor.execute(
                    """
                    UPDATE bookmarks
                    SET thumbnail_status = :thumbnail_status,
                        thumbnail_path = :thumbnail_path,
                        thumbnail_updated_at = :thumbnail_updated_at,
                        updated_at = :updated_at
                    WHERE id = :id
                    """,
                    {
                        "thumbnail_status": payload.thumbnail_status.value,
                        "thumbnail_path": payload.thumbnail_path,
                        "thumbnail_updated_at": payload.thumbnail_updated_at,
                        "updated_at": _utcnow(),
                        "id": bookmark_id,
                    },
                )
            conn.commit()
            return self._fetch_bookmark(conn, bookmark_id)

    def list_tags(self) -> list[Tag]:
        """List all tags.

        Returns:
            list[Tag]: Tags sorted by name.
        """
        with self._acquire() as conn, _cursor(conn) as cursor:
            cursor.execute("SELECT id, name, created_at FROM tags ORDER BY name")
            rows = cursor.fetchall()
            return [
                Tag(id=int(row[0]), name=row[1], created_at=_parse_datetime(row[2]))
                for row in rows
            ]

    def create_tag(self, payload: TagCreate) -> Tag:
        """Create a tag.

        Args:
            payload (TagCreate): Tag creation payload.

        Returns:
            Tag: Created tag.

        Raises:
            ConflictError: If the tag name already exists.
        """
        now = _utcnow()
        with self._acquire() as conn, _cursor(conn) as cursor:
            cursor.execute(
                "SELECT id FROM tags WHERE name = :name",
                {"name": payload.name},
            )
            existing = cursor.fetchone()
            if existing is not None:
                raise ConflictError(f"Tag '{payload.name}' already exists")
            tag_id = self._insert_id(
                cursor,
                "INSERT INTO tags (name, created_at) VALUES (:name, :created_at)",
                {"name": payload.name, "created_at": now},
            )
            conn.commit()
            cursor.execute(
                "SELECT id, name, created_at FROM tags WHERE id = :id",
                {"id": tag_id},
            )
            row = cursor.fetchone()
            return Tag(id=int(row[0]), name=row[1], created_at=_parse_datetime(row[2]))

    def delete_tag(self, tag_id: int) -> None:
        """Delete a tag and detach it from bookmarks.

        Args:
            tag_id (int): Tag primary key.

        Raises:
            NotFoundError: If the tag does not exist.
        """
        with self._acquire() as conn, _cursor(conn) as cursor:
            cursor.execute(
                "SELECT id FROM tags WHERE id = :id",
                {"id": tag_id},
            )
            row = cursor.fetchone()
            if row is None:
                raise NotFoundError(f"Tag {tag_id} not found")
            cursor.execute(
                "DELETE FROM bookmark_tags WHERE tag_id = :id",
                {"id": tag_id},
            )
            cursor.execute("DELETE FROM tags WHERE id = :id", {"id": tag_id})
            conn.commit()

    def enqueue_job(self, payload: JobEnqueue) -> Job:
        """Enqueue a background job.

        Args:
            payload (JobEnqueue): Job enqueue payload.

        Returns:
            Job: Created pending job.
        """
        now = _utcnow()
        with self._acquire() as conn, _cursor(conn) as cursor:
            scheduled_at = payload.scheduled_at or now
            max_attempts = payload.max_attempts or self._settings.job_max_attempts
            job_id = self._insert_id(
                cursor,
                """
                INSERT INTO jobs (
                    job_type, payload_json, status, attempts, max_attempts,
                    scheduled_at, created_at, updated_at
                )
                VALUES (
                    :job_type, :payload_json, :status, 0, :max_attempts,
                    :scheduled_at, :created_at, :updated_at
                )
                """,
                {
                    "job_type": payload.job_type,
                    "payload_json": payload.payload_json,
                    "status": JobStatus.PENDING.value,
                    "max_attempts": max_attempts,
                    "scheduled_at": scheduled_at,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            conn.commit()
            return self.get_job(job_id)

    def claim_next_job(self) -> Job | None:
        """Atomically claim the next eligible pending job.

        SQLite serializes writers, so a single UPDATE...RETURNING on the
        oldest eligible row is sufficient without SKIP LOCKED.

        Returns:
            Job | None: Claimed running job, or None if none eligible.
        """
        now = _utcnow()
        with self._acquire() as conn, _cursor(conn) as cursor:
            try:
                cursor.execute(
                    _CLAIM_NEXT_JOB_SQL,
                    {
                        "running": JobStatus.RUNNING.value,
                        "started_at": now,
                        "updated_at": now,
                        "pending": JobStatus.PENDING.value,
                        "now": now,
                    },
                )
                row = cursor.fetchone()
            except sqlite3.Error as exc:
                conn.rollback()
                logger.error("job_claim_failed err={}", exc)
                raise
            if row is None:
                conn.rollback()
                return None
            job_id = int(row[0])
            conn.commit()
            return self.get_job(job_id)

    def mark_job_succeeded(self, job_id: int) -> Job:
        """Mark a job as succeeded.

        Args:
            job_id (int): Job primary key.

        Returns:
            Job: Updated job.
        """
        now = _utcnow()
        with self._acquire() as conn, _cursor(conn) as cursor:
            self.get_job(job_id)
            cursor.execute(
                """
                UPDATE jobs
                SET status = :status,
                    finished_at = :finished_at,
                    last_error = NULL,
                    updated_at = :updated_at
                WHERE id = :id
                """,
                {
                    "status": JobStatus.SUCCEEDED.value,
                    "finished_at": now,
                    "updated_at": now,
                    "id": job_id,
                },
            )
            conn.commit()
            return self.get_job(job_id)

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
        """
        now = _utcnow()
        with self._acquire() as conn, _cursor(conn) as cursor:
            job = self.get_job(job_id)
            if retry:
                retry_at = (
                    scheduled_at
                    if isinstance(scheduled_at, datetime)
                    else now + timedelta(seconds=2**job.attempts)
                )
                cursor.execute(
                    """
                    UPDATE jobs
                    SET status = :status,
                        scheduled_at = :scheduled_at,
                        finished_at = NULL,
                        last_error = :last_error,
                        updated_at = :updated_at
                    WHERE id = :id
                    """,
                    {
                        "status": JobStatus.PENDING.value,
                        "scheduled_at": retry_at,
                        "last_error": error,
                        "updated_at": now,
                        "id": job_id,
                    },
                )
            else:
                cursor.execute(
                    """
                    UPDATE jobs
                    SET status = :status,
                        finished_at = :finished_at,
                        last_error = :last_error,
                        updated_at = :updated_at
                    WHERE id = :id
                    """,
                    {
                        "status": JobStatus.FAILED.value,
                        "finished_at": now,
                        "last_error": error,
                        "updated_at": now,
                        "id": job_id,
                    },
                )
            conn.commit()
            return self.get_job(job_id)

    def list_jobs(self, *, limit: int = 100) -> list[Job]:
        """List recent jobs newest first.

        Args:
            limit (int): Maximum rows to return.

        Returns:
            list[Job]: Job rows.
        """
        with self._acquire() as conn, _cursor(conn) as cursor:
            cursor.execute(
                """
                SELECT id, job_type, payload_json, status, attempts, max_attempts,
                       scheduled_at, started_at, finished_at, last_error,
                       created_at, updated_at
                FROM jobs
                ORDER BY created_at DESC
                LIMIT :limit_rows
                """,
                {"limit_rows": limit},
            )
            rows = cursor.fetchall()
            return [self._row_to_job(row) for row in rows]

    def get_job(self, job_id: int) -> Job:
        """Fetch a job by id.

        Args:
            job_id (int): Job primary key.

        Returns:
            Job: Matching job.

        Raises:
            NotFoundError: If the job does not exist.
        """
        with self._acquire() as conn, _cursor(conn) as cursor:
            cursor.execute(
                """
                SELECT id, job_type, payload_json, status, attempts, max_attempts,
                       scheduled_at, started_at, finished_at, last_error,
                       created_at, updated_at
                FROM jobs
                WHERE id = :id
                """,
                {"id": job_id},
            )
            row = cursor.fetchone()
            if row is None:
                raise NotFoundError(f"Job {job_id} not found")
            return self._row_to_job(row)
