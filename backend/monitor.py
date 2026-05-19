"""
Site monitoring — checks registered domains for content changes
and triggers new generation jobs when detected.

Change detection strategy (in priority order):
  1. Sitemap XML hash  — fetch raw sitemap XML, SHA256 it, compare to stored hash
  2. HTTP HEAD on watchlist pages — fallback for sites without sitemaps;
     compares ETag / Last-Modified headers against values stored on the Page row
"""

import asyncio
import hashlib
import logging
from urllib.parse import urlparse

import httpx
from sqlmodel import select

from crawler import _fetch_text, _parse_robots
from database import get_engine
from models import Domain, Job, JobPage, Page, _now
from scorer import OPTIONAL_THRESHOLD

logger = logging.getLogger(__name__)

WATCHLIST_SIZE = 5   # max pages to HEAD-check per domain (must score >= OPTIONAL_THRESHOLD)


# ---------------------------------------------------------------------------
# Sitemap hash
# ---------------------------------------------------------------------------

async def _fetch_sitemap_hash(base_url: str) -> str | None:
    """
    Fetch the first available sitemap XML for base_url and return its SHA256.
    Returns None if no sitemap could be fetched.
    """
    parsed = urlparse(base_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    robots_text = await _fetch_text(robots_url)
    _, robots_sitemap = _parse_robots(robots_text) if robots_text else ([], None)

    candidates = []
    if robots_sitemap:
        candidates.append(robots_sitemap)
    default = f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"
    if default not in candidates:
        candidates.append(default)

    for sitemap_url in candidates:
        text = await _fetch_text(sitemap_url)
        if text:
            return hashlib.sha256(text.encode()).hexdigest()

    return None


# ---------------------------------------------------------------------------
# HTTP header check
# ---------------------------------------------------------------------------

async def _check_page_headers(
    url: str,
    stored_etag: str | None,
    stored_last_modified: str | None,
) -> tuple[bool, str | None, str | None]:
    """
    HEAD request to check if a page changed.
    Returns (changed, new_etag, new_last_modified).
    A page is considered changed only when we have a previous value to compare against.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.head(url)
        new_etag = resp.headers.get("etag")
        new_lm   = resp.headers.get("last-modified")

        changed = False
        if new_etag and stored_etag and new_etag != stored_etag:
            changed = True
        elif new_lm and stored_last_modified and new_lm != stored_last_modified:
            changed = True

        return changed, new_etag, new_lm

    except Exception as exc:
        logger.warning("MONITOR  HEAD %s failed: %s", url, exc)
        return False, stored_etag, stored_last_modified


# ---------------------------------------------------------------------------
# Per-domain check
# ---------------------------------------------------------------------------

async def check_domain(domain: Domain, session) -> bool:
    """
    Check one domain for content changes.
    Triggers a new job if changes are detected.
    Returns True if a job was triggered.
    """
    logger.info("MONITOR  checking %s", domain.base_url)

    # --- Step 1: Sitemap hash ---
    sitemap_hash = await _fetch_sitemap_hash(domain.base_url)
    if sitemap_hash:
        if domain.sitemap_hash and domain.sitemap_hash != sitemap_hash:
            logger.info("MONITOR  sitemap changed for %s — triggering job", domain.base_url)
            await _trigger_job(domain, session)
            domain.sitemap_hash = sitemap_hash
            domain.last_checked_at = _now()
            domain.updated_at = _now()
            await session.commit()
            return True
        # Store hash on first run (no trigger)
        domain.sitemap_hash = sitemap_hash

    # --- Step 2: HTTP header watchlist ---
    if domain.last_job_id:
        stmt = (
            select(Page)
            .join(JobPage, JobPage.page_id == Page.id)
            .where(JobPage.job_id == domain.last_job_id)
            .where(JobPage.score >= OPTIONAL_THRESHOLD)
            .order_by(JobPage.rank)
            .limit(WATCHLIST_SIZE)
        )
        result = await session.execute(stmt)
        watched = result.scalars().all()

        triggered = False
        for page in watched:
            changed, new_etag, new_lm = await _check_page_headers(
                page.url, page.etag, page.last_modified
            )
            page.etag          = new_etag
            page.last_modified = new_lm
            page.updated_at    = _now()

            if changed and not triggered:
                logger.info("MONITOR  headers changed for %s — triggering job", page.url)
                await _trigger_job(domain, session)
                triggered = True

        if triggered:
            domain.last_checked_at = _now()
            domain.updated_at = _now()
            await session.commit()
            return True

        await session.commit()  # persist updated headers even when unchanged

    domain.last_checked_at = _now()
    domain.updated_at = _now()
    await session.commit()
    return False


async def _trigger_job(domain: Domain, session) -> None:
    """Create a new Job and schedule _process_job as a background task."""
    # Import here to avoid circular import (main imports monitor)
    from main import _process_job

    job = Job(url=domain.base_url)
    session.add(job)
    await session.commit()
    await session.refresh(job)

    asyncio.create_task(_process_job(job.id, domain.base_url, 2))
    logger.info("MONITOR  triggered job %s for %s", job.id, domain.base_url)

    domain.last_job_id = job.id


# ---------------------------------------------------------------------------
# Scheduled entry point
# ---------------------------------------------------------------------------

async def run_monitoring() -> None:
    """Scheduled task — check all enabled domains for changes."""
    logger.info("MONITOR  starting scheduled check")
    _, session_factory = get_engine()
    async with session_factory() as session:
        result = await session.execute(
            select(Domain).where(Domain.monitoring_enabled == True)  # noqa: E712
        )
        domains = result.scalars().all()
        logger.info("MONITOR  %d domains to check", len(domains))
        for domain in domains:
            try:
                await check_domain(domain, session)
            except Exception:
                logger.exception("MONITOR  error checking %s", domain.base_url)
