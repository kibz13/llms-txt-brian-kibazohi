import asyncio
import json
import logging
import re
import sys
from datetime import datetime, timezone
from urllib.parse import parse_qs, urljoin, urlparse
from xml.etree import ElementTree as ET

import httpx
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig

from classifier import classify_url
from models import CrawledPage, CrawlResult
from scorer import DEFAULT_PAGE_SCORE, PAGE_TYPE_SCORES

logger = logging.getLogger(__name__)

PAGE_CAP       = 100
MAX_CONCURRENT = 10   # max parallel requests to a single domain

SKIP_PATTERNS = re.compile(
    r"(/cdn-cgi/|\.pdf$|\.jpg$|\.jpeg$|\.png$|\.gif$|\.svg$|\.ico$|#)",
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


_CRAWL_CONFIG = CrawlerRunConfig(
    # Fixed delay instead of waiting for a specific selector — the selector
    # approach caused 30s timeouts on sites that use different DOM structure.
    # 1s is enough for most JS frameworks to render their initial content.
    page_timeout=30000,
    delay_before_return_html=1.0,
)

_HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; llmstxt-bot/1.0)"}


# ---------------------------------------------------------------------------
# Robots.txt helpers
# ---------------------------------------------------------------------------

async def _fetch_text(url: str, timeout: float = 10.0) -> str | None:
    """Fetch plain text from a URL. Returns None on any error."""
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers=_HTTP_HEADERS,
        ) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                return resp.text
    except Exception:
        pass
    return None


def _parse_robots(text: str) -> tuple[list[str], str | None]:
    """
    Parse robots.txt.
    Returns (disallowed_prefixes, sitemap_url).
    Only respects User-agent: * rules.
    """
    disallowed: list[str] = []
    sitemap_url: str | None = None
    in_wildcard_block = False

    for raw_line in text.splitlines():
        line = raw_line.split("#")[0].strip()
        if not line:
            continue

        lower = line.lower()

        if lower.startswith("user-agent:"):
            agent = line.split(":", 1)[1].strip()
            in_wildcard_block = (agent == "*")

        elif lower.startswith("disallow:") and in_wildcard_block:
            path = line.split(":", 1)[1].strip()
            if path:  # empty Disallow means "allow all"
                disallowed.append(path)

        elif lower.startswith("sitemap:"):
            # Take the first Sitemap: directive found
            if sitemap_url is None:
                raw = line.split(":", 1)[1].strip()
                # Reconstruct full URL if protocol-relative
                sitemap_url = "https:" + raw if raw.startswith("//") else raw

    return disallowed, sitemap_url


def _is_disallowed(url: str, disallowed_prefixes: list[str]) -> bool:
    path = urlparse(url).path
    return any(path.startswith(prefix) for prefix in disallowed_prefixes)


# ---------------------------------------------------------------------------
# Sitemap helpers
# ---------------------------------------------------------------------------

async def _parse_sitemap(
    sitemap_url: str,
    base_url: str,
    disallowed: list[str],
    _depth: int = 0,
) -> list[str]:
    """
    Recursively parse a sitemap or sitemap index.
    Returns filtered list of same-domain URLs.
    Caps recursion at depth 2 (handles most sitemap index structures).
    """
    if _depth > 3:
        return []

    text = await _fetch_text(sitemap_url)
    if not text:
        return []

    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        logger.warning("SITEMAP  parse error for %s", sitemap_url)
        return []

    # Detect sitemap index vs regular sitemap by tag name (strip namespace)
    tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag

    if tag == "sitemapindex":
        # Fetch up to 10 child sitemaps
        # findall supports {*} namespace wildcard; iter() does not
        child_locs = [el.text.strip() for el in root.findall(".//{*}loc") if el.text]
        urls: list[str] = []
        for child_url in child_locs[:10]:
            child_urls = await _parse_sitemap(child_url, base_url, disallowed, _depth + 1)
            urls.extend(child_urls)
        return urls

    # Regular <urlset> — collect <loc> values
    urls = []
    for loc_el in root.findall(".//{*}loc"):
        url = loc_el.text.strip() if loc_el.text else ""
        if not url:
            continue
        clean = normalise_url(url)
        if not same_domain(base_url, clean):
            continue
        if should_skip(clean):
            continue
        if _is_disallowed(clean, disallowed):
            continue
        urls.append(clean)

    return urls


