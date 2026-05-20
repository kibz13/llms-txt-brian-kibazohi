"""
JobProcessor — orchestrates the full crawl → classify → score → generate → persist pipeline.

Responsibilities:
  - Drive job state transitions (queued → crawling → generating → done/error/cancelled)
  - Enforce the 10-minute wall-clock timeout (sets status to cancelled on breach)
  - Delegate all persistence to JobRepository
  - Delegate all business logic to crawler, classifier, scorer, generator

Note on tab-close cancellation: in a polling architecture the background task
runs regardless of client connection. The 10-minute timeout is the practical
cancellation mechanism. True tab-close detection requires a heartbeat endpoint
and is tracked as a future enhancement.
"""

import asyncio
import logging
import time
from uuid import UUID

from classifier import classify
from crawler import crawl
from database import get_engine
from errors import JobCancelledError, LlmsTxtError
from generator import generate
from models import Job, JobState
from repository import JobRepository
from scorer import score_all

logger = logging.getLogger(__name__)

JOB_TIMEOUT_S = 600  # 10 minutes


class JobProcessor:
    def __init__(self, job_id: UUID, url: str, depth: int) -> None:
        self.job_id = job_id
        self.url    = url
        self.depth  = depth

    async def run(self) -> None:
        """Entry point — called by FastAPI BackgroundTasks."""
        _, session_factory = get_engine()
        async with session_factory() as session:
            repo = JobRepository(session)
            job  = await repo.get(self.job_id)
            try:
                await asyncio.wait_for(self._execute(job, repo), timeout=JOB_TIMEOUT_S)
            except asyncio.TimeoutError:
                logger.warning("JOB %s  cancelled  reason=10min_timeout", self.job_id)
                await repo.set_status(
                    job, JobState.CANCELLED,
                    error="Job exceeded the 10-minute time limit and was cancelled.",
                )
            except JobCancelledError:
                logger.info("JOB %s  cancelled  reason=user_request", self.job_id)
                await repo.set_status(job, JobState.CANCELLED)
            except LlmsTxtError as exc:
                logger.warning("JOB %s  error  type=%s  detail=%s", self.job_id, type(exc).__name__, exc)
                await repo.set_status(job, JobState.ERROR, error=exc.user_message)
            except Exception as exc:
                logger.exception("JOB %s  unexpected_error  error=%s", self.job_id, exc)
                await repo.set_status(job, JobState.ERROR, error="An unexpected error occurred.")

    async def _execute(self, job: Job, repo: JobRepository) -> None:
        """Run the full pipeline. Raises on any failure; caller handles state transitions."""
        logger.info("JOB %s  url=%s  depth=%d  status=crawling", self.job_id, self.url, self.depth)
        await repo.set_status(job, JobState.CRAWLING)

        start        = time.time()
        crawl_result = await crawl(self.url, self.depth)
        pages        = crawl_result.pages
        logger.info("JOB %s  crawled=%d pages  elapsed=%dms",
                    self.job_id, len(pages), int((time.time() - start) * 1000))

        # Checkpoint 1 — after crawl
        if await repo.is_cancel_requested(job):
            raise JobCancelledError("cancelled after crawl")

        classification = classify(pages)

        # Checkpoint 2 — after classification
        if await repo.is_cancel_requested(job):
            raise JobCancelledError("cancelled after classification")

        logger.info("JOB %s  status=generating", self.job_id)
        await repo.set_status(job, JobState.GENERATING)

        # Checkpoint 3 — before Claude call
        if await repo.is_cancel_requested(job):
            raise JobCancelledError("cancelled before generation")

        llms_txt, tokens_in, tokens_out = await generate(pages)
        elapsed_ms = int((time.time() - start) * 1000)

        page_id_map: dict[str, UUID] = {}
        for page in pages:
            page_clf = classification.get(page.url)
            pid = await repo.upsert_page(page, page_clf)
            page_id_map[page.url] = pid

        scored = score_all(pages, classification, self.url)
        repo.stage_job_pages(self.job_id, scored, page_id_map)

        await repo.set_status(
            job, JobState.DONE,
            result=llms_txt,
            page_count=len(pages),
            generation_time_ms=elapsed_ms,
            tokens_in=tokens_in or None,
            tokens_out=tokens_out or None,
        )
        logger.info("JOB %s  done  pages=%d  total_ms=%d  output_chars=%d",
                    self.job_id, len(pages), elapsed_ms, len(llms_txt))

        await repo.upsert_domain(self.url, self.job_id)
