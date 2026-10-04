import logging
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
from app.llm import LLMCallError, LLMConfigError, analyze, daily_limit, require_config
from app.schemas import AnalysisOut, CollectOut, HealthOut, ItemOut

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
    except (LLMConfigError, LLMCallError) as exc:
        release_quota()
        status = 400 if isinstance(exc, LLMConfigError) else 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    except Exception:
        release_quota()
        raise

    return save_analysis(item_id, model, text)


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
