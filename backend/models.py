from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel


# ---------------------------------------------------------------------------
# DB table models
# ---------------------------------------------------------------------------

class Job(SQLModel, table=True):
    __tablename__ = "jobs"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    url: str
    status: str = Field(default="queued")  # queued | processing | done | failed
    result: Optional[str] = None           # llms.txt output
    error: Optional[str] = None
    site_type: Optional[str] = None        # blog | documentation | saas | e-commerce | portfolio | news | other
    page_count: Optional[int] = None
    generation_time_ms: Optional[int] = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Page(SQLModel, table=True):
    __tablename__ = "pages"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    url: str = Field(unique=True)
    domain: str = Field(default="")
    title: Optional[str] = None
    description: Optional[str] = None
    content_hash: Optional[str] = None     # SHA-256 — change detection only, content never stored

    page_type: Optional[str] = None        # blog_post | guide | pricing | hero | about | faq | ...
    page_type_confidence: Optional[float] = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class JobPage(SQLModel, table=True):
    __tablename__ = "job_pages"

    job_id: UUID = Field(foreign_key="jobs.id", primary_key=True)
    page_id: UUID = Field(foreign_key="pages.id", primary_key=True)
    rank: Optional[int] = None             # position in final llms.txt (1 = most important)


# ---------------------------------------------------------------------------
# Transient schemas (crawler output — not persisted directly)
# ---------------------------------------------------------------------------

class CrawledPage(SQLModel):
    """Ephemeral page data produced by the crawler.
    content is used in-memory for hashing, classification, and scoring — never persisted."""
    url: str
    title: str
    description: str
    content: str        # transient — discarded after hash + classification
    content_hash: str   # SHA-256 of content
    depth: int


class CrawledPagePublic(SQLModel):
    """Public shape for /crawl response — raw content excluded."""
    url: str
    title: str
    description: str
    content_hash: str


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
