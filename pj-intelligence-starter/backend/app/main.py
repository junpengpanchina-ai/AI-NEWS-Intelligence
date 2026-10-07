import logging
import time
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.crawler import collect
from app.db import (
    get_analysis,
    get_item,
    init_db,
    list_items,
    project_root,
    release_quota,
    reserve_quota,
    save_analysis,
)
from app.events import (
    build_events,
    event_prompt,
    get_event,
    get_event_analysis,
    list_events,
    save_event_analysis,
)
from app.competitors import (
    competitor_prompt,
    create_competitor,
    get_competitor,
    get_competitor_analysis,
    list_competitors,
    save_competitor_analysis,
)
from app.google_search import (
    GoogleSearchError,
    check_google_cse,
    google_cse_card,
    import_competitors,
    install_google_log_redaction,
    provider_health,
    serp_choices,
    set_serp_provider,
    test_google_cse,
)
from app.serp import search_serp
from app.inbox import (
    bind_raw_record,
    get_import,
    import_csv,
    import_uploaded_csv,
    evidence_stats,
    list_imports,
    list_raw_records,
    promote_serp_competitors,
    update_import_source,
)
from app.ledger import (
    create_source,
    create_source_record,
    get_source,
    list_source_records,
    list_sources,
    set_source_enabled,
)
from app.explorer import (
    external_opportunities,
    get_import_batch,
    list_explorer_records,
    list_import_batches,
)
from app.market import market_pulse
from app.feed import (
    apply_feed_action,
    collect_now,
    collect_status,
    list_feed,
    today_feed,
    run_source,
    source_records,
    top_rankings,
)
from app.intake import (
    build_preview,
    confirm_batch,
    dataforseo_health,
    ga4_health,
    gsc_health,
    ignore_trend_signal,
    intake_overview,
    list_trend_signals,
    run_crawl,
)
from app.keywords import (
    get_keyword_analysis,
    get_keyword_cluster,
    keyword_prompt,
    list_keywords,
    save_keyword_analysis,
    seed_keywords,
)
from app.llm import (
    LLMCallError,
    LLMConfigError,
    analyze,
    analyze_event,
    analyze_competitor,
    analyze_keyword,
    analyze_opportunity,
    call_llm,
    chat,
    daily_limit,
    require_config,
    require_gateway,
)
from app.opportunities import (
    create_opportunity_from_keyword,
    get_opportunity,
    get_opportunity_analysis,
    list_opportunities,
    opportunity_prompt,
    save_opportunity_analysis,
)
from app.sitedata import get_settings, recent_signals, run_all, run_rankings, set_auto_create, top_opportunities
from app.storage import backup_database, export_csv, list_backups, log_storage_startup, storage_health
from app.trace import clear_traces, list_traces, record_trace
from app.schemas import (
    AnalysisOut,
    BuildEventsOut,
    CollectOut,
    EventAnalysisOut,
    EventDetailOut,
    EventOut,
    HealthOut,
    ItemOut,
    TraceOut,
    CompetitorAnalysisOut,
    CompetitorIn,
    CompetitorOut,
    KeywordAnalysisOut,
    KeywordClusterOut,
    KeywordDetailOut,
    KeywordSeedOut,
    OpportunityAnalysisOut,
    OpportunityOut,
    ProviderHealthOut,
    LlmSmokeIn,
    CsvImportIn,
    CsvImportResult,
    UploadCsvResult,
    ImportDetailOut,
    ImportOut,
    ImportSourceIn,
    ImportSourceResult,
    PromoteSerpIn,
    PromoteSerpResult,
    GoogleSearchImportIn,
    GoogleSearchImportOut,
    GoogleSearchQueryIn,
    GoogleSearchQueryOut,
    RawBindIn,
    RawRecordOut,
    SourceIn,
    SourceOut,
    SourceRecordIn,
    SourceRecordOut,
    IntakeConfirmIn,
    IntakeConfirmOut,
    IntakePreviewOut,
    CrawlJobIn,
    EvidenceStatsOut,
    CollectNowOut,
    CollectStatusOut,
    FeedActionIn,
    FeedActionOut,
    RankBoard,
    SourceRunOut,
    ExplorerPage,
    ExternalOpportunityPage,
    FeedOut,
    ImportBatchDetail,
    ImportBatchSummary,
    SiteDataOpportunityPage,
    SiteDataRunAllOut,
    SiteDataRunIn,
    SiteDataRunOut,
    SiteDataSettings,
    SiteDataSignalPage,
    DossierActionIn,
    DossierActionOut,
    DossierDetailOut,
    DossierListOut,
    ManualIntakeIn,
    StorageBackupListOut,
    StorageBackupOut,
    StorageExportOut,
    StorageHealthOut,
    MarketPulseOut,
    GoogleCseCardOut,
    GoogleCseTestIn,
    GoogleCseTestOut,
    SerpProviderIn,
    SerpProviderOut,
)
from app.dossiers import (
    add_evidence,
    add_screenshot,
    from_domain,
    from_feed,
    from_record,
    get_dossier,
    list_dossiers,
    manual_intake,
    run_action,
    screenshot_path,
)

