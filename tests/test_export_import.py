"""Tests for bookmark backup, export, and import features."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from bald_bookmarks.db.sqlite.driver import SQLiteDriver
from bald_bookmarks.domain.bookmarks import BookmarkCreate
from bald_bookmarks.domain.export_import import (
    ExportBackup,
    ExportBookmark,
    ExportFolder,
    ExportFormat,
)
from bald_bookmarks.domain.folders import FolderCreate
from bald_bookmarks.services.export_import import (
    BookmarkBackupService,
    NetscapeBookmarkParser,
)
from tests.conftest import sqlite_settings


def test_netscape_html_parser_basic() -> None:
    """HTML parser extracts nested folders, bookmarks, tags, and notes."""
    html_sample = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
    <TITLE>Bookmarks</TITLE>
    <H1>Bookmarks</H1>
    <DL><p>
        <DT><H3 ADD_DATE="1670000000">Development</H3>
        <DL><p>
            <DT><A HREF="https://github.com" TAGS="git,code">GitHub</A>
            <DD>Where the world builds software
            <DT><H3 ADD_DATE="1670000002">Python</H3>
            <DL><p>
                <DT><A HREF="https://docs.python.org">Python Docs</A>
            </DL><p>
        </DL><p>
        <DT><A HREF="https://news.ycombinator.com">Hacker News</A>
        <DD>Tech news aggregator
    </DL><p>
    """
    parser = NetscapeBookmarkParser()
    parser.feed(html_sample)
    backup = parser.build_backup()

    assert len(backup.folders) == 1
    assert backup.folders[0].name == "Development"
    assert len(backup.folders[0].bookmarks) == 1
    github = backup.folders[0].bookmarks[0]
    assert github.title == "GitHub"
    assert github.url == "https://github.com"
    assert github.description == "Where the world builds software"
    assert github.tags == ["git", "code"]

    assert len(backup.folders[0].folders) == 1
    python_folder = backup.folders[0].folders[0]
    assert python_folder.name == "Python"
    assert len(python_folder.bookmarks) == 1
    assert python_folder.bookmarks[0].url == "https://docs.python.org"

    assert len(backup.bookmarks) == 1
    assert backup.bookmarks[0].title == "Hacker News"
    assert backup.bookmarks[0].url == "https://news.ycombinator.com"
    assert backup.bookmarks[0].description == "Tech news aggregator"


def test_export_backup_service(driver: SQLiteDriver, tmp_path: Path) -> None:
    """Backup service exports full library as structured model and HTML."""
    settings = sqlite_settings(tmp_path=tmp_path)
    service = BookmarkBackupService(driver=driver, settings=settings)

    work_folder = driver.create_folder(
        payload=FolderCreate(name="Work", parent_id=None, sort_order=0)
    )
    docs_folder = driver.create_folder(
        payload=FolderCreate(name="Docs", parent_id=work_folder.id, sort_order=1)
    )

    driver.create_bookmark(
        payload=BookmarkCreate(
            title="Work Portal",
            url="https://work.example.com",
            description="Company portal",
            folder_id=work_folder.id,
            tag_names=["internal", "work"],
        )
    )
    driver.create_bookmark(
        payload=BookmarkCreate(
            title="API Specs",
            url="https://specs.example.com",
            description=None,
            folder_id=docs_folder.id,
            tag_names=["api"],
        )
    )
    driver.create_bookmark(
        payload=BookmarkCreate(
            title="Search",
            url="https://search.example.com",
            description="Quick search",
            folder_id=None,
            tag_names=["utility"],
        )
    )

    backup = service.export_backup()
    assert len(backup.folders) == 1
    assert backup.folders[0].name == "Work"
    assert len(backup.folders[0].bookmarks) == 1
    assert backup.folders[0].bookmarks[0].title == "Work Portal"
    assert backup.folders[0].bookmarks[0].tags == ["internal", "work"]

    assert len(backup.folders[0].folders) == 1
    assert backup.folders[0].folders[0].name == "Docs"
    assert backup.folders[0].folders[0].bookmarks[0].title == "API Specs"

    assert len(backup.bookmarks) == 1
    assert backup.bookmarks[0].title == "Search"
    assert backup.bookmarks[0].tags == ["utility"]

    html_out = service.export_html()
    assert "<!DOCTYPE NETSCAPE-Bookmark-file-1>" in html_out
    assert "Work Portal" in html_out
    assert "https://work.example.com" in html_out
    assert "Company portal" in html_out
    assert "TAGS=" in html_out


