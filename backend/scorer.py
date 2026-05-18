"""
Page scoring.

Scorer's only job: decide which pages are valuable and how valuable.
Section assignment and grouping is handled by the generator.

Scores are universal — not profile-dependent.
"""

from dataclasses import dataclass

from classifier import PageClassification
from models import CrawledPage

DROP_THRESHOLD         = 0
OPTIONAL_THRESHOLD     = 5
RELAXED_DROP_THRESHOLD = -3

# Base score per page_type — universal across all site types
_PAGE_TYPE_SCORES: dict[str, int] = {
    "guide":     8,
    "product":   7,
    "pricing":   6,
    "about":     5,
    "faq":       5,
    "blog_post": 4,
    "contact":   2,
}

_DEFAULT_PAGE_SCORE = 1  # any page_type not in the table (e.g. "other")


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

def _base_score(page_type: str) -> int:
    return _PAGE_TYPE_SCORES.get(page_type, _DEFAULT_PAGE_SCORE)


def _content_score(page: CrawledPage) -> int:
    word_count = len(page.content.split())
    score = 0

    # Word count signals
    if word_count > 500:
        score += 2
    elif word_count > 200:
        score += 1
    elif word_count < 100:
        score -= 3

    # Good meta description
    if page.description and len(page.description) > 50:
        score += 2

    # Code blocks indicate technical content
    if "```" in page.content:
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
    base_url: str,
) -> ScoredPage:
    page_type = page_clf.page_type

    # Hero (homepage) always top score
    if page.url.rstrip("/") == base_url.rstrip("/"):
        return ScoredPage(page=page, page_type=page_type, score=15, included=True)

    depth_penalty = page.depth
    score = _base_score(page_type) + _content_score(page) - depth_penalty

    return ScoredPage(page=page, page_type=page_type, score=score)


# ---------------------------------------------------------------------------
# Score all pages with fallback logic
# ---------------------------------------------------------------------------

def score_all(
    pages: list[CrawledPage],
    classification: dict[str, PageClassification],
    base_url: str,
) -> list[ScoredPage]:
    def _run(threshold: int) -> list[ScoredPage]:
        results = []
        for page in pages:
            page_clf = classification.get(page.url)
            if page_clf is None:
                continue
            sp = score_page(page, page_clf, base_url)
            if sp.score < threshold and sp.score != 15:  # never drop homepage
                continue
            results.append(sp)
        return results

    scored = _run(DROP_THRESHOLD)

    # Relax threshold if too few pages survive
    if len(scored) < 5:
        scored = _run(RELAXED_DROP_THRESHOLD)

    # Mark included, sort by score
    for sp in scored:
        sp.included = sp.score >= DROP_THRESHOLD

    scored.sort(key=lambda x: x.score, reverse=True)
    return scored
