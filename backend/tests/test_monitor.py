"""
Monitor tests — no DB, no real HTTP.

_fetch_text and httpx.AsyncClient are mocked throughout.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from monitor import _fetch_sitemap_hash, _check_page_headers, check_domain
from models import Domain, Page, _now


# ---------------------------------------------------------------------------
# _fetch_sitemap_hash
# ---------------------------------------------------------------------------

async def test_fetch_sitemap_hash_returns_hash_on_success():
    robots = "User-agent: *\nSitemap: https://example.com/sitemap.xml\n"
    sitemap = "<urlset><url><loc>https://example.com/</loc></url></urlset>"

    def fetch_side_effect(url, **kwargs):
        if "robots.txt" in url:
            return robots
        return sitemap

    with patch("monitor._fetch_text", new=AsyncMock(side_effect=fetch_side_effect)):
        result = await _fetch_sitemap_hash("https://example.com")

    assert result is not None
    assert len(result) == 64  # SHA256 hex digest


async def test_fetch_sitemap_hash_returns_none_when_no_sitemap():
    with patch("monitor._fetch_text", new=AsyncMock(return_value=None)):
        result = await _fetch_sitemap_hash("https://example.com")

    assert result is None


async def test_fetch_sitemap_hash_is_deterministic():
    sitemap = "<urlset><url><loc>https://example.com/page</loc></url></urlset>"
    with patch("monitor._fetch_text", new=AsyncMock(return_value=sitemap)):
        h1 = await _fetch_sitemap_hash("https://example.com")
        h2 = await _fetch_sitemap_hash("https://example.com")

    assert h1 == h2


async def test_fetch_sitemap_hash_differs_on_changed_content():
    sitemap_v1 = "<urlset><url><loc>https://example.com/page-1</loc></url></urlset>"
    sitemap_v2 = "<urlset><url><loc>https://example.com/page-2</loc></url></urlset>"

    with patch("monitor._fetch_text", new=AsyncMock(return_value=sitemap_v1)):
        h1 = await _fetch_sitemap_hash("https://example.com")
    with patch("monitor._fetch_text", new=AsyncMock(return_value=sitemap_v2)):
        h2 = await _fetch_sitemap_hash("https://example.com")

    assert h1 != h2


# ---------------------------------------------------------------------------
# _check_page_headers
# ---------------------------------------------------------------------------

async def test_check_page_headers_detects_etag_change():
    mock_resp = MagicMock()
    mock_resp.headers = {"etag": '"new-etag"', "last-modified": ""}

    with patch("monitor.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.head = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_client

        changed, new_etag, _ = await _check_page_headers(
            "https://example.com/page", '"old-etag"', None
        )

    assert changed is True
    assert new_etag == '"new-etag"'


async def test_check_page_headers_detects_last_modified_change():
    mock_resp = MagicMock()
    mock_resp.headers = {"etag": "", "last-modified": "Mon, 01 Jan 2026 00:00:00 GMT"}

    with patch("monitor.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.head = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_client

        changed, _, new_lm = await _check_page_headers(
            "https://example.com/page", None, "Sat, 01 Jan 2025 00:00:00 GMT"
        )

    assert changed is True
    assert "2026" in new_lm


async def test_check_page_headers_no_change_when_same():
    mock_resp = MagicMock()
    mock_resp.headers = {"etag": '"same"', "last-modified": ""}

    with patch("monitor.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.head = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_client

        changed, _, _ = await _check_page_headers(
            "https://example.com/page", '"same"', None
        )

    assert changed is False


async def test_check_page_headers_no_trigger_on_first_observation():
    """When no stored values exist, seeing headers for the first time should not trigger."""
    mock_resp = MagicMock()
    mock_resp.headers = {"etag": '"first-time"', "last-modified": ""}

    with patch("monitor.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.head = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_client

        changed, new_etag, _ = await _check_page_headers(
            "https://example.com/page", None, None
        )

    assert changed is False
    assert new_etag == '"first-time"'


async def test_check_page_headers_returns_stored_on_network_error():
    with patch("monitor.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.head = AsyncMock(side_effect=Exception("timeout"))
        mock_client_cls.return_value = mock_client

        changed, etag, lm = await _check_page_headers(
            "https://example.com/page", '"stored"', "Wed, 01 Jan 2025 00:00:00 GMT"
        )

    assert changed is False
    assert etag == '"stored"'
    assert lm == "Wed, 01 Jan 2025 00:00:00 GMT"


# ---------------------------------------------------------------------------
# check_domain
# ---------------------------------------------------------------------------

def make_domain(**kwargs):
    defaults = dict(
        id=uuid4(),
        base_url="https://example.com",
        domain="example.com",
        monitoring_enabled=True,
        last_job_id=None,
        sitemap_hash=None,
        created_at=_now(),
        updated_at=_now(),
    )
    defaults.update(kwargs)
    return Domain(**defaults)


def make_mock_session():
    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))
    return session


async def test_check_domain_triggers_job_on_sitemap_change():
    domain = make_domain(sitemap_hash="old-hash")
    session = make_mock_session()

    with patch("monitor._fetch_sitemap_hash", new=AsyncMock(return_value="new-hash")):
        with patch("monitor._trigger_job", new=AsyncMock()) as mock_trigger:
            triggered = await check_domain(domain, session)

    assert triggered is True
    mock_trigger.assert_called_once()
    assert domain.sitemap_hash == "new-hash"


async def test_check_domain_no_trigger_on_first_sitemap_observation():
    """First time we see a sitemap hash — store it, don't trigger."""
    domain = make_domain(sitemap_hash=None)
    session = make_mock_session()

    with patch("monitor._fetch_sitemap_hash", new=AsyncMock(return_value="first-hash")):
        with patch("monitor._trigger_job", new=AsyncMock()) as mock_trigger:
            triggered = await check_domain(domain, session)

    assert triggered is False
    mock_trigger.assert_not_called()
    assert domain.sitemap_hash == "first-hash"


async def test_check_domain_no_trigger_when_sitemap_unchanged():
    domain = make_domain(sitemap_hash="same-hash")
    session = make_mock_session()

    with patch("monitor._fetch_sitemap_hash", new=AsyncMock(return_value="same-hash")):
        with patch("monitor._trigger_job", new=AsyncMock()) as mock_trigger:
            triggered = await check_domain(domain, session)

    assert triggered is False
    mock_trigger.assert_not_called()


async def test_check_domain_updates_last_checked_at():
    domain = make_domain(sitemap_hash=None, last_checked_at=None)
    session = make_mock_session()

    with patch("monitor._fetch_sitemap_hash", new=AsyncMock(return_value="hash")):
        await check_domain(domain, session)

    assert domain.last_checked_at is not None
