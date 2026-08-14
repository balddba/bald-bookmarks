"""Tests for URL metadata preview parsing and API."""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from bald_bookmarks.domain.bookmarks import DESCRIPTION_MAX_LENGTH
from bald_bookmarks.services.url_metadata import (
    UrlMetadataError,
    normalize_preview_url,
    parse_html_metadata,
)


def test_parse_html_metadata_prefers_open_graph() -> None:
    """Open Graph title/description win over the document title."""
    html = """
    <html><head>
      <title>Fallback Title</title>
      <meta property="og:title" content="OG Title" />
      <meta property="og:description" content="OG Description" />
      <meta name="description" content="Meta Description" />
    </head></html>
    """
    title, description = parse_html_metadata(html)
    assert title == "OG Title"
    assert description == "OG Description"


def test_parse_html_metadata_falls_back_to_title_and_meta() -> None:
    """Missing OG tags fall back to title and meta description."""
    html = """
    <html><head>
      <title>  Example &amp; Friends  </title>
      <meta name="description" content="A simple page." />
    </head></html>
    """
    title, description = parse_html_metadata(html)
    assert title == "Example & Friends"
    assert description == "A simple page."


def test_parse_html_metadata_empty() -> None:
    """HTML without metadata returns None values."""
    title, description = parse_html_metadata("<html><body>Hi</body></html>")
    assert title is None
    assert description is None


def test_parse_html_metadata_truncates_long_description() -> None:
    """Page descriptions are capped to the bookmark column length."""
    long_description = "d" * (DESCRIPTION_MAX_LENGTH + 40)
    html = f"""
    <html><head>
      <title>Long Page</title>
      <meta name="description" content="{long_description}" />
    </head></html>
    """
    title, description = parse_html_metadata(html)
    assert title == "Long Page"
    assert description == "d" * DESCRIPTION_MAX_LENGTH


def test_normalize_preview_url_adds_https() -> None:
    """Bare hosts are normalized to https URLs."""
    assert normalize_preview_url("example.com/path").startswith("https://example.com")


def test_normalize_preview_url_rejects_non_http() -> None:
    """Non-http schemes are rejected."""
    with pytest.raises(UrlMetadataError, match="http and https"):
        normalize_preview_url("ftp://example.com")


def test_normalize_preview_url_rejects_credentials() -> None:
    """Embedded credentials are rejected."""
    with pytest.raises(UrlMetadataError, match="credentials"):
        normalize_preview_url("https://user:pass@example.com")


def test_url_preview_endpoint_success(client: TestClient) -> None:
    """Preview endpoint returns parsed metadata from a mocked fetch."""
    html = b"<html><head><title>Example Domain</title></head></html>"
    request = httpx.Request("GET", "https://example.com/")
    response = httpx.Response(
        200,
        headers={"content-type": "text/html; charset=utf-8"},
        content=html,
        request=request,
    )

    mock_stream = MagicMock()
    mock_stream.__enter__.return_value = response
    mock_stream.__exit__.return_value = None
    # Ensure iter_bytes works for streamed reading
    response.iter_bytes = lambda: iter([html])  # type: ignore[method-assign]

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = None
    mock_client.stream.return_value = mock_stream

    with patch(
        "bald_bookmarks.services.url_metadata.httpx.Client",
        return_value=mock_client,
    ):
        result = client.post(
            "/api/bookmarks/url-preview",
            json={"url": "https://example.com"},
        )

    assert result.status_code == 200
    body = result.json()
    assert body["title"] == "Example Domain"
    assert body["description"] is None
    assert "example.com" in body["url"]


def test_url_preview_endpoint_rejects_invalid_url(client: TestClient) -> None:
    """Preview endpoint rejects unsupported URL schemes."""
    result = client.post(
        "/api/bookmarks/url-preview",
        json={"url": "javascript:alert(1)"},
    )
    assert result.status_code == 400
