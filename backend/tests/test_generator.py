from generator import generate
from models import Page


def make_page(url, title, description, content="", depth=0):
    return Page(url=url, title=title, description=description, content=content, depth=depth)


def test_generate_has_h1():
    pages = [make_page("https://example.com", "Example Site", "We do X for Y.")]
    result = generate(pages)
    assert result.startswith("# Example Site")


def test_generate_has_blockquote():
    pages = [make_page("https://example.com", "Example Site", "We do X for Y.")]
    result = generate(pages)
    assert "> We do X for Y." in result


def test_generate_docs_page_in_docs_section():
    pages = [
        make_page("https://example.com", "Home", "The home page.", depth=0),
        make_page(
            "https://example.com/docs/getting-started",
            "Getting Started",
            "How to get started.",
            content="# Getting Started\n\n" + "word " * 600,
            depth=1,
        ),
    ]
    result = generate(pages)
    assert "## Docs" in result
    assert "Getting Started" in result


def test_generate_low_score_page_in_optional():
    pages = [
        make_page("https://example.com", "Home", "Home page.", depth=0),
        make_page(
            "https://example.com/terms",
            "Terms of Service",
            "Legal terms.",
            content="Terms content.",
            depth=1,
        ),
    ]
    result = generate(pages)
    # terms pages score -5 (URL) -2 (depth) = -7, below DROP_THRESHOLD → dropped
    assert "Terms of Service" not in result


def test_generate_empty_pages_returns_empty():
    assert generate([]) == ""
