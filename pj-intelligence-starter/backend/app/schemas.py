from pydantic import BaseModel


class HealthOut(BaseModel):
    status: str


class TraceOut(BaseModel):
    timestamp: str
    method: str
    path: str
    status_code: int | str | None = None
    elapsed_ms: int
    kind: str
    note: str = ""


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


class KeywordClusterOut(BaseModel):
    id: int
    name: str | None = None
    category: str | None = None
    search_intent: str | None = None
    page_type: str | None = None
    priority: int
    status: str | None = None
    score: int
    notes: str | None = None


class KeywordItemOut(BaseModel):
    id: int
    keyword: str
    intent: str | None = None
    difficulty: str | None = None
    source: str | None = None
    status: str | None = None


class KeywordDetailOut(BaseModel):
    cluster: KeywordClusterOut
    items: list[KeywordItemOut]


class KeywordSeedOut(BaseModel):
    clusters_created: int
    clusters_skipped: int
    keywords_created: int


class KeywordAnalysisOut(BaseModel):
    id: int
    cluster_id: int
    model: str
    analysis: str
    elapsed_seconds: int | None = None
    created_at: str


class CompetitorIn(BaseModel):
    cluster_id: int
    url: str
    title: str = ""
    h1: str = ""
    page_type: str
    target_keyword: str = ""
    cta_text: str = ""
    pricing_signal: str = ""
    signup_signal: str = ""
    payment_signal: str = ""
    geo_signal: str = ""
    notes: str = ""


class CompetitorOut(BaseModel):
    id: int
    cluster_id: int
    url: str
    domain: str
    title: str
    h1: str
    page_type: str
    target_keyword: str
    cta_text: str
    pricing_signal: str
    signup_signal: str
    payment_signal: str
    geo_signal: str
    copyability_score: int
    risk_level: str
    notes: str
    created_at: str
    updated_at: str


class CompetitorAnalysisOut(BaseModel):
    id: int
    page_id: int
    model: str
    analysis: str
    elapsed_seconds: int | None = None
    created_at: str


class OpportunityOut(BaseModel):
    id: int
    cluster_id: int
    title: str
    verdict: str
    target_keyword: str
    page_type: str
    user_intent: str
    competitor_summary: str
    product_angle: str
    first_page_plan: str
    seven_day_action: str
    fourteen_day_action: str
    thirty_day_metric: str
    sixty_day_stop_rule: str
    score: int
    keyword_score: int = 0
    competitor_count: int = 0
    best_competitor_score: int = 0
    best_competitor_domain: str = ""
    verdict_reason: str = ""
    status: str
    notes: str
    mode: str | None = None
    created_at: str
    updated_at: str


class OpportunityAnalysisOut(BaseModel):
    id: int
    card_id: int
    model: str
    analysis: str
    elapsed_seconds: int | None = None
    created_at: str


class SourceIn(BaseModel):
    name: str
    source_type: str
    provider: str = ""
    url: str = ""
    region: str = ""
    time_range: str = ""
    data_format: str = ""
    credibility: str = ""
    notes: str = ""
    enabled: int = 1


class SourceOut(BaseModel):
    id: int
    name: str
    source_type: str
    provider: str
    url: str
    region: str
    time_range: str
    data_format: str
    credibility: str
    notes: str
    enabled: int
    created_at: str
    updated_at: str


class SourceRecordIn(BaseModel):
    source_id: int
    record_type: str
    linked_table: str
    linked_id: int
    raw_ref: str = ""
    confidence: str = ""


class SourceRecordOut(BaseModel):
    id: int
    source_id: int
    record_type: str
    linked_table: str
    linked_id: int
    raw_ref: str
    confidence: str
    created_at: str
    source_name: str = ""
    provider: str = ""


class CsvImportIn(BaseModel):
    source_id: int
    import_name: str
    record_type: str
    csv_text: str = ""
    notes: str = ""
    original_filename: str = ""


class CsvImportResult(BaseModel):
    import_id: int
    row_count: int
    status: str


class ImportOut(BaseModel):
    id: int
    source_id: int
    import_name: str
    source_type: str
    record_type: str
    original_filename: str
    row_count: int
    status: str
    notes: str
    created_at: str
    source_name: str = ""


class RawRecordOut(BaseModel):
    id: int
    import_id: int
    source_id: int
    record_type: str
    raw_json: str
    normalized_title: str
    normalized_url: str
    normalized_keyword: str
    normalized_domain: str
    metric_name: str
    metric_value: str
    time_range: str
    confidence: str
    status: str
    created_at: str


class ImportDetailOut(ImportOut):
    records: list[RawRecordOut]


class RawBindIn(BaseModel):
    raw_record_id: int
    linked_table: str
    linked_id: int
    record_type: str
    confidence: str = "medium"
