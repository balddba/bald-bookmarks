"""Oracle DatabaseDriver implementation using oracledb thin mode."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Any

import oracledb
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


def _utcnow() -> datetime:
    """Return the current UTC timestamp.

    Returns:
        datetime: Aware UTC datetime.
    """
    return datetime.now(UTC)


class OracleDriver(DatabaseDriver):
    """Persist Bald Bookmarks data with oracledb connection pooling."""

    def __init__(self, settings: Settings) -> None:
        """Store settings for pool creation.

        Args:
            settings (Settings): Application settings with Oracle credentials.
        """
        self._settings = settings
        self._pool: oracledb.ConnectionPool | None = None

    def connect(self) -> None:
        """Create the oracledb thin-mode connection pool.

        Raises:
            ValueError: If Oracle connection settings are incomplete.
        """
        if self._pool is not None:
            return
        if (
            not self._settings.oracle_user
            or not self._settings.oracle_password
            or not self._settings.oracle_dsn
        ):
            raise ValueError("Oracle connection settings are incomplete")
        self._pool = oracledb.create_pool(
            user=self._settings.oracle_user,
            password=self._settings.oracle_password,
            dsn=self._settings.oracle_dsn,
            min=1,
            max=4,
            increment=1,
        )
        logger.info("Oracle connection pool created")

    def close(self) -> None:
        """Close the connection pool."""
        if self._pool is not None:
            self._pool.close()
            self._pool = None
            logger.info("Oracle connection pool closed")

    def health_check(self) -> DatabaseHealth:
        """Run SELECT 1 FROM DUAL against the pooled connection.

        Returns:
            DatabaseHealth: Probe result including latency when measured.
        """
        started = perf_counter()
        if self._pool is None:
            return DatabaseHealth(
                ok=False,
                driver="oracle",
                latency_ms=None,
                message="Oracle connection pool is not open",
            )
        try:
            with self._acquire() as conn, conn.cursor() as cursor:
                try:
                    cursor.execute("SELECT 1 FROM DUAL")
                    cursor.fetchone()
                except oracledb.DatabaseError as exc:
                    latency_ms = round((perf_counter() - started) * 1000, 2)
                    logger.bind(dsn=self._settings.oracle_dsn).error(
                        "db_health_check_failed err={}", exc
                    )
                    return DatabaseHealth(
                        ok=False,
                        driver="oracle",
                        latency_ms=latency_ms,
                        message=str(exc),
                    )
        except Exception as exc:  # noqa: BLE001
            latency_ms = round((perf_counter() - started) * 1000, 2)
            logger.bind(dsn=self._settings.oracle_dsn).error(
                "db_health_check_failed err={}", exc
            )
            return DatabaseHealth(
                ok=False,
                driver="oracle",
                latency_ms=latency_ms,
                message=str(exc),
            )
        latency_ms = round((perf_counter() - started) * 1000, 2)
        return DatabaseHealth(
            ok=True,
            driver="oracle",
            latency_ms=latency_ms,
            message="SELECT 1 FROM DUAL succeeded",
        )

    def alembic_revision(self) -> str | None:
        """Read version_num from the Alembic version table.

        Returns:
            str | None: Deployed revision id, or None when the table is empty.

        Raises:
            oracledb.DatabaseError: If alembic_version cannot be queried.
            RuntimeError: If the pool has not been created.
        """
        with self._acquire() as conn, conn.cursor() as cursor:
            try:
                cursor.execute("SELECT version_num FROM alembic_version")
                row = cursor.fetchone()
            except oracledb.DatabaseError as exc:
                logger.bind(dsn=self._settings.oracle_dsn).error(
                    "alembic_revision_failed err={}", exc
                )
                raise
        if row is None:
            return None
        return str(row[0])

    def _acquire(self) -> oracledb.Connection:
        """Acquire a pooled connection.

        Returns:
            oracledb.Connection: Open connection.

        Raises:
            RuntimeError: If the pool has not been created.
        """
        if self._pool is None:
            raise RuntimeError("OracleDriver is not connected")
        return self._pool.acquire()

    def _fetch_folder(self, conn: oracledb.Connection, folder_id: int) -> Folder:
        """Load a folder row.

        Args:
            conn (oracledb.Connection): Active connection.
            folder_id (int): Folder primary key.

        Returns:
            Folder: Matching folder.

        Raises:
            NotFoundError: If the folder does not exist.
        """
        row = (
            conn.cursor()
            .execute(
                """
            SELECT f.id, f.parent_id, f.name, f.sort_order,
                   f.created_at, f.updated_at,
                   (SELECT COUNT(*)
                    FROM bookmarks b
                    WHERE b.folder_id = f.id) AS bookmark_count
            FROM folders f
            WHERE f.id = :id
            """,
                id=folder_id,
            )
            .fetchone()
        )
        if row is None:
            raise NotFoundError(f"Folder {folder_id} not found")
        return Folder(
            id=int(row[0]),
            parent_id=int(row[1]) if row[1] is not None else None,
            name=row[2],
            sort_order=int(row[3]),
            created_at=row[4],
            updated_at=row[5],
            bookmark_count=int(row[6]),
        )

    def _bookmark_counts(self, conn: oracledb.Connection) -> dict[int, int]:
        """Load bookmark counts grouped by folder id.

        Args:
            conn (oracledb.Connection): Active connection.

        Returns:
            dict[int, int]: Bookmark count keyed by folder id.
        """
        rows = (
            conn.cursor()
            .execute(
                """
            SELECT folder_id, COUNT(*)
            FROM bookmarks
            WHERE folder_id IS NOT NULL
            GROUP BY folder_id
            """
            )
            .fetchall()
        )
        return {int(row[0]): int(row[1]) for row in rows}

    def _folder_descendants(
        self,
        conn: oracledb.Connection,
        folder_id: int,
    ) -> set[int]:
        """Collect descendant folder ids via hierarchical query.

        Args:
            conn (oracledb.Connection): Active connection.
            folder_id (int): Ancestor folder id.

        Returns:
            set[int]: Descendant ids excluding folder_id.
        """
        rows = (
            conn.cursor()
            .execute(
                """
            SELECT id
            FROM folders
            START WITH parent_id = :id
            CONNECT BY PRIOR id = parent_id
            """,
                id=folder_id,
            )
            .fetchall()
        )
        return {int(row[0]) for row in rows}

    def _bookmark_tags(self, conn: oracledb.Connection, bookmark_id: int) -> list[Tag]:
        """Load tags for a bookmark.

        Args:
            conn (oracledb.Connection): Active connection.
            bookmark_id (int): Bookmark primary key.

        Returns:
            list[Tag]: Attached tags.
        """
        rows = (
            conn.cursor()
            .execute(
                """
            SELECT t.id, t.name, t.created_at
            FROM tags t
            JOIN bookmark_tags bt ON bt.tag_id = t.id
            WHERE bt.bookmark_id = :bookmark_id
            ORDER BY t.name
            """,
                bookmark_id=bookmark_id,
            )
            .fetchall()
        )
        return [Tag(id=int(row[0]), name=row[1], created_at=row[2]) for row in rows]

    def _row_to_bookmark(
        self,
        conn: oracledb.Connection,
        row: tuple[Any, ...],
    ) -> Bookmark:
        """Map a bookmarks SELECT row to a Bookmark model.

        Args:
            conn (oracledb.Connection): Active connection.
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
            thumbnail_updated_at=row[7],
            created_at=row[8],
            updated_at=row[9],
            tags=self._bookmark_tags(conn, bookmark_id),
        )

    def _fetch_bookmark(self, conn: oracledb.Connection, bookmark_id: int) -> Bookmark:
        """Load a bookmark with tags.

        Args:
            conn (oracledb.Connection): Active connection.
            bookmark_id (int): Bookmark primary key.

        Returns:
            Bookmark: Matching bookmark.

        Raises:
            NotFoundError: If the bookmark does not exist.
        """
        row = (
            conn.cursor()
            .execute(
                """
            SELECT id, folder_id, title, url, description, thumbnail_status,
                   thumbnail_path, thumbnail_updated_at, created_at, updated_at
            FROM bookmarks
            WHERE id = :id
            """,
                id=bookmark_id,
            )
            .fetchone()
        )
        if row is None:
            raise NotFoundError(f"Bookmark {bookmark_id} not found")
        return self._row_to_bookmark(conn, row)

    def _get_or_create_tag(self, conn: oracledb.Connection, name: str) -> Tag:
        """Return an existing tag or insert a new one.

        Args:
            conn (oracledb.Connection): Active connection.
            name (str): Raw tag name.

        Returns:
            Tag: Matching tag.
        """
        normalized = normalize_tag_name(name)
        cursor = conn.cursor()
        row = cursor.execute(
            "SELECT id, name, created_at FROM tags WHERE name = :name",
            name=normalized,
        ).fetchone()
        if row is not None:
            return Tag(id=int(row[0]), name=row[1], created_at=row[2])
        new_id = cursor.var(oracledb.DB_TYPE_NUMBER)
        cursor.execute(
            """
            INSERT INTO tags (name, created_at)
            VALUES (:name, SYSTIMESTAMP)
            RETURNING id INTO :id
            """,
            name=normalized,
            id=new_id,
        )
        tag_id = int(new_id.getvalue()[0])
        created = cursor.execute(
            "SELECT created_at FROM tags WHERE id = :id",
            id=tag_id,
        ).fetchone()
        return Tag(id=tag_id, name=normalized, created_at=created[0])

    def _set_bookmark_tags(
        self,
        conn: oracledb.Connection,
        bookmark_id: int,
        tag_names: list[str],
    ) -> None:
        """Replace bookmark tag links with the given names.

        Args:
            conn (oracledb.Connection): Active connection.
            bookmark_id (int): Bookmark primary key.
            tag_names (list[str]): Desired tag names.
        """
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM bookmark_tags WHERE bookmark_id = :bookmark_id",
            bookmark_id=bookmark_id,
        )
        for name in tag_names:
            tag = self._get_or_create_tag(conn, name)
            cursor.execute(
                """
                INSERT INTO bookmark_tags (bookmark_id, tag_id)
                VALUES (:bookmark_id, :tag_id)
                """,
                bookmark_id=bookmark_id,
                tag_id=tag.id,
            )

    def _row_to_job(self, row: tuple[Any, ...]) -> Job:
        """Map a jobs SELECT row to a Job model.

        Args:
            row (tuple[Any, ...]): Selected columns.

        Returns:
            Job: Domain job.
        """
        payload = row[2]
        if hasattr(payload, "read"):
            payload = payload.read()
        last_error = row[9]
        if hasattr(last_error, "read"):
            last_error = last_error.read()
        return Job(
            id=int(row[0]),
            job_type=row[1],
            payload_json=str(payload),
            status=JobStatus(row[3]),
            attempts=int(row[4]),
            max_attempts=int(row[5]),
            scheduled_at=row[6],
            started_at=row[7],
            finished_at=row[8],
            last_error=str(last_error) if last_error is not None else None,
            created_at=row[10],
            updated_at=row[11],
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
        with self._acquire() as conn:
            if payload.parent_id is not None:
                self._fetch_folder(conn, payload.parent_id)
            cursor = conn.cursor()
            new_id = cursor.var(oracledb.DB_TYPE_NUMBER)
            cursor.execute(
                """
                INSERT INTO folders (
                    parent_id, name, sort_order, created_at, updated_at
                )
                VALUES (
                    :parent_id, :name, :sort_order, SYSTIMESTAMP, SYSTIMESTAMP
                )
                RETURNING id INTO :id
                """,
                parent_id=payload.parent_id,
                name=payload.name,
                sort_order=payload.sort_order,
                id=new_id,
            )
            folder_id = int(new_id.getvalue()[0])
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
        with self._acquire() as conn:
            if parent_id is None:
                rows = (
                    conn.cursor()
                    .execute(
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
                    .fetchall()
                )
            else:
                rows = (
                    conn.cursor()
                    .execute(
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
                        parent_id=parent_id,
                    )
                    .fetchall()
                )
            return [
                Folder(
                    id=int(row[0]),
                    parent_id=int(row[1]) if row[1] is not None else None,
                    name=row[2],
                    sort_order=int(row[3]),
                    created_at=row[4],
                    updated_at=row[5],
                    bookmark_count=int(row[6]),
                )
                for row in rows
            ]

    def get_folder_tree(self) -> list[FolderTreeNode]:
        """Build the full nested folder tree.

        Returns:
            list[FolderTreeNode]: Root nodes with nested children.
        """
        with self._acquire() as conn:
            rows = (
                conn.cursor()
                .execute(
                    """
                SELECT id, parent_id, name, sort_order, created_at, updated_at
                FROM folders
                ORDER BY sort_order, LOWER(name)
                """
                )
                .fetchall()
            )
            bookmark_counts = self._bookmark_counts(conn)
            folders = [
                Folder(
                    id=int(row[0]),
                    parent_id=int(row[1]) if row[1] is not None else None,
                    name=row[2],
                    sort_order=int(row[3]),
                    created_at=row[4],
                    updated_at=row[5],
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
            conn.cursor().execute(
                """
                UPDATE folders
                SET name = :name,
                    parent_id = :parent_id,
                    sort_order = :sort_order,
                    updated_at = SYSTIMESTAMP
                WHERE id = :id
                """,
                name=name,
                parent_id=parent_id,
                sort_order=sort_order,
                id=folder_id,
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
            cursor = conn.cursor()
            child_count = cursor.execute(
                "SELECT COUNT(*) FROM folders WHERE parent_id = :id",
                id=folder_id,
            ).fetchone()[0]
            bookmark_count = cursor.execute(
                "SELECT COUNT(*) FROM bookmarks WHERE folder_id = :id",
                id=folder_id,
            ).fetchone()[0]
            if not recursive and (child_count or bookmark_count):
                raise ConflictError(
                    "Folder is not empty; pass recursive=true to delete contents"
                )
            targets = {folder_id} | self._folder_descendants(conn, folder_id)
            for target_id in targets:
                bookmark_ids = [
                    int(row[0])
                    for row in cursor.execute(
                        "SELECT id FROM bookmarks WHERE folder_id = :id",
                        id=target_id,
                    ).fetchall()
                ]
                for bookmark_id in bookmark_ids:
                    cursor.execute(
                        "DELETE FROM bookmark_tags WHERE bookmark_id = :id",
                        id=bookmark_id,
                    )
                    cursor.execute(
                        "DELETE FROM bookmarks WHERE id = :id",
                        id=bookmark_id,
                    )
            try:
                ordered = cursor.execute(
                    """
                    SELECT id
                    FROM folders
                    START WITH id = :id
                    CONNECT BY PRIOR id = parent_id
                    ORDER BY LEVEL DESC
                    """,
                    id=folder_id,
                ).fetchall()
            except oracledb.DatabaseError as exc:
                logger.error("folder_delete_order_failed err={}", exc)
                raise
            for row in ordered:
                cursor.execute("DELETE FROM folders WHERE id = :id", id=int(row[0]))
            conn.commit()

    def create_bookmark(self, payload: BookmarkCreate) -> Bookmark:
        """Create a bookmark and attach tags.

        Args:
            payload (BookmarkCreate): Bookmark creation payload.

        Returns:
            Bookmark: Created bookmark with tags.
        """
        with self._acquire() as conn:
            if payload.folder_id is not None:
                self._fetch_folder(conn, payload.folder_id)
            cursor = conn.cursor()
            new_id = cursor.var(oracledb.DB_TYPE_NUMBER)
            cursor.execute(
                """
                INSERT INTO bookmarks (
                    folder_id, title, url, description, thumbnail_status,
                    created_at, updated_at
                )
                VALUES (
                    :folder_id, :title, :url, :description, :thumbnail_status,
                    SYSTIMESTAMP, SYSTIMESTAMP
                )
                RETURNING id INTO :id
                """,
                folder_id=payload.folder_id,
                title=payload.title,
                url=payload.url,
                description=payload.description,
                thumbnail_status=ThumbnailStatus.PENDING.value,
                id=new_id,
            )
            bookmark_id = int(new_id.getvalue()[0])
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
        with self._acquire() as conn:
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
                    "OR LOWER(NVL(b.description, '')) LIKE :q"
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
            rows = (
                conn.cursor()
                .execute(
                    f"""
                SELECT b.id, b.folder_id, b.title, b.url, b.description,
                       b.thumbnail_status, b.thumbnail_path, b.thumbnail_updated_at,
                       b.created_at, b.updated_at
                FROM bookmarks b
                {where}
                ORDER BY b.created_at DESC
                """,
                    **params,
                )
                .fetchall()
            )
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
            conn.cursor().execute(
                """
                UPDATE bookmarks
                SET title = :title,
                    url = :url,
                    description = :description,
                    folder_id = :folder_id,
                    updated_at = SYSTIMESTAMP
                WHERE id = :id
                """,
                title=title,
                url=url,
                description=description,
                folder_id=folder_id,
                id=bookmark_id,
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
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM bookmark_tags WHERE bookmark_id = :id",
                id=bookmark_id,
            )
            cursor.execute("DELETE FROM bookmarks WHERE id = :id", id=bookmark_id)
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
            conn.cursor().execute(
                """
                UPDATE bookmarks
                SET thumbnail_status = :thumbnail_status,
                    thumbnail_path = :thumbnail_path,
                    thumbnail_updated_at = :thumbnail_updated_at,
                    updated_at = SYSTIMESTAMP
                WHERE id = :id
                """,
                thumbnail_status=payload.thumbnail_status.value,
                thumbnail_path=payload.thumbnail_path,
                thumbnail_updated_at=payload.thumbnail_updated_at,
                id=bookmark_id,
            )
            conn.commit()
            return self._fetch_bookmark(conn, bookmark_id)

    def list_tags(self) -> list[Tag]:
        """List all tags.

        Returns:
            list[Tag]: Tags sorted by name.
        """
        with self._acquire() as conn:
            rows = (
                conn.cursor()
                .execute("SELECT id, name, created_at FROM tags ORDER BY name")
                .fetchall()
            )
            return [Tag(id=int(row[0]), name=row[1], created_at=row[2]) for row in rows]

    def create_tag(self, payload: TagCreate) -> Tag:
        """Create a tag.

        Args:
            payload (TagCreate): Tag creation payload.

        Returns:
            Tag: Created tag.

        Raises:
            ConflictError: If the tag name already exists.
        """
        with self._acquire() as conn:
            existing = (
                conn.cursor()
                .execute(
                    "SELECT id FROM tags WHERE name = :name",
                    name=payload.name,
                )
                .fetchone()
            )
            if existing is not None:
                raise ConflictError(f"Tag '{payload.name}' already exists")
            cursor = conn.cursor()
            new_id = cursor.var(oracledb.DB_TYPE_NUMBER)
            cursor.execute(
                """
                INSERT INTO tags (name, created_at)
                VALUES (:name, SYSTIMESTAMP)
                RETURNING id INTO :id
                """,
                name=payload.name,
                id=new_id,
            )
            tag_id = int(new_id.getvalue()[0])
            conn.commit()
            row = cursor.execute(
                "SELECT id, name, created_at FROM tags WHERE id = :id",
                id=tag_id,
            ).fetchone()
            return Tag(id=int(row[0]), name=row[1], created_at=row[2])

    def delete_tag(self, tag_id: int) -> None:
        """Delete a tag and detach it from bookmarks.

        Args:
            tag_id (int): Tag primary key.

        Raises:
            NotFoundError: If the tag does not exist.
        """
        with self._acquire() as conn:
            row = (
                conn.cursor()
                .execute(
                    "SELECT id FROM tags WHERE id = :id",
                    id=tag_id,
                )
                .fetchone()
            )
            if row is None:
                raise NotFoundError(f"Tag {tag_id} not found")
            cursor = conn.cursor()
            cursor.execute("DELETE FROM bookmark_tags WHERE tag_id = :id", id=tag_id)
            cursor.execute("DELETE FROM tags WHERE id = :id", id=tag_id)
            conn.commit()

    def enqueue_job(self, payload: JobEnqueue) -> Job:
        """Enqueue a background job.

        Args:
            payload (JobEnqueue): Job enqueue payload.

        Returns:
            Job: Created pending job.
        """
        with self._acquire() as conn:
            cursor = conn.cursor()
            new_id = cursor.var(oracledb.DB_TYPE_NUMBER)
            scheduled_at = payload.scheduled_at or _utcnow()
            max_attempts = payload.max_attempts or self._settings.job_max_attempts
            cursor.execute(
                """
                INSERT INTO jobs (
                    job_type, payload_json, status, attempts, max_attempts,
                    scheduled_at, created_at, updated_at
                )
                VALUES (
                    :job_type, :payload_json, :status, 0, :max_attempts,
                    :scheduled_at, SYSTIMESTAMP, SYSTIMESTAMP
                )
                RETURNING id INTO :id
                """,
                job_type=payload.job_type,
                payload_json=payload.payload_json,
                status=JobStatus.PENDING.value,
                max_attempts=max_attempts,
                scheduled_at=scheduled_at,
                id=new_id,
            )
            job_id = int(new_id.getvalue()[0])
            conn.commit()
            return self.get_job(job_id)

    def claim_next_job(self) -> Job | None:
        """Atomically claim the next eligible pending job.

        Oracle rejects SELECT FOR UPDATE on an ORDER BY/ROWNUM inline view
        (ORA-02014). Claim with a single-row UPDATE on the base table instead.

        Returns:
            Job | None: Claimed running job, or None if none eligible.
        """
        with self._acquire() as conn:
            cursor = conn.cursor()
            claimed_id = cursor.var(oracledb.DB_TYPE_NUMBER)
            try:
                cursor.execute(
                    """
                    UPDATE jobs
                    SET status = :running,
                        attempts = attempts + 1,
                        started_at = SYSTIMESTAMP,
                        updated_at = SYSTIMESTAMP
                    WHERE id = (
                        SELECT id
                        FROM (
                            SELECT id
                            FROM jobs
                            WHERE status = :pending
                              AND scheduled_at <= SYSTIMESTAMP
                            ORDER BY scheduled_at, id
                        )
                        WHERE ROWNUM = 1
                    )
                    AND status = :pending
                    RETURNING id INTO :id
                    """,
                    running=JobStatus.RUNNING.value,
                    pending=JobStatus.PENDING.value,
                    id=claimed_id,
                )
            except oracledb.DatabaseError as exc:
                conn.rollback()
                logger.error("job_claim_failed err={}", exc)
                raise
            values = claimed_id.getvalue()
            if cursor.rowcount == 0 or not values or values[0] is None:
                conn.rollback()
                return None
            job_id = int(values[0])
            conn.commit()
            return self.get_job(job_id)

    def mark_job_succeeded(self, job_id: int) -> Job:
        """Mark a job as succeeded.

        Args:
            job_id (int): Job primary key.

        Returns:
            Job: Updated job.
        """
        with self._acquire() as conn:
            self.get_job(job_id)
            conn.cursor().execute(
                """
                UPDATE jobs
                SET status = :status,
                    finished_at = SYSTIMESTAMP,
                    last_error = NULL,
                    updated_at = SYSTIMESTAMP
                WHERE id = :id
                """,
                status=JobStatus.SUCCEEDED.value,
                id=job_id,
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
        with self._acquire() as conn:
            job = self.get_job(job_id)
            if retry:
                retry_at = (
                    scheduled_at
                    if isinstance(scheduled_at, datetime)
                    else _utcnow() + timedelta(seconds=2**job.attempts)
                )
                conn.cursor().execute(
                    """
                    UPDATE jobs
                    SET status = :status,
                        scheduled_at = :scheduled_at,
                        finished_at = NULL,
                        last_error = :last_error,
                        updated_at = SYSTIMESTAMP
                    WHERE id = :id
                    """,
                    status=JobStatus.PENDING.value,
                    scheduled_at=retry_at,
                    last_error=error,
                    id=job_id,
                )
            else:
                conn.cursor().execute(
                    """
                    UPDATE jobs
                    SET status = :status,
                        finished_at = SYSTIMESTAMP,
                        last_error = :last_error,
                        updated_at = SYSTIMESTAMP
                    WHERE id = :id
                    """,
                    status=JobStatus.FAILED.value,
                    last_error=error,
                    id=job_id,
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
        with self._acquire() as conn:
            rows = (
                conn.cursor()
                .execute(
                    """
                SELECT id, job_type, payload_json, status, attempts, max_attempts,
                       scheduled_at, started_at, finished_at, last_error,
                       created_at, updated_at
                FROM (
                    SELECT id, job_type, payload_json, status, attempts, max_attempts,
                           scheduled_at, started_at, finished_at, last_error,
                           created_at, updated_at
                    FROM jobs
                    ORDER BY created_at DESC
                )
                WHERE ROWNUM <= :limit_rows
                """,
                    limit_rows=limit,
                )
                .fetchall()
            )
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
        with self._acquire() as conn:
            row = (
                conn.cursor()
                .execute(
                    """
                SELECT id, job_type, payload_json, status, attempts, max_attempts,
                       scheduled_at, started_at, finished_at, last_error,
                       created_at, updated_at
                FROM jobs
                WHERE id = :id
                """,
                    id=job_id,
                )
                .fetchone()
            )
            if row is None:
                raise NotFoundError(f"Job {job_id} not found")
            return self._row_to_job(row)
