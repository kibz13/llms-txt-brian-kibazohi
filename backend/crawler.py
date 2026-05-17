import asyncio
import hashlib
import json
import logging
import re
import sys
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from crawl4ai import AsyncWebCrawler, CrawlerRunConfig

from models import CrawledPage, CrawlResult

logger = logging.getLogger(__name__)

PAGE_CAP       = 100
MAX_CONCURRENT = 5    # max parallel requests to a single domain

SKIP_PATTERNS = re.compile(
    r"(/cdn-cgi/|\.pdf$|\.jpg$|\.jpeg$|\.png$|\.gif$|\.svg$|\.ico$|#)",
    re.IGNORECASE,
)

_CRAWL_CONFIG = CrawlerRunConfig(
    # Wait for any common content container before extracting text.
    # Without this, Crawl4AI captures the DOM before JS frameworks render
    # the main content — returning nav chrome instead of page content.
    wait_for="css:main, article, .content, #content, #main-content",
    page_timeout=30000,
    delay_before_return_html=0.5,
)


def same_domain(base: str, url: str) -> bool:
    return urlparse(url).netloc == urlparse(base).netloc


def should_skip(url: str) -> bool:
    return bool(SKIP_PATTERNS.search(url))


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
        absolute = urljoin(base_url, href)
        parsed   = urlparse(absolute)
        clean    = parsed._replace(fragment="").geturl()
        if same_domain(base_url, clean) and not should_skip(clean):
            links.append(clean)
    return links


async def _fetch(crawler, url: str, semaphore: asyncio.Semaphore):
    async with semaphore:
        return await crawler.arun(url=url, config=_CRAWL_CONFIG)


async def crawl(url: str, depth: int) -> CrawlResult:
    visited: set[str] = set()
    pages:   list[CrawledPage] = []
    current_level = [url]
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    async with AsyncWebCrawler(verbose=False) as crawler:
        for current_depth in range(depth):
            if not current_level or len(pages) >= PAGE_CAP:
                break

            # Deduplicate and respect PAGE_CAP
            remaining = PAGE_CAP - len(pages)
            to_crawl  = []
            for u in current_level:
                if u not in visited and len(to_crawl) < remaining:
                    visited.add(u)
                    to_crawl.append(u)

            if not to_crawl:
                break

            logger.info("CRAWL  depth=%d  pages=%d  fetching=%d in parallel",
                        current_depth, len(pages), len(to_crawl))

            results = await asyncio.gather(
                *[_fetch(crawler, u, semaphore) for u in to_crawl],
                return_exceptions=True,
            )

            next_level_seen: set[str] = set()
            next_level: list[str] = []

            for u, result in zip(to_crawl, results):
                if isinstance(result, Exception):
                    logger.warning("CRAWL  error %s — %s", u, result)
                    continue
                if not result.success:
                    logger.warning("CRAWL  failed %s", u)
                    continue

                content = result.markdown or ""
                pages.append(CrawledPage(
                    url=u,
                    title=extract_title(result),
                    description=extract_description(result),
                    content=content,
                    content_hash=hashlib.sha256(content.encode()).hexdigest(),
                    depth=current_depth,
                ))

                if current_depth < depth - 1:
                    for link in extract_links(result, url):
                        if link not in visited and link not in next_level_seen:
                            next_level_seen.add(link)
                            next_level.append(link)

            current_level = next_level

    logger.info("CRAWL  done  total=%d pages", len(pages))
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
