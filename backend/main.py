import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from urllib.parse import urlparse
from uuid import UUID


from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import field_validator
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from crawler import crawl
from database import get_session
from errors import CrawlError, LlmsTxtError
from models import (
    CrawledPagePublic,
    CrawlResponse,
    Domain,
    Job,
    JobListItem,
    JobQueued,
    JobResult,
    JobState,
    JobStatus,
)
from processor import JobProcessor
from repository import JobRepository

logger = logging.getLogger(__name__)

APP_ENV                  = os.getenv("APP_ENV", "development")
CRAWL_DEPTH              = int(os.getenv("CRAWL4AI_DEPTH", "2"))
MONITOR_INTERVAL_HRS     = int(os.getenv("MONITOR_INTERVAL_HOURS", "24"))
MONITOR_JOB_CONCURRENCY  = int(os.getenv("MONITOR_JOB_CONCURRENCY", "1"))

monitor_semaphore = asyncio.Semaphore(MONITOR_JOB_CONCURRENCY)


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


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------

@app.exception_handler(CrawlError)
async def crawl_error_handler(request: Request, exc: CrawlError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": exc.user_message})


@app.exception_handler(LlmsTxtError)
async def llmstxt_error_handler(request: Request, exc: LlmsTxtError) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": exc.user_message})


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
    # Join domains → jobs to return only the latest job per domain (no duplicates)
    result = await session.execute(
        select(Job)
        .join(Domain, Domain.last_job_id == Job.id)
        .where(Job.status == JobState.DONE)
        .order_by(Job.created_at.desc())
        .limit(100)
    )
    jobs = result.scalars().all()
    return [
        JobListItem(
            job_id=j.id,
            url=j.url,
            page_count=j.page_count,
            total_tokens=(j.tokens_in or 0) + (j.tokens_out or 0) or None,
            created_at=j.created_at,
        )
        for j in jobs
    ]


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
    background_tasks.add_task(JobProcessor(job.id, body.url, body.depth).run)

    return JobQueued(job_id=job.id, status=job.status)


@app.get("/jobs/{job_id}")
async def get_job(job_id: UUID, session: AsyncSession = Depends(get_session)):
    job = await session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status == JobState.DONE:
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


@app.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: UUID, session: AsyncSession = Depends(get_session)):
    repo = JobRepository(session)
    job  = await repo.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    cancellable = {JobState.QUEUED, JobState.CRAWLING, JobState.GENERATING}
    if job.status not in cancellable:
        raise HTTPException(status_code=409, detail=f"Cannot cancel a job with status '{job.status}'")
    await repo.set_status(job, JobState.CANCEL_REQUESTED)
    return {"job_id": str(job_id), "status": JobState.CANCEL_REQUESTED}


@app.post("/crawl", response_model=CrawlResponse)
async def crawl_endpoint(body: CrawlRequest):
    """Debug/testing utility only. Disabled in production."""
    if APP_ENV == "production":
        raise HTTPException(status_code=404, detail="Not found")

    parsed = urlparse(body.url)
    if not parsed.scheme or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Invalid URL")

    result = await crawl(body.url, body.depth)

    return CrawlResponse(
        pages=[CrawledPagePublic(**p.model_dump()) for p in result.pages],
        crawled_at=result.crawled_at,
    )
