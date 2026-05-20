"""
URL pre-filtering and pre-crawl prioritisation.

Decides, from the URL alone (before any HTTP request is made):
  - should_skip(url)              — should we crawl this URL at all?
  - score_url(url)                — how valuable is this URL? (used to sort the crawl queue)
  - normalise_url(url)            — canonical form to prevent duplicate crawling
  - same_domain(base, url)
  - detect_lang_prefix(urls)      — detect multi-language site and preferred language
  - filter_language_variants(urls) — keep only preferred language URLs
  - is_non_preferred_lang(url, preferred) — per-URL check for BFS filtering
"""

import re
from urllib.parse import parse_qs, urlparse

from classifier import classify_url
from scorer import DEFAULT_PAGE_SCORE, PAGE_TYPE_SCORES, compute_url_boost

# ---------------------------------------------------------------------------
# Skip constants
# ---------------------------------------------------------------------------

SKIP_PATTERNS = re.compile(
    r"(/cdn-cgi/|\.pdf$|\.jpg$|\.jpeg$|\.png$|\.gif$|\.svg$|\.ico$|#|/page:\d)",
    re.IGNORECASE,
)

# Paths that are never useful to an LLM — skipped before any crawl request is made.
PATH_BLACKLIST = (
    # Metadata & taxonomy hubs
    "/tag/", "/tags/", "/category/", "/categories/", "/archive/", "/archives/",
    "/author/", "/authors/", "/topic/", "/topics/", "/labels/",
    # Structural noise
    "/page/", "/pages/", "/search", "/query", "/feed/", "/rss",
    # Auth & account
    "/login", "/signup", "/register", "/signin", "/logout", "/profile",
    "/settings", "/cart", "/checkout", "/billing",
    # Legal & footers
    "/privacy", "/privacy-policy", "/terms", "/tos", "/cookie-policy",
    "/legal", "/license", "/dpa",
    # App shell & admin (login-walled, no useful content for LLMs)
    "/dashboard", "/app/", "/console", "/admin",
)

# Query parameters that indicate duplicate content, pagination, tracking, or UI state.
# Any URL whose query string contains one of these keys is skipped.
QUERY_PARAM_BLACKLIST = frozenset({
    # Pagination
    "page", "p", "offset", "cursor", "limit", "start",
    # Sorting & filtering
    "sort", "order", "orderby", "filter", "category", "tag", "view",
    # Tracking & sessions
    "gclid", "session", "sid", "ph",
    # Actions
    "action", "replytocom", "share", "print",
})


# ---------------------------------------------------------------------------
# URL utilities
# ---------------------------------------------------------------------------

def normalise_url(url: str) -> str:
    """
    Canonicalise a URL to prevent duplicate crawling:
    - Lowercase scheme and host
    - Remove default ports (80 for http, 443 for https)
    - Strip trailing slash from non-root paths  (/about/ → /about)
    - Remove fragment
    """
    p = urlparse(url)
    scheme = p.scheme.lower()
    host   = p.netloc.lower()

    # Strip default port
    if ":" in host:
        hostname, port = host.rsplit(":", 1)
        if (scheme == "http" and port == "80") or (scheme == "https" and port == "443"):
            host = hostname

    # Strip trailing slash except on root
    path = p.path if p.path != "/" else "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    return p._replace(scheme=scheme, netloc=host, path=path, fragment="").geturl()


def same_domain(base: str, url: str) -> bool:
    return urlparse(url).netloc == urlparse(base).netloc


# ---------------------------------------------------------------------------
# URL filtering
# ---------------------------------------------------------------------------

def _path_blacklisted(path: str) -> bool:
    for entry in PATH_BLACKLIST:
        prefix = entry if entry.endswith("/") else entry + "/"
        exact  = entry.rstrip("/")
        if path == exact or path.startswith(prefix):
            return True
    return False


