from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from crawler import PAGE_CAP, crawl
from models import CrawledPage, CrawlResult


def make_mock_result(url, title, description, content, internal_links=None):
    result = MagicMock()
    result.success = True
    result.markdown = content
    result.metadata = {"title": title, "description": description}
    result.links = {
        "internal": [{"href": l} for l in (internal_links or [])],
    }
    return result


@pytest.mark.asyncio
async def test_crawl_returns_expected_shape():
    mock_result = make_mock_result(
        url="https://example.com",
        title="Example",
        description="An example site.",
        content="# Example\n\nAn example site.",
    )

    mock_crawler = AsyncMock()
    mock_crawler.arun = AsyncMock(return_value=mock_result)
    mock_crawler.__aenter__ = AsyncMock(return_value=mock_crawler)
    mock_crawler.__aexit__ = AsyncMock(return_value=None)

    with patch("crawler.AsyncWebCrawler", return_value=mock_crawler):
        result = await crawl("https://example.com", depth=1)

    assert isinstance(result, CrawlResult)
    assert len(result.pages) == 1
    page = result.pages[0]
    assert isinstance(page, CrawledPage)
    assert page.url == "https://example.com"
    assert page.title == "Example"
    assert page.description == "An example site."
    assert page.content is not None
    assert page.content_hash is not None
    assert len(page.content_hash) == 64  # SHA-256 hex digest
    assert page.depth == 0


@pytest.mark.asyncio
async def test_depth_1_crawls_only_homepage():
    homepage = make_mock_result(
        url="https://example.com",
        title="Home",
        description="Home page.",
        content="# Home",
        internal_links=["https://example.com/about", "https://example.com/docs"],
    )

    mock_crawler = AsyncMock()
    mock_crawler.arun = AsyncMock(return_value=homepage)
    mock_crawler.__aenter__ = AsyncMock(return_value=mock_crawler)
    mock_crawler.__aexit__ = AsyncMock(return_value=None)

    with patch("crawler.AsyncWebCrawler", return_value=mock_crawler):
        result = await crawl("https://example.com", depth=1)

    assert len(result.pages) == 1
    assert result.pages[0].url == "https://example.com"


@pytest.mark.asyncio
async def test_depth_2_crawls_linked_pages():
    homepage = make_mock_result(
        url="https://example.com",
        title="Home",
        description="Home page.",
        content="# Home",
        internal_links=["https://example.com/about"],
    )
    about = make_mock_result(
        url="https://example.com/about",
        title="About",
        description="About us.",
        content="# About",
    )

    mock_crawler = AsyncMock()
    mock_crawler.arun = AsyncMock(side_effect=[homepage, about])
    mock_crawler.__aenter__ = AsyncMock(return_value=mock_crawler)
    mock_crawler.__aexit__ = AsyncMock(return_value=None)

    with patch("crawler.AsyncWebCrawler", return_value=mock_crawler):
        result = await crawl("https://example.com", depth=2)

    assert len(result.pages) == 2
    urls = [p.url for p in result.pages]
    assert "https://example.com" in urls
    assert "https://example.com/about" in urls


@pytest.mark.asyncio
async def test_page_cap_respected():
    """Crawl stops at PAGE_CAP regardless of depth and available links."""
    links = [f"https://example.com/page-{i}" for i in range(PAGE_CAP + 10)]
    homepage = make_mock_result(
        url="https://example.com",
        title="Home",
        description="Home.",
        content="# Home",
        internal_links=links,
    )
    child = make_mock_result(
        url="child",
        title="Child",
        description="Child.",
        content="# Child",
    )

    mock_crawler = AsyncMock()
    # homepage first, then unlimited child pages
    mock_crawler.arun = AsyncMock(side_effect=[homepage] + [child] * (PAGE_CAP + 10))
    mock_crawler.__aenter__ = AsyncMock(return_value=mock_crawler)
    mock_crawler.__aexit__ = AsyncMock(return_value=None)

    with patch("crawler.AsyncWebCrawler", return_value=mock_crawler):
        result = await crawl("https://example.com", depth=2)

    assert len(result.pages) <= PAGE_CAP