def test_export_backup_scoped_folder(driver: SQLiteDriver, tmp_path: Path) -> None:
    """Exporting scoped to a folder only includes that subtree."""
    settings = sqlite_settings(tmp_path=tmp_path)
    service = BookmarkBackupService(driver=driver, settings=settings)

    f1 = driver.create_folder(payload=FolderCreate(name="F1"))
    f2 = driver.create_folder(payload=FolderCreate(name="F2"))
    driver.create_bookmark(
        payload=BookmarkCreate(title="B1", url="https://b1.com", folder_id=f1.id)
    )
    driver.create_bookmark(
        payload=BookmarkCreate(title="B2", url="https://b2.com", folder_id=f2.id)
    )

    scoped_backup = service.export_backup(folder_id=f1.id)
    assert len(scoped_backup.folders) == 1
    assert scoped_backup.folders[0].name == "F1"
    assert len(scoped_backup.folders[0].bookmarks) == 1
    assert scoped_backup.folders[0].bookmarks[0].title == "B1"
    assert len(scoped_backup.bookmarks) == 0


def test_import_backup_service(driver: SQLiteDriver, tmp_path: Path) -> None:
    """Importing backup restores folders, bookmarks, and tags."""
    settings = sqlite_settings(tmp_path=tmp_path)
    service = BookmarkBackupService(driver=driver, settings=settings)

    backup = ExportBackup(
        folders=[
            ExportFolder(
                name="Imported Tree",
                sort_order=0,
                folders=[
                    ExportFolder(
                        name="Sub Tree",
                        sort_order=0,
                        folders=[],
                        bookmarks=[
                            ExportBookmark(
                                title="Sub Bookmark",
                                url="https://sub.example.com",
                                description="Nested link",
                                tags=["subtag"],
                            )
                        ],
                    )
                ],
                bookmarks=[
                    ExportBookmark(
                        title="Tree Bookmark",
                        url="https://tree.example.com",
                        description=None,
                        tags=["treetag"],
                    )
                ],
            )
        ],
        bookmarks=[
            ExportBookmark(
                title="Unfiled Imported",
                url="https://unfiled.example.com",
                description="Unfiled link",
                tags=["root"],
            )
        ],
    )

    result = service.import_backup(
        backup=backup,
        skip_existing=True,
        enqueue_thumbnails=False,
    )
    assert result.folders_created == 2
    assert result.bookmarks_created == 3
    assert result.bookmarks_skipped == 0
    assert result.tags_created == 3
    assert len(result.errors) == 0

    tree = driver.get_folder_tree()
    assert len(tree) == 1
    assert tree[0].name == "Imported Tree"
    assert len(tree[0].children) == 1
    assert tree[0].children[0].name == "Sub Tree"

    all_bookmarks = driver.list_bookmarks()
    urls = {b.url for b in all_bookmarks}
    assert "https://sub.example.com" in urls
    assert "https://tree.example.com" in urls
    assert "https://unfiled.example.com" in urls


def test_import_duplicate_skipping(driver: SQLiteDriver, tmp_path: Path) -> None:
    """Duplicate URLs are skipped when skip_existing is True."""
    settings = sqlite_settings(tmp_path=tmp_path)
    service = BookmarkBackupService(driver=driver, settings=settings)

    driver.create_bookmark(
        payload=BookmarkCreate(
            title="Existing",
            url="https://dup.example.com",
            description=None,
            folder_id=None,
        )
    )

    backup = ExportBackup(
        folders=[],
        bookmarks=[
            ExportBookmark(
                title="New Dup",
                url="https://dup.example.com",
                description="Duplicate",
                tags=[],
            ),
            ExportBookmark(
                title="Unique",
                url="https://unique.example.com",
                description=None,
                tags=[],
            ),
        ],
    )

    result = service.import_backup(
        backup=backup,
        skip_existing=True,
        enqueue_thumbnails=False,
    )
    assert result.bookmarks_created == 1
    assert result.bookmarks_skipped == 1


