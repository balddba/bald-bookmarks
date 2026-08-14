"""Fetch and parse page metadata for bookmark URL previews."""

from __future__ import annotations

import html
import re
from urllib.parse import urlparse

import httpx
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from bald_bookmarks.domain.bookmarks import DESCRIPTION_MAX_LENGTH

_TITLE_RE = re.compile(
    r"<title[^>]*>(.*?)</title>",
    re.IGNORECASE | re.DOTALL,
)
_META_ATTR_RE = re.compile(
    r"<meta\b[^>]*>",
    re.IGNORECASE,
)
_ATTR_RE = re.compile(
    r"""([^\s=]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""",
    re.IGNORECASE,
)

MAX_RESPONSE_BYTES = 512_000
FETCH_TIMEOUT_SECONDS = 8.0
USER_AGENT = "BaldBookmarks/0.1 (+https://localhost; metadata preview)"


class UrlMetadataRequest(BaseModel):
    """Request body for URL metadata preview.

    Attributes:
        url (str): Absolute http(s) URL to inspect.
    """

    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=2048)


class UrlMetadataResponse(BaseModel):
    """Parsed metadata for a URL.

    Attributes:
        url (str): Canonical request URL that was fetched.
        title (str | None): Best-effort page title.
        description (str | None): Best-effort page description.
    """

    model_config = ConfigDict(extra="forbid")

    url: str
    title: str | None = None
    description: str | None = None


class UrlMetadataError(Exception):
    """Raised when URL metadata cannot be retrieved.

    Attributes:
        message (str): Human-readable error detail.
        status_code (int): Suggested HTTP status for API responses.
    """

    def __init__(self, message: str, status_code: int = 400) -> None:
        """Initialize the error.

        Args:
            message (str): Human-readable error detail.
            status_code (int): Suggested HTTP status for API responses.
        """
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def normalize_preview_url(raw_url: str) -> str:
    """Validate and normalize a user-supplied URL for metadata fetch.

    Args:
        raw_url (str): Raw URL from the client.

    Returns:
        str: Normalized absolute http(s) URL.

    Raises:
        UrlMetadataError: If the URL is missing, has a bad scheme, or is invalid.
    """
    candidate = raw_url.strip()
    if not candidate:
        raise UrlMetadataError("URL is required")
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"}:
        raise UrlMetadataError("Only http and https URLs are supported")
    if not parsed.netloc:
        raise UrlMetadataError("URL must include a host")
    # Reject credentials in the authority to reduce SSRF/abuse surface.
    if parsed.username or parsed.password:
        raise UrlMetadataError("URLs with embedded credentials are not allowed")
    try:
        validated = HttpUrl(candidate)
    except Exception as exc:
        raise UrlMetadataError("Invalid URL") from exc
    return str(validated)


def fetch_url_metadata(raw_url: str) -> UrlMetadataResponse:
    """Fetch a URL and extract title/description metadata.

    Args:
        raw_url (str): Raw URL from the client.

    Returns:
        UrlMetadataResponse: Parsed metadata for the page.

    Raises:
        UrlMetadataError: If validation or the remote fetch fails.
    """
    url = normalize_preview_url(raw_url)
    content_type = ""
    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=FETCH_TIMEOUT_SECONDS,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
            },
        ) as client:
            with client.stream("GET", url) as response:
                if response.status_code >= 400:
                    raise UrlMetadataError(
                        f"Remote site returned HTTP {response.status_code}",
                        status_code=502,
                    )
                content_type = response.headers.get("content-type", "")
                if content_type and "html" not in content_type.lower():
                    raise UrlMetadataError(
                        "Remote resource is not an HTML page",
                        status_code=422,
                    )
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    chunks.append(chunk)
                    total += len(chunk)
                    if total >= MAX_RESPONSE_BYTES:
                        break
                body = b"".join(chunks)[:MAX_RESPONSE_BYTES]
    except UrlMetadataError:
        raise
    except httpx.TimeoutException as exc:
        raise UrlMetadataError("Timed out fetching URL", status_code=504) from exc
    except httpx.RequestError as exc:
        logger.warning("URL metadata fetch failed for {}: {}", url, exc)
        raise UrlMetadataError("Unable to fetch URL", status_code=502) from exc

    charset = _guess_charset(content_type, body)
    text = body.decode(charset, errors="replace")
    title, description = parse_html_metadata(text)
    return UrlMetadataResponse(url=url, title=title, description=description)


def parse_html_metadata(html_text: str) -> tuple[str | None, str | None]:
    """Extract title and description from HTML markup.

    Prefers Open Graph / Twitter meta tags, then falls back to the document
    title and standard meta description. Descriptions longer than
    DESCRIPTION_MAX_LENGTH are truncated.

    Args:
        html_text (str): HTML document text.

    Returns:
        tuple[str | None, str | None]: Title and description, each optional.
    """
    meta = _collect_meta(html_text)
    title = _first_nonempty(
        meta.get("og:title"),
        meta.get("twitter:title"),
        _extract_title_tag(html_text),
    )
    description = _first_nonempty(
        meta.get("og:description"),
        meta.get("twitter:description"),
        meta.get("description"),
    )
    return _clean_text(title), _truncate_description(_clean_text(description))


def _extract_title_tag(html_text: str) -> str | None:
    """Return the contents of the first title element.

    Args:
        html_text (str): HTML document text.

    Returns:
        str | None: Decoded title text, or None when absent.
    """
    match = _TITLE_RE.search(html_text)
    if not match:
        return None
    return html.unescape(match.group(1))


def _collect_meta(html_text: str) -> dict[str, str]:
    """Collect name/property meta tag content values.

    Args:
        html_text (str): HTML document text.

    Returns:
        dict[str, str]: Lowercased meta key to content value.
    """
    values: dict[str, str] = {}
    for tag in _META_ATTR_RE.findall(html_text):
        attrs = {
            key.lower(): (quoted or single or bare or "")
            for key, quoted, single, bare in _ATTR_RE.findall(tag)
        }
        key = attrs.get("property") or attrs.get("name")
        content = attrs.get("content")
        if key and content and key.lower() not in values:
            values[key.lower()] = html.unescape(content)
    return values


def _truncate_description(value: str | None) -> str | None:
    """Cap description length to the bookmark column size.

    Args:
        value (str | None): Cleaned description text.

    Returns:
        str | None: Description truncated to DESCRIPTION_MAX_LENGTH, or None.
    """
    if value is None:
        return None
    return value[:DESCRIPTION_MAX_LENGTH]


def _clean_text(value: str | None) -> str | None:
    """Normalize whitespace in extracted text.

    Args:
        value (str | None): Raw extracted string.

    Returns:
        str | None: Collapsed text, or None when empty.
    """
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip()
    return cleaned or None


def _first_nonempty(*values: str | None) -> str | None:
    """Return the first non-empty string among candidates.

    Args:
        *values (str | None): Candidate strings.

    Returns:
        str | None: First non-empty value, or None.
    """
    for value in values:
        if value and value.strip():
            return value
    return None


def _guess_charset(content_type: str | None, body: bytes) -> str:
    """Guess a text encoding for the response body.

    Args:
        content_type (str | None): Response Content-Type header.
        body (bytes): Truncated response body.

    Returns:
        str: Encoding name suitable for decode().
    """
    if content_type:
        match = re.search(r"charset=([^\s;]+)", content_type, re.IGNORECASE)
        if match:
            return match.group(1).strip("\"'")
    _ = body
    return "utf-8"