load_dotenv(project_root() / ".env")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
install_google_log_redaction()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    log_storage_startup()
    yield


app = FastAPI(title="PJ Intelligence", lifespan=lifespan)


@app.middleware("http")
async def remember_api(request: Request, call_next):
    path = request.url.path
    if not path.startswith("/api/") or path.startswith("/api/debug/"):
        return await call_next(request)
    started = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        record_trace(
            request.method,
            path,
            status_code,
            int((time.perf_counter() - started) * 1000),
            "local_api",
            "",
        )


@app.get("/api/debug/trace", response_model=list[TraceOut])
def debug_trace():
    return list_traces()


@app.delete("/api/debug/trace")
def debug_trace_clear():
    clear_traces()
    return {"cleared": True}


@app.get("/api/health", response_model=HealthOut)
def health():
    return {"status": "ok"}


@app.post("/api/collect", response_model=CollectOut)
async def run_collect():
    return await collect()


@app.get("/api/items", response_model=list[ItemOut])
def items(limit: int = 50):
    if limit <= 0:
        limit = 50
    return list_items(limit)


@app.get("/api/items/{item_id}", response_model=ItemOut)
def item_detail(item_id: int):
    item = get_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="资讯不存在")
    return item


@app.post("/api/items/{item_id}/analyze", response_model=AnalysisOut)
async def analyze_item(item_id: int):
    item = get_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="资讯不存在")
    try:
        require_config()
    except LLMConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    limit = daily_limit()
    if not reserve_quota(limit):
        raise HTTPException(status_code=429, detail=f"已达到今日调用上限 {limit}")

    try:
        model, text = await analyze(
            title=item["title"],
            source=item["source_name"],
            url=item["url"],
            summary=item["summary"],
        )
    except LLMConfigError as exc:
        release_quota()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LLMCallError as exc:
        release_quota()
        raise HTTPException(status_code=502, detail=exc.detail) from exc
    except Exception:
        release_quota()
        raise

    return save_analysis(item_id, model, text)


@app.post("/api/events/build", response_model=BuildEventsOut)
def run_build_events():
    return build_events()


@app.get("/api/events", response_model=list[EventOut])
def events(limit: int = 50):
    if limit <= 0:
        limit = 50
    return list_events(limit)


@app.get("/api/events/{event_id}", response_model=EventDetailOut)
def event_detail(event_id: int):
    event = get_event(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="事件不存在")
    items = event.pop("items")
    return {"event": event, "items": items}


