"""
Profile-based page scoring.

Scorer's only job: decide which pages are valuable and how valuable.
Section assignment and grouping is handled by the generator.

Hard-drop:  legal, dashboard — universally low value
Profiles:   documentation | blog | news | saas | e-commerce | portfolio | other
"""

from dataclasses import dataclass

from classifier import ClassificationResult, PageClassification, SiteClassification
from models import CrawledPage

DROP_THRESHOLD         = 0
OPTIONAL_THRESHOLD     = 5
RELAXED_DROP_THRESHOLD = -3

# Page types that are always dropped regardless of profile
_HARD_DROP_TYPES = {"legal", "dashboard"}

# Base score per page_type per profile
_PROFILE_SCORES: dict[str, dict[str, int]] = {
    "documentation": {
        "guide":     10,
        "faq":        8,
        "about":      5,
        "product":    3,
        "pricing":    3,
        "contact":    2,
        "blog_post":  2,
    },
    "blog": {
        "blog_post": 10,
        "guide":      8,
        "about":      5,
        "faq":        3,
        "contact":    2,
    },
    "news": {
        "blog_post": 10,
        "about":      5,
        "faq":        3,
        "contact":    2,
    },
    "saas": {
        "pricing":   10,
        "product":    8,
        "about":      5,
        "contact":    5,
        "guide":      4,
        "faq":        4,
        "blog_post":  2,
    },
    "e-commerce": {
        "product":    8,
        "pricing":    8,
        "faq":        5,
        "guide":      4,
        "about":      3,
        "contact":    3,
    },
    "portfolio": {
        "about":     10,
        "product":   10,
        "blog_post":  5,
        "guide":      4,
        "contact":    3,
    },
    "other": {},
}

_DEFAULT_PAGE_SCORE = 1   # any page_type not in the profile


# ---------------------------------------------------------------------------
# Output type
# ---------------------------------------------------------------------------

@dataclass
class ScoredPage:
    page: CrawledPage
    page_type: str
    score: int
    included: bool = False


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _base_score(page_type: str, profile: str) -> int:
    return _PROFILE_SCORES.get(profile, {}).get(page_type, _DEFAULT_PAGE_SCORE)


def _content_score(page: CrawledPage, profile: str) -> int:
    word_count = len(page.content.split())
    score = 0

    # Word count signals (universal)
    if word_count > 500:
        score += 2
    elif word_count > 200:
        score += 1
    elif word_count < 100:
        score -= 3

    # Good meta description
    if page.description and len(page.description) > 50:
        score += 2

    # Code blocks boost for documentation
    if profile == "documentation" and "```" in page.content:
        score += 2

    # High link density = index/nav page, less useful
    link_density = page.content.count("](") / max(word_count, 1)
    if link_density > 0.1:
        score -= 2

    return score


# ---------------------------------------------------------------------------
# Main scoring function
# ---------------------------------------------------------------------------

def score_page(
    page: CrawledPage,
    page_clf: PageClassification,
    site_clf: SiteClassification,
    base_url: str,
) -> ScoredPage | None:
    """Returns None for hard-dropped pages."""
    page_type = page_clf.page_type
    profile = site_clf.primary_type

    # Hero (homepage) always top score
    if page.url.rstrip("/") == base_url.rstrip("/"):
        return ScoredPage(page=page, page_type=page_type, score=15, included=True)

    # Hard drop
    if page_type in _HARD_DROP_TYPES:
        return None

    depth_penalty = page.depth
    base = _base_score(page_type, profile)
    content = _content_score(page, profile)
    score = base + content - depth_penalty

    return ScoredPage(page=page, page_type=page_type, score=score)


# ---------------------------------------------------------------------------
# Score all pages with fallback logic
# ---------------------------------------------------------------------------

def score_all(
    pages: list[CrawledPage],
    classification: ClassificationResult,
    base_url: str,
) -> list[ScoredPage]:
    site_clf = classification.site

    def _run(threshold: int) -> list[ScoredPage]:
        results = []
        for page in pages:
            page_clf = classification.pages.get(page.url)
            if page_clf is None:
                continue
            sp = score_page(page, page_clf, site_clf, base_url)
            if sp is None:
                continue
            if sp.score < threshold and sp.score != 15:  # never drop homepage
                continue
            results.append(sp)
        return results

    scored = _run(DROP_THRESHOLD)

    # Relax threshold if too few pages survive
    if len(scored) < 5:
        scored = _run(RELAXED_DROP_THRESHOLD)

    # Mark included, sort by score, cap at MAX_PAGES
    for sp in scored:
        sp.included = sp.score >= DROP_THRESHOLD

    scored.sort(key=lambda x: x.score, reverse=True)
    return scored
