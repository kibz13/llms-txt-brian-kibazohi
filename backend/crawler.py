import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from crawl4ai import AsyncWebCrawler

from models import CrawlResult, Page

SKIP_PATTERNS = re.compile(
    r"(/cdn-cgi/|\.pdf$|\.jpg$|\.jpeg$|\.png$|\.gif$|\.svg$|\.ico$|#)",
    re.IGNORECASE,
)


def same_domain(base: str, url: str) -> bool:
    return urlparse(url).netloc == urlparse(base).netloc


def should_skip(url: str) -> bool:
    return bool(SKIP_PATTERNS.search(url))


def extract_title(result) -> str:
    if result.metadata and result.metadata.get("title"):
        return result.metadata["title"]
    # Fall back to first H1 in markdown
    for line in (result.markdown or "").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def extract_description(result) -> str:
    if result.metadata and result.metadata.get("description"):
        return result.metadata["description"]
    # Fall back to first non-empty paragraph in markdown
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
        parsed = urlparse(absolute)
        clean = parsed._replace(fragment="").geturl()
        if same_domain(base_url, clean) and not should_skip(clean):
            links.append(clean)
    return links


async def crawl(url: str, depth: int) -> CrawlResult:
    visited = set()
    pages = []
    queue = [(url, 0)]

    async with AsyncWebCrawler(verbose=False) as crawler:
        while queue:
            current_url, current_depth = queue.pop(0)

            if current_url in visited:
                continue
            visited.add(current_url)

            print(f"  crawling ({current_depth}): {current_url}", file=sys.stderr)
            result = await crawler.arun(url=current_url)

            if not result.success:
                print(f"  failed: {current_url}", file=sys.stderr)
                continue

            pages.append(
                Page(
                    url=current_url,
                    title=extract_title(result),
                    description=extract_description(result),
                    content=result.markdown or "",
                    depth=current_depth,
                )
            )

            if current_depth < depth - 1:
                for link in extract_links(result, url):
                    if link not in visited:
                        queue.append((link, current_depth + 1))

    return CrawlResult(
        pages=pages,
        crawled_at=datetime.now(timezone.utc).isoformat(),
    )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python crawler.py <url> [depth]")
        sys.exit(1)

    target_url = sys.argv[1]
    target_depth = int(sys.argv[2]) if len(sys.argv) > 2 else 2

    print(f"Crawling {target_url} at depth {target_depth}...", file=sys.stderr)
    output = asyncio.run(crawl(target_url, target_depth))
    print(json.dumps(output, indent=2))
