from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from models import CrawlResult, Page

client = TestClient(app)

MOCK_CRAWL_RESULT = CrawlResult(
    pages=[
        Page(
            url="https://example.com",
            title="Example",
            description="An example site.",
            content="# Example\n\nAn example site.",
            depth=0,
        )
    ],
    crawled_at="2025-01-01T00:00:00+00:00",
)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_crawl_malformed_url():
    response = client.post("/crawl", json={"url": "not-a-url", "depth": 2})
    assert response.status_code == 400


def test_crawl_depth_too_low():
    response = client.post("/crawl", json={"url": "https://example.com", "depth": 0})
    assert response.status_code == 422


def test_crawl_depth_too_high():
    response = client.post("/crawl", json={"url": "https://example.com", "depth": 6})
    assert response.status_code == 422


def test_crawl_returns_pages():
    with patch("main.crawl", new=AsyncMock(return_value=MOCK_CRAWL_RESULT)):
        response = client.post("/crawl", json={"url": "https://example.com", "depth": 2})
    assert response.status_code == 200
    data = response.json()
    assert "pages" in data
    assert "crawled_at" in data
    assert len(data["pages"]) == 1
    page = data["pages"][0]
    assert "url" in page
    assert "title" in page
    assert "description" in page
    assert "content" in page


def test_generate_malformed_url():
    response = client.post("/generate", json={"url": "not-a-url", "depth": 2})
    assert response.status_code == 400


def test_generate_returns_llms_txt():
    with patch("main.crawl", new=AsyncMock(return_value=MOCK_CRAWL_RESULT)):
        response = client.post("/generate", json={"url": "https://example.com", "depth": 2})
    assert response.status_code == 200
    data = response.json()
    assert "llms_txt" in data
    assert "page_count" in data
    assert "crawled_at" in data
