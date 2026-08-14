"""Job handler registry."""

from collections.abc import Callable

from bald_bookmarks.db.abc import DatabaseDriver
from bald_bookmarks.domain.jobs import Job

JobHandler = Callable[[DatabaseDriver, Job, object], None]


class JobRegistry:
    """Map job_type strings to handler callables.

    Attributes:
        _handlers (dict[str, JobHandler]): Registered handlers by job type.
    """

    def __init__(self) -> None:
        """Initialize an empty registry."""
        self._handlers: dict[str, JobHandler] = {}

    def register(self, job_type: str, handler: JobHandler) -> None:
        """Register a handler for a job type.

        Args:
            job_type (str): Job type key.
            handler (JobHandler): Callable invoked for matching jobs.
        """
        self._handlers[job_type] = handler

    def get(self, job_type: str) -> JobHandler | None:
        """Look up a handler by job type.

        Args:
            job_type (str): Job type key.

        Returns:
            JobHandler | None: Matching handler, or None.
        """
        return self._handlers.get(job_type)

    def registered_types(self) -> list[str]:
        """List registered job type keys.

        Returns:
            list[str]: Sorted handler keys.
        """
        return sorted(self._handlers)


def build_default_registry() -> JobRegistry:
    """Build the default job registry with built-in handlers.

    Returns:
        JobRegistry: Registry including thumbnail.capture.
    """
    from bald_bookmarks.jobs.handlers.thumbnail import handle_thumbnail_capture

    registry = JobRegistry()
    registry.register("thumbnail.capture", handle_thumbnail_capture)
    return registry
