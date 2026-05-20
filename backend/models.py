from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import Column, TIMESTAMP
from sqlmodel import Field, SQLModel


class JobState(str, Enum):
    """Valid states for a Job. Using StrEnum so values compare equal to plain strings."""
    QUEUED     = "queued"
    CRAWLING   = "crawling"
    GENERATING = "generating"
    DONE             = "done"
    ERROR            = "error"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED        = "cancelled"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ts_col() -> Column:
    """Timezone-aware timestamp column."""
    return Column(TIMESTAMP(timezone=True), nullable=False)


# ---------------------------------------------------------------------------
# DB table models
# ---------------------------------------------------------------------------

class Job(SQLModel, table=True):
    __tablename__ = "jobs"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    url: str
    status: str = Field(default=JobState.QUEUED)  # queued | crawling | generating | done | error | cancelled
    result: Optional[str] = None           # llms.txt output
    error: Optional[str] = None
    site_type: Optional[str] = None        # blog | documentation | saas | e-commerce | portfolio | news | other
    page_count: Optional[int] = None
    generation_time_ms: Optional[int] = None
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None

    created_at: datetime = Field(default_factory=_now, sa_column=_ts_col())
    updated_at: datetime = Field(default_factory=_now, sa_column=_ts_col())


class Page(SQLModel, table=True):
    __tablename__ = "pages"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    url: str = Field(unique=True)
    domain: str = Field(default="")
    title: Optional[str] = None
    description: Optional[str] = None
    page_type: Optional[str] = None        # blog_post | guide | pricing | hero | about | faq | ...
    page_type_confidence: Optional[float] = None
    etag: Optional[str] = None             # HTTP ETag for change detection
    last_modified: Optional[str] = None    # HTTP Last-Modified for change detection

    created_at: datetime = Field(default_factory=_now, sa_column=_ts_col())
    updated_at: datetime = Field(default_factory=_now, sa_column=_ts_col())


class JobPage(SQLModel, table=True):
    __tablename__ = "job_pages"

    job_id: UUID = Field(foreign_key="jobs.id", primary_key=True)
    page_id: UUID = Field(foreign_key="pages.id", primary_key=True)
    rank: Optional[int] = None             # position in final llms.txt (1 = most important)
    score: Optional[int] = None            # post-crawl score used to prioritise watchlist


class Domain(SQLModel, table=True):
    __tablename__ = "domains"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    base_url: str = Field(unique=True)
    domain: str
    monitoring_enabled: bool = Field(default=True)
    last_checked_at: Optional[datetime] = None
    last_job_id: Optional[UUID] = Field(default=None, foreign_key="jobs.id")
    sitemap_hash: Optional[str] = None     # SHA256 of raw sitemap XML for change detection

    created_at: datetime = Field(default_factory=_now, sa_column=_ts_col())
    updated_at: datetime = Field(default_factory=_now, sa_column=_ts_col())


# ---------------------------------------------------------------------------
# Transient schemas (crawler output — not persisted directly)
# ---------------------------------------------------------------------------

class CrawledPage(SQLModel):
    """Ephemeral page data produced by the crawler.
    content is used in-memory for classification and scoring — never persisted."""
    url: str
    title: str
    description: str
    content: str        # transient — discarded after classification
    depth: int


class CrawledPagePublic(SQLModel):
    """Public shape for /crawl response — raw content excluded."""
    url: str
    title: str
    description: str


class CrawlResult(SQLModel):
    """Internal result returned by crawl(). Contains full CrawledPage objects with content."""
    pages: list[CrawledPage]
    crawled_at: str


class CrawlResponse(SQLModel):
    """API response for POST /crawl — content stripped, hash exposed."""
    pages: list[CrawledPagePublic]
    crawled_at: str


# ---------------------------------------------------------------------------
# API response schemas
# ---------------------------------------------------------------------------

class JobListItem(SQLModel):
    job_id: UUID
    url: str
    page_count: Optional[int]
    total_tokens: Optional[int]
    created_at: datetime


class JobQueued(SQLModel):
    job_id: UUID
    status: str


class JobStatus(SQLModel):
    job_id: UUID
    status: str
    url: str
    site_type: Optional[str]
    page_count: Optional[int]
    error: Optional[str]
    created_at: datetime
    updated_at: datetime


class JobResult(SQLModel):
    job_id: UUID
    status: str
    url: str
    site_type: Optional[str]
    result: str
    page_count: int
    generation_time_ms: Optional[int]
    created_at: datetime