def should_skip(url: str) -> bool:
    if SKIP_PATTERNS.search(url):
        return True
    parsed = urlparse(url)
    if _path_blacklisted(parsed.path):
        return True
    if parsed.query:
        params = {k.lower() for k in parse_qs(parsed.query)}
        if params & QUERY_PARAM_BLACKLIST:
            return True
        if any(k.startswith("utm_") for k in params):
            return True
    return False


# ---------------------------------------------------------------------------
# Multi-language deduplication
# ---------------------------------------------------------------------------

# Known language codes that commonly appear as the first URL path segment.
_LANG_CODES = frozenset([
    # ISO 639-1 (2-letter)
    "en", "fr", "de", "it", "es", "pt", "nl", "ru", "zh", "ja", "ko",
    "pl", "sv", "no", "da", "fi", "cs", "sk", "hu", "ro", "tr", "ar",
    "he", "th", "vi", "id", "ms",
    # ISO 639-2 (3-letter)
    "eng", "fra", "deu", "ita", "pol", "esp", "por", "nld", "rus",
    "zho", "jpn", "kor", "swe", "nor", "dan", "fin", "ces", "slk",
    "hun", "ron", "tur", "ara", "heb", "tha", "vie", "ind", "msa",
])

# English is preferred for LLM context — check these codes first.
_ENGLISH_CODES = frozenset(["en", "eng"])


def detect_lang_prefix(urls: list[str]) -> str | None:
    """
    Scan a URL list for multi-language path prefixes.

    Returns the preferred language code to keep, or None if the site does
    not appear to use language-prefixed URLs. A site is considered
    multi-language only when 2+ distinct known language codes appear as
    the first path segment. English is preferred; otherwise the language
    with the most URLs wins.
    """
    counts: dict[str, int] = {}
    for url in urls:
        parts = [p for p in urlparse(url).path.split("/") if p]
        if parts and parts[0].lower() in _LANG_CODES:
            code = parts[0].lower()
            counts[code] = counts.get(code, 0) + 1

    if len(counts) < 2:
        return None  # single-language or no language prefix

    for code in _ENGLISH_CODES:
        if code in counts:
            return code

    return max(counts, key=lambda c: counts[c])


def filter_language_variants(urls: list[str]) -> list[str]:
    """
    For multi-language sites, keep only URLs in the preferred language.
    URLs with no language prefix are always kept.
    Returns the original list unchanged for single-language sites.
    """
    preferred = detect_lang_prefix(urls)
    if preferred is None:
        return urls

    result = []
    for url in urls:
        parts = [p for p in urlparse(url).path.split("/") if p]
        if not parts or parts[0].lower() not in _LANG_CODES:
            result.append(url)          # no language prefix — keep
        elif parts[0].lower() == preferred:
            result.append(url)          # preferred language — keep
        # else: non-preferred language variant — drop
    return result


def is_non_preferred_lang(url: str, preferred: str) -> bool:
    """
    Returns True if the URL has a language prefix that is NOT the preferred
    language. Used for per-link filtering in BFS mode where the preferred
    language has already been detected.
    """
    parts = [p for p in urlparse(url).path.split("/") if p]
    if not parts:
        return False
    return parts[0].lower() in _LANG_CODES and parts[0].lower() != preferred


# ---------------------------------------------------------------------------
# Pre-crawl URL scoring
# ---------------------------------------------------------------------------

def score_url(url: str) -> int:
    """
    Estimate page importance from URL path alone — used to sort the crawl queue
    before content is available. Combines classify_url() base score with
    compute_url_boost() so pre-crawl and post-crawl priorities use the same signals.
    """
    page_type = classify_url(url).page_type
    boost = compute_url_boost(url)
    if page_type in PAGE_TYPE_SCORES:
        return PAGE_TYPE_SCORES[page_type] + boost
    # "other" / "hero": fall back to depth-based heuristic
    depth = len([s for s in urlparse(url).path.split("/") if s])
    return max(DEFAULT_PAGE_SCORE, 3 - depth) + boost
