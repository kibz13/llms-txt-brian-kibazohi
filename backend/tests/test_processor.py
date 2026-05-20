"""
Unit tests for JobProcessor.

All external dependencies (repo, crawl, classify, score_all, generate)
are mocked so tests run without a DB or network.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from errors import AntibotError
from models import CrawledPage, CrawlResult, Job, JobState
from processor import JOB_TIMEOUT_S, JobProcessor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pages():
    return [CrawledPage(
        url="https://example.com",
        title="Example",
        description="A site.",
        content="# Example\n\nContent.",
        depth=0,
    )]


def _make_crawl_result():
    return CrawlResult(pages=_make_pages(), crawled_at="2025-01-01T00:00:00+00:00")


def _make_job(job_id=None):
    return Job(id=job_id or uuid4(), url="https://example.com", status=JobState.QUEUED)


def _make_repo(job):
    repo = MagicMock()
    repo.get = AsyncMock(return_value=job)
    repo.set_status = AsyncMock()
    repo.upsert_page = AsyncMock(return_value=uuid4())
    repo.upsert_domain = AsyncMock()
    repo.stage_job_pages = MagicMock()
    repo.is_cancel_requested = AsyncMock(return_value=False)
    return repo


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_processor_happy_path_sets_done():
    job = _make_job()
    repo = _make_repo(job)
    processor = JobProcessor(job.id, "https://example.com", depth=2)

    with (
        patch("processor.JobRepository", return_value=repo),
        patch("processor.get_engine", return_value=(MagicMock(), AsyncMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=MagicMock()), __aexit__=AsyncMock())))),
        patch("processor.crawl", new=AsyncMock(return_value=_make_crawl_result())),
        patch("processor.classify", return_value={}),
        patch("processor.score_all", return_value=[]),
        patch("processor.generate", new=AsyncMock(return_value=("# Site\n\n> Desc.", 100, 50))),
    ):
        await processor._execute(job, repo)

    final_call = repo.set_status.call_args_list[-1]
    assert final_call.args[1] == JobState.DONE
    assert final_call.kwargs["result"] == "# Site\n\n> Desc."
    assert final_call.kwargs["tokens_in"] == 100


# ---------------------------------------------------------------------------
# Error states
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_processor_crawl_error_sets_error_status():
    job = _make_job()
    repo = _make_repo(job)
    processor = JobProcessor(job.id, "https://example.com", depth=2)

    session_cm = AsyncMock()
    session_cm.__aenter__ = AsyncMock(return_value=MagicMock())
    session_cm.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("processor.JobRepository", return_value=repo),
        patch("processor.get_engine") as mock_engine,
        patch("processor.crawl", new=AsyncMock(side_effect=AntibotError("blocked"))),
    ):
        mock_engine.return_value = (MagicMock(), MagicMock(return_value=session_cm))
        await processor.run()

    final_call = repo.set_status.call_args
    assert final_call.args[1] == JobState.ERROR
    assert "antibot" in final_call.kwargs["error"].lower() or "blocking" in final_call.kwargs["error"].lower()


@pytest.mark.asyncio
async def test_processor_timeout_sets_cancelled():
    job = _make_job()
    repo = _make_repo(job)
    processor = JobProcessor(job.id, "https://example.com", depth=2)

    async def slow_crawl(*args, **kwargs):
        await asyncio.sleep(9999)

    session_cm = AsyncMock()
    session_cm.__aenter__ = AsyncMock(return_value=MagicMock())
    session_cm.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("processor.JobRepository", return_value=repo),
        patch("processor.get_engine") as mock_engine,
        patch("processor.crawl", new=slow_crawl),
        patch("processor.JOB_TIMEOUT_S", 0.01),  # tiny timeout so test is fast
    ):
        mock_engine.return_value = (MagicMock(), MagicMock(return_value=session_cm))
        await processor.run()

    final_call = repo.set_status.call_args
    assert final_call.args[1] == JobState.CANCELLED
    assert "10-minute" in final_call.kwargs["error"]


@pytest.mark.asyncio
async def test_processor_unexpected_error_sets_error_with_generic_message():
    job = _make_job()
    repo = _make_repo(job)
    processor = JobProcessor(job.id, "https://example.com", depth=2)

    session_cm = AsyncMock()
    session_cm.__aenter__ = AsyncMock(return_value=MagicMock())
    session_cm.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("processor.JobRepository", return_value=repo),
        patch("processor.get_engine") as mock_engine,
        patch("processor.crawl", new=AsyncMock(side_effect=RuntimeError("unexpected!"))),
    ):
        mock_engine.return_value = (MagicMock(), MagicMock(return_value=session_cm))
        await processor.run()

    final_call = repo.set_status.call_args
    assert final_call.args[1] == JobState.ERROR
    assert final_call.kwargs["error"] == "An unexpected error occurred."


@pytest.mark.asyncio
async def test_processor_cancel_at_checkpoint_sets_cancelled():
    """Cancellation requested between crawl and generate → CANCELLED, not ERROR."""
    job = _make_job()
    repo = _make_repo(job)
    # First call to is_cancel_requested (after crawl) returns True
    repo.is_cancel_requested = AsyncMock(return_value=True)
    processor = JobProcessor(job.id, "https://example.com", depth=2)

    session_cm = AsyncMock()
    session_cm.__aenter__ = AsyncMock(return_value=MagicMock())
    session_cm.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("processor.JobRepository", return_value=repo),
        patch("processor.get_engine") as mock_engine,
        patch("processor.crawl", new=AsyncMock(return_value=_make_crawl_result())),
        patch("processor.classify", return_value={}),
    ):
        mock_engine.return_value = (MagicMock(), MagicMock(return_value=session_cm))
        await processor.run()

    final_call = repo.set_status.call_args
    assert final_call.args[1] == JobState.CANCELLED


# ---------------------------------------------------------------------------
# JobState enum
# ---------------------------------------------------------------------------

def test_job_state_values():
    assert JobState.QUEUED     == "queued"
    assert JobState.CRAWLING   == "crawling"
    assert JobState.GENERATING == "generating"
    assert JobState.DONE       == "done"
    assert JobState.ERROR      == "error"
    assert JobState.CANCELLED  == "cancelled"


def test_job_state_is_str():
    """StrEnum values compare equal to plain strings for DB/JSON compatibility."""
    assert isinstance(JobState.DONE, str)
    assert JobState.CANCELLED == "cancelled"


def test_job_timeout_constant():
    assert JOB_TIMEOUT_S == 600
