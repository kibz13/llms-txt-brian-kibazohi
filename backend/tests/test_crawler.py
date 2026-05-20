"""
Crawler tests — robots.txt parsing, sitemap parsing, BFS crawl.
Network calls (_fetch_text, AsyncWebCrawler) are always mocked.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from crawler import (
    PAGE_CAP,
    _get_sitemap_urls,
    _is_disallowed,
    _parse_robots,
    _parse_sitemap,
    crawl,
)
from models import CrawledPage, CrawlResult


# ---------------------------------------------------------------------------
# Helpers shared by BFS crawl tests
# ---------------------------------------------------------------------------

def make_mock_result(url, title, description, content, internal_links=None):
    result = MagicMock()
    result.success = True
    result.markdown = content
    result.metadata = {"title": title, "description": description}
    result.links = {"internal": [{"href": l} for l in (internal_links or [])]}
    return result


def mock_crawler_ctx(side_effect):
    """Return a patched AsyncWebCrawler context manager."""
    mc = AsyncMock()
    mc.arun = AsyncMock(side_effect=side_effect)
    mc.__aenter__ = AsyncMock(return_value=mc)
    mc.__aexit__ = AsyncMock(return_value=None)
    return mc


# BFS crawl tests patch _fetch_text so no real HTTP calls are made and the
# crawler always falls back to BFS (no sitemap found).
BFS_PATCHES = [
    patch("crawler._fetch_text", new=AsyncMock(return_value=None)),
]


# ---------------------------------------------------------------------------
# _parse_robots
# ---------------------------------------------------------------------------

def test_parse_robots_disallow_paths():
    text = "User-agent: *\nDisallow: /admin/\nDisallow: /private/\n"
    disallowed, sitemap = _parse_robots(text)
    assert "/admin/" in disallowed
    assert "/private/" in disallowed
    assert sitemap is None


def test_parse_robots_sitemap_directive():
    text = "User-agent: *\nDisallow:\nSitemap: https://example.com/sitemap.xml\n"
    disallowed, sitemap = _parse_robots(text)
    assert disallowed == []
    assert sitemap == "https://example.com/sitemap.xml"


def test_parse_robots_ignores_other_agents():
    text = (
        "User-agent: Googlebot\nDisallow: /secret/\n\n"
        "User-agent: *\nDisallow: /public-block/\n"
    )
    disallowed, _ = _parse_robots(text)
    assert "/secret/" not in disallowed
    assert "/public-block/" in disallowed


def test_parse_robots_empty_disallow_means_allow_all():
    text = "User-agent: *\nDisallow:\n"
    disallowed, _ = _parse_robots(text)
    assert disallowed == []


def test_parse_robots_strips_comments():
    text = "User-agent: * # all bots\nDisallow: /block/ # this path\n"
    disallowed, _ = _parse_robots(text)
    assert "/block/" in disallowed


def test_parse_robots_protocol_relative_sitemap():
    text = "Sitemap: //example.com/sitemap.xml\n"
    _, sitemap = _parse_robots(text)
    assert sitemap == "https://example.com/sitemap.xml"


# ---------------------------------------------------------------------------
# _is_disallowed
# ---------------------------------------------------------------------------

def test_is_disallowed_matches_prefix():
    assert _is_disallowed("https://example.com/admin/settings", ["/admin/"])


def test_is_disallowed_no_match():
    assert not _is_disallowed("https://example.com/about", ["/admin/", "/private/"])


def test_is_disallowed_empty_list():
    assert not _is_disallowed("https://example.com/anything", [])


# ---------------------------------------------------------------------------
# _parse_sitemap
# ---------------------------------------------------------------------------

SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/</loc></url>
  <url><loc>https://example.com/about</loc></url>
  <url><loc>https://example.com/pricing</loc></url>
  <url><loc>https://other.com/page</loc></url>
</urlset>"""

SITEMAP_INDEX_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://example.com/sitemap-pages.xml</loc></sitemap>
  <sitemap><loc>https://example.com/sitemap-blog.xml</loc></sitemap>
</sitemapindex>"""

CHILD_SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/blog/post-1</loc></url>
  <url><loc>https://example.com/blog/post-2</loc></url>
</urlset>"""


async def test_parse_sitemap_returns_same_domain_urls():
    with patch("crawler._fetch_text", new=AsyncMock(return_value=SITEMAP_XML)):
        urls = await _parse_sitemap("https://example.com/sitemap.xml", "https://example.com", [])
    assert "https://example.com/" in urls
    assert "https://example.com/about" in urls
    assert "https://other.com/page" not in urls


async def test_parse_sitemap_filters_disallowed():
    with patch("crawler._fetch_text", new=AsyncMock(return_value=SITEMAP_XML)):
        urls = await _parse_sitemap(
            "https://example.com/sitemap.xml", "https://example.com", ["/pricing"],
        )
    assert "https://example.com/pricing" not in urls


