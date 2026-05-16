"""
Weighted heuristic rule based approach as a fallback mechanism when API calls to an LLM fails or when retries are exhausted.

Logic
Every page gets a score. High scoring pages go into primary sections. Low scoring pages go into ## Optional or get dropped entirely (very low scores). The sections themselves are determined by URL
patterns and content signals.


/docs/, /documentation/     → +10  (almost certainly important)
/api/, /reference/          → +10
/guide/, /tutorial/         → +8
/getting-started/, /quickstart/ → +8
/about/, /overview/         → +6
/blog/, /news/, /changelog/ → +3  (informational but secondary)
/pricing/                   → +2
/legal/, /privacy/, /terms/ → -5  (rarely useful for LLMs)
/cdn-cgi/, /assets/         → skip entirely
Depth from homepage         → -2 per level (deeper = less important)
Is homepage                 → +15 (always included)


Has meta description        → +3
Description length > 50 chars → +2
Page content length > 500 words → +3
Has H1 matching page title  → +2
Has code blocks             → +4  (technical content = high value)
High link density (nav page) → -3 (navigation pages add little value)
Very short content < 100 words → -4
Duplicate/near-duplicate of another page → skip


/docs/*, /documentation/*   → ## Docs
/api/*, /reference/*        → ## API Reference
/guide/*, /tutorial/*       → ## Guides
/blog/*, /news/*            → ## Blog (or ## Optional)
/about, /overview           → ## About
/examples/*, /demos/*       → ## Examples
everything else             → ## Optional
"""

import re
from urllib.parse import urlparse

from models import Page

DROP_THRESHOLD = 0
OPTIONAL_THRESHOLD = 5

URL_SCORES = [
    (r"/docs?/", 10),
    (r"/documentation/", 10),
    (r"/api/", 10),
    (r"/reference/", 10),
    (r"/guide/", 8),
    (r"/tutorial/", 8),
    (r"/getting-started/", 8),
    (r"/quickstart/", 8),
    (r"/about", 6),
    (r"/overview", 6),
    (r"/blog/", 3),
    (r"/news/", 3),
    (r"/changelog/", 3),
    (r"/pricing", 2),
    (r"/legal/", -5),
    (r"/privacy", -5),
    (r"/terms", -5),
]

SKIP_URL = re.compile(r"/cdn-cgi/|/assets/", re.IGNORECASE)

SECTION_PATTERNS = [
    (r"/docs?/|/documentation/", "## Docs"),
    (r"/api/|/reference/", "## API Reference"),
    (r"/guide/|/tutorial/", "## Guides"),
    (r"/blog/|/news/", "## Blog"),
    (r"/about|/overview", "## About"),
    (r"/examples?/|/demos?/", "## Examples"),
]


def score_page(page: Page, base_url: str) -> int:
    path = urlparse(page.url).path

    if SKIP_URL.search(path):
        return -999

    # Homepage always wins
    if page.url.rstrip("/") == base_url.rstrip("/"):
        return 15

    score = 0

    # URL pattern scoring
    for pattern, points in URL_SCORES:
        if re.search(pattern, path, re.IGNORECASE):
            score += points
            break

    # Depth penalty
    score -= page.depth * 2

    # Content signals
    word_count = len(page.content.split())

    if page.description:
        score += 3
        if len(page.description) > 50:
            score += 2

    if word_count > 500:
        score += 3
    elif word_count < 100:
        score -= 4

    # H1 matching title
    if page.title and f"# {page.title}" in page.content:
        score += 2

    # Code blocks = technical content
    if "```" in page.content:
        score += 4

    # High link density = navigation page
    link_count = page.content.count("](")
    if word_count > 0 and link_count / max(word_count, 1) > 0.1:
        score -= 3

    return score


def get_section(url: str) -> str:
    path = urlparse(url).path
    for pattern, section in SECTION_PATTERNS:
        if re.search(pattern, path, re.IGNORECASE):
            return section
    return "## Optional"


def generate(pages: list[Page]) -> str:
    if not pages:
        return ""

    base_url = pages[0].url
    homepage = pages[0]

    # Score and deduplicate
    scored = []
    seen_fingerprints = set()

    for page in pages:
        fingerprint = " ".join(page.content.split()[:50])
        if fingerprint and fingerprint in seen_fingerprints:
            continue
        if fingerprint:
            seen_fingerprints.add(fingerprint)

        s = score_page(page, base_url)
        if s != -999:
            scored.append((s, page))

    scored.sort(key=lambda x: x[0], reverse=True)

    # Bucket into sections
    primary: dict[str, list[Page]] = {}
    optional: list[Page] = []

    for s, page in scored:
        if page.url.rstrip("/") == base_url.rstrip("/"):
            continue  # homepage is the header, not a list entry

        if s < DROP_THRESHOLD:
            continue

        section = get_section(page.url)
        if s < OPTIONAL_THRESHOLD or section == "## Optional":
            optional.append(page)
        else:
            primary.setdefault(section, []).append(page)

    # Build llms.txt
    lines = []

    site_name = homepage.title or urlparse(base_url).netloc
    lines.append(f"# {site_name}")
    lines.append("")

    lines.append(f"> {homepage.description}")
    lines.append("")

    for section, section_pages in primary.items():
        lines.append(section)
        lines.append("")
        for page in section_pages:
            lines.append(f"- [{page.title or page.url}]({page.url}): {page.description}")
        lines.append("")

    if optional:
        lines.append("## Optional")
        lines.append("")
        for page in optional:
            lines.append(f"- [{page.title or page.url}]({page.url}): {page.description}")
        lines.append("")

    return "\n".join(lines)
