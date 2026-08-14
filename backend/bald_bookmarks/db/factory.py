"""Database driver factory."""

from bald_bookmarks.config import Settings
from bald_bookmarks.db.abc import DatabaseDriver
from bald_bookmarks.db.memory import MemoryDriver


def create_driver(settings: Settings) -> DatabaseDriver:
    """Create a DatabaseDriver from settings.

    Args:
        settings (Settings): Application settings.

    Returns:
        DatabaseDriver: Concrete driver instance (not yet connected).

    Raises:
        ValueError: If db_driver is unsupported.
    """
    driver_name = settings.db_driver.strip().lower()
    if driver_name == "memory":
        return MemoryDriver(default_max_attempts=settings.job_max_attempts)
    if driver_name == "oracle":
        from bald_bookmarks.db.oracle.driver import OracleDriver

        return OracleDriver(settings)
    raise ValueError(f"Unsupported db_driver: {settings.db_driver}")