async def _get_sitemap_urls(
    base_url: str,
    robots_sitemap: str | None,
    disallowed: list[str],
) -> list[str]:
    """
    Try to get URLs from sitemap.
    Checks robots.txt Sitemap: hint first, then falls back to /sitemap.xml.
    Returns empty list if neither yields URLs.
    """
    parsed = urlparse(base_url)
    default_sitemap = f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"

    candidates = []
    if robots_sitemap:
        candidates.append(robots_sitemap)
    if default_sitemap not in candidates:
        candidates.append(default_sitemap)

    for sitemap_url in candidates:
        logger.info("SITEMAP  trying %s", sitemap_url)
        urls = await _parse_sitemap(sitemap_url, base_url, disallowed)
        if urls:
            logger.info("SITEMAP  found %d URLs at %s", len(urls), sitemap_url)
            return urls

    logger.info("SITEMAP  not found — falling back to BFS crawl")
    return []


# ---------------------------------------------------------------------------
# Shared crawl helpers
# ---------------------------------------------------------------------------

def score_url(url: str) -> int:
    """
    Estimate page importance from URL path alone — used to prioritise the
    crawl queue before content is available.
    Derives score from classify_url() + PAGE_TYPE_SCORES (same source of truth
    as post-crawl scoring). Shallower unrecognised paths score higher than deeper ones.
    """
    page_type = classify_url(url).page_type
    if page_type in PAGE_TYPE_SCORES:
        return PAGE_TYPE_SCORES[page_type]
    # "other" / "hero": fall back to depth-based heuristic
    depth = len([s for s in urlparse(url).path.split("/") if s])
    return max(DEFAULT_PAGE_SCORE, 3 - depth)


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


def extract_title(result) -> str:
    if result.metadata and result.metadata.get("title"):
        return result.metadata["title"]
    for line in (result.markdown or "").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def extract_description(result) -> str:
    if result.metadata and result.metadata.get("description"):
        return result.metadata["description"]
    for line in (result.markdown or "").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and not line.startswith("-"):
            return line
    return ""


def extract_links(result, base_url: str) -> list[str]:
    links = []
    for link in result.links.get("internal", []):
        href = link.get("href", "")
        if not href:
            continue
        absolute = normalise_url(urljoin(base_url, href))
        if same_domain(base_url, absolute) and not should_skip(absolute):
            links.append(absolute)
    return links


async def _fetch(crawler, url: str, semaphore: asyncio.Semaphore):
    async with semaphore:
        return await crawler.arun(url=url, config=_CRAWL_CONFIG)


_ANTIBOT_SIGNALS = (
    "err_connection_refused",
    "antibot",
    "err_tunnel_connection_failed",
    "403",
    "blocked",
)


def _is_antibot_error(msg: str) -> bool:
    lower = msg.lower()
    return any(s in lower for s in _ANTIBOT_SIGNALS)


def _process_results(
    to_crawl: list[str],
    results: list,
    depth: int,
    pages: list[CrawledPage],
    base_url: str,
    visited: set[str],
    errors: list[str],
) -> list[str]:
    """
    Process a batch of crawl results. Appends to pages in place.
    Appends error strings to errors in place.
    Returns next-level URLs (for BFS mode only; ignored in sitemap mode).
    """
    next_level_seen: set[str] = set()
    next_level: list[str] = []

    for u, result in zip(to_crawl, results):
        if isinstance(result, Exception):
            msg = str(result)
            logger.warning("CRAWL  error %s — %s", u, msg)
            errors.append(msg)
            continue
        if not result.success:
            msg = getattr(result, "error_message", "") or ""
            logger.warning("CRAWL  failed %s — %s", u, msg)
            errors.append(msg)
            continue

        pages.append(CrawledPage(
            url=u,
            title=extract_title(result),
            description=extract_description(result),
            content=result.markdown or "",
            depth=depth,
        ))

        for link in extract_links(result, base_url):
            if link not in visited and link not in next_level_seen:
                next_level_seen.add(link)
                next_level.append(link)

    return next_level


# ---------------------------------------------------------------------------
# Main crawl entry point
# ---------------------------------------------------------------------------

