"""Bookmark backup, restore, export, and import services."""

import html
import json
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

from loguru import logger

from bald_bookmarks.config import Settings
from bald_bookmarks.db.abc import DatabaseDriver
from bald_bookmarks.domain.bookmarks import BookmarkCreate
from bald_bookmarks.domain.export_import import (
    ExportBackup,
    ExportBookmark,
    ExportFolder,
    ImportResult,
)
from bald_bookmarks.domain.folders import FolderCreate, FolderTreeNode
from bald_bookmarks.services.thumbnail_jobs import enqueue_thumbnail_capture


class _FolderAccumulator:
    """Internal mutable folder representation used while parsing Netscape HTML."""

    def __init__(self, *, name: str) -> None:
        """Initialize the accumulator.

        Args:
            name (str): Folder display name.
        """
        self.name = name
        self.folders: list[_FolderAccumulator] = []
        self.bookmarks: list[ExportBookmark] = []


class NetscapeBookmarkParser(HTMLParser):
    """Parser for Netscape Bookmark File format (HTML).

    Extracts nested folder hierarchies, bookmarks, tags, descriptions,
    and timestamps from standard browser bookmark exports.
    """

    def __init__(self) -> None:
        """Initialize the Netscape HTML parser."""
        super().__init__(convert_charrefs=True)
        self.root: _FolderAccumulator = _FolderAccumulator(name="root")
        self.stack: list[_FolderAccumulator] = [self.root]
        self.current_tag: str | None = None
        self.pending_folder_name: str = ""
        self.current_bookmark_data: dict[str, Any] | None = None
        self.is_collecting_desc: bool = False

    def _flush_description(self) -> None:
        """Trim collected description on the last added bookmark."""
        self.is_collecting_desc = False
        if self.stack and self.stack[-1].bookmarks:
            last_b = self.stack[-1].bookmarks[-1]
            if last_b.description:
                last_b.description = last_b.description.strip()[:256] or None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Process opening HTML tags.

        Args:
            tag (str): Tag name.
            attrs (list[tuple[str, str | None]]): Tag attribute key-value pairs.
        """
        tag_lower = tag.lower()
        self.current_tag = tag_lower
        attrs_map = {k.lower(): v or "" for k, v in attrs}

        if tag_lower in {"h3", "a", "dl", "dt"}:
            self._flush_description()

        if tag_lower == "h3":
            self.pending_folder_name = ""
        elif tag_lower == "dl":
            if self.pending_folder_name.strip():
                new_folder = _FolderAccumulator(name=self.pending_folder_name.strip())
                self.stack[-1].folders.append(new_folder)
                self.stack.append(new_folder)
                self.pending_folder_name = ""
        elif tag_lower == "a":
            href = attrs_map.get("href", "").strip()
            raw_tags = attrs_map.get("tags", "")
            tags = [
                tag_part.strip() for tag_part in raw_tags.split(",") if tag_part.strip()
            ]
            add_date_str = attrs_map.get("add_date")
            created_at: datetime | None = None
            if add_date_str and add_date_str.isdigit():
                try:
                    created_at = datetime.fromtimestamp(
                        int(add_date_str),
                        tz=UTC,
                    )
                except (ValueError, OverflowError):
                    created_at = None

            self.current_bookmark_data = {
                "url": href,
                "title": "",
                "tags": tags,
                "created_at": created_at,
            }
        elif tag_lower == "dd":
            self.is_collecting_desc = True

    def handle_endtag(self, tag: str) -> None:
        """Process closing HTML tags.

        Args:
            tag (str): Tag name.
        """
        tag_lower = tag.lower()
        self.current_tag = None

        if tag_lower == "a":
            if (
                self.current_bookmark_data is not None
                and self.current_bookmark_data.get("url")
            ):
                bookmark_url = self.current_bookmark_data["url"]
                bookmark_title = (
                    self.current_bookmark_data["title"].strip() or bookmark_url
                )
                self.stack[-1].bookmarks.append(
                    ExportBookmark(
                        title=bookmark_title[:512],
                        url=bookmark_url[:2048],
                        description=None,
                        created_at=self.current_bookmark_data.get("created_at"),
                        tags=self.current_bookmark_data.get("tags", []),
                    )
                )
            self.current_bookmark_data = None
        elif tag_lower == "dl":
            self._flush_description()
            if len(self.stack) > 1:
                self.stack.pop()
        elif tag_lower == "dd":
            self._flush_description()

    def handle_data(self, data: str) -> None:
        """Process tag text content.

        Args:
            data (str): Inner text content.
        """
        if self.current_tag == "h3":
            self.pending_folder_name += data
        elif self.current_tag == "a":
            if self.current_bookmark_data is not None:
                self.current_bookmark_data["title"] += data
        elif self.is_collecting_desc and self.stack[-1].bookmarks:
            last_b = self.stack[-1].bookmarks[-1]
            last_b.description = (last_b.description or "") + data

    def build_backup(self) -> ExportBackup:
        """Convert accumulated tree into an ExportBackup model.

        Returns:
            ExportBackup: Parsed backup container.
        """

        def convert_folder(acc: _FolderAccumulator) -> ExportFolder:
            return ExportFolder(
                name=acc.name[:255],
                sort_order=0,
                folders=[convert_folder(f) for f in acc.folders],
                bookmarks=acc.bookmarks,
            )

        return ExportBackup(
            folders=[convert_folder(f) for f in self.root.folders],
            bookmarks=self.root.bookmarks,
        )


class NetscapeBookmarkExporter:
    """Renderer for Netscape Bookmark File format (HTML)."""

    def export_html(self, *, backup: ExportBackup) -> str:
        """Render an ExportBackup into Netscape HTML format.

        Args:
            backup (ExportBackup): Backup container to serialize.

        Returns:
            str: Standard Netscape HTML bookmark file content.
        """
        lines = [
            "<!DOCTYPE NETSCAPE-Bookmark-file-1>",
            "<!-- This is an automatically generated file.",
            "     It will be read and overwritten.",
            "     DO NOT EDIT! -->",
            '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">',
            "<TITLE>Bookmarks</TITLE>",
            "<H1>Bookmarks</H1>",
            "<DL><p>",
        ]

        def render_bookmark(bookmark: ExportBookmark, indent: str) -> None:
            escaped_url = html.escape(bookmark.url, quote=True)
            escaped_title = html.escape(bookmark.title)
            tags_attr = ""
            if bookmark.tags:
                escaped_tags = html.escape(",".join(bookmark.tags), quote=True)
                tags_attr = f' TAGS="{escaped_tags}"'
            add_date_attr = ""
            if bookmark.created_at:
                epoch_sec = int(bookmark.created_at.timestamp())
                add_date_attr = f' ADD_DATE="{epoch_sec}"'

            link_tag = (
                f'{indent}<DT><A HREF="{escaped_url}"'
                f"{add_date_attr}{tags_attr}>{escaped_title}</A>"
            )
            lines.append(link_tag)
            if bookmark.description:
                escaped_desc = html.escape(bookmark.description)
                lines.append(f"{indent}<DD>{escaped_desc}")

        def render_folder(folder: ExportFolder, indent: str) -> None:
            escaped_name = html.escape(folder.name)
            lines.append(f"{indent}<DT><H3>{escaped_name}</H3>")
            lines.append(f"{indent}<DL><p>")
            child_indent = indent + "    "
            for bookmark in folder.bookmarks:
                render_bookmark(bookmark, child_indent)
            for subfolder in folder.folders:
                render_folder(subfolder, child_indent)
            lines.append(f"{indent}</DL><p>")

        for folder in backup.folders:
            render_folder(folder, "    ")

        for bookmark in backup.bookmarks:
            render_bookmark(bookmark, "    ")

        lines.append("</DL><p>")
        return "\n".join(lines) + "\n"


class BookmarkBackupService:
    """Service orchestrating bookmark export, backup, restore, and import."""

    def __init__(self, *, driver: DatabaseDriver, settings: Settings) -> None:
        """Initialize the backup service with database driver and settings.

        Args:
            driver (DatabaseDriver): Connected database driver.
            settings (Settings): Application settings.
        """
        self.driver = driver
        self.settings = settings
        self.exporter = NetscapeBookmarkExporter()

    def _convert_folder_node(self, node: FolderTreeNode) -> ExportFolder:
        """Convert a database folder tree node into an ExportFolder model.

        Args:
            node (FolderTreeNode): Folder tree node from database.

        Returns:
            ExportFolder: Export folder model with child bookmarks and folders.
        """
        bookmarks = self.driver.list_bookmarks(folder_id=node.id)
        export_bookmarks = [
            ExportBookmark(
                title=b.title,
                url=b.url,
                description=b.description,
                created_at=b.created_at,
                tags=[tag.name for tag in b.tags],
            )
            for b in bookmarks
        ]
        child_folders = [self._convert_folder_node(child) for child in node.children]
        return ExportFolder(
            name=node.name,
            sort_order=node.sort_order,
            folders=child_folders,
            bookmarks=export_bookmarks,
        )

    def export_backup(self, *, folder_id: int | None = None) -> ExportBackup:
        """Generate a complete or folder-scoped ExportBackup model.

        Args:
            folder_id (int | None): Optional folder id scope.

        Returns:
            ExportBackup: Populated backup container.

        Raises:
            NotFoundError: If a specified folder_id does not exist.
        """
        if folder_id is not None:
            folder = self.driver.get_folder(folder_id)
            tree = self.driver.get_folder_tree()

            def find_node(nodes: list[FolderTreeNode]) -> FolderTreeNode | None:
                for n in nodes:
                    if n.id == folder.id:
                        return n
                    found = find_node(n.children)
                    if found:
                        return found
                return None

            matching_node = find_node(tree)
            if matching_node is None:
                matching_node = FolderTreeNode(
                    id=folder.id,
                    name=folder.name,
                    parent_id=folder.parent_id,
                    sort_order=folder.sort_order,
                    created_at=folder.created_at,
                    updated_at=folder.updated_at,
                    bookmark_count=folder.bookmark_count,
                    children=[],
                )
            export_folder = self._convert_folder_node(matching_node)
            return ExportBackup(folders=[export_folder], bookmarks=[])

        tree = self.driver.get_folder_tree()
        folders = [self._convert_folder_node(node) for node in tree]
        unfiled = self.driver.list_bookmarks(unfiled_only=True)
        export_bookmarks = [
            ExportBookmark(
                title=b.title,
                url=b.url,
                description=b.description,
                created_at=b.created_at,
                tags=[tag.name for tag in b.tags],
            )
            for b in unfiled
        ]
        return ExportBackup(folders=folders, bookmarks=export_bookmarks)

    def export_html(self, *, folder_id: int | None = None) -> str:
        """Export bookmarks as a Netscape Bookmark HTML string.

        Args:
            folder_id (int | None): Optional folder id scope.

        Returns:
            str: Netscape HTML bookmark content.
        """
        backup = self.export_backup(folder_id=folder_id)
        return self.exporter.export_html(backup=backup)

    def import_backup(
        self,
        *,
        backup: ExportBackup,
        target_folder_id: int | None = None,
        skip_existing: bool = True,
        enqueue_thumbnails: bool = True,
    ) -> ImportResult:
        """Import bookmarks and folders from an ExportBackup container.

        Args:
            backup (ExportBackup): Structured backup data to import.
            target_folder_id (int | None): Target parent folder id.
            skip_existing (bool): Skip bookmark URLs already in library.
            enqueue_thumbnails (bool): Enqueue thumbnail capture jobs.

        Returns:
            ImportResult: Import execution metrics and warnings.

        Raises:
            NotFoundError: If target_folder_id does not exist.
        """
        if target_folder_id is not None:
            self.driver.get_folder(target_folder_id)

        existing_urls: set[str] = set()
        if skip_existing:
            all_bookmarks = self.driver.list_bookmarks()
            existing_urls = {b.url.strip().lower() for b in all_bookmarks}

        folders_created = 0
        bookmarks_created = 0
        bookmarks_skipped = 0
        known_tags_before = {t.name for t in self.driver.list_tags()}
        created_tag_names: set[str] = set()
        errors: list[str] = []

        def import_bookmark(
            bookmark_data: ExportBookmark, parent_id: int | None
        ) -> None:
            nonlocal bookmarks_created, bookmarks_skipped
            raw_url = bookmark_data.url.strip()
            parsed = urlparse(raw_url)
            if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
                bookmarks_skipped += 1
                errors.append(f"Skipped non-web URL: {raw_url[:60]}")
                return

            if skip_existing and raw_url.lower() in existing_urls:
                bookmarks_skipped += 1
                return

            title = (bookmark_data.title or raw_url).strip()[:512]
            if not title:
                title = raw_url[:512]
            description = (
                bookmark_data.description[:256] if bookmark_data.description else None
            )

            try:
                created = self.driver.create_bookmark(
                    payload=BookmarkCreate(
                        title=title,
                        url=raw_url,
                        description=description,
                        folder_id=parent_id,
                        tag_names=bookmark_data.tags,
                    )
                )
                existing_urls.add(raw_url.lower())
                bookmarks_created += 1
                for tag_name in bookmark_data.tags:
                    cleaned_tag = tag_name.strip()
                    if cleaned_tag and cleaned_tag not in known_tags_before:
                        created_tag_names.add(cleaned_tag)

                if enqueue_thumbnails:
                    enqueue_thumbnail_capture(
                        self.driver,
                        created.id,
                        self.settings,
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Failed to import bookmark url={}: {}",
                    raw_url,
                    exc,
                )
                errors.append(f"Error importing {raw_url[:60]}: {exc}")

        def import_folder(folder_data: ExportFolder, parent_id: int | None) -> None:
            nonlocal folders_created
            folder_name = folder_data.name.strip()[:255] or "Imported Folder"
            try:
                new_folder = self.driver.create_folder(
                    payload=FolderCreate(
                        name=folder_name,
                        parent_id=parent_id,
                        sort_order=folder_data.sort_order,
                    )
                )
                folders_created += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Failed to create folder name={}: {}",
                    folder_name,
                    exc,
                )
                errors.append(f"Error creating folder {folder_name}: {exc}")
                return

            for b in folder_data.bookmarks:
                import_bookmark(b, new_folder.id)

            for subfolder in folder_data.folders:
                import_folder(subfolder, new_folder.id)

        for folder in backup.folders:
            import_folder(folder, target_folder_id)

        for bookmark in backup.bookmarks:
            import_bookmark(bookmark, target_folder_id)

        logger.info(
            "Bookmark import complete: folders={} bookmarks={} skipped={} errors={}",
            folders_created,
            bookmarks_created,
            bookmarks_skipped,
            len(errors),
        )

        return ImportResult(
            folders_created=folders_created,
            bookmarks_created=bookmarks_created,
            bookmarks_skipped=bookmarks_skipped,
            tags_created=len(created_tag_names),
            errors=errors,
        )

    def import_text(
        self,
        *,
        text: str,
        target_folder_id: int | None = None,
        skip_existing: bool = True,
        enqueue_thumbnails: bool = True,
    ) -> ImportResult:
        """Parse raw text (JSON or Netscape HTML) and import into the library.

        Args:
            text (str): File content string.
            target_folder_id (int | None): Target parent folder id.
            skip_existing (bool): Skip bookmark URLs already in library.
            enqueue_thumbnails (bool): Enqueue thumbnail capture jobs.

        Returns:
            ImportResult: Import execution metrics and warnings.

        Raises:
            ValueError: If the text content is empty or unparseable.
            NotFoundError: If target_folder_id does not exist.
        """
        trimmed = text.strip()
        if not trimmed:
            raise ValueError("Import text content is empty")

        backup: ExportBackup | None = None

        if trimmed.startswith("{") or trimmed.startswith("["):
            try:
                parsed_json = json.loads(trimmed)
                if isinstance(parsed_json, dict):
                    if "backup" in parsed_json and isinstance(
                        parsed_json["backup"], dict
                    ):
                        backup = ExportBackup.model_validate(parsed_json["backup"])
                    else:
                        backup = ExportBackup.model_validate(parsed_json)
                elif isinstance(parsed_json, list):
                    bookmarks_list = [
                        ExportBookmark.model_validate(item) for item in parsed_json
                    ]
                    backup = ExportBackup(
                        folders=[],
                        bookmarks=bookmarks_list,
                    )
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "JSON validation failed, falling back to HTML parser: {}",
                    exc,
                )

        if backup is None:
            parser = NetscapeBookmarkParser()
            parser.feed(trimmed)
            backup = parser.build_backup()

        return self.import_backup(
            backup=backup,
            target_folder_id=target_folder_id,
            skip_existing=skip_existing,
            enqueue_thumbnails=enqueue_thumbnails,
        )
