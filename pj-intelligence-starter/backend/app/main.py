import logging
import time
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
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
from app.llm import LLMCallError, LLMConfigError, analyze, analyze_event, daily_limit, require_config
from app.schemas import (
    AnalysisOut,
    BuildEventsOut,
    CollectOut,
    EventAnalysisOut,
    EventDetailOut,
    EventOut,
    HealthOut,
    ItemOut,
)

load_dotenv(project_root() / ".env")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="PJ Intelligence", lifespan=lifespan)


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
