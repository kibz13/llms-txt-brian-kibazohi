"""
llms.txt assembly.

Pipeline:
  1. classifier.py  — site type + page type classification
  2. scorer.py      — page scoring and filtering
  3. generator.py   — prepare structured metadata → Claude → raw llms.txt
                      fallback to heuristic assembly if Claude unavailable

Claude receives only metadata (url, title, description, score, section_hint).
No raw page content is ever sent to Claude.
"""

import json
import logging
import os
import re
from urllib.parse import urlparse

from classifier import classify
from models import CrawledPage
from scorer import DROP_THRESHOLD, OPTIONAL_THRESHOLD, ScoredPage, score_all

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

CLAUDE_MODEL = "claude-sonnet-4-6"

# Heuristic section mapping by page_type (used for section_hint and fallback assembly)
_PAGE_TYPE_SECTION = {
    "guide":     "## Docs",
    "blog_post": "## Blog",
    "product":   "## Product",
    "pricing":   "## Pricing",
    "about":     "## About",
    "faq":       "## FAQ",
    "contact":   "## Contact",
}

SYSTEM_PROMPT = """
You are an expert at generating spec-compliant llms.txt files following the
standard at llmstxt.org. You receive a list of crawled pages from a website
with their metadata and produce a clean, well-structured llms.txt.

You always follow these rules:

STRUCTURE:
- Start with # Site Name on the very first line — use the actual site name,
  strip suffixes like "| Company" or "- Tagline" from title tags
- Follow immediately with > One factual paragraph — what the site does, who
  it is for, and what an LLM needs to know. Written for an LLM reader, not
  a human. No marketing language.
- Group pages into logical H2 sections with clear, descriptive names
- Each page entry: - [Clean Title](url): One sentence description
- ## Optional must always be the last section if used

SECTIONS:
- Create between 3 and 8 sections (excluding ## Optional)
- Never create a section with fewer than 2 pages — fold single pages into
  the most relevant existing section or ## Optional
- Group pages by what they DO, not just their URL structure
- section_hint is a starting point from a rule-based system — use your
  judgment, override it when it is wrong
- For documentation sites, prefer fewer broader sections over many narrow ones

DESCRIPTIONS:
- Write one factual sentence per page (max 120 chars)
- Pages with null descriptions: write from the title and URL alone
- Never use marketing language — write for an LLM reader, not a buyer
- If a description contains navigation text like "Skip to main content", ignore
  it and write a fresh description

INCLUSION:
- Pages with score >= 5 belong in named sections
- Pages with score < 5 belong in ## Optional
- Event pages, conference pages, time-sensitive promotional pages → ## Optional
- Legal, login, signup, brand asset pages → ## Optional or omit entirely
- If a page adds no value to an LLM understanding the site → omit it

DO NOT:
- Add pages that were not in the input
- Include code fences or explanation in your response
- Start with anything before # Site Name
- Use marketing superlatives or promotional language in descriptions

Return only the raw llms.txt content starting with # Site Name.
""".strip()


# ---------------------------------------------------------------------------
# Description sanitisation
# ---------------------------------------------------------------------------

_NAV_PATTERNS = [
    r"^skip to (main )?content$",
    r"^back to top$",
    r"^navigation$",
    r"^menu$",
]


def sanitise_description(text: str | None) -> str | None:
    if not text:
        return None
    # Strip markdown links: [text](url) → text, [](url) → ""
    cleaned = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text).strip()
    # Strip markdown formatting
    cleaned = re.sub(r"[#*`_>]", "", cleaned).strip()
    # Reject navigation/boilerplate text
    if any(re.match(p, cleaned.lower()) for p in _NAV_PATTERNS):
        return None
    if len(cleaned) < 20:
        return None
    # Truncate at last sentence boundary within 120 chars
    if len(cleaned) > 120:
        truncated = cleaned[:120]
        last_period = truncated.rfind(". ")
        if last_period > 60:
            return truncated[: last_period + 1]
        last_space = truncated.rfind(" ")
        return truncated[:last_space] + "…"
    return cleaned


# ---------------------------------------------------------------------------
# Pre-Claude preparation
# ---------------------------------------------------------------------------

def prepare_for_claude(scored_pages: list[ScoredPage], base_url: str) -> list[dict]:
    """
    Build the structured page list sent to Claude.
    Excludes homepage (rendered in header) and hard-dropped pages.
    Sorted by score descending so Claude sees the most important pages first.
    """
    result = []
    for sp in sorted(scored_pages, key=lambda x: x.score, reverse=True):
        if sp.score < DROP_THRESHOLD:
            continue
        if sp.page.url.rstrip("/") == base_url.rstrip("/"):
            continue  # homepage handled separately
        result.append({
            "url":          sp.page.url,
            "title":        sp.page.title or sp.page.url,
            "description":  sanitise_description(sp.page.description),
            "score":        sp.score,
            "section_hint": _PAGE_TYPE_SECTION.get(sp.page_type),
        })
    return result


# ---------------------------------------------------------------------------
# Claude call
# ---------------------------------------------------------------------------

