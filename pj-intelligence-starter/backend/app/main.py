import logging
import time
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
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
    import_competitors,
    install_google_log_redaction,
    provider_health,
)
from app.serp import search_serp
from app.inbox import (
    bind_raw_record,
    get_import,
    import_csv,
    import_uploaded_csv,
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
)

load_dotenv(project_root() / ".env")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
install_google_log_redaction()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
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
    return provider_health()


@app.post("/api/providers/google-cse/check", response_model=ProviderHealthOut)
def providers_google_check():
    check_google_cse()
    return provider_health()


@app.get("/api/raw-records", response_model=list[RawRecordOut])
def raw_records(source_id: int | None = None, record_type: str | None = None):
    return list_raw_records(source_id, record_type)


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


frontend_dir = project_root() / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
