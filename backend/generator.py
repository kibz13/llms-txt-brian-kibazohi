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

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

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
- URLs in page entries must use the .md form: append .md to the original URL
  (e.g. /about → /about.md, / → /index.html.md, /docs/ → /docs/index.html.md)
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
- Blog/news sections: include a maximum of 8–10 representative posts across
  categories — do not list every post. Prefer research studies and original
  data over commentary and opinion pieces
- Product announcements: include only the most significant launches; omit
  minor updates and incremental feature additions

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
# Markdown URL conversion (llms.txt spec)
# ---------------------------------------------------------------------------

def to_md_url(url: str) -> str:
    """
    Return the .md equivalent of a page URL per the llms.txt spec:
      /          →  /index.html.md
      /about     →  /about.md
      /docs/api  →  /docs/api.md
    URLs ending in / (directory-style) get index.html.md; all others get .md.
    Our URL normaliser strips trailing slashes, so only the root path hits the
    first branch in practice.
    """
    parsed = urlparse(url)
    path   = parsed.path
    if not path or path == "/":
        new_path = "/index.html.md"
    elif path.endswith("/"):
        new_path = path + "index.html.md"
    else:
        new_path = path + ".md"
    return parsed._replace(path=new_path).geturl()


# ---------------------------------------------------------------------------
# Template deduplication
# ---------------------------------------------------------------------------

def _template_key(url: str) -> str:
    """
    Return a structural group key by stripping the content slug (last segment).
    Groups pages that share the same parent path so we can cap entries per group.

    /blog/my-post.md         → /blog
    /docs/api/list-all.md    → /docs/api
    /v1/reference/create.md  → /v1/reference
    """
    path = urlparse(url).path.rstrip("/")
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 2:
        return "/" + "/".join(parts[:-1])
    return path or "/"


_NO_DEDUP_SECTIONS = {"## Docs"}  # every docs page is individually valuable


def _dedup_templates(pages: list[dict], max_per_group: int = 8) -> list[dict]:
    """
    Keep at most max_per_group pages per structural URL group.
    Input must be sorted by score descending so the highest-value pages
    in each group are retained when the cap is reached.

    Docs sections are exempt — /guide/philosophy and /guide/performance are
    genuinely distinct pages, not templates. The cap targets editorial sections
    (blog, changelog) where many entries really are interchangeable.
    """
    counts: dict[str, int] = {}
    result = []
    for page in pages:
        if page.get("section_hint") in _NO_DEDUP_SECTIONS:
            result.append(page)
            continue
        key = _template_key(page["url"])
        n = counts.get(key, 0)
        if n < max_per_group:
            counts[key] = n + 1
            result.append(page)
    return result


# ---------------------------------------------------------------------------
# Pre-Claude preparation
# ---------------------------------------------------------------------------

def prepare_for_claude(scored_pages: list[ScoredPage], base_url: str) -> list[dict]:
    """
    Build the structured page list sent to Claude.
    Excludes homepage (rendered in header) and hard-dropped pages.
    Sorted by score descending so Claude sees the most important pages first.
    Template deduplication keeps at most 8 pages per structural URL group.
    """
    dropped_by_score: list[tuple[float, str]] = []
    result = []
    for sp in sorted(scored_pages, key=lambda x: x.score, reverse=True):
        if sp.page.url.rstrip("/") == base_url.rstrip("/"):
            continue  # homepage handled separately
        if sp.score < DROP_THRESHOLD:
            dropped_by_score.append((sp.score, sp.page.url))
            continue
        result.append({
            "url":          to_md_url(sp.page.url),
            "title":        sp.page.title or sp.page.url,
            "description":  sanitise_description(sp.page.description),
            "score":        sp.score,
            "section_hint": _PAGE_TYPE_SECTION.get(sp.page_type),
        })
    deduped = _dedup_templates(result)
    deduped_urls = {p["url"] for p in deduped}
    dropped_by_dedup = [p for p in result if p["url"] not in deduped_urls]

    logger.info(
        "PREPARE  %d scored  →  %d after drop  →  %d sent to Claude  (DROP_THRESHOLD=%s)",
        len(scored_pages) - 1,  # exclude homepage
        len(result),
        len(deduped),
        DROP_THRESHOLD,
    )

    logger.info("SENT (%d):", len(deduped))
    for p in deduped:
        logger.info("  [SEND]  score=%-4s  hint=%-16s  %s", p["score"], p["section_hint"] or "(none)", p["url"])

    if dropped_by_dedup:
        logger.info("DEDUPED OUT (%d):", len(dropped_by_dedup))
        for p in dropped_by_dedup:
            logger.info("  [DEDUP] score=%-4s  hint=%-16s  %s", p["score"], p["section_hint"] or "(none)", p["url"])

    if dropped_by_score:
        logger.info("DROPPED BY SCORE (%d):", len(dropped_by_score))
        for score, url in dropped_by_score:
            logger.info("  [DROP]  score=%-4s  %s", score, url)

    return deduped


# ---------------------------------------------------------------------------
# Claude call
# ---------------------------------------------------------------------------

async def _call_claude(
    pages: list[dict],
    homepage: CrawledPage,
) -> tuple[str, int, int] | None:
    """
    Ask Claude to generate the full llms.txt from structured page metadata.
    Returns (llms_txt, tokens_in, tokens_out), or None if unavailable/failed.
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
        f"Homepage title: {homepage.title}\n"
        f"Homepage description: {sanitise_description(homepage.description) or '(none)'}\n"
        f"Homepage excerpt (first 200 words):\n{homepage_excerpt}\n\n"
        f"Pages (sorted by score, highest first):\n"
        f"{json.dumps(pages, indent=2)}\n\n"
        f"Generate the llms.txt file for this site."
    )

    logger.info("CLAUDE  sending %d pages", len(pages))

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
        tokens_in  = message.usage.input_tokens
        tokens_out = message.usage.output_tokens
        logger.info(
            "CLAUDE  success  chars=%d  tokens_in=%d  tokens_out=%d",
            len(result), tokens_in, tokens_out,
        )
        return result, tokens_in, tokens_out
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
            lines.append(f"- [{title}]({to_md_url(sp.page.url)}){suffix}")
        lines.append("")

    if optional:
        lines.append("## Optional")
        lines.append("")
        for sp in optional:
            title  = _clean_title(sp.page.title, base_domain) or sp.page.url
            desc   = sanitise_description(sp.page.description) or ""
            suffix = f": {desc}" if desc else ""
            lines.append(f"- [{title}]({to_md_url(sp.page.url)}){suffix}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def generate(pages: list[CrawledPage]) -> tuple[str, int, int]:
    """
    Returns (llms_txt, tokens_in, tokens_out).
    tokens_in/tokens_out are 0 when the heuristic fallback is used.
    """
    if not pages:
        return "", 0, 0

    # Find homepage
    homepage = next(
        (p for p in pages if urlparse(p.url).path in ("/", "")),
        pages[0],
    )
    base_url    = homepage.url
    base_domain = urlparse(base_url).netloc

    logger.info("CLASSIFY  %d pages", len(pages))

    classification = classify(pages)
    scored         = score_all(pages, classification, base_url)
    prepared       = prepare_for_claude(scored, base_url)

    claude_result = await _call_claude(prepared, homepage)
    if claude_result:
        llms_txt, tokens_in, tokens_out = claude_result
        return llms_txt, tokens_in, tokens_out

    # Heuristic fallback — no tokens used
    logger.info("ASSEMBLE  heuristic fallback")
    return _assemble_heuristic(homepage, base_url, base_domain, scored), 0, 0
