"""Tests for the domain exception hierarchy."""
import pytest

from errors import (
    AntibotError,
    CrawlError,
    GenerationError,
    LlmsTxtError,
    UnreachableError,
)


# ---------------------------------------------------------------------------
# Hierarchy
# ---------------------------------------------------------------------------

def test_crawl_error_is_llmstxt_error():
    assert issubclass(CrawlError, LlmsTxtError)


def test_antibot_is_crawl_error():
    assert issubclass(AntibotError, CrawlError)


def test_unreachable_is_crawl_error():
    assert issubclass(UnreachableError, CrawlError)


def test_generation_error_is_llmstxt_error():
    assert issubclass(GenerationError, LlmsTxtError)


# ---------------------------------------------------------------------------
# user_message
# ---------------------------------------------------------------------------

def test_all_exceptions_have_nonempty_user_message():
    for cls in (AntibotError, UnreachableError, CrawlError, GenerationError, LlmsTxtError):
        assert isinstance(cls.user_message, str)
        assert len(cls.user_message) > 10


def test_user_message_on_instance_matches_class():
    exc = AntibotError("internal detail")
    assert exc.user_message == AntibotError.user_message


def test_str_contains_internal_detail():
    exc = UnreachableError("no pages for https://example.com")
    assert "https://example.com" in str(exc)


# ---------------------------------------------------------------------------
# Catchability
# ---------------------------------------------------------------------------

def test_antibot_caught_as_crawl_error():
    with pytest.raises(CrawlError):
        raise AntibotError("blocked")


def test_unreachable_caught_as_crawl_error():
    with pytest.raises(CrawlError):
        raise UnreachableError("down")


def test_crawl_error_caught_as_llmstxt_error():
    with pytest.raises(LlmsTxtError):
        raise CrawlError("generic crawl failure")


def test_generation_error_caught_as_llmstxt_error():
    with pytest.raises(LlmsTxtError):
        raise GenerationError("generation failed")
