from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from crawler import crawl
from generator import generate
from models import CrawlResult, GenerateResult

app = FastAPI()


class CrawlRequest(BaseModel):
    url: str
    depth: int = Field(default=2, ge=1, le=5)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/generate", response_model=GenerateResult)
async def generate_endpoint(body: CrawlRequest):
    parsed = urlparse(body.url)
    if not parsed.scheme or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Malformed URL")

    try:
        result = await crawl(body.url, body.depth)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Crawl failed: {e}")

    try:
        llms_txt = generate(result.pages)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {e}")

    return GenerateResult(
        llms_txt=llms_txt,
        page_count=len(result.pages),
        crawled_at=result.crawled_at,
    )


@app.post("/crawl", response_model=CrawlResult)
async def crawl_endpoint(body: CrawlRequest):
    parsed = urlparse(body.url)
    if not parsed.scheme or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Malformed URL")

    try:
        result = await crawl(body.url, body.depth)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return result