@app.get("/api/event-analysis/{event_id}", response_model=EventAnalysisOut)
def event_analysis(event_id: int):
    if get_event(event_id) is None:
        raise HTTPException(status_code=404, detail="事件不存在")
    row = get_event_analysis(event_id)
    if row is None:
        raise HTTPException(status_code=404, detail="暂无分析")
    return row


@app.post("/api/events/{event_id}/analyze", response_model=EventAnalysisOut)
async def analyze_event_item(event_id: int):
    event = get_event(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="事件不存在")
    try:
        require_config()
    except LLMConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    limit = daily_limit()
    if not reserve_quota(limit):
        raise HTTPException(status_code=429, detail=f"已达到今日调用上限 {limit}")

    started = time.monotonic()
    try:
        model, text = await analyze_event(event_prompt(event))
    except LLMConfigError as exc:
        release_quota()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LLMCallError as exc:
        release_quota()
        raise HTTPException(status_code=502, detail=exc.detail) from exc
    except Exception:
        release_quota()
        raise

    elapsed_seconds = max(0, int(round(time.monotonic() - started)))
    return save_event_analysis(event_id, model, text, elapsed_seconds)


@app.get("/api/keywords", response_model=list[KeywordClusterOut])
def keywords():
    return list_keywords()


@app.post("/api/keywords/seed", response_model=KeywordSeedOut)
def run_seed_keywords():
    return seed_keywords()


@app.get("/api/keywords/{cluster_id}", response_model=KeywordDetailOut)
def keyword_detail(cluster_id: int):
    cluster = get_keyword_cluster(cluster_id)
    if cluster is None:
        raise HTTPException(status_code=404, detail="关键词簇不存在")
    items = cluster.pop("items")
    return {"cluster": cluster, "items": items}


@app.get("/api/keyword-analysis/{cluster_id}", response_model=KeywordAnalysisOut)
def keyword_analysis(cluster_id: int):
    if get_keyword_cluster(cluster_id) is None:
        raise HTTPException(status_code=404, detail="关键词簇不存在")
    row = get_keyword_analysis(cluster_id)
    if row is None:
        raise HTTPException(status_code=404, detail="暂无分析")
    return row


@app.post("/api/keywords/{cluster_id}/analyze", response_model=KeywordAnalysisOut)
async def analyze_keyword_cluster(cluster_id: int):
    cluster = get_keyword_cluster(cluster_id)
    if cluster is None:
        raise HTTPException(status_code=404, detail="关键词簇不存在")
    try:
        require_config()
    except LLMConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    limit = daily_limit()
    if not reserve_quota(limit):
        raise HTTPException(status_code=429, detail=f"已达到今日调用上限 {limit}")

    started = time.monotonic()
    try:
        model, text = await analyze_keyword(keyword_prompt(cluster))
    except LLMConfigError as exc:
        release_quota()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LLMCallError as exc:
        release_quota()
        raise HTTPException(status_code=502, detail=exc.detail) from exc
    except Exception:
        release_quota()
        raise

    elapsed_seconds = max(0, int(round(time.monotonic() - started)))
    return save_keyword_analysis(cluster_id, model, text, elapsed_seconds)


@app.get("/api/competitors", response_model=list[CompetitorOut])
def competitors(cluster_id: int | None = None):
    return list_competitors(cluster_id)


