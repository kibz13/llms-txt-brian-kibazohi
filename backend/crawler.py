import asyncio
import json
import logging
import re
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET

import httpx
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig

from errors import AntibotError, UnreachableError
from models import CrawledPage, CrawlResult
from prefilter import (
    detect_lang_prefix,
    filter_language_variants,
    filter_template_explosion,
    is_non_preferred_lang,
    normalise_url,
    same_domain,
    score_url,
    should_skip,
)

logger = logging.getLogger(__name__)

PAGE_CAP              = 100   # default; overridden per-crawl by _depth_to_page_cap()
MAX_CONCURRENT        = 10    # max parallel requests to a single domain
SLOW_SITE_THRESHOLD_S = 10.0  # avg seconds/page → trigger slow-site cap
SLOW_SITE_PAGE_CAP    = 20    # reduced cap for slow sites

# Maps crawl depth (set by Coverage selector) to a page budget.
# Applied in both sitemap mode and BFS mode so coverage is meaningful regardless.
_DEPTH_PAGE_CAPS: dict[int, int] = {1: 25, 2: 100, 3: 150, 4: 175, 5: 200}


def _depth_to_page_cap(depth: int) -> int:
    return _DEPTH_PAGE_CAPS.get(depth, PAGE_CAP)


_CRAWL_CONFIG = CrawlerRunConfig(
    # Hard ceiling per page. No wait_for selector — adding one causes crawl4ai
    # to wait an additional page_timeout after load, doubling the wall time.
    page_timeout=15000,
    delay_before_return_html=0.5,
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
# Content extraction helpers
# ---------------------------------------------------------------------------

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


@dataclass
class _HttpxResult:
    """Minimal crawl result produced by the httpx fallback path."""
    success: bool
    error_message: str = ""
    markdown: str = ""
    metadata: dict = field(default_factory=dict)
    links: dict = field(default_factory=lambda: {"internal": []})


def _html_to_result(html: str) -> _HttpxResult:
    """Parse raw HTML into an _HttpxResult compatible with extract_* helpers."""
    title_m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    title = title_m.group(1).strip() if title_m else ""

    desc_m = re.search(
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)["\']'
        r'|<meta[^>]+content=["\']([^"\']*)["\'][^>]+name=["\']description["\']',
        html, re.I,
    )
    description = (desc_m.group(1) or desc_m.group(2) or "").strip() if desc_m else ""

    # Strip scripts/styles then all tags to get plain text
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    content = f"# {title}\n\n{text[:8000]}" if title else text[:8000]

    hrefs = [{"href": m.group(1)} for m in re.finditer(r'<a[^>]+href=["\']([^"\'#][^"\']*)["\']', html, re.I)]

    return _HttpxResult(
        success=True,
        markdown=content,
        metadata={"title": title, "description": description},
        links={"internal": hrefs},
    )


async def _httpx_fetch(url: str) -> _HttpxResult:
    """Fetch a page with plain httpx — no JS rendering, but fast."""
    try:
        async with httpx.AsyncClient(
            timeout=8.0,
            follow_redirects=True,
            headers=_HTTP_HEADERS,
        ) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                return _html_to_result(resp.text)
            return _HttpxResult(success=False, error_message=f"HTTP {resp.status_code}")
    except Exception as exc:
        return _HttpxResult(success=False, error_message=str(exc))


_TIMEOUT_SIGNALS = ("timeout", "timed out", "time out")


async def _fetch(crawler, url: str, semaphore: asyncio.Semaphore):
    async with semaphore:
        result = await crawler.arun(url=url, config=_CRAWL_CONFIG)
        if not result.success:
            err = (getattr(result, "error_message", "") or "").lower()
            if any(s in err for s in _TIMEOUT_SIGNALS):
                logger.info("FALLBACK  httpx  url=%s", url)
                return await _httpx_fetch(url)
        return result


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

async def crawl(
    url: str,
    depth: int,
    on_batch: Callable[[list[str]], Awaitable[None]] | None = None,
) -> CrawlResult:
    url       = normalise_url(url)
    page_cap  = _depth_to_page_cap(depth)
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

    # Step 3: filter language variants from sitemap before scoring
    if sitemap_urls:
        filtered = filter_language_variants(sitemap_urls)
        if len(filtered) < len(sitemap_urls):
            logger.info(
                "PREFILTER  multi-language site, dropped %d non-preferred language URLs",
                len(sitemap_urls) - len(filtered),
            )
        sitemap_urls = filtered

    # Template explosion filter — applied before crawling so we never
    # fetch hundreds of near-identical parameterised pages (city pages,
    # product SKUs, etc.).  Groups below explosion_threshold are untouched.
    before_explosion = len(sitemap_urls)
    sitemap_urls = filter_template_explosion(sitemap_urls)
    if len(sitemap_urls) < before_explosion:
        logger.info(
            "PREFILTER  template explosion, dropped %d URLs",
            before_explosion - len(sitemap_urls),
        )

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
            # Homepage always first, then highest-scored pages up to page_cap
            queue = [url] + unique_rest
            queue = queue[:page_cap]

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
                t0 = time.time()
                results = await asyncio.gather(
                    *[_fetch(crawler, u, semaphore) for u in batch],
                    return_exceptions=True,
                )
                elapsed = time.time() - t0

                # After first batch: detect slow site by wall-clock time.
                # Parallel fetches mean elapsed ≈ slowest page, not sum —
                # dividing by batch size would mask slow sites.
                if i == 0 and len(batch) >= 3 and elapsed > SLOW_SITE_THRESHOLD_S:
                    logger.warning(
                        "SLOW_SITE  batch_elapsed=%.1fs → capping at %d pages",
                        elapsed, SLOW_SITE_PAGE_CAP,
                    )
                    queue = queue[:SLOW_SITE_PAGE_CAP]

                # depth=1 for all sitemap pages (homepage gets depth=0 via position)
                page_depth = 0 if i == 0 else 1
                _process_results(batch, results, page_depth, pages, url, visited, errors)
                if on_batch:
                    await on_batch([p.url for p in pages])

        else:
            # --- BFS mode: fallback when no sitemap found ---
            current_level = [url]
            preferred_lang: str | None = None  # detected once after homepage crawl
            effective_cap = page_cap

            for current_depth in range(depth):
                if not current_level or len(pages) >= effective_cap:
                    break

                # Sort within each level so the crawl budget favours
                # high-value paths when PAGE_CAP is reached mid-level.
                current_level.sort(key=score_url, reverse=True)

                remaining = effective_cap - len(pages)
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
                t0 = time.time()
                results = await asyncio.gather(
                    *[_fetch(crawler, u, semaphore) for u in to_crawl],
                    return_exceptions=True,
                )
                elapsed = time.time() - t0

                # After depth-1 (first real batch of discovered links): detect slow site.
                # Depth-0 is always just the homepage (1 URL) — not enough signal.
                if current_depth == 1 and len(to_crawl) >= 3 and elapsed > SLOW_SITE_THRESHOLD_S:
                    logger.warning(
                        "SLOW_SITE  batch_elapsed=%.1fs → capping at %d pages",
                        elapsed, SLOW_SITE_PAGE_CAP,
                    )
                    effective_cap = SLOW_SITE_PAGE_CAP
                next_level = _process_results(
                    to_crawl, results, current_depth, pages, url, visited, errors,
                )

                # Detect language prefix from homepage's outgoing links (depth 0 only).
                # All subsequent levels are filtered to the preferred language.
                if current_depth == 0:
                    preferred_lang = detect_lang_prefix(next_level)
                    if preferred_lang:
                        logger.info(
                            "PREFILTER  multi-language site, keeping '%s' only",
                            preferred_lang,
                        )
                if preferred_lang:
                    next_level = [
                        u for u in next_level
                        if not is_non_preferred_lang(u, preferred_lang)
                    ]

                if on_batch:
                    await on_batch([p.url for p in pages])

                # Only follow links if there are more depth levels to go
                current_level = (
                    sorted(next_level, key=score_url, reverse=True)
                    if current_depth < depth - 1 else []
                )

    logger.info("CRAWL  done  total=%d pages", len(pages))

    if not pages:
        if any(_is_antibot_error(e) for e in errors):
            raise AntibotError("antibot protection detected for %s" % url)
        raise UnreachableError("no pages crawled for %s" % url)

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