async def crawl(url: str, depth: int) -> CrawlResult:
    url       = normalise_url(url)
    visited: set[str] = set()
    pages:   list[CrawledPage] = []
    errors:  list[str] = []
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    # Step 1: robots.txt — get disallow rules and sitemap hint
    parsed_base  = urlparse(url)
    robots_url   = f"{parsed_base.scheme}://{parsed_base.netloc}/robots.txt"
    robots_text  = await _fetch_text(robots_url)
    disallowed, robots_sitemap = [], None
    if robots_text:
        disallowed, robots_sitemap = _parse_robots(robots_text)
        logger.info(
            "ROBOTS  disallowed=%d paths  sitemap_hint=%s",
            len(disallowed), robots_sitemap or "none",
        )

    # Step 2: sitemap — try to get URL list
    sitemap_urls = await _get_sitemap_urls(url, robots_sitemap, disallowed)

    async with AsyncWebCrawler(verbose=False) as crawler:

        if sitemap_urls:
            # --- Sitemap mode: crawl flat list from sitemap ---
            # Deduplicate, then sort by URL priority so the PAGE_CAP budget
            # is spent on the highest-value pages when the sitemap is large.
            seen_set: set[str] = set()
            unique_rest: list[str] = []
            for u in sitemap_urls:
                if u != url and u not in seen_set:
                    seen_set.add(u)
                    unique_rest.append(u)
            unique_rest.sort(key=score_url, reverse=True)
            # Homepage always first, then highest-scored pages up to PAGE_CAP
            queue = [url] + unique_rest
            queue = queue[:PAGE_CAP]

            logger.info("SITEMAP  crawling %d URLs in batches", len(queue))

            # Crawl in batches of MAX_CONCURRENT * 4 to keep memory bounded
            batch_size = MAX_CONCURRENT * 4
            for i in range(0, len(queue), batch_size):
                batch = [u for u in queue[i:i + batch_size] if u not in visited]
                if not batch:
                    continue
                for u in batch:
                    visited.add(u)

                logger.info(
                    "SITEMAP  batch %d/%d  fetching=%d",
                    i // batch_size + 1, -(-len(queue) // batch_size), len(batch),
                )
                results = await asyncio.gather(
                    *[_fetch(crawler, u, semaphore) for u in batch],
                    return_exceptions=True,
                )
                # depth=1 for all sitemap pages (homepage gets depth=0 via position)
                page_depth = 0 if i == 0 else 1
                _process_results(batch, results, page_depth, pages, url, visited, errors)

        else:
            # --- BFS mode: fallback when no sitemap found ---
            current_level = [url]

            for current_depth in range(depth):
                if not current_level or len(pages) >= PAGE_CAP:
                    break

                # Sort within each level so the crawl budget favours
                # high-value paths when PAGE_CAP is reached mid-level.
                current_level.sort(key=score_url, reverse=True)

                remaining = PAGE_CAP - len(pages)
                to_crawl  = []
                for u in current_level:
                    if u not in visited and len(to_crawl) < remaining:
                        visited.add(u)
                        to_crawl.append(u)

                if not to_crawl:
                    break

                logger.info(
                    "CRAWL  depth=%d  pages=%d  fetching=%d in parallel",
                    current_depth, len(pages), len(to_crawl),
                )
                results = await asyncio.gather(
                    *[_fetch(crawler, u, semaphore) for u in to_crawl],
                    return_exceptions=True,
                )
                next_level = _process_results(
                    to_crawl, results, current_depth, pages, url, visited, errors,
                )
                # Only follow links if there are more depth levels to go
                current_level = (
                    sorted(next_level, key=score_url, reverse=True)
                    if current_depth < depth - 1 else []
                )

    logger.info("CRAWL  done  total=%d pages", len(pages))

    if not pages:
        if any(_is_antibot_error(e) for e in errors):
            raise RuntimeError(
                "This site is blocking automated requests (antibot protection). "
                "We were unable to crawl any pages."
            )
        raise RuntimeError(
            "No pages could be crawled from this site. "
            "It may be unreachable or blocking automated requests."
        )

    return CrawlResult(
        pages=pages,
        crawled_at=datetime.now(timezone.utc).isoformat(),
    )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python crawler.py <url> [depth]")
        sys.exit(1)

    target_url   = sys.argv[1]
    target_depth = int(sys.argv[2]) if len(sys.argv) > 2 else 2

    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
    output = asyncio.run(crawl(target_url, target_depth))
    print(json.dumps(output, indent=2))