async def test_parse_sitemap_filters_skippable_urls():
    xml = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://example.com/image.png</loc></url>
      <url><loc>https://example.com/doc.pdf</loc></url>
      <url><loc>https://example.com/about</loc></url>
    </urlset>"""
    with patch("crawler._fetch_text", new=AsyncMock(return_value=xml)):
        urls = await _parse_sitemap("https://example.com/sitemap.xml", "https://example.com", [])
    assert "https://example.com/image.png" not in urls
    assert "https://example.com/doc.pdf" not in urls
    assert "https://example.com/about" in urls


async def test_parse_sitemap_returns_empty_on_fetch_failure():
    with patch("crawler._fetch_text", new=AsyncMock(return_value=None)):
        urls = await _parse_sitemap("https://example.com/sitemap.xml", "https://example.com", [])
    assert urls == []


async def test_parse_sitemap_returns_empty_on_invalid_xml():
    with patch("crawler._fetch_text", new=AsyncMock(return_value="not xml")):
        urls = await _parse_sitemap("https://example.com/sitemap.xml", "https://example.com", [])
    assert urls == []


async def test_parse_sitemap_index_fetches_children():
    def side_effect(url, **kwargs):
        if "sitemap-pages" in url or "sitemap-blog" in url:
            return CHILD_SITEMAP_XML
        return SITEMAP_INDEX_XML

    with patch("crawler._fetch_text", new=AsyncMock(side_effect=side_effect)):
        urls = await _parse_sitemap("https://example.com/sitemap.xml", "https://example.com", [])
    assert "https://example.com/blog/post-1" in urls
    assert "https://example.com/blog/post-2" in urls


# ---------------------------------------------------------------------------
# _get_sitemap_urls
# ---------------------------------------------------------------------------

async def test_get_sitemap_urls_uses_robots_hint_first():
    called = []

    async def mock_parse(sitemap_url, base_url, disallowed, _depth=0):
        called.append(sitemap_url)
        if "robots-hint" in sitemap_url:
            return ["https://example.com/page1"]
        return []

    with patch("crawler._parse_sitemap", side_effect=mock_parse):
        urls = await _get_sitemap_urls(
            "https://example.com",
            "https://example.com/robots-hint-sitemap.xml",
            [],
        )

    assert called[0] == "https://example.com/robots-hint-sitemap.xml"
    assert urls == ["https://example.com/page1"]


async def test_get_sitemap_urls_falls_back_to_default():
    async def mock_parse(sitemap_url, base_url, disallowed, _depth=0):
        if sitemap_url == "https://example.com/sitemap.xml":
            return ["https://example.com/page1"]
        return []

    with patch("crawler._parse_sitemap", side_effect=mock_parse):
        urls = await _get_sitemap_urls("https://example.com", None, [])

    assert urls == ["https://example.com/page1"]


async def test_get_sitemap_urls_returns_empty_when_none_found():
    with patch("crawler._parse_sitemap", new=AsyncMock(return_value=[])):
        urls = await _get_sitemap_urls("https://example.com", None, [])
    assert urls == []


# ---------------------------------------------------------------------------
# BFS crawl tests (sitemap disabled via _fetch_text → None)
# ---------------------------------------------------------------------------

async def test_crawl_returns_expected_shape():
    mock_result = make_mock_result(
        url="https://example.com",
        title="Example",
        description="An example site.",
        content="# Example\n\nAn example site.",
    )
    mc = mock_crawler_ctx([mock_result])

    with patch("crawler._fetch_text", new=AsyncMock(return_value=None)):
        with patch("crawler.AsyncWebCrawler", return_value=mc):
            result = await crawl("https://example.com", depth=1)

    assert isinstance(result, CrawlResult)
    assert len(result.pages) == 1
    page = result.pages[0]
    assert isinstance(page, CrawledPage)
    assert page.url == "https://example.com"
    assert page.title == "Example"
    assert page.description == "An example site."
    assert page.depth == 0


async def test_depth_1_crawls_only_homepage():
    homepage = make_mock_result(
        url="https://example.com",
        title="Home",
        description="Home page.",
        content="# Home",
        internal_links=["https://example.com/about", "https://example.com/docs"],
    )
    mc = mock_crawler_ctx([homepage])

    with patch("crawler._fetch_text", new=AsyncMock(return_value=None)):
        with patch("crawler.AsyncWebCrawler", return_value=mc):
            result = await crawl("https://example.com", depth=1)

    assert len(result.pages) == 1
    assert result.pages[0].url == "https://example.com"


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
    mc = mock_crawler_ctx([homepage, about])

    with patch("crawler._fetch_text", new=AsyncMock(return_value=None)):
        with patch("crawler.AsyncWebCrawler", return_value=mc):
            result = await crawl("https://example.com", depth=2)

    assert len(result.pages) == 2
    urls = [p.url for p in result.pages]
    assert "https://example.com" in urls
    assert "https://example.com/about" in urls


async def test_page_cap_respected():
    links = [f"https://example.com/page-{i}" for i in range(PAGE_CAP + 10)]
    homepage = make_mock_result(
        url="https://example.com",
        title="Home",
        description="Home.",
        content="# Home",
        internal_links=links,
    )
    child = make_mock_result(url="child", title="Child", description="Child.", content="# Child")
    mc = mock_crawler_ctx([homepage] + [child] * (PAGE_CAP + 10))

    with patch("crawler._fetch_text", new=AsyncMock(return_value=None)):
        with patch("crawler.AsyncWebCrawler", return_value=mc):
            result = await crawl("https://example.com", depth=2)

    assert len(result.pages) <= PAGE_CAP
