import logging
import os
import time
from urllib.parse import urlparse
from uuid import UUID

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from pydantic import field_validator
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from classifier import classify
from crawler import crawl
from database import get_engine, get_session
from generator import generate
from models import (
    CrawledPagePublic,
    CrawlResponse,
    Job,
    JobPage,
    JobQueued,
    JobResult,
    JobStatus,
    Page,
    _now,
)
from scorer import score_all

logger = logging.getLogger(__name__)

APP_ENV     = os.getenv("APP_ENV", "development")
CRAWL_DEPTH = int(os.getenv("CRAWL4AI_DEPTH", "2"))

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class JobRequest(BaseModel):
    url: str
    depth: int = 2

    @field_validator("depth")
    @classmethod
    def validate_depth(cls, v: int) -> int:
        if v < 1 or v > 5:
            raise ValueError("depth must be between 1 and 5")
        return v


class CrawlRequest(BaseModel):
    url: str
    depth: int = 2


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

async def _upsert_page(session: AsyncSession, page, page_clf) -> UUID:
    """Insert or update a Page row. Returns the page id."""
    domain = urlparse(page.url).netloc

    result = await session.execute(select(Page).where(Page.url == page.url))
    existing = result.scalars().first()

    if existing:
        existing.title               = page.title
        existing.description         = page.description
        existing.content_hash        = page.content_hash
        existing.domain              = domain
        existing.page_type           = page_clf.page_type if page_clf else None
        existing.page_type_confidence = page_clf.confidence if page_clf else None
        existing.updated_at          = _now()
        await session.commit()
        await session.refresh(existing)
        return existing.id

    db_page = Page(
        url=page.url,
        domain=domain,
        title=page.title,
        description=page.description,
        content_hash=page.content_hash,
        page_type=page_clf.page_type if page_clf else None,
        page_type_confidence=page_clf.confidence if page_clf else None,
    )
    session.add(db_page)
    await session.commit()
    await session.refresh(db_page)
    return db_page.id


# ---------------------------------------------------------------------------
# Background job processor
# ---------------------------------------------------------------------------

async def _process_job(job_id: UUID, url: str, depth: int) -> None:
    _, session_factory = get_engine()
    async with session_factory() as session:
        job = await session.get(Job, job_id)
        try:
            job.status     = "crawling"
            job.updated_at = _now()
            await session.commit()

            start        = time.time()
            crawl_result = await crawl(url, depth)
            raw_pages    = crawl_result.pages

            # Deduplicate by content hash (same logic as generator.py)
            seen: set[str] = set()
            unique = []
            for p in raw_pages:
                if p.content_hash not in seen:
                    seen.add(p.content_hash)
                    unique.append(p)

            # Classify once — used for DB persistence and passed implicitly to generate()
            classification = classify(unique)
            site_type      = classification.site.primary_type

            job.status     = "generating"
            job.updated_at = _now()
            await session.commit()

            # Generate llms.txt (runs classify/score internally — accepted MVP redundancy)
            llms_txt      = await generate(raw_pages)
            elapsed_ms    = int((time.time() - start) * 1000)

            # Upsert pages → collect {url: page_id}
            page_id_map: dict[str, UUID] = {}
            for page in unique:
                page_clf = classification.pages.get(page.url)
                pid = await _upsert_page(session, page, page_clf)
                page_id_map[page.url] = pid

            # Score to get rank order for job_pages
            scored = score_all(unique, classification, url)
            for rank, sp in enumerate(scored, 1):
                pid = page_id_map.get(sp.page.url)
                if pid:
                    session.add(JobPage(job_id=job_id, page_id=pid, rank=rank))

            job.status             = "done"
            job.result             = llms_txt
            job.page_count         = len(unique)
            job.site_type          = site_type
            job.generation_time_ms = elapsed_ms
            job.updated_at         = _now()
            await session.commit()

        except Exception as exc:
            logger.exception("JOB %s failed", job_id)
            job.status     = "error"
            job.error      = str(exc)
            job.updated_at = _now()
            await session.commit()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health(session: AsyncSession = Depends(get_session)):
    try:
        await session.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "error"
    return {"status": "ok", "db": db_status}


@app.post("/jobs", response_model=JobQueued)
async def create_job(
    body: JobRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    parsed = urlparse(body.url)
    if not parsed.scheme or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Invalid URL")

    job = Job(url=body.url)
    session.add(job)
    await session.commit()
    await session.refresh(job)

    background_tasks.add_task(_process_job, job.id, body.url, body.depth)

    return JobQueued(job_id=job.id, status=job.status)


@app.get("/jobs/{job_id}")
async def get_job(job_id: UUID, session: AsyncSession = Depends(get_session)):
    job = await session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status == "done":
        return JobResult(
            job_id=job.id,
            status=job.status,
            url=job.url,
            site_type=job.site_type,
            result=job.result,
            page_count=job.page_count or 0,
            generation_time_ms=job.generation_time_ms,
            created_at=job.created_at,
        )

    return JobStatus(
        job_id=job.id,
        status=job.status,
        url=job.url,
        site_type=job.site_type,
        page_count=job.page_count,
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@app.post("/crawl", response_model=CrawlResponse)
async def crawl_endpoint(body: CrawlRequest):
    """Debug/testing utility only. Disabled in production."""
    if APP_ENV == "production":
        raise HTTPException(status_code=404, detail="Not found")

    parsed = urlparse(body.url)
    if not parsed.scheme or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Invalid URL")

    try:
        result = await crawl(body.url, body.depth)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return CrawlResponse(
        pages=[CrawledPagePublic(**p.model_dump()) for p in result.pages],
        crawled_at=result.crawled_at,
    )
