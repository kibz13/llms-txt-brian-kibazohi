"""
Page-level classification.

Assigns a page_type to every crawled page based on URL path and content signals.

Page types:  hero | guide | blog_post | product | pricing | about |
             faq | contact | other
"""

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from models import CrawledPage


@dataclass
class PageClassification:
    page_type: str
    confidence: float
    signals: list[str] = field(default_factory=list)


def classify_page(page: CrawledPage) -> PageClassification:
    path = urlparse(page.url).path
    path_lower = path.lower()
    content_lower = page.content.lower()

    # Hero — root URL
    if path in ("/", ""):
        return PageClassification("hero", 1.0, ["root_url"])

    # Contact
    if re.search(r"/contact", path_lower):
        return PageClassification("contact", 0.9, ["contact_url"])

    # Pricing
    if re.search(r"/pricing|/plans?", path_lower):
        return PageClassification("pricing", 0.9, ["pricing_url"])

    # About
    if re.search(r"^/about$|^/about/|/company|/team", path_lower):
        return PageClassification("about", 0.9, ["about_url"])

    # FAQ / help / support
    if re.search(r"/faq|/help|/support", path_lower):
        return PageClassification("faq", 0.85, ["faq_url"])

    # Guide / documentation (sub-path)
    if re.search(r"/docs?/|/documentation/|/guide/|/tutorial/|/getting-started|/quickstart|/reference/|/api/", path_lower):
        has_code = "```" in page.content
        has_methods = bool(re.search(r"\b(GET|POST|PUT|DELETE|PATCH)\b", page.content))
        signals = ["doc_url"]
        if has_code:
            signals.append("code_blocks")
        if has_methods:
            signals.append("http_methods")
        return PageClassification("guide", 0.9 if has_code else 0.75, signals)

    # Guide index (bare /docs, /documentation, /reference)
    if re.search(r"^/docs?$|^/documentation$|^/developers?$|^/reference$", path_lower):
        return PageClassification("guide", 0.8, ["doc_index_url"])

    # Blog post (sub-path)
    if re.search(r"/blog/|/posts?/|/articles?/|/news/|/insights?/", path_lower):
        has_date = bool(re.search(
            r"\d{4}-\d{2}-\d{2}|\b(january|february|march|april|may|june|july|august"
            r"|september|october|november|december)\b", content_lower
        ))
        has_author = bool(re.search(r"by\s+[A-Z][a-z]+|author:", page.content))
        signals = ["blog_url"]
        if has_date:
            signals.append("has_date")
        if has_author:
            signals.append("has_author")
        return PageClassification("blog_post", 0.85 if (has_date or has_author) else 0.7, signals)

    # Product / feature / solution
    if re.search(r"/product/|/products?$|/features?/|/solutions?/|/platform/|/use-cases?/|/integrations?/", path_lower):
        return PageClassification("product", 0.85, ["product_url"])

    return PageClassification("other", 0.0, [])


def classify(pages: list[CrawledPage]) -> dict[str, PageClassification]:
    """Returns a url → PageClassification mapping for every page."""
    return {p.url: classify_page(p) for p in pages}