async def _call_claude(
    pages: list[dict],
    site_type: str,
    homepage: CrawledPage,
) -> str | None:
    """
    Ask Claude to generate the full llms.txt from structured page metadata.
    Returns raw llms.txt string, or None if unavailable/failed.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("CLAUDE  ANTHROPIC_API_KEY not set — using heuristic fallback")
        return None

    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=api_key)
    except ImportError:
        logger.warning("CLAUDE  anthropic package not installed — using heuristic fallback")
        return None

    homepage_excerpt = " ".join(homepage.content.split()[:200])

    user_message = (
        f"Site type: {site_type}\n"
        f"Homepage title: {homepage.title}\n"
        f"Homepage description: {sanitise_description(homepage.description) or '(none)'}\n"
        f"Homepage excerpt (first 200 words):\n{homepage_excerpt}\n\n"
        f"Pages (sorted by score, highest first):\n"
        f"{json.dumps(pages, indent=2)}\n\n"
        f"Generate the llms.txt file for this site."
    )

    logger.info("CLAUDE  sending %d pages (site_type=%s)", len(pages), site_type)

    try:
        message = await client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        result = message.content[0].text.strip()
        if not result.startswith("#"):
            logger.warning("CLAUDE  response did not start with # — discarding")
            return None
        logger.info("CLAUDE  success (%d chars)", len(result))
        return result
    except Exception as exc:
        logger.warning("CLAUDE  call failed: %s — using heuristic fallback", exc)
        return None


# ---------------------------------------------------------------------------
# Heuristic fallback assembly
# ---------------------------------------------------------------------------

def _build_summary(homepage: CrawledPage, base_url: str) -> str:
    if homepage.description and len(homepage.description) > 50:
        return homepage.description
    for line in homepage.content.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and not line.startswith("-") and not line.startswith("!"):
            return line[:300]
    return f"Website at {base_url}."


def _clean_title(title: str | None, base_domain: str) -> str | None:
    if not title:
        return None
    cleaned = re.sub(
        r"\s*[|\-–—]\s*" + re.escape(base_domain) + r".*",
        "", title, flags=re.IGNORECASE
    ).strip()
    cleaned = re.sub(r"\s*[|\-–—]\s*\w[\w\s]{10,}$", "", cleaned).strip()
    return cleaned or title


def _assemble_heuristic(
    homepage: CrawledPage,
    base_url: str,
    base_domain: str,
    scored_pages: list[ScoredPage],
) -> str:
    """Heuristic fallback — used when Claude is unavailable or fails."""
    sections: dict[str, list[ScoredPage]] = {}
    optional: list[ScoredPage] = []

    for sp in scored_pages:
        if sp.page.url.rstrip("/") == base_url.rstrip("/"):
            continue
        if sp.score < OPTIONAL_THRESHOLD:
            optional.append(sp)
            continue
        section = _PAGE_TYPE_SECTION.get(sp.page_type)
        if section:
            sections.setdefault(section, []).append(sp)
        else:
            optional.append(sp)

    if not sections and optional:
        for sp in optional:
            section = _PAGE_TYPE_SECTION.get(sp.page_type, "## Other")
            sections.setdefault(section, []).append(sp)
        optional = []

    site_name = _clean_title(homepage.title, base_domain) or urlparse(base_url).netloc
    summary   = _build_summary(homepage, base_url)

    lines = [f"# {site_name}", "", f"> {summary}", ""]

    for section, pages in sections.items():
        lines.append(section)
        lines.append("")
        for sp in pages:
            title  = _clean_title(sp.page.title, base_domain) or sp.page.url
            desc   = sanitise_description(sp.page.description) or ""
            suffix = f": {desc}" if desc else ""
            lines.append(f"- [{title}]({sp.page.url}){suffix}")
        lines.append("")

    if optional:
        lines.append("## Optional")
        lines.append("")
        for sp in optional:
            title  = _clean_title(sp.page.title, base_domain) or sp.page.url
            desc   = sanitise_description(sp.page.description) or ""
            suffix = f": {desc}" if desc else ""
            lines.append(f"- [{title}]({sp.page.url}){suffix}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def generate(pages: list[CrawledPage]) -> str:
    if not pages:
        return ""

    # Find homepage
    homepage = next(
        (p for p in pages if urlparse(p.url).path in ("/", "")),
        pages[0],
    )
    base_url    = homepage.url
    base_domain = urlparse(base_url).netloc

    # Deduplicate by content hash
    seen: set[str] = set()
    unique: list[CrawledPage] = []
    for page in pages:
        if page.content_hash in seen:
            logger.debug("DEDUP  %s", page.url)
            continue
        seen.add(page.content_hash)
        unique.append(page)

    logger.info("CLASSIFY  %d unique pages (%d dupes dropped)", len(unique), len(pages) - len(unique))

    classification = classify(unique)
    site = classification.site
    logger.info(
        "SITE  primary=%s  confidence=%s",
        site.primary_type,
        {k: f"{v:.2f}" for k, v in site.confidence.items()},
    )

    scored  = score_all(unique, classification, base_url)
    prepared = prepare_for_claude(scored, base_url)

    result = await _call_claude(prepared, site.primary_type, homepage)
    if result:
        return result

    # Heuristic fallback
    logger.info("ASSEMBLE  heuristic fallback")
    return _assemble_heuristic(homepage, base_url, base_domain, scored)
