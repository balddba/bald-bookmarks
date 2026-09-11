"""Sentry error monitoring and tracing for the FastAPI app."""

from __future__ import annotations

import sys
from collections.abc import Mapping
from typing import Any

import sentry_sdk

from bald_bookmarks import __version__
from bald_bookmarks.config import Settings

_HEALTH_PATH = "/api/health"


def _running_under_pytest() -> bool:
    """Return True when this process is a pytest run.

    Returns:
        bool: True when pytest has already been imported.
    """
    return "pytest" in sys.modules


def init_sentry(settings: Settings) -> None:
    """Initialize the Sentry SDK for unhandled errors and request tracing.

    Skips initialization when the DSN is empty or when running under pytest so
    unit tests do not send events.

    Args:
        settings (Settings): Application settings with Sentry fields.
    """
    dsn = settings.sentry_dsn.strip()
    if not dsn or _running_under_pytest():
        return

    sample_rate = settings.sentry_traces_sample_rate

    def traces_sampler(sampling_context: Mapping[str, Any]) -> float:
        """Honor parent sampling and drop health-check transactions.

        Args:
            sampling_context (Mapping[str, Any]): Sentry sampling context.

        Returns:
            float: Sample rate between 0.0 and 1.0.
        """
        parent = sampling_context.get("parent_sampled")
        if parent is not None:
            return float(parent)
        transaction = sampling_context.get("transaction_context") or {}
        name = str(transaction.get("name", ""))
        if name.endswith(_HEALTH_PATH):
            return 0.0
        return sample_rate

    sentry_sdk.init(
        dsn=dsn,
        environment=settings.sentry_environment,
        release=f"bald-bookmarks@{__version__}",
        send_default_pii=True,
        traces_sampler=traces_sampler,
    )
