"""
Endpoint tests — no DB required.

DB session is replaced with an AsyncMock via dependency_overrides.
Background job processing (_process_job) is mocked to prevent DB/crawl calls.
"""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from database import get_session
from main import app
from models import CrawledPage, CrawlResult, Job, JobState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_mock_session(job=None):
    """Return an AsyncMock session. job is returned by session.get()."""
    from unittest.mock import MagicMock
    session = AsyncMock()
    session.get = AsyncMock(return_value=job)
    session.add = MagicMock()  # synchronous in SQLAlchemy
    return session


def session_override(job=None):
    """FastAPI dependency override that yields a mock session."""
    async def _override():
        yield make_mock_session(job=job)
    return _override


MOCK_CRAWL_RESULT = CrawlResult(
    pages=[
        CrawledPage(
            url="https://example.com",
            title="Example",
            description="An example site with great content.",
            content="# Example\n\nAn example site.",
            depth=0,
        )
    ],
    crawled_at="2025-01-01T00:00:00+00:00",
)

client = TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# POST /jobs
# ---------------------------------------------------------------------------

def test_create_job_returns_queued():
    app.dependency_overrides[get_session] = session_override()
    try:
        with patch("main.JobProcessor") as mock_processor_cls:
            mock_processor_cls.return_value.run = AsyncMock()
            response = client.post("/jobs", json={"url": "https://example.com"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert "job_id" in data
    assert data["status"] == "queued"


def test_create_job_invalid_url():
    app.dependency_overrides[get_session] = session_override()
    try:
        response = client.post("/jobs", json={"url": "not-a-url"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# GET /jobs/{job_id}
# ---------------------------------------------------------------------------

def test_get_job_not_found():
    app.dependency_overrides[get_session] = session_override(job=None)
    try:
        response = client.get(f"/jobs/{uuid4()}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


def test_get_job_crawling_returns_status():
    job = Job(id=uuid4(), url="https://example.com", status=JobState.CRAWLING)
    app.dependency_overrides[get_session] = session_override(job=job)
    try:
        response = client.get(f"/jobs/{job.id}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "crawling"
    assert data["job_id"] == str(job.id)
    assert "result" not in data


def test_get_job_done_returns_result():
    job = Job(
        id=uuid4(),
        url="https://example.com",
        status=JobState.DONE,
        result="# Example\n\n> A site.",
        page_count=5,
        site_type="saas",
    )
    app.dependency_overrides[get_session] = session_override(job=job)
    try:
        response = client.get(f"/jobs/{job.id}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "done"
    assert data["result"] == "# Example\n\n> A site."
    assert data["page_count"] == 5
    assert data["site_type"] == "saas"


def test_get_job_error_returns_error():
    job = Job(
        id=uuid4(),
        url="https://example.com",
        status=JobState.ERROR,
        error="Crawl timed out",
    )
    app.dependency_overrides[get_session] = session_override(job=job)
    try:
        response = client.get(f"/jobs/{job.id}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "error"
    assert data["error"] == "Crawl timed out"


# ---------------------------------------------------------------------------
# POST /crawl (debug only)
# ---------------------------------------------------------------------------

def test_crawl_malformed_url():
    response = client.post("/crawl", json={"url": "not-a-url"})
    assert response.status_code == 400


def test_crawl_disabled_in_production():
    with patch("main.APP_ENV", "production"):
        response = client.post("/crawl", json={"url": "https://example.com"})
    assert response.status_code == 404


def test_crawl_returns_pages_without_content():
    with patch("main.crawl", new=AsyncMock(return_value=MOCK_CRAWL_RESULT)):
        response = client.post("/crawl", json={"url": "https://example.com"})

    assert response.status_code == 200
    data = response.json()
    assert "pages" in data
    page = data["pages"][0]
    assert "content_hash" not in page
    assert "content" not in page


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

def test_get_job_cancelled_returns_status():
    job = Job(
        id=uuid4(),
        url="https://example.com",
        status=JobState.CANCELLED,
        error="Job exceeded the 10-minute time limit and was cancelled.",
    )
    app.dependency_overrides[get_session] = session_override(job=job)
    try:
        response = client.get(f"/jobs/{job.id}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "cancelled"
    assert "10-minute" in data["error"]


def test_health_db_error_still_returns_200():
    """Health returns 200 even when DB is down — db field signals the error."""
    app.dependency_overrides[get_session] = session_override()
    # Simulate DB execute failing
    async def bad_session():
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=Exception("connection refused"))
        yield session

    app.dependency_overrides[get_session] = bad_session
    try:
        response = client.get("/health")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["db"] == "error"
