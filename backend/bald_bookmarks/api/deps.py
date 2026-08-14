"""FastAPI dependency helpers."""

from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, Request

from bald_bookmarks.config import Settings
from bald_bookmarks.db.abc import DatabaseDriver
from bald_bookmarks.jobs.scheduler import JobScheduler


def get_settings(request: Request) -> Settings:
    """Resolve application settings from app state.

    Args:
        request (Request): Current request.

    Returns:
        Settings: Shared settings instance.
    """
    return request.app.state.settings


def get_driver(request: Request) -> Generator[DatabaseDriver]:
    """Resolve the connected database driver from app state.

    Args:
        request (Request): Current request.

    Yields:
        DatabaseDriver: Shared driver instance.
    """
    yield request.app.state.driver


def get_scheduler(request: Request) -> JobScheduler:
    """Resolve the job scheduler from app state.

    Args:
        request (Request): Current request.

    Returns:
        JobScheduler: Shared scheduler instance.
    """
    return request.app.state.scheduler


SettingsDep = Annotated[Settings, Depends(get_settings)]
DriverDep = Annotated[DatabaseDriver, Depends(get_driver)]
SchedulerDep = Annotated[JobScheduler, Depends(get_scheduler)]
