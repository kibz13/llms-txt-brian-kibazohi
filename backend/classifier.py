"""
Site and page classification.

Produces two outputs:
  1. SiteClassification  — primary_type and per-type confidence
  2. PageClassification  — page_type and confidence for every crawled page

Page types:  hero | guide | blog_post | product | pricing | about |
             faq | contact | legal | dashboard | other

Site types:  documentation | blog | saas | e-commerce | portfolio | news | other
"""

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from models import CrawledPage

CONFIDENCE_THRESHOLD = 0.25  # lower threshold — 6 site types share the space


# ---------------------------------------------------------------------------
# Output types
# ---------------------------------------------------------------------------

@dataclass
class PageClassification:
    page_type: str
    confidence: float
    signals: list[str] = field(default_factory=list)


@dataclass
class SiteClassification:
    primary_type: str   # documentation | blog | saas | e-commerce | portfolio | news | other
    confidence: dict[str, float]


@dataclass
class ClassificationResult:
    site: SiteClassification
    pages: dict[str, PageClassification]  # url → PageClassification


# ---------------------------------------------------------------------------
# Page-level classification
# ---------------------------------------------------------------------------

def classify_page(page: CrawledPage) -> PageClassification:
    path = urlparse(page.url).path
    path_lower = path.lower()
    content_lower = page.content.lower()

    # Hero — root URL
    if path in ("/", ""):
        return PageClassification("hero", 1.0, ["root_url"])

    # Legal
    if re.search(r"/privacy|/terms|/legal|/cookies|/dpa", path_lower):
        return PageClassification("legal", 0.95, ["legal_url"])

    # Dashboard / app (login-walled, low value)
    if re.search(r"/dashboard|/app/|/console|/admin", path_lower):
        return PageClassification("dashboard", 0.9, ["dashboard_url"])

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


# ---------------------------------------------------------------------------
# Site-level classification
# ---------------------------------------------------------------------------

_DOC_PAGE_TYPES  = {"guide"}
_BLOG_PAGE_TYPES = {"blog_post"}
_PROD_PAGE_TYPES = {"product", "pricing"}


def classify_site(
    pages: list[CrawledPage],
    page_classifications: dict[str, PageClassification],
) -> SiteClassification:
    if not pages:
        return SiteClassification("other", {})

    total = len(pages)
    pcs = list(page_classifications.values())

    guide_ratio   = sum(1 for pc in pcs if pc.page_type in _DOC_PAGE_TYPES)  / total
    blog_ratio    = sum(1 for pc in pcs if pc.page_type in _BLOG_PAGE_TYPES) / total
    product_ratio = sum(1 for pc in pcs if pc.page_type == "product")        / total
    pricing_count = sum(1 for pc in pcs if pc.page_type == "pricing")

    # Content signals (sampled across all pages, capped to avoid domination)
    has_code     = any("```" in p.content for p in pages)
    has_cart     = any(re.search(r"/cart|/checkout|add.to.cart", p.content.lower()) for p in pages)
    has_cta      = any(re.search(r"free trial|sign up free|get started|book a demo|request demo", p.content.lower()) for p in pages)
    has_github   = any("github.com" in p.content.lower() for p in pages)
    has_bylines  = sum(1 for p in pages if re.search(r"by\s+[A-Z][a-z]+|author:", p.content))

    confidence: dict[str, float] = {
        "documentation": min(1.0, guide_ratio + (0.2 if has_code else 0.0)),
        "blog":          min(1.0, blog_ratio * (0.8 if has_bylines / total < 0.3 else 1.0)),
        "news":          min(1.0, blog_ratio * (1.2 if has_bylines / total >= 0.3 else 0.5)),
        "saas":          min(1.0, (product_ratio * 0.5) + (0.3 if pricing_count > 0 else 0.0) + (0.2 if has_cta else 0.0)),
        "e-commerce":    min(1.0, product_ratio + (0.4 if has_cart else 0.0)),
        "portfolio":     0.6 if (has_github and total <= 20 and guide_ratio < 0.2) else 0.0,
    }

    ranked = sorted(confidence.items(), key=lambda x: x[1], reverse=True)
    primary_type = ranked[0][0] if ranked[0][1] >= CONFIDENCE_THRESHOLD else "other"

    return SiteClassification(primary_type, confidence)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def classify(pages: list[CrawledPage]) -> ClassificationResult:
    page_clf = {p.url: classify_page(p) for p in pages}
    site_clf = classify_site(pages, page_clf)
    return ClassificationResult(site=site_clf, pages=page_clf)
