"""Dialect-aware helpers for Alembic migrations."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME as MYSQL_DATETIME


def server_timestamp_now() -> sa.TextClause:
    """Return a server-side timestamp default for the current dialect.

    Returns:
        sa.TextClause: SYSTIMESTAMP, NOW(), CURRENT_TIMESTAMP(6), or CURRENT_TIMESTAMP.
    """
    name = op.get_bind().dialect.name
    if name == "oracle":
        return sa.text("SYSTIMESTAMP")
    if name == "postgresql":
        return sa.text("NOW()")
    if name == "mysql":
        return sa.text("CURRENT_TIMESTAMP(6)")
    return sa.text("CURRENT_TIMESTAMP")


def timestamp_type() -> sa.types.TypeEngine:
    """Return a datetime column type that matches server_timestamp_now.

    MySQL rejects DATETIME DEFAULT CURRENT_TIMESTAMP(6) unless the column
    itself is DATETIME(6).

    Returns:
        sa.types.TypeEngine: DATETIME(6) on MySQL, timezone-aware DateTime otherwise.
    """
    name = op.get_bind().dialect.name
    if name == "mysql":
        return MYSQL_DATETIME(fsp=6)
    return sa.DateTime(timezone=True)


def integer_pk() -> sa.Column:
    """Return an integer identity or autoincrement primary key column.

    Returns:
        sa.Column: Dialect-appropriate id column.
    """
    name = op.get_bind().dialect.name
    if name in {"mysql", "sqlite"}:
        return sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True)
    return sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True)
