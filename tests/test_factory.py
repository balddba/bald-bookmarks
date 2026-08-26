"""Unit tests for the database driver factory."""

import pytest

from bald_bookmarks.config import Settings
from bald_bookmarks.db.factory import create_driver
from bald_bookmarks.db.mysql.driver import MySQLDriver
from bald_bookmarks.db.oracle.driver import OracleDriver
from bald_bookmarks.db.postgres.driver import PostgresDriver
from bald_bookmarks.db.sqlite.driver import SQLiteDriver


def test_create_driver_sqlite() -> None:
    """SQLite driver is constructed from SQLite settings."""
    driver = create_driver(Settings(db_driver="sqlite"))
    assert isinstance(driver, SQLiteDriver)


def test_create_driver_oracle() -> None:
    """Oracle driver is constructed from Oracle settings."""
    driver = create_driver(
        Settings(
            db_driver="oracle",
            oracle_user="bookmarks",
            oracle_password="secret",
            oracle_dsn="localhost:1521/lab",
        )
    )
    assert isinstance(driver, OracleDriver)


def test_create_driver_postgres() -> None:
    """PostgreSQL driver is constructed from PostgreSQL settings."""
    driver = create_driver(
        Settings(
            db_driver="postgres",
            postgres_host="localhost",
            postgres_user="bookmarks",
            postgres_password="secret",
            postgres_database="bald_bookmarks",
        )
    )
    assert isinstance(driver, PostgresDriver)


def test_create_driver_postgresql_alias() -> None:
    """postgresql is accepted as an alias for postgres."""
    driver = create_driver(
        Settings(
            db_driver="postgresql",
            postgres_host="localhost",
            postgres_user="bookmarks",
            postgres_password="secret",
            postgres_database="bald_bookmarks",
        )
    )
    assert isinstance(driver, PostgresDriver)


def test_create_driver_mysql() -> None:
    """MySQL driver is constructed from MySQL settings."""
    driver = create_driver(
        Settings(
            db_driver="mysql",
            mysql_host="localhost",
            mysql_user="bookmarks",
            mysql_password="secret",
            mysql_database="bald_bookmarks",
        )
    )
    assert isinstance(driver, MySQLDriver)


def test_create_driver_unsupported() -> None:
    """Unknown driver names fail fast."""
    with pytest.raises(ValueError, match="Unsupported db_driver"):
        create_driver(Settings(db_driver="redis"))
