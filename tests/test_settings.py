"""Settings parsing tests."""

from pathlib import Path

import pytest

from bald_bookmarks.config import Settings


def test_cors_origins_comma_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    """Comma-separated CORS_ORIGINS env values parse into a list.

    Args:
        monkeypatch (pytest.MonkeyPatch): Pytest monkeypatch fixture.
    """
    monkeypatch.setenv("DB_DRIVER", "sqlite")
    monkeypatch.setenv(
        "CORS_ORIGINS",
        "http://localhost:8080,http://127.0.0.1:8080",
    )
    settings = Settings()
    assert settings.cors_origins == [
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    ]


def test_cors_origins_json_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """JSON-array CORS_ORIGINS env values still parse.

    Args:
        monkeypatch (pytest.MonkeyPatch): Pytest monkeypatch fixture.
    """
    monkeypatch.setenv("DB_DRIVER", "sqlite")
    monkeypatch.setenv(
        "CORS_ORIGINS",
        '["http://localhost:5173"]',
    )
    settings = Settings()
    assert settings.cors_origins == ["http://localhost:5173"]


def test_sqlalchemy_url_uses_service_name_for_easy_connect() -> None:
    """Easy Connect DSNs are emitted as service_name, not a SID path."""
    settings = Settings(
        db_driver="oracle",
        oracle_user="bookmarks",
        oracle_password="secret",
        oracle_dsn="db.example.net:1521/lab",
    )
    assert settings.sqlalchemy_url == (
        "oracle+oracledb://bookmarks:secret@db.example.net:1521/?service_name=lab"
    )
    assert settings.oracle_connect_args() == {
        "user": "bookmarks",
        "password": "secret",
        "dsn": "db.example.net:1521/lab",
    }


def test_sqlalchemy_url_encodes_credentials() -> None:
    """Special characters in Oracle credentials are URL-encoded."""
    settings = Settings(
        db_driver="oracle",
        oracle_user="book marks",
        oracle_password="p@ss/word",
        oracle_dsn="localhost:1521/xepdb1",
    )
    assert settings.sqlalchemy_url == (
        "oracle+oracledb://book+marks:p%40ss%2Fword@localhost:1521/?service_name=xepdb1"
    )


def test_sqlalchemy_url_requires_oracle_fields() -> None:
    """Alembic URL construction fails fast without Oracle settings."""
    settings = Settings(
        db_driver="sqlite",
        oracle_user=None,
        oracle_password=None,
        oracle_dsn=None,
    )
    with pytest.raises(ValueError, match="Oracle connection settings"):
        settings.oracle_connect_args()


def test_postgres_settings_required() -> None:
    """PostgreSQL driver construction fails without connection fields."""
    with pytest.raises(ValueError, match="PostgreSQL driver requires settings"):
        Settings(db_driver="postgres")


def test_mysql_settings_required() -> None:
    """MySQL driver construction fails without connection fields."""
    with pytest.raises(ValueError, match="MySQL driver requires settings"):
        Settings(db_driver="mysql")


def test_postgres_sqlalchemy_url_encodes_credentials() -> None:
    """Special characters in PostgreSQL credentials are URL-encoded."""
    settings = Settings(
        db_driver="postgres",
        postgres_host="db.example.net",
        postgres_port=5433,
        postgres_user="book marks",
        postgres_password="p@ss/word",
        postgres_database="bald bookmarks",
    )
    assert settings.sqlalchemy_url == (
        "postgresql+psycopg://book+marks:p%40ss%2Fword@db.example.net:5433/"
        "bald+bookmarks"
    )


def test_mysql_sqlalchemy_url_encodes_credentials() -> None:
    """Special characters in MySQL credentials are URL-encoded."""
    settings = Settings(
        db_driver="mysql",
        mysql_host="db.example.net",
        mysql_port=3307,
        mysql_user="book marks",
        mysql_password="p@ss/word",
        mysql_database="bald bookmarks",
    )
    assert settings.sqlalchemy_url == (
        "mysql+mysqlconnector://book+marks:p%40ss%2Fword@db.example.net:3307/"
        "bald+bookmarks?charset=utf8mb4"
    )


def test_sqlite_sqlalchemy_url_uses_absolute_path(tmp_path: Path) -> None:
    """SQLite Alembic URLs use an absolute filesystem path.

    Args:
        tmp_path (Path): Pytest temporary directory.
    """
    db_path = tmp_path / "bookmarks.db"
    settings = Settings(db_driver="sqlite", sqlite_path=db_path)
    assert settings.sqlalchemy_url == f"sqlite+pysqlite:///{db_path.as_posix()}"


def test_normalized_driver_maps_postgresql() -> None:
    """postgresql is normalized to postgres."""
    settings = Settings(
        db_driver="postgresql",
        postgres_host="localhost",
        postgres_user="bookmarks",
        postgres_password="secret",
        postgres_database="bald_bookmarks",
    )
    assert settings.normalized_driver == "postgres"
