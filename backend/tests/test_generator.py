"""
Generator tests — no DB, no Claude API required.

generate() is async. Test pages are crafted so Claude augmentation never
triggers (no "other" page types, descriptions always provided).
"""

from unittest.mock import AsyncMock, patch

import pytest

from generator import generate, to_md_url
from models import CrawledPage

# Patch _call_claude to return None so all tests exercise the heuristic fallback.
# Claude output is non-deterministic and tested manually against real sites.
pytestmark = pytest.mark.usefixtures("no_claude")


@pytest.fixture(autouse=True)
def no_claude():
    with patch("generator._call_claude", new=AsyncMock(return_value=None)):
        yield


def make_page(url, title, description, content="", depth=0):
    return CrawledPage(
        url=url,
        title=title,
        description=description,
        content=content,
        depth=depth,
    )


# ---------------------------------------------------------------------------
# to_md_url
# ---------------------------------------------------------------------------

def test_to_md_url_root():
    assert to_md_url("https://example.com/") == "https://example.com/index.html.md"


def test_to_md_url_simple_path():
    assert to_md_url("https://example.com/about") == "https://example.com/about.md"


def test_to_md_url_nested_path():
    assert to_md_url("https://example.com/docs/getting-started") == "https://example.com/docs/getting-started.md"


def test_to_md_url_directory_path():
    assert to_md_url("https://example.com/docs/") == "https://example.com/docs/index.html.md"


def test_to_md_url_preserves_domain():
    url = "https://docs.example.com/api/reference"
    assert to_md_url(url) == "https://docs.example.com/api/reference.md"


# ---------------------------------------------------------------------------
# Basic structure
# ---------------------------------------------------------------------------

async def test_generate_empty_returns_empty():
    text, tokens_in, tokens_out = await generate([])
    assert text == "" and tokens_in == 0 and tokens_out == 0


async def test_generate_has_h1():
    pages = [make_page("https://example.com", "Example Site", "We do X for Y.")]
    text, _, _ = await generate(pages)
    assert text.startswith("# Example Site")


async def test_generate_has_blockquote():
    desc = "We help teams build better software faster with AI-powered tools."
    pages = [make_page("https://example.com", "Example Site", desc)]
    text, _, _ = await generate(pages)
    assert f"> {desc}" in text


# ---------------------------------------------------------------------------
# Section assignment (heuristic, no Claude)
# ---------------------------------------------------------------------------

async def test_guide_page_appears_in_docs_section():
    pages = [
        make_page("https://example.com", "Home", "The home page.", depth=0),
        make_page(
            "https://example.com/docs/getting-started",
            "Getting Started",
            "How to get started with our product.",
            content="# Getting Started\n\n" + "word " * 600,
            depth=1,
        ),
    ]
    text, _, _ = await generate(pages)
    assert "## Docs" in text
    assert "Getting Started" in text


async def test_blog_post_appears_in_blog_section():
    pages = [
        make_page("https://example.com", "Home", "Home page.", depth=0),
        make_page(
            "https://example.com/blog/my-post",
            "My Post",
            "A blog post about something interesting.",
            content="# My Post\n\nBy Jane Smith\n\n" + "word " * 400,
            depth=1,
        ),
    ]
    text, _, _ = await generate(pages)
    assert "## Blog" in text
    assert "My Post" in text


async def test_pricing_page_appears_in_pricing_section():
    pages = [
        make_page("https://example.com", "Home", "Home page.", depth=0),
        make_page(
            "https://example.com/pricing",
            "Pricing",
            "Simple, transparent pricing for all team sizes.",
            content="# Pricing\n\n" + "word " * 300,
            depth=1,
        ),
    ]
    text, _, _ = await generate(pages)
    assert "## Pricing" in text


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------
# Legal, auth, and app-shell paths (/terms, /dashboard, /login, etc.) are
# filtered by PATH_BLACKLIST in crawler.py before they ever reach the
# generator. See test_should_skip_* tests in test_crawler.py.
