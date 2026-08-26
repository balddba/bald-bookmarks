"""Database driver factory."""

from bald_bookmarks.config import Settings
from bald_bookmarks.db.abc import DatabaseDriver


def create_driver(settings: Settings) -> DatabaseDriver:
    """Create a DatabaseDriver from settings.

    Args:
        settings (Settings): Application settings.

    Returns:
        DatabaseDriver: Concrete driver instance (not yet connected).

    Raises:
        ValueError: If db_driver is unsupported.
    """
    driver_name = settings.normalized_driver
    if driver_name == "sqlite":
        from bald_bookmarks.db.sqlite.driver import SQLiteDriver

        return SQLiteDriver(settings)
    if driver_name == "oracle":
        from bald_bookmarks.db.oracle.driver import OracleDriver

        return OracleDriver(settings)
    if driver_name == "postgres":
        from bald_bookmarks.db.postgres.driver import PostgresDriver

        return PostgresDriver(settings)
    if driver_name == "mysql":
        from bald_bookmarks.db.mysql.driver import MySQLDriver

        return MySQLDriver(settings)
    raise ValueError(f"Unsupported db_driver: {settings.db_driver}")
