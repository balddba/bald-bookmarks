"""Tests for FastAPI Sentry initialization."""

from collections.abc import Iterator
from typing import Any

import pytest
import sentry_sdk
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sentry_sdk.transport import Transport

from bald_bookmarks.config import Settings
from bald_bookmarks.sentry import init_sentry


class _CapturingTransport(Transport):
    """Record envelopes instead of sending them to Sentry."""

    def __init__(self) -> None:
        """Create an empty envelope buffer."""
        super().__init__()
        self.envelopes: list[Any] = []

    def capture_envelope(self, envelope: Any) -> None:
        """Store one captured envelope.

        Args:
            envelope (Any): Envelope emitted by the SDK.
        """
        self.envelopes.append(envelope)


def _sqlite_settings(**overrides: object) -> Settings:
    """Build sqlite settings for Sentry tests.

    Args:
        **overrides (object): Extra Settings field values.

    Returns:
        Settings: Validated settings.
    """
    values: dict[str, object] = {
        "db_driver": "sqlite",
        "sentry_dsn": "https://key@sentry.example/1",
        "sentry_environment": "test",
        "sentry_traces_sample_rate": 1.0,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def enable_sentry_init(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Allow init_sentry to run inside pytest.

    Args:
        monkeypatch (pytest.MonkeyPatch): Pytest monkeypatch fixture.

    Yields:
        None: Control while the guard is disabled.
    """
    monkeypatch.setattr("bald_bookmarks.sentry._running_under_pytest", lambda: False)
    yield
    sentry_sdk.init(dsn=None)


def test_init_sentry_skips_blank_dsn(
    monkeypatch: pytest.MonkeyPatch, enable_sentry_init: None
) -> None:
    """An empty DSN leaves the SDK uninitialized.

    Args:
        monkeypatch (pytest.MonkeyPatch): Pytest monkeypatch fixture.
        enable_sentry_init (None): Fixture that disables the pytest skip.
    """
    called: list[dict[str, object]] = []
    monkeypatch.setattr(
        "bald_bookmarks.sentry.sentry_sdk.init",
        lambda **kwargs: called.append(kwargs),
    )
    init_sentry(_sqlite_settings(sentry_dsn="  "))
    assert called == []


def test_init_sentry_skips_under_pytest(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pytest runs do not send events even when a DSN is configured.

    Args:
        monkeypatch (pytest.MonkeyPatch): Pytest monkeypatch fixture.
    """
    called: list[dict[str, object]] = []
    monkeypatch.setattr(
        "bald_bookmarks.sentry.sentry_sdk.init",
        lambda **kwargs: called.append(kwargs),
    )
    init_sentry(_sqlite_settings())
    assert called == []


def test_init_sentry_enables_errors_and_tracing(
    monkeypatch: pytest.MonkeyPatch, enable_sentry_init: None
) -> None:
    """SDK init uses the FastAPI DSN, PII flag, and a traces sampler.

    Args:
        monkeypatch (pytest.MonkeyPatch): Pytest monkeypatch fixture.
        enable_sentry_init (None): Fixture that disables the pytest skip.
    """
    captured: dict[str, object] = {}

    def fake_init(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr("bald_bookmarks.sentry.sentry_sdk.init", fake_init)
    settings = _sqlite_settings(sentry_traces_sample_rate=0.5)
    init_sentry(settings)
    assert captured["dsn"] == settings.sentry_dsn
    assert captured["send_default_pii"] is True
    assert captured["environment"] == "test"
    assert captured["release"] == "bald-bookmarks@0.2.0"
    sampler = captured["traces_sampler"]
    assert callable(sampler)
    assert sampler({"transaction_context": {"name": "GET /api/health"}}) == 0.0
    assert (
        sampler(
            {
                "parent_sampled": True,
                "transaction_context": {"name": "GET /api/health"},
            }
        )
        == 1.0
    )
    assert sampler({"transaction_context": {"name": "GET /api/folders"}}) == 0.5


def test_fastapi_unhandled_error_is_captured(enable_sentry_init: None) -> None:
    """Unhandled FastAPI exceptions are captured as Sentry error events.

    Args:
        enable_sentry_init (None): Fixture that disables the pytest skip.
    """
    transport = _CapturingTransport()
    sentry_sdk.init(
        dsn="https://key@sentry.example/1",
        transport=transport,
        send_default_pii=True,
        traces_sample_rate=1.0,
    )
    app = FastAPI()

    @app.get("/boom")
    def boom() -> None:
        """Raise a distinctive error for the Sentry capture test."""
        raise RuntimeError("Sentry FastAPI test error")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom")
    sentry_sdk.flush()
    assert response.status_code == 500
    item_types = [
        item.headers.get("type")
        for envelope in transport.envelopes
        for item in envelope.items
    ]
    assert "event" in item_types
