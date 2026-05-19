import logging
import os
import time
from contextlib import asynccontextmanager
from urllib.parse import urlparse
from uuid import UUID

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
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
    Domain,
    Job,
    JobListItem,
    JobPage,
    JobQueued,
    JobResult,
    JobStatus,
    Page,
    _now,
)
from scorer import score_all

logger = logging.getLogger(__name__)

APP_ENV              = os.getenv("APP_ENV", "development")
CRAWL_DEPTH          = int(os.getenv("CRAWL4AI_DEPTH", "2"))
MONITOR_INTERVAL_HRS = int(os.getenv("MONITOR_INTERVAL_HOURS", "24"))


# ---------------------------------------------------------------------------
# Lifespan — APScheduler
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    from monitor import run_monitoring
    scheduler = AsyncIOScheduler()
    scheduler.add_job(run_monitoring, "interval", hours=MONITOR_INTERVAL_HRS)
    scheduler.start()
    logger.info("MONITOR  scheduler started  interval=%dh", MONITOR_INTERVAL_HRS)
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_origin_regex=os.getenv("CORS_ORIGIN_REGEX", ""),
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    ms = int((time.time() - start) * 1000)
    logger.info(
        "HTTP  %s %s  status=%d  duration=%dms",
        request.method, request.url.path, response.status_code, ms,
    )
    return response


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
        page_type=page_clf.page_type if page_clf else None,
        page_type_confidence=page_clf.confidence if page_clf else None,
    )
    session.add(db_page)
    await session.commit()
    await session.refresh(db_page)
    return db_page.id


async def _upsert_domain(session: AsyncSession, base_url: str, job_id: UUID) -> None:
    """Register or update a Domain row for monitoring."""
    domain_str = urlparse(base_url).netloc
    result = await session.execute(select(Domain).where(Domain.base_url == base_url))
    existing = result.scalars().first()

    if existing:
        existing.last_job_id = job_id
        existing.updated_at  = _now()
    else:
        session.add(Domain(base_url=base_url, domain=domain_str, last_job_id=job_id))

    await session.commit()


# ---------------------------------------------------------------------------
# Background job processor
# ---------------------------------------------------------------------------

async def _process_job(job_id: UUID, url: str, depth: int) -> None:
    _, session_factory = get_engine()
    async with session_factory() as session:
        job = await session.get(Job, job_id)
        try:
            logger.info("JOB %s  url=%s  depth=%d  status=crawling", job_id, url, depth)
            job.status     = "crawling"
            job.updated_at = _now()
            await session.commit()

            start        = time.time()
            crawl_result = await crawl(url, depth)
            pages        = crawl_result.pages
            logger.info("JOB %s  crawled=%d pages  elapsed=%dms", job_id, len(pages), int((time.time() - start) * 1000))

            # Classify once — used for DB persistence and passed implicitly to generate()
            classification = classify(pages)

            logger.info("JOB %s  status=generating", job_id)
            job.status     = "generating"
            job.updated_at = _now()
            await session.commit()

            # Generate llms.txt (runs classify/score internally — accepted MVP redundancy)
            llms_txt   = await generate(pages)
            elapsed_ms = int((time.time() - start) * 1000)

            # Upsert pages → collect {url: page_id}
            page_id_map: dict[str, UUID] = {}
            for page in pages:
                page_clf = classification.get(page.url)
                pid = await _upsert_page(session, page, page_clf)
                page_id_map[page.url] = pid

            # Score to get rank order for job_pages
            scored = score_all(pages, classification, url)
            for rank, sp in enumerate(scored, 1):
                pid = page_id_map.get(sp.page.url)
                if pid:
                    session.add(JobPage(job_id=job_id, page_id=pid, rank=rank, score=sp.score))

            job.status             = "done"
            job.result             = llms_txt
            job.page_count         = len(pages)
            job.generation_time_ms = elapsed_ms
            job.updated_at         = _now()
            await session.commit()

            logger.info("JOB %s  status=done  pages=%d  total_ms=%d  output_chars=%d", job_id, len(pages), elapsed_ms, len(llms_txt))

            # Register domain for monitoring
            await _upsert_domain(session, url, job_id)

        except Exception as exc:
            logger.exception("JOB %s  status=error  error=%s", job_id, exc)
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


@app.get("/jobs", response_model=list[JobListItem])
async def list_jobs(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Job)
        .where(Job.status == "done")
        .order_by(Job.created_at.desc())
        .limit(100)
    )
    jobs = result.scalars().all()
    return [JobListItem(job_id=j.id, url=j.url, page_count=j.page_count, created_at=j.created_at) for j in jobs]


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

    logger.info("JOB %s  created  url=%s  depth=%d", job.id, body.url, body.depth)
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
