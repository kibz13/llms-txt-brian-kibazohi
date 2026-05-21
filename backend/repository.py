"""
JobRepository — all database operations for jobs, pages, and domains.

Keeps persistence logic out of route handlers and the job processor,
making each layer independently testable.
"""

import logging
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from models import (
    CrawledPage,
    Domain,
    Job,
    JobPage,
    JobState,
    Page,
    _now,
)
from scorer import ScoredPage

logger = logging.getLogger(__name__)


class JobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Job
    # ------------------------------------------------------------------

    async def get(self, job_id: UUID) -> Job | None:
        return await self.session.get(Job, job_id)

    async def set_status(self, job: Job, status: JobState, **kwargs) -> None:
        """Update job status and any extra fields, then commit."""
        job.status     = status
        job.updated_at = _now()
        for key, value in kwargs.items():
            setattr(job, key, value)
        await self.session.commit()

    async def is_cancel_requested(self, job: Job) -> bool:
        """Refresh job from DB and return True if cancellation has been requested."""
        await self.session.refresh(job)
        return job.status == JobState.CANCEL_REQUESTED

    # ------------------------------------------------------------------
    # Pages
    # ------------------------------------------------------------------

    async def upsert_page(self, page: CrawledPage, page_clf) -> UUID:
        """Insert or update a Page row. Returns the page id."""
        domain = urlparse(page.url).netloc
        result = await self.session.execute(select(Page).where(Page.url == page.url))
        existing = result.scalars().first()

        if existing:
            existing.title                = page.title
            existing.description          = page.description
            existing.domain               = domain
            existing.page_type            = page_clf.page_type if page_clf else None
            existing.page_type_confidence = page_clf.confidence if page_clf else None
            existing.updated_at           = _now()
            await self.session.commit()
            await self.session.refresh(existing)
            return existing.id

        db_page = Page(
            url=page.url,
            domain=domain,
            title=page.title,
            description=page.description,
            page_type=page_clf.page_type if page_clf else None,
            page_type_confidence=page_clf.confidence if page_clf else None,
        )
        self.session.add(db_page)
        await self.session.commit()
        await self.session.refresh(db_page)
        return db_page.id

    def stage_job_pages(self, job_id: UUID, scored: list[ScoredPage], page_id_map: dict[str, UUID]) -> None:
        """
        Stage JobPage rows for insertion.
        Does NOT commit — caller should call set_status() immediately after,
        which commits everything in one transaction.
        """
        for rank, sp in enumerate(scored, 1):
            pid = page_id_map.get(sp.page.url)
            if pid:
                self.session.add(JobPage(job_id=job_id, page_id=pid, rank=rank, score=sp.score))

    # ------------------------------------------------------------------
    # Domains
    # ------------------------------------------------------------------

    async def upsert_domain(self, base_url: str, job_id: UUID) -> None:
        """Register or update a Domain row for monitoring.

        Normalises www vs apex (www.example.com → example.com) so repeated
        submissions with/without www resolve to the same domain row and appear
        only once in the directory.
        """
        parsed     = urlparse(base_url)
        netloc     = parsed.netloc.removeprefix("www.")
        canonical  = parsed._replace(netloc=netloc).geturl()

        result = await self.session.execute(select(Domain).where(Domain.base_url == canonical))
        existing = result.scalars().first()

        if existing:
            existing.last_job_id = job_id
            existing.updated_at  = _now()
        else:
            self.session.add(Domain(base_url=canonical, domain=netloc, last_job_id=job_id))

        await self.session.commit()
