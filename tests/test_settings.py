"""Settings parsing tests."""

import pytest

from bald_bookmarks.config import Settings


def test_cors_origins_comma_separated(monkeypatch) -> None:
    """Comma-separated CORS_ORIGINS env values parse into a list."""
    monkeypatch.setenv("DB_DRIVER", "memory")
    monkeypatch.setenv(
        "CORS_ORIGINS",
        "http://localhost:8080,http://127.0.0.1:8080",
    )
    settings = Settings()
    assert settings.cors_origins == [
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    ]


def test_cors_origins_json_list(monkeypatch) -> None:
    """JSON-array CORS_ORIGINS env values still parse."""
    monkeypatch.setenv("DB_DRIVER", "memory")
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
        db_driver="memory",
        oracle_user=None,
        oracle_password=None,
        oracle_dsn=None,
    )
    with pytest.raises(ValueError, match="Oracle connection settings"):
        settings.oracle_connect_args()
