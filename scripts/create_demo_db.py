#!/usr/bin/env python3
"""Script to generate a seed demo.db SQLite database with example sites."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from loguru import logger

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "backend"))

from bald_bookmarks.config import Settings  # noqa: E402
from bald_bookmarks.db.migrate import upgrade_schema  # noqa: E402
from bald_bookmarks.db.sqlite.driver import SQLiteDriver  # noqa: E402
from bald_bookmarks.domain.bookmarks import BookmarkCreate  # noqa: E402
from bald_bookmarks.domain.folders import FolderCreate  # noqa: E402


def seed_demo_database(db_path: Path) -> None:
    """Create and seed a demo SQLite database at the specified path.

    Applies Alembic migrations to head and inserts sample folders, tags, and bookmarks.

    Args:
        db_path (Path): Path where demo.db should be created.
    """
    db_path = db_path.resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    settings = Settings(db_driver="sqlite", sqlite_path=db_path)
    logger.info("Applying Alembic migrations to {}", db_path)
    upgrade_schema(settings)

    driver = SQLiteDriver(settings)
    driver.connect()

    try:
        logger.info("Seeding folders...")
        dev_folder = driver.create_folder(
            FolderCreate(name="Development", sort_order=1)
        )
        py_folder = driver.create_folder(
            FolderCreate(
                name="Python & FastAPI",
                parent_id=dev_folder.id,
                sort_order=1,
            )
        )
        fe_folder = driver.create_folder(
            FolderCreate(
                name="Frontend & UI",
                parent_id=dev_folder.id,
                sort_order=2,
            )
        )
        db_folder = driver.create_folder(
            FolderCreate(
                name="Databases & Storage",
                parent_id=dev_folder.id,
                sort_order=3,
            )
        )

        news_folder = driver.create_folder(
            FolderCreate(name="News & Articles", sort_order=2)
        )
        tools_folder = driver.create_folder(
            FolderCreate(name="Developer Tools", sort_order=3)
        )
        docs_folder = driver.create_folder(
            FolderCreate(name="Documentation", sort_order=4)
        )

        bookmarks_data = [
            # Python & FastAPI
            BookmarkCreate(
                title="Python Documentation",
                url="https://docs.python.org/3/",
                description=(
                    "Official Python 3 language documentation, standard library "
                    "reference, and tutorials."
                ),
                folder_id=py_folder.id,
                tag_names=["python", "docs"],
            ),
            BookmarkCreate(
                title="FastAPI Framework",
                url="https://fastapi.tiangolo.com/",
                description=(
                    "High-performance Python web framework for building APIs "
                    "based on standard Python type hints."
                ),
                folder_id=py_folder.id,
                tag_names=["python", "fastapi", "docs"],
            ),
            BookmarkCreate(
                title="Pydantic",
                url="https://docs.pydantic.dev/",
                description=(
                    "Data validation using Python type hints with fast Rust-powered "
                    "parsing."
                ),
                folder_id=py_folder.id,
                tag_names=["python", "docs"],
            ),
            # Frontend & UI
            BookmarkCreate(
                title="React Documentation",
                url="https://react.dev/",
                description="The library for web and native user interfaces.",
                folder_id=fe_folder.id,
                tag_names=["react", "frontend", "docs", "open-source"],
            ),
            BookmarkCreate(
                title="Tailwind CSS",
                url="https://tailwindcss.com/",
                description="Utility-first CSS framework for rapid UI development.",
                folder_id=fe_folder.id,
                tag_names=["tailwind", "css", "design"],
            ),
            BookmarkCreate(
                title="HeroUI Components",
                url="https://www.heroui.com/",
                description=(
                    "Beautiful, fast, and accessible React UI library built on top "
                    "of Tailwind CSS."
                ),
                folder_id=fe_folder.id,
                tag_names=["react", "tailwind", "design"],
            ),
            # Databases & Storage
            BookmarkCreate(
                title="SQLite Documentation",
                url="https://www.sqlite.org/",
                description=(
                    "Small, fast, self-contained, high-reliability, full-featured "
                    "SQL database engine."
                ),
                folder_id=db_folder.id,
                tag_names=["sqlite", "database", "docs", "open-source"],
            ),
            BookmarkCreate(
                title="PostgreSQL Database",
                url="https://www.postgresql.org/",
                description="Powerful, open source object-relational database system.",
                folder_id=db_folder.id,
                tag_names=["postgres", "database", "docs", "open-source"],
            ),
            BookmarkCreate(
                title="Oracle Database Documentation",
                url="https://docs.oracle.com/en/database/",
                description=(
                    "Comprehensive guides, API reference, and SQL manuals for "
                    "Oracle Database."
                ),
                folder_id=db_folder.id,
                tag_names=["oracle", "database", "docs"],
            ),
            BookmarkCreate(
                title="MySQL Reference Manual",
                url="https://dev.mysql.com/doc/",
                description=(
                    "Official documentation for MySQL Server, MySQL Shell, "
                    "and connectors."
                ),
                folder_id=db_folder.id,
                tag_names=["mysql", "database", "docs"],
            ),
            BookmarkCreate(
                title="Alembic Migrations",
                url="https://alembic.sqlalchemy.org/",
                description=(
                    "Lightweight database migration tool for usage with SQLAlchemy "
                    "and relational databases."
                ),
                folder_id=db_folder.id,
                tag_names=["python", "database", "alembic"],
            ),
            # News & Articles
            BookmarkCreate(
                title="Hacker News",
                url="https://news.ycombinator.com/",
                description=(
                    "Social news website focusing on computer science, technology, "
                    "and entrepreneurship."
                ),
                folder_id=news_folder.id,
                tag_names=["news", "tech"],
            ),
            BookmarkCreate(
                title="Lobsters Tech Community",
                url="https://lobste.rs/",
                description=(
                    "Computing-focused link aggregation community with open invitation "
                    "tree and tag filtering."
                ),
                folder_id=news_folder.id,
                tag_names=["news", "tech"],
            ),
            # Developer Tools
            BookmarkCreate(
                title="GitHub",
                url="https://github.com/",
                description=(
                    "Complete developer platform to build, scale, and deliver "
                    "secure software."
                ),
                folder_id=tools_folder.id,
                tag_names=["tools", "git", "open-source"],
            ),
            # Documentation
            BookmarkCreate(
                title="MDN Web Docs",
                url="https://developer.mozilla.org/",
                description=(
                    "Documenting web technologies including HTML, CSS, JavaScript, "
                    "and Web APIs."
                ),
                folder_id=docs_folder.id,
                tag_names=["docs", "web", "frontend"],
            ),
        ]

        logger.info("Seeding bookmarks...")
        for bm in bookmarks_data:
            driver.create_bookmark(bm)

        folders_list = driver.get_folder_tree()
        tags_list = driver.list_tags()
        bookmarks_list = driver.list_bookmarks()
        logger.info(
            "Demo database successfully seeded at {path}: "
            "{f_count} root folders, {t_count} tags, {b_count} bookmarks",
            path=db_path,
            f_count=len(folders_list),
            t_count=len(tags_list),
            b_count=len(bookmarks_list),
        )
    finally:
        driver.close()


def main() -> int:
    """Parse CLI arguments and seed demo database.

    Returns:
        int: Process exit code.
    """
    parser = argparse.ArgumentParser(
        description="Generate seed demo.db SQLite database."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("demo.db"),
        help="Path for output demo database file (default: demo.db)",
    )
    args = parser.parse_args()

    target_path = args.output
    seed_demo_database(target_path)

    data_dir_copy = REPO_ROOT / "backend/bald_bookmarks/data/demo.db"
    if target_path.resolve() != data_dir_copy.resolve():
        data_dir_copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target_path, data_dir_copy)
        logger.info("Copied demo database to {}", data_dir_copy)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
