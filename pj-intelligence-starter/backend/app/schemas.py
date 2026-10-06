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
    last_run_at: str = ""
    last_status: str = ""
    records_collected: int = 0
    error_message: str = ""


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
    warning: str = ""


class UploadCsvResult(BaseModel):
    import_id: int
    record_type: str
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
    provider: str = ""


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
    source_name: str = ""
    provider: str = ""
    source_type: str = ""


class ImportDetailOut(ImportOut):
    records: list[RawRecordOut]


class ImportSourceIn(BaseModel):
    source_id: int


class ImportSourceResult(BaseModel):
    import_id: int
    old_source_id: int
    new_source_id: int
    updated_records: int


class LlmSmokeIn(BaseModel):
    task: str = "fast"
    prompt: str = "用中文回复：模型路由成功"


class ProviderHealthItem(BaseModel):
    name: str
    type: str
    enabled: bool
    configured: bool
    status: str
    message: str
    last_status_code: int | None = None
    action: str | None = None
    details: list[str] = []


class ProviderHealthOut(BaseModel):
    serp_provider: str
    providers: list[ProviderHealthItem]


class PromoteSerpIn(BaseModel):
    cluster_id: int


class PromoteSerpResult(BaseModel):
    import_id: int
    cluster_id: int
    created: int
    skipped: int


class RawBindIn(BaseModel):
    raw_record_id: int
    linked_table: str
    linked_id: int
    record_type: str
    confidence: str = "medium"


class GoogleSearchQueryIn(BaseModel):
    query: str
    num: int = 10
    gl: str = "us"
    hl: str = "en"


class GoogleSearchItem(BaseModel):
    title: str
    link: str
    displayLink: str
    snippet: str
    rank: int | None = None


class GoogleSearchQueryOut(BaseModel):
    provider: str
    query: str
    count: int
    items: list[GoogleSearchItem]


class GoogleSearchImportIn(BaseModel):
    cluster_id: int
    query: str
    num: int = 10
    gl: str = "us"
    hl: str = "en"


class GoogleSearchImportOut(BaseModel):
    provider: str
    query: str
    raw_records_created: int
    competitors_created: int
    skipped: int = 0


class IntakePreviewFile(BaseModel):
    file_name: str
    relative_path: str = ""
    detected_dataset_type: str
    record_type: str = ""
    provider: str = ""
    period_month: str = ""
    previous_month: str = ""
    columns: list[str] = []
    sample_rows: list[dict] = []
    confidence: float = 0
    warnings: list[str] = []


class IntakePreviewOut(BaseModel):
    preview_id: str
    status: str = "preview"
    files: list[IntakePreviewFile]


class IntakeConfirmFile(BaseModel):
    file_name: str
    relative_path: str = ""
    dataset_type: str = ""
    record_type: str = ""
    provider: str = ""
    import_note: str = ""


class IntakeConfirmIn(BaseModel):
    preview_id: str
    import_name: str = ""
    import_note: str = ""
    source_id: int | None = None
    review_confirmed: bool = False
    files: list[IntakeConfirmFile] = []


class IntakeImportResult(BaseModel):
    file_name: str
    import_id: int = 0
    record_type: str = ""
    dataset_type: str = ""
    row_count: int = 0
    status: str
    message: str = ""


class IntakeConfirmOut(BaseModel):
    imports: list[IntakeImportResult]


class CrawlJobIn(BaseModel):
    url: str = ""
    domain: str = ""
    keyword: str = ""
    crawl_type: str


class EvidenceGroupStats(BaseModel):
    record_type: str
    dataset_type: str = ""
    row_count: int = 0
    month_count: int = 0
    latest_month: str = ""
    source_count: int = 0
    sample_count: int = 0
    real_count: int = 0


class EvidenceRecordStats(EvidenceGroupStats):
    top_domains: list[str] = []
    source_name: str = ""
    keyword_count: int = 0
    best_keyword_count: int = 0
    validation_streak: int = 0


class EvidenceStatsOut(BaseModel):
    groups: list[EvidenceGroupStats]
    record_types: list[EvidenceRecordStats]
    serp_urls: list[str] = []


