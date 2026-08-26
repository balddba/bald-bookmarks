"""Tests for the demo database generation script and demo.db content."""

from __future__ import annotations

from pathlib import Path

from scripts.create_demo_db import seed_demo_database

from bald_bookmarks.config import Settings
from bald_bookmarks.db.sqlite.driver import SQLiteDriver


def test_seed_demo_database(tmp_path: Path) -> None:
    """Verify that seed_demo_database creates a valid SQLite database.

    Args:
        tmp_path (Path): Pytest temporary path fixture.
    """
    db_file = tmp_path / "test_demo.db"
    seed_demo_database(db_file)

    assert db_file.is_file()

    settings = Settings(db_driver="sqlite", sqlite_path=db_file)
    driver = SQLiteDriver(settings)
    driver.connect()

    try:
        assert driver.alembic_revision() == "0002_description_varchar"

        tree = driver.get_folder_tree()
        root_names = {node.name for node in tree}
        assert "Development" in root_names
        assert "News & Articles" in root_names
        assert "Developer Tools" in root_names
        assert "Documentation" in root_names

        dev_node = next(node for node in tree if node.name == "Development")
        child_names = {child.name for child in dev_node.children}
        assert "Python & FastAPI" in child_names
        assert "Frontend & UI" in child_names
        assert "Databases & Storage" in child_names

        bookmarks = driver.list_bookmarks()
        assert len(bookmarks) == 15

        titles = {b.title for b in bookmarks}
        assert "Python Documentation" in titles
        assert "FastAPI Framework" in titles
        assert "React Documentation" in titles
        assert "SQLite Documentation" in titles
        assert "Hacker News" in titles

        tags = driver.list_tags()
        tag_names = {t.name for t in tags}
        assert "python" in tag_names
        assert "fastapi" in tag_names
        assert "react" in tag_names
        assert "sqlite" in tag_names
    finally:
        driver.close()