def test_import_text_html_and_target_folder(
    driver: SQLiteDriver, tmp_path: Path
) -> None:
    """HTML import correctly places items inside specified target folder."""
    settings = sqlite_settings(tmp_path=tmp_path)
    service = BookmarkBackupService(driver=driver, settings=settings)

    target_folder = driver.create_folder(payload=FolderCreate(name="Target"))

    html_content = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
    <TITLE>Bookmarks</TITLE>
    <H1>Bookmarks</H1>
    <DL><p>
        <DT><H3>Imported Subfolder</H3>
        <DL><p>
            <DT><A HREF="https://html-child.example.com">Child Link</A>
        </DL><p>
        <DT><A HREF="https://html-root.example.com">Root Link</A>
    </DL><p>
    """

    result = service.import_text(
        text=html_content,
        target_folder_id=target_folder.id,
        skip_existing=True,
        enqueue_thumbnails=False,
    )

    assert result.folders_created == 1
    assert result.bookmarks_created == 2

    children = driver.list_folder_children(parent_id=target_folder.id)
    assert len(children) == 1
    assert children[0].name == "Imported Subfolder"

    target_bookmarks = driver.list_bookmarks(folder_id=target_folder.id)
    assert len(target_bookmarks) == 1
    assert target_bookmarks[0].url == "https://html-root.example.com"


def test_api_export_json_and_html(client: TestClient) -> None:
    """GET /api/bookmarks/export returns JSON and HTML attachments."""
    f = client.post(
        url="/api/folders",
        json={"name": "Dev", "sort_order": 0},
    ).json()
    client.post(
        url="/api/bookmarks",
        json={
            "title": "GitHub",
            "url": "https://github.com",
            "description": "Code host",
            "folder_id": f["id"],
            "tag_names": ["git", "code"],
        },
    )

    resp_json = client.get(
        url="/api/bookmarks/export",
        params={"format": ExportFormat.JSON.value},
    )
    assert resp_json.status_code == 200
    assert "application/json" in resp_json.headers["content-type"]
    assert "attachment;" in resp_json.headers["content-disposition"]
    data = resp_json.json()
    assert "folders" in data
    assert data["folders"][0]["name"] == "Dev"
    assert data["folders"][0]["bookmarks"][0]["title"] == "GitHub"

    resp_html = client.get(
        url="/api/bookmarks/export",
        params={"format": ExportFormat.HTML.value},
    )
    assert resp_html.status_code == 200
    assert "text/html" in resp_html.headers["content-type"]
    assert "attachment;" in resp_html.headers["content-disposition"]
    assert "<!DOCTYPE NETSCAPE-Bookmark-file-1>" in resp_html.text
    assert "GitHub" in resp_html.text


def test_api_import_json_and_html(client: TestClient) -> None:
    """POST /api/bookmarks/import handles JSON and HTML payloads."""
    backup_data = {
        "version": 1,
        "folders": [
            {
                "name": "API Folder",
                "sort_order": 0,
                "folders": [],
                "bookmarks": [
                    {
                        "title": "API Link",
                        "url": "https://api-link.example.com",
                        "description": "JSON import test",
                        "tags": ["test"],
                    }
                ],
            }
        ],
        "bookmarks": [],
    }

    import_resp = client.post(
        url="/api/bookmarks/import",
        content=json.dumps(obj=backup_data),
        headers={"Content-Type": "application/json"},
    )
    assert import_resp.status_code == 200
    result = import_resp.json()
    assert result["folders_created"] == 1
    assert result["bookmarks_created"] == 1
    assert result["bookmarks_skipped"] == 0

    html_payload = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
    <DL><p>
        <DT><A HREF="https://html-import.example.com">HTML Bookmark</A>
    </DL><p>
    """
    html_resp = client.post(
        url="/api/bookmarks/import",
        content=html_payload,
        headers={"Content-Type": "text/html"},
    )
    assert html_resp.status_code == 200
    html_result = html_resp.json()
    assert html_result["bookmarks_created"] == 1

    empty_resp = client.post(
        url="/api/bookmarks/import",
        content="",
    )
    assert empty_resp.status_code == 400

    missing_folder_resp = client.post(
        url="/api/bookmarks/import",
        params={"target_folder_id": 99999},
        content=html_payload,
    )
    assert missing_folder_resp.status_code == 404
