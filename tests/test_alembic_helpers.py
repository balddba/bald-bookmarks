"""Unit tests for Alembic dialect helpers."""

from unittest.mock import MagicMock, patch

import sqlalchemy as sa
from sqlalchemy.dialects.mysql import DATETIME as MYSQL_DATETIME

from bald_bookmarks.db.alembic_helpers import (
    integer_pk,
    server_timestamp_now,
    timestamp_type,
)


def _bind(dialect_name: str) -> MagicMock:
    """Build a fake Alembic bind with a dialect name.

    Args:
        dialect_name (str): SQLAlchemy dialect name.

    Returns:
        MagicMock: Object with dialect.name set.
    """
    bind = MagicMock()
    bind.dialect.name = dialect_name
    return bind


def test_server_timestamp_now_oracle() -> None:
    """Oracle migrations keep SYSTIMESTAMP defaults."""
    with patch(
        "bald_bookmarks.db.alembic_helpers.op.get_bind",
        return_value=_bind("oracle"),
    ):
        assert str(server_timestamp_now()) == "SYSTIMESTAMP"


def test_server_timestamp_now_postgres() -> None:
    """PostgreSQL migrations use NOW()."""
    with patch(
        "bald_bookmarks.db.alembic_helpers.op.get_bind",
        return_value=_bind("postgresql"),
    ):
        assert str(server_timestamp_now()) == "NOW()"


def test_server_timestamp_now_mysql() -> None:
    """MySQL migrations use CURRENT_TIMESTAMP(6)."""
    with patch(
        "bald_bookmarks.db.alembic_helpers.op.get_bind",
        return_value=_bind("mysql"),
    ):
        assert str(server_timestamp_now()) == "CURRENT_TIMESTAMP(6)"


def test_server_timestamp_now_sqlite() -> None:
    """SQLite migrations use CURRENT_TIMESTAMP."""
    with patch(
        "bald_bookmarks.db.alembic_helpers.op.get_bind",
        return_value=_bind("sqlite"),
    ):
        assert str(server_timestamp_now()) == "CURRENT_TIMESTAMP"


def test_timestamp_type_mysql_uses_datetime_fsp() -> None:
    """MySQL timestamp columns use DATETIME(6) to match CURRENT_TIMESTAMP(6)."""
    with patch(
        "bald_bookmarks.db.alembic_helpers.op.get_bind",
        return_value=_bind("mysql"),
    ):
        column_type = timestamp_type()
    assert isinstance(column_type, MYSQL_DATETIME)
    assert column_type.fsp == 6


def test_timestamp_type_postgres_uses_timezone_datetime() -> None:
    """PostgreSQL timestamp columns stay timezone-aware DateTime."""
    with patch(
        "bald_bookmarks.db.alembic_helpers.op.get_bind",
        return_value=_bind("postgresql"),
    ):
        column_type = timestamp_type()
    assert isinstance(column_type, sa.DateTime)
    assert column_type.timezone is True


def test_integer_pk_sqlite_uses_autoincrement() -> None:
    """SQLite primary keys use AUTOINCREMENT instead of Identity."""
    with patch(
        "bald_bookmarks.db.alembic_helpers.op.get_bind",
        return_value=_bind("sqlite"),
    ):
        column = integer_pk()
    assert column.autoincrement is True
    assert column.identity is None


def test_integer_pk_mysql_uses_autoincrement() -> None:
    """MySQL primary keys use AUTO_INCREMENT instead of Identity."""
    with patch(
        "bald_bookmarks.db.alembic_helpers.op.get_bind",
        return_value=_bind("mysql"),
    ):
        column = integer_pk()
    assert column.autoincrement is True
    assert column.identity is None


def test_integer_pk_postgres_uses_identity() -> None:
    """PostgreSQL primary keys use Identity."""
    with patch(
        "bald_bookmarks.db.alembic_helpers.op.get_bind",
        return_value=_bind("postgresql"),
    ):
        column = integer_pk()
    assert column.identity is not None