class ExplorerRecord(BaseModel):
    id: int
    domain: str = ""
    title: str = ""
    dataset_type: str = ""
    record_type: str = ""
    provider: str = ""
    period_month: str = ""
    rank: str = ""
    payment_traffic: str = ""
    monthly_traffic: str = ""
    current_traffic: str = ""
    traffic_growth: str = ""
    growth_rate: str = ""
    current_dr: str = ""
    previous_dr: str = ""
    dr_growth: str = ""
    domain_rating: str = ""
    source_name: str = ""
    original_file_name: str = ""
    batch_id: int | None = None
    imported_at: str = ""
    sample: bool = False
    raw_json: str = ""
    normalized: dict[str, str] = {}


class ExplorerPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[ExplorerRecord]


class ImportBatchSummary(BaseModel):
    batch_id: int
    import_name: str = ""
    status: str = ""
    dataset_type: str = ""
    record_type: str = ""
    provider: str = ""
    file_count: int = 0
    row_count: int = 0
    created_at: str = ""
    source_name: str = ""


class BatchFileOut(BaseModel):
    import_id: int
    original_file_name: str = ""
    period_month: str = ""
    row_count: int = 0
    status: str = ""
    warnings: list[str] = []


class BatchSampleOut(BaseModel):
    domain: str = ""
    rank: str = ""
    title: str = ""
    normalized: dict[str, str] = {}


class ImportBatchDetail(ImportBatchSummary):
    month_count: int = 0
    latest_month: str = ""
    imported_rows: int = 0
    skipped_rows: int = 0
    failed_files: list[str] = []
    files: list[BatchFileOut] = []
    sample_rows: list[BatchSampleOut] = []


class ExternalOpportunity(BaseModel):
    domain: str
    opportunity_score: int = 0
    evidence_count: int = 0
    payment_status: str = "Missing"
    traffic_status: str = "Missing"
    authority_status: str = "Missing"
    serp_status: str = "Missing"
    competitor_status: str = "Missing"
    latest_month: str = ""
    top_keyword: str = ""
    best_payment_traffic: str = ""
    best_traffic_growth: str = ""
    best_dr_growth: str = ""
    recommended_action: str = ""
    tags: list[str] = []


class ExternalOpportunityPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[ExternalOpportunity]


class FeedItem(BaseModel):
    id: int = 0
    time: str = ""
    source: str = ""
    source_name: str = ""
    domain: str = ""
    url: str = ""
    title: str = ""
    signal: str = ""
    feed_type: str = ""
    why: str = ""
    why_it_matters: str = ""
    related_keyword: str = ""
    related_opportunity_id: int | None = None
    created_at: str = ""


class FeedOut(BaseModel):
    items: list[FeedItem]


class CollectError(BaseModel):
    source_name: str = ""
    status: str = ""
    error_message: str = ""
    last_run_at: str = ""


class CollectNowOut(BaseModel):
    inserted: int = 0
    skipped: int = 0
    sources_checked: int = 0
    new_items: int = 0
    errors: list[CollectError] = []
    top_signal: str = ""
    finished_at: str = ""


class CollectStatusOut(BaseModel):
    finished_at: str = ""
    sources_checked: int = 0
    new_items: int = 0
    error_count: int = 0
    top_signal: str = ""


class RankRow(BaseModel):
    domain: str = ""
    title: str = ""
    rank: int = 0
    period_month: str = ""
    metric: str = ""


class RankBoard(BaseModel):
    payment: list[RankRow] = []
    traffic: list[RankRow] = []
    authority: list[RankRow] = []


class FeedActionIn(BaseModel):
    action: str


class FeedActionOut(BaseModel):
    ok: bool = True
    message: str = ""
    opportunity_id: int | None = None
    cluster_id: int | None = None
    competitor_id: int | None = None
    status: str = ""


class SourceRunOut(BaseModel):
    source_name: str = ""
    status: str = ""
    records_collected: int = 0
    error_message: str = ""
    last_run_at: str = ""
