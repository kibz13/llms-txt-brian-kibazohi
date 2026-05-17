"""
Generator tests — no DB, no Claude API required.

generate() is async. Test pages are crafted so Claude augmentation never
triggers (no "other" page types, descriptions always provided).
"""

import hashlib
from unittest.mock import AsyncMock, patch

import pytest

from generator import generate
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
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
        depth=depth,
    )


# ---------------------------------------------------------------------------
# Basic structure
# ---------------------------------------------------------------------------

async def test_generate_empty_returns_empty():
    assert await generate([]) == ""


async def test_generate_has_h1():
    pages = [make_page("https://example.com", "Example Site", "We do X for Y.")]
    result = await generate(pages)
    assert result.startswith("# Example Site")


async def test_generate_has_blockquote():
    desc = "We help teams build better software faster with AI-powered tools."
    pages = [make_page("https://example.com", "Example Site", desc)]
    result = await generate(pages)
    assert f"> {desc}" in result


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
    result = await generate(pages)
    assert "## Docs" in result
    assert "Getting Started" in result


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
    result = await generate(pages)
    assert "## Blog" in result
    assert "My Post" in result


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
    result = await generate(pages)
    assert "## Pricing" in result


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

async def test_legal_page_is_dropped():
    pages = [
        make_page("https://example.com", "Home", "Home page.", depth=0),
        make_page(
            "https://example.com/terms",
            "Terms of Service",
            "Legal terms and conditions.",
            content="Terms content.",
            depth=1,
        ),
    ]
    result = await generate(pages)
    assert "Terms of Service" not in result


async def test_dashboard_page_is_dropped():
    pages = [
        make_page("https://example.com", "Home", "Home page.", depth=0),
        make_page(
            "https://example.com/dashboard",
            "Dashboard",
            "Your personal dashboard.",
            content="Dashboard content.",
            depth=1,
        ),
    ]
    result = await generate(pages)
    assert "Dashboard" not in result


async def test_duplicate_content_deduped():
    same_content = "# Same\n\n" + "word " * 200
    same_hash = hashlib.sha256(same_content.encode()).hexdigest()
    pages = [
        make_page("https://example.com", "Home", "Home page.", depth=0),
        CrawledPage(url="https://example.com/a", title="Page A",
                    description="Description A with enough chars here.",
                    content=same_content, content_hash=same_hash, depth=1),
        CrawledPage(url="https://example.com/b", title="Page B",
                    description="Description B with enough chars here.",
                    content=same_content, content_hash=same_hash, depth=1),
    ]
    result = await generate(pages)
    # Only one of the two duplicate pages should appear
    assert result.count("Page A") + result.count("Page B") <= 1
