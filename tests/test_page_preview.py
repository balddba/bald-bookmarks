"""Tests for Playwright page preview capture helpers."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bald_bookmarks.services.page_preview import PagePreviewError, capture_page_preview


def test_capture_page_preview_rejects_bad_url(tmp_path: Path) -> None:
    """Invalid schemes raise PagePreviewError before launching a browser."""
    with pytest.raises(PagePreviewError, match="http"):
        capture_page_preview("ftp://example.com", tmp_path / "out.png")


def test_capture_page_preview_writes_png(tmp_path: Path) -> None:
    """Successful capture writes a non-empty PNG via Playwright."""
    destination = tmp_path / "preview.png"
    fake_page = MagicMock()
    fake_browser = MagicMock()
    fake_browser.new_page.return_value = fake_page

    def _screenshot(*, path: str, type: str, full_page: bool) -> None:
        """Persist a tiny PNG at the Playwright screenshot path.

        Args:
            path (str): Destination file path.
            type (str): Image type requested by Playwright.
            full_page (bool): Whether a full-page shot was requested.
        """
        assert type == "png"
        assert full_page is False
        Path(path).write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
            b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )

    fake_page.screenshot.side_effect = _screenshot
    fake_playwright = MagicMock()
    fake_playwright.chromium.launch.return_value = fake_browser
    fake_cm = MagicMock()
    fake_cm.__enter__.return_value = fake_playwright
    fake_cm.__exit__.return_value = False

    with patch(
        "bald_bookmarks.services.page_preview.sync_playwright",
        return_value=fake_cm,
    ):
        result = capture_page_preview(
            "example.com/docs",
            destination,
            no_sandbox=True,
        )

    assert result == destination
    assert destination.is_file()
    fake_playwright.chromium.launch.assert_called_once()
    launch_kwargs = fake_playwright.chromium.launch.call_args.kwargs
    assert launch_kwargs["headless"] is True
    assert "--no-sandbox" in (launch_kwargs["args"] or [])
    fake_page.goto.assert_called_once()
    assert fake_page.goto.call_args.args[0].startswith("https://example.com")


def test_capture_page_preview_maps_playwright_errors(tmp_path: Path) -> None:
    """Playwright failures become PagePreviewError."""
    from playwright.sync_api import Error as PlaywrightError

    fake_playwright = MagicMock()
    fake_playwright.chromium.launch.side_effect = PlaywrightError("launch failed")
    fake_cm = MagicMock()
    fake_cm.__enter__.return_value = fake_playwright
    fake_cm.__exit__.return_value = False

    with (
        patch(
            "bald_bookmarks.services.page_preview.sync_playwright",
            return_value=fake_cm,
        ),
        pytest.raises(PagePreviewError, match="Unable to capture"),
    ):
        capture_page_preview("https://example.com", tmp_path / "out.png")
