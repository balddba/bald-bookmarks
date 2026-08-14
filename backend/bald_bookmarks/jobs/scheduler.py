"""In-process background job scheduler."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from loguru import logger

from bald_bookmarks.config import Settings
from bald_bookmarks.db.abc import DatabaseDriver
from bald_bookmarks.jobs.registry import JobRegistry


class JobScheduler:
    """Poll the jobs table and dispatch claimed work to handlers.

    Attributes:
        driver (DatabaseDriver): Persistence driver.
        registry (JobRegistry): Job type to handler map.
        settings (Settings): Runtime settings.
    """

    def __init__(
        self,
        driver: DatabaseDriver,
        registry: JobRegistry,
        settings: Settings,
    ) -> None:
        """Initialize the scheduler.

        Args:
            driver (DatabaseDriver): Persistence driver.
            registry (JobRegistry): Job type to handler map.
            settings (Settings): Runtime settings.
        """
        self.driver = driver
        self.registry = registry
        self.settings = settings
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        """Start the background poll loop."""
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run_loop(), name="job-scheduler")
        logger.info(
            "Job scheduler started poll_seconds={}",
            self.settings.job_poll_seconds,
        )

    async def stop(self) -> None:
        """Stop the background poll loop."""
        self._stop.set()
        if self._task is not None:
            await self._task
            self._task = None
        logger.info("Job scheduler stopped")

    def is_running(self) -> bool:
        """Return whether the poll loop task is active.

        Returns:
            bool: True when the scheduler task exists and is not done.
        """
        return self._task is not None and not self._task.done()

    async def _run_loop(self) -> None:
        """Continuously claim and process jobs until stopped."""
        while not self._stop.is_set():
            try:
                processed = await asyncio.to_thread(self._process_one)
                if not processed:
                    try:
                        await asyncio.wait_for(
                            self._stop.wait(),
                            timeout=self.settings.job_poll_seconds,
                        )
                    except TimeoutError:
                        continue
            except Exception:
                logger.exception("Job scheduler loop error")
                try:
                    await asyncio.wait_for(
                        self._stop.wait(),
                        timeout=self.settings.job_poll_seconds,
                    )
                except TimeoutError:
                    continue

    def _process_one(self) -> bool:
        """Claim and run a single job if available.

        Returns:
            bool: True when a job was claimed and processed.
        """
        job = self.driver.claim_next_job()
        if job is None:
            return False
        handler = self.registry.get(job.job_type)
        if handler is None:
            self.driver.mark_job_failed(
                job.id,
                f"Unknown job_type: {job.job_type}",
                retry=False,
            )
            logger.error("Unknown job_type={} job_id={}", job.job_type, job.id)
            return True
        try:
            handler(self.driver, job, self.settings)
            self.driver.mark_job_succeeded(job.id)
            logger.info("Job succeeded job_id={} type={}", job.id, job.job_type)
        except Exception as exc:
            retry = job.attempts < job.max_attempts
            scheduled_at = datetime.now(UTC) + timedelta(seconds=2**job.attempts)
            self.driver.mark_job_failed(
                job.id,
                str(exc),
                retry=retry,
                scheduled_at=scheduled_at if retry else None,
            )
            logger.exception(
                "Job failed job_id={} type={} retry={}",
                job.id,
                job.job_type,
                retry,
            )
        return True