@app.post("/api/competitors", response_model=CompetitorOut)
def add_competitor(payload: CompetitorIn):
    try:
        page = create_competitor(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if page is None:
        raise HTTPException(status_code=404, detail="关键词簇不存在")
    return page


@app.get("/api/competitors/{page_id}", response_model=CompetitorOut)
def competitor_detail(page_id: int):
    page = get_competitor(page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="竞品页面不存在")
    return page


@app.get("/api/competitor-analysis/{page_id}", response_model=CompetitorAnalysisOut)
def competitor_analysis(page_id: int):
    if get_competitor(page_id) is None:
        raise HTTPException(status_code=404, detail="竞品页面不存在")
    row = get_competitor_analysis(page_id)
    if row is None:
        raise HTTPException(status_code=404, detail="暂无分析")
    return row


@app.post("/api/debug/llm-smoke")
async def llm_smoke(payload: LlmSmokeIn | None = None):
    body = payload or LlmSmokeIn()
    try:
        require_gateway()
    except LLMConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    limit = daily_limit()
    if not reserve_quota(limit):
        raise HTTPException(status_code=429, detail=f"已达到今日调用上限 {limit}")
    try:
        return await call_llm(body.prompt, body.task)
    except LLMConfigError as exc:
        release_quota()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LLMCallError as exc:
        release_quota()
        raise HTTPException(status_code=502, detail=exc.detail) from exc
    except Exception:
        release_quota()
        raise


@app.post("/api/competitors/{page_id}/analyze", response_model=CompetitorAnalysisOut)
async def analyze_competitor_page(page_id: int, type: str = "fast"):
    page = get_competitor(page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="竞品页面不存在")
    if type != "fast":
        raise HTTPException(status_code=400, detail="仅支持 type=fast")
    try:
        require_config()
    except LLMConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    limit = daily_limit()
    if not reserve_quota(limit):
        raise HTTPException(status_code=429, detail=f"已达到今日调用上限 {limit}")

    started = time.monotonic()
    try:
        model, text = await analyze_competitor(competitor_prompt(page))
    except LLMConfigError as exc:
        release_quota()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LLMCallError as exc:
        release_quota()
        raise HTTPException(status_code=502, detail=exc.detail) from exc
    except Exception:
        release_quota()
        raise

    elapsed_seconds = max(0, int(round(time.monotonic() - started)))
    return save_competitor_analysis(page_id, model, text, elapsed_seconds)


@app.get("/api/opportunities", response_model=list[OpportunityOut])
def opportunities():
    return list_opportunities()


@app.post("/api/opportunities/from-keyword/{cluster_id}", response_model=OpportunityOut)
def opportunity_from_keyword(cluster_id: int):
    card = create_opportunity_from_keyword(cluster_id)
    if card is None:
        raise HTTPException(status_code=404, detail="关键词簇不存在")
    return card


@app.get("/api/opportunities/{card_id}", response_model=OpportunityOut)
def opportunity_detail(card_id: int):
    card = get_opportunity(card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="项目卡不存在")
    return card


@app.get("/api/opportunity-analysis/{card_id}", response_model=OpportunityAnalysisOut)
def opportunity_analysis(card_id: int):
    if get_opportunity(card_id) is None:
        raise HTTPException(status_code=404, detail="项目卡不存在")
    row = get_opportunity_analysis(card_id)
    if row is None:
        raise HTTPException(status_code=404, detail="暂无分析")
    return row


@app.post("/api/opportunities/{card_id}/analyze", response_model=OpportunityAnalysisOut)
async def analyze_opportunity_card(card_id: int):
    card = get_opportunity(card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="项目卡不存在")
    try:
        require_config()
    except LLMConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    limit = daily_limit()
    if not reserve_quota(limit):
        raise HTTPException(status_code=429, detail=f"已达到今日调用上限 {limit}")

    started = time.monotonic()
    try:
        model, text = await analyze_opportunity(opportunity_prompt(card))
    except LLMConfigError as exc:
        release_quota()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LLMCallError as exc:
        release_quota()
        raise HTTPException(status_code=502, detail=exc.detail) from exc
    except Exception:
        release_quota()
        raise

    elapsed_seconds = max(0, int(round(time.monotonic() - started)))
    return save_opportunity_analysis(card_id, model, text, elapsed_seconds)


@app.get("/api/sources", response_model=list[SourceOut])
def sources():
    return list_sources()


@app.post("/api/sources", response_model=SourceOut)
def add_source(payload: SourceIn):
    try:
        return create_source(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/sources/{source_id}", response_model=SourceOut)
def source_detail(source_id: int):
    source = get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="数据源不存在")
    return source


@app.get("/api/source-records", response_model=list[SourceRecordOut])
def source_records(linked_table: str, linked_id: int):
    table = linked_table.strip()
    if not table:
        raise HTTPException(status_code=400, detail="linked_table 不能为空")
    return list_source_records(table, linked_id)


@app.post("/api/source-records/from-raw", response_model=SourceRecordOut)
def source_record_from_raw(payload: RawBindIn):
    try:
        return bind_raw_record(payload.model_dump())
    except ValueError as exc:
        missing = str(exc) in {"数据源不存在", "原始记录不存在"}
        raise HTTPException(status_code=404 if missing else 400, detail=str(exc)) from exc


@app.post("/api/imports/csv", response_model=CsvImportResult)
def upload_csv(payload: CsvImportIn):
    try:
        return import_csv(payload.model_dump())
    except ValueError as exc:
        status = 404 if str(exc) == "数据源不存在" else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@app.post("/api/imports/upload-csv", response_model=UploadCsvResult)
async def upload_csv_file(
    file: UploadFile = File(...),
    source_id: int = Form(...),
    record_type: str = Form(...),
    import_name: str = Form(""),
):
    raw_bytes = await file.read()
    filename = (file.filename or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    try:
        return import_uploaded_csv(source_id, record_type, import_name, filename, raw_bytes)
    except ValueError as exc:
        status = 404 if str(exc) == "数据源不存在" else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@app.post("/api/imports/upload-batch", response_model=IntakePreviewOut)
async def upload_batch(request: Request):
    form = await request.form()
    uploads = [item for item in form.getlist("files") if hasattr(item, "read")]
    paths = [str(item) for item in form.getlist("relative_paths")]
    source_raw = str(form.get("source_id") or "").strip()
    source_id = int(source_raw) if source_raw.isdigit() else None
    auto_detect = str(form.get("auto_detect") or "true").strip().lower() != "false"
    files = []
    for index, upload in enumerate(uploads):
        data = await upload.read()
        name = upload.filename or ""
        relative = paths[index] if index < len(paths) and paths[index] else name
        files.append((name, relative, data))
    try:
        return build_preview(
            files,
            str(form.get("import_name") or ""),
            str(form.get("import_note") or ""),
            source_id,
            str(form.get("dataset_type") or ""),
            auto_detect,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/imports/confirm-batch", response_model=IntakeConfirmOut)
def confirm_import_batch(payload: IntakeConfirmIn):
    try:
        return confirm_batch(payload.model_dump())
    except ValueError as exc:
        status = 404 if str(exc) == "数据源不存在" else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@app.get("/api/intake/overview")
def intake_home():
    return intake_overview()


@app.get("/api/trends")
def trend_signals(limit: int = 10):
    return list_trend_signals(limit)


@app.post("/api/trends/{record_id}/ignore")
def trend_ignore(record_id: int):
    try:
        return ignore_trend_signal(record_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/crawl/jobs")
def crawl_job(payload: CrawlJobIn):
    try:
        return run_crawl(payload.url, payload.domain, payload.keyword, payload.crawl_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/gsc/health")
def gsc_connector_health():
    return gsc_health()


@app.post("/api/gsc/query")
def gsc_query():
    raise HTTPException(status_code=400, detail="GSC 尚未完成授权，未请求 Google。")


@app.get("/api/ga4/health")
def ga4_connector_health():
    return ga4_health()


@app.post("/api/ga4/run-report")
def ga4_run_report():
    raise HTTPException(status_code=400, detail="GA4 尚未完成授权，未请求 Google。")


@app.get("/api/dataforseo/health")
def dataforseo_connector_health():
    return dataforseo_health()


@app.get("/api/imports", response_model=list[ImportOut])
def imports():
    return list_imports()


@app.patch("/api/imports/{import_id}/source", response_model=ImportSourceResult)
def patch_import_source(import_id: int, payload: ImportSourceIn):
    try:
        result = update_import_source(import_id, payload.source_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="导入批次不存在")
    return result


@app.post("/api/imports/{import_id}/promote-serp-competitors", response_model=PromoteSerpResult)
def promote_import_serp(import_id: int, payload: PromoteSerpIn):
    try:
        result = promote_serp_competitors(import_id, payload.cluster_id)
    except ValueError as exc:
        status = 404 if str(exc) == "关键词簇不存在" else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="导入批次不存在")
    return result


@app.get("/api/imports/{import_id}", response_model=ImportDetailOut)
def import_detail(import_id: int):
    detail = get_import(import_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="导入批次不存在")
    return detail


@app.get("/api/providers/health", response_model=ProviderHealthOut)
def providers_health():
    return provider_health(probe_sitedata=True)


@app.get("/api/storage/health", response_model=StorageHealthOut)
def storage_health_view():
    return storage_health()


@app.post("/api/storage/backup", response_model=StorageBackupOut)
def storage_backup():
    try:
        return backup_database()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/storage/backups", response_model=StorageBackupListOut)
def storage_backups():
    return {"items": list_backups()}


@app.post("/api/storage/export", response_model=StorageExportOut)
def storage_export():
    return export_csv()


@app.post("/api/sitedata/rankings/run", response_model=SiteDataRunOut)
def sitedata_rankings_run(payload: SiteDataRunIn):
    try:
        return run_rankings(payload.ranking_type, payload.period, payload.limit, payload.month)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/sitedata/rankings/run-all", response_model=SiteDataRunAllOut)
def sitedata_rankings_run_all(payload: SiteDataRunIn):
    try:
        return run_all(payload.period, payload.month, payload.limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/sitedata/signals", response_model=SiteDataSignalPage)
def sitedata_signals(limit: int = 20):
    return recent_signals(limit)


@app.get("/api/sitedata/opportunities", response_model=SiteDataOpportunityPage)
def sitedata_opportunities(limit: int = 10):
    return top_opportunities(limit)


@app.get("/api/sitedata/settings", response_model=SiteDataSettings)
def sitedata_settings():
    return get_settings()


@app.post("/api/sitedata/settings", response_model=SiteDataSettings)
def sitedata_settings_update(payload: SiteDataSettings):
    return set_auto_create(payload.auto_create_dossier)


@app.post("/api/providers/google-cse/check", response_model=ProviderHealthOut)
def providers_google_check():
    check_google_cse()
    return provider_health()


@app.get("/api/market/pulse", response_model=MarketPulseOut)
def market_pulse_view():
    return market_pulse()


@app.get("/api/providers/google-cse", response_model=GoogleCseCardOut)
def google_cse_view():
    return google_cse_card()


@app.post("/api/providers/google-cse/test", response_model=GoogleCseTestOut, response_model_exclude_none=True)
def google_cse_test(payload: GoogleCseTestIn):
    return test_google_cse(payload.query, payload.num)


@app.get("/api/providers/serp", response_model=SerpProviderOut)
def serp_provider_view():
    return serp_choices()


@app.post("/api/providers/serp", response_model=SerpProviderOut)
def serp_provider_update(payload: SerpProviderIn):
    try:
        return set_serp_provider(payload.provider)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/raw-records", response_model=list[RawRecordOut])
def raw_records(source_id: int | None = None, record_type: str | None = None):
    return list_raw_records(source_id, record_type)


@app.get("/api/evidence/stats", response_model=EvidenceStatsOut)
def evidence_slot_stats():
    return evidence_stats()


@app.get("/api/explorer/records", response_model=ExplorerPage)
def explorer_records(
    dataset_type: str | None = None,
    record_type: str | None = None,
    provider: str | None = None,
    batch_id: int | None = None,
    period_month: str | None = None,
    domain: str | None = None,
    keyword: str | None = None,
    source_name: str | None = None,
    limit: int | None = Query(default=50),
    offset: int | None = Query(default=0),
):
    return list_explorer_records(
        dataset_type,
        record_type,
        provider,
        batch_id,
        period_month,
        domain,
        keyword,
        source_name,
        limit,
        offset,
    )


@app.get("/api/import-batches", response_model=list[ImportBatchSummary])
def import_batches():
    return list_import_batches()


@app.get("/api/import-batches/{batch_id}", response_model=ImportBatchDetail)
def import_batch_detail(batch_id: int):
    detail = get_import_batch(batch_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="导入批次不存在")
    return detail


@app.get("/api/external-opportunities", response_model=ExternalOpportunityPage)
def external_opportunity_list(
    min_score: int | None = None,
    evidence_type: str | None = None,
    domain: str | None = None,
    limit: int | None = Query(default=50),
    offset: int | None = Query(default=0),
    home: bool = False,
):
    return external_opportunities(min_score, evidence_type, domain, limit, offset, home)


@app.get("/api/intelligence/feed", response_model=FeedOut)
@app.get("/api/feed", response_model=FeedOut)
def intelligence_feed_list(limit: int = 20):
    return list_feed(limit)


@app.get("/api/dashboard/today", response_model=FeedOut)
def dashboard_today(limit: int = 10):
    return today_feed(limit)


@app.post("/api/intelligence/feed/{feed_id}/action", response_model=FeedActionOut)
def intelligence_feed_action(feed_id: int, payload: FeedActionIn):
    try:
        return apply_feed_action(feed_id, payload.action)
    except ValueError as exc:
        missing = str(exc) in {"资讯不存在", "关键词簇不存在"}
        raise HTTPException(status_code=404 if missing else 400, detail=str(exc)) from exc


@app.post("/api/intake/collect-now", response_model=CollectNowOut)
async def intake_collect_now():
    return await collect_now()


@app.get("/api/intake/collect-status", response_model=CollectStatusOut)
def intake_collect_status():
    return collect_status()


@app.get("/api/dashboard/ranks", response_model=RankBoard)
def dashboard_ranks(limit: int = 10):
    return top_rankings(limit)


@app.post("/api/sources/{source_id}/run", response_model=SourceRunOut)
async def source_run(source_id: int):
    try:
        return await run_source(source_id)
    except ValueError as exc:
        missing = str(exc) == "数据源不存在"
        raise HTTPException(status_code=404 if missing else 400, detail=str(exc)) from exc


@app.post("/api/sources/{source_id}/enabled", response_model=SourceOut)
def source_enabled(source_id: int, enabled: int = Query(...)):
    try:
        source = set_source_enabled(source_id, enabled)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if source is None:
        raise HTTPException(status_code=404, detail="数据源不存在")
    return source


@app.get("/api/sources/{source_id}/records")
def source_record_list(source_id: int):
    try:
        return source_records(source_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _run_serp_query(payload: GoogleSearchQueryIn):
    try:
        return search_serp(payload.query, payload.num, payload.gl, payload.hl)
    except GoogleSearchError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/api/google-search/query", response_model=GoogleSearchQueryOut)
def google_search_query(payload: GoogleSearchQueryIn):
    return _run_serp_query(payload)


@app.post("/api/serp/query", response_model=GoogleSearchQueryOut)
def serp_query(payload: GoogleSearchQueryIn):
    return _run_serp_query(payload)


@app.post("/api/google-search/import-competitors", response_model=GoogleSearchImportOut)
def google_search_import(payload: GoogleSearchImportIn):
    try:
        return import_competitors(payload.cluster_id, payload.query, payload.num, payload.gl, payload.hl)
    except GoogleSearchError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/api/source-records", response_model=SourceRecordOut)
def add_source_record(payload: SourceRecordIn):
    try:
        return create_source_record(payload.model_dump())
    except ValueError as exc:
        status = 404 if str(exc) == "数据源不存在" else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@app.get("/api/analysis/{item_id}", response_model=AnalysisOut)
def analysis(item_id: int):
    if get_item(item_id) is None:
        raise HTTPException(status_code=404, detail="资讯不存在")
    row = get_analysis(item_id)
    if row is None:
        raise HTTPException(status_code=404, detail="暂无分析")
    return row


def _dossier_error(exc: ValueError) -> HTTPException:
    missing = str(exc) in {"资讯不存在", "记录不存在", "案卷不存在"}
    return HTTPException(status_code=404 if missing else 400, detail=str(exc))


@app.get("/api/dossiers", response_model=DossierListOut)
def dossier_list(limit: int = 10):
    return list_dossiers(limit)


@app.get("/api/dossiers/{dossier_id}", response_model=DossierDetailOut)
def dossier_detail(dossier_id: int):
    detail = get_dossier(dossier_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="案卷不存在")
    return detail


@app.post("/api/dossiers/manual", response_model=DossierActionOut)
def dossier_manual(payload: ManualIntakeIn):
    try:
        return manual_intake(payload.model_dump())
    except ValueError as exc:
        raise _dossier_error(exc) from exc


@app.post("/api/dossiers/from-feed", response_model=DossierActionOut)
def dossier_from_feed(payload: DossierActionIn):
    try:
        return from_feed(payload.feed_id, payload.action)
    except ValueError as exc:
        raise _dossier_error(exc) from exc


@app.post("/api/dossiers/from-domain", response_model=DossierActionOut)
def dossier_from_domain(payload: DossierActionIn):
    try:
        return from_domain(payload.domain, payload.action)
    except ValueError as exc:
        raise _dossier_error(exc) from exc


@app.post("/api/dossiers/from-record", response_model=DossierActionOut)
def dossier_from_record(payload: DossierActionIn):
    try:
        return from_record(payload.record_id)
    except ValueError as exc:
        raise _dossier_error(exc) from exc


@app.post("/api/dossiers/{dossier_id}/evidence", response_model=DossierActionOut)
def dossier_add_evidence(dossier_id: int, payload: ManualIntakeIn):
    try:
        return add_evidence(dossier_id, payload.model_dump())
    except ValueError as exc:
        raise _dossier_error(exc) from exc


@app.post("/api/dossiers/{dossier_id}/screenshot", response_model=DossierActionOut)
async def dossier_screenshot(
    dossier_id: int,
    file: UploadFile = File(...),
    note: str = Form(""),
    metric_name: str = Form(""),
    metric_value: str = Form(""),
    period_month: str = Form(""),
    title: str = Form(""),
):
    content = await file.read()
    try:
        return add_screenshot(
            dossier_id,
            file.filename or "screenshot",
            content,
            {"note": note, "metric_name": metric_name, "metric_value": metric_value, "period_month": period_month, "title": title},
        )
    except ValueError as exc:
        raise _dossier_error(exc) from exc


@app.post("/api/dossiers/{dossier_id}/action", response_model=DossierActionOut)
def dossier_action(dossier_id: int, payload: DossierActionIn):
    try:
        return run_action(dossier_id, payload.action)
    except ValueError as exc:
        raise _dossier_error(exc) from exc


@app.get("/api/dossiers/{dossier_id}/evidence/{evidence_id}/file")
def dossier_screenshot_file(dossier_id: int, evidence_id: int):
    path = screenshot_path(dossier_id, evidence_id)
    if path is None:
        raise HTTPException(status_code=404, detail="截图不存在")
    return FileResponse(path)


frontend_dir = project_root() / "frontend"


@app.get("/")
def index_page():
    return FileResponse(frontend_dir / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/dossiers/{dossier_id}")
def dossier_page(dossier_id: int):
    return FileResponse(frontend_dir / "index.html", headers={"Cache-Control": "no-store"})


if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
