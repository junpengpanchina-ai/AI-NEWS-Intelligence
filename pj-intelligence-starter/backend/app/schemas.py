from pydantic import BaseModel


class HealthOut(BaseModel):
    status: str


class CollectOut(BaseModel):
    inserted: int
    skipped: int
    errors: list[str]


class ItemOut(BaseModel):
    id: int
    source_name: str
    title: str
    url: str
    summary: str
    author: str
    published_at: str | None
    fetched_at: str
    score: int
    status: str


class AnalysisOut(BaseModel):
    id: int
    item_id: int
    model: str
    analysis: str
    created_at: str
