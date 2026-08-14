"""Tests for Alembic schema upgrades on Oracle startup."""

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


def test_find_alembic_root_from_repo() -> None:
    """Discover alembic.ini from the repository layout."""
    root = find_alembic_root()
    assert (root / "alembic.ini").is_file()
    assert (root / "alembic" / "env.py").is_file()


def test_upgrade_schema_skips_memory() -> None:
    """Memory driver startups do not invoke Alembic."""
    settings = Settings(db_driver="memory")
    with patch("bald_bookmarks.db.migrate.command.upgrade") as upgrade:
        upgrade_schema(settings)
    upgrade.assert_not_called()


def test_upgrade_schema_runs_alembic_for_oracle(tmp_path: Path) -> None:
    """Oracle startups apply Alembic migrations to head."""
    (tmp_path / "alembic.ini").write_text("[alembic]\nscript_location = alembic\n")
    (tmp_path / "alembic").mkdir()
    settings = _oracle_settings()
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
    """Oracle startups fail fast when alembic.ini is missing."""
    settings = _oracle_settings()
    with pytest.raises(FileNotFoundError, match="alembic.ini"):
        upgrade_schema(settings, alembic_root=tmp_path)


def test_lifespan_runs_schema_upgrade(tmp_path: Path) -> None:
    """API lifespan applies schema upgrades before serving requests."""
    settings = Settings(
        db_driver="memory",
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


def test_description_varchar_migration_follows_initial() -> None:
    """Bookmark description is narrowed from CLOB to VARCHAR2(256)."""
    root = find_alembic_root()
    text = (root / "alembic" / "versions" / "0002_description_varchar.py").read_text()
    assert 'down_revision: str | None = "0001_initial"' in text
    assert "sa.String(length=256)" in text
    assert "SUBSTR(description, 1, 256)" in text
