"""Capture bookmark page preview screenshots with Playwright."""

from __future__ import annotations

from pathlib import Path

from loguru import logger
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from bald_bookmarks.services.url_metadata import UrlMetadataError, normalize_preview_url

DEFAULT_VIEWPORT_WIDTH = 1280
DEFAULT_VIEWPORT_HEIGHT = 720
DEFAULT_TIMEOUT_MS = 20_000
USER_AGENT = "BaldBookmarks/0.1 (+https://localhost; page preview)"


class PagePreviewError(Exception):
    """Raised when a page preview screenshot cannot be captured.

    Attributes:
        message (str): Human-readable error detail.
    """

    def __init__(self, message: str) -> None:
        """Initialize the error.

        Args:
            message (str): Human-readable error detail.
        """
        super().__init__(message)
        self.message = message


def capture_page_preview(
    raw_url: str,
    destination: Path,
    *,
    viewport_width: int = DEFAULT_VIEWPORT_WIDTH,
    viewport_height: int = DEFAULT_VIEWPORT_HEIGHT,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    no_sandbox: bool = False,
) -> Path:
    """Render a URL in headless Chromium and save a PNG screenshot.

    Args:
        raw_url (str): Bookmark URL to capture.
        destination (Path): Absolute or relative PNG output path.
        viewport_width (int): Browser viewport width in pixels.
        viewport_height (int): Browser viewport height in pixels.
        timeout_ms (int): Navigation timeout in milliseconds.
        no_sandbox (bool): Pass Chromium --no-sandbox (needed in many containers).

    Returns:
        Path: The written destination path.

    Raises:
        PagePreviewError: If the URL is invalid or capture fails.
    """
    try:
        url = normalize_preview_url(raw_url)
    except UrlMetadataError as exc:
        raise PagePreviewError(exc.message) from exc

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    launch_args: list[str] = []
    if no_sandbox:
        launch_args.extend(["--no-sandbox", "--disable-setuid-sandbox"])

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=launch_args or None,
            )
            try:
                page = browser.new_page(
                    viewport={
                        "width": viewport_width,
                        "height": viewport_height,
                    },
                    user_agent=USER_AGENT,
                )
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                # Allow late-loading above-the-fold assets a brief moment.
                page.wait_for_timeout(750)
                page.screenshot(path=str(destination), type="png", full_page=False)
            finally:
                browser.close()
    except PlaywrightTimeoutError as exc:
        raise PagePreviewError("Timed out rendering page preview") from exc
    except PlaywrightError as exc:
        logger.warning("Page preview capture failed for {}: {}", url, exc)
        raise PagePreviewError("Unable to capture page preview") from exc
    except OSError as exc:
        logger.warning("Page preview write failed for {}: {}", destination, exc)
        raise PagePreviewError("Unable to write page preview image") from exc

    if not destination.is_file() or destination.stat().st_size == 0:
        raise PagePreviewError("Page preview image was not written")

    logger.info("Wrote page preview path={} url={}", destination, url)
    return destination
