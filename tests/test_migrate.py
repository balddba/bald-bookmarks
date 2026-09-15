"""Tests for Alembic schema upgrades on relational driver startup."""

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from bald_bookmarks.config import Settings
from bald_bookmarks.db.migrate import alembic_config, find_alembic_root, upgrade_schema
from bald_bookmarks.main import create_app


def _oracle_settings() -> Settings:
    """Build Oracle settings that do not require a live database.

    Returns:
        Settings: Validated Oracle driver settings.
    """
    return Settings(
        db_driver="oracle",
        oracle_user="bookmarks",
        oracle_password="secret",
        oracle_dsn="localhost:1521/xepdb1",
    )


def _postgres_settings() -> Settings:
    """Build PostgreSQL settings that do not require a live database.

    Returns:
        Settings: Validated PostgreSQL driver settings.
    """
    return Settings(
        db_driver="postgres",
        postgres_host="localhost",
        postgres_user="bookmarks",
        postgres_password="secret",
        postgres_database="bald_bookmarks",
    )


def _mysql_settings() -> Settings:
    """Build MySQL settings that do not require a live database.

    Returns:
        Settings: Validated MySQL driver settings.
    """
    return Settings(
        db_driver="mysql",
        mysql_host="localhost",
        mysql_user="bookmarks",
        mysql_password="secret",
        mysql_database="bald_bookmarks",
    )


def _sqlite_settings() -> Settings:
    """Build SQLite settings that do not require a live database.

    Returns:
        Settings: Validated SQLite driver settings.
    """
    return Settings(db_driver="sqlite")


def test_find_alembic_root_from_repo() -> None:
    """Discover alembic.ini from the repository layout."""
    root = find_alembic_root()
    assert (root / "alembic.ini").is_file()
    assert (root / "alembic" / "env.py").is_file()


def test_upgrade_schema_runs_alembic_for_sqlite(tmp_path: Path) -> None:
    """SQLite startups apply Alembic migrations to a local file.

    Args:
        tmp_path (Path): Pytest temporary directory.
    """
    settings = Settings(
        db_driver="sqlite",
        sqlite_path=tmp_path / "bookmarks.db",
    )
    upgrade_schema(settings)
    assert (tmp_path / "bookmarks.db").is_file()


def test_upgrade_schema_creates_nested_sqlite_dir(tmp_path: Path) -> None:
    """SQLite migrations create missing parent directories automatically.

    Args:
        tmp_path (Path): Pytest temporary directory.
    """
    db_file = tmp_path / "nested" / "db" / "bookmarks.db"
    assert not db_file.parent.exists()
    settings = Settings(
        db_driver="sqlite",
        sqlite_path=db_file,
    )
    upgrade_schema(settings)
    assert db_file.is_file()


@pytest.mark.parametrize(
    "settings",
    [_oracle_settings(), _postgres_settings(), _mysql_settings(), _sqlite_settings()],
    ids=["oracle", "postgres", "mysql", "sqlite"],
)
def test_upgrade_schema_runs_alembic_for_relational_drivers(
    tmp_path: Path,
    settings: Settings,
) -> None:
    """Relational driver startups apply Alembic migrations to head.

    Args:
        tmp_path (Path): Pytest temporary directory.
        settings (Settings): Driver configuration.
    """
    (tmp_path / "alembic.ini").write_text("[alembic]\nscript_location = alembic\n")
    (tmp_path / "alembic").mkdir()
    with patch("bald_bookmarks.db.migrate.command.upgrade") as upgrade:
        upgrade_schema(settings, alembic_root=tmp_path)
    upgrade.assert_called_once()
    config = upgrade.call_args.args[0]
    assert upgrade.call_args.args[1] == "head"
    assert config.get_main_option("script_location") == str(tmp_path / "alembic")


def test_alembic_config_points_at_script_location() -> None:
    """Alembic config uses the repository script directory."""
    root = find_alembic_root()
    config = alembic_config(root)
    assert config.get_main_option("script_location") == str(root / "alembic")


def test_upgrade_schema_requires_alembic_ini(tmp_path: Path) -> None:
    """Relational startups fail fast when alembic.ini is missing.

    Args:
        tmp_path (Path): Pytest temporary directory.
    """
    settings = _oracle_settings()
    with pytest.raises(FileNotFoundError, match="alembic.ini"):
        upgrade_schema(settings, alembic_root=tmp_path)


def test_lifespan_runs_schema_upgrade(tmp_path: Path) -> None:
    """API lifespan applies schema upgrades before serving requests.

    Args:
        tmp_path (Path): Pytest temporary directory.
    """
    settings = Settings(
        db_driver="sqlite",
        sqlite_path=tmp_path / "bookmarks.db",
        media_root=tmp_path / "media",
        job_poll_seconds=0.05,
    )
    with patch("bald_bookmarks.main.upgrade_schema") as upgrade:
        app = create_app(settings)
        with TestClient(app) as client:
            assert client.get("/api/health").status_code == 200
        upgrade.assert_called_once_with(settings)


def test_initial_migration_uses_unique_constraint_for_tag_name() -> None:
    """Oracle rejects a second index on tags.name once uq_tags_name exists."""
    root = find_alembic_root()
    text = (root / "alembic" / "versions" / "0001_initial.py").read_text()
    assert "uq_tags_name" in text
    assert "ix_tags_name" not in text
    assert "sa.Clob(" not in text
    assert "sa.Text()" in text
    assert "server_timestamp_now" in text
    assert "integer_pk" in text
    assert "SYSTIMESTAMP" not in text


def test_description_varchar_migration_follows_initial() -> None:
    """Bookmark description is narrowed from CLOB to VARCHAR2(256)."""
    root = find_alembic_root()
    text = (root / "alembic" / "versions" / "0002_description_varchar.py").read_text()
    assert 'down_revision: str | None = "0001_initial"' in text
    assert "sa.String(length=256)" in text
    assert "SUBSTR(description, 1, 256)" in text
