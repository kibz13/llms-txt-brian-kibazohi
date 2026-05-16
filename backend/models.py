from pydantic import BaseModel


class Page(BaseModel):
    url: str
    title: str
    description: str
    content: str
    depth: int


class CrawlResult(BaseModel):
    pages: list[Page]
    crawled_at: str


class GenerateResult(BaseModel):
    llms_txt: str
    page_count: int
    crawled_at: str
