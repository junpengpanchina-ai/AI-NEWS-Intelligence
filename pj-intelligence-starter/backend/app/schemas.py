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


class BuildEventsOut(BaseModel):
    events_created: int
    events_updated: int
    linked_items: int
    errors: list[str]


class EventOut(BaseModel):
    id: int
    title: str | None = None
    summary: str | None = None
    primary_keyword: str | None = None
    item_count: int
    source_count: int
    event_score: int
    first_seen_at: str | None = None
    last_seen_at: str | None = None


class EventItemOut(BaseModel):
    id: int
    title: str
    source_name: str
    score: int
    url: str
    published_at: str | None = None


class EventDetailOut(BaseModel):
    event: EventOut
    items: list[EventItemOut]


class EventAnalysisOut(BaseModel):
    id: int
    event_id: int
    model: str
    analysis: str
    analysis_type: str
    elapsed_seconds: int | None = None
    created_at: str
