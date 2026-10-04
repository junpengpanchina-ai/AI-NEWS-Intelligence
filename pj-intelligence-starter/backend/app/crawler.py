import asyncio
import logging
from datetime import datetime, timezone
from html import unescape

import feedparser
import httpx

from app.db import content_hash, insert_item, list_sources
from app.scoring import compute_score

logger = logging.getLogger("pj.collect")

HN_ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{item_id}.json"
HN_LIMIT = 30
RSS_LIMIT = 20
USER_AGENT = "PJIntelligence/0.1"


def strip_html(value: str) -> str:
    text = unescape(value or "")
    out = []
    inside = False
    for char in text:
        if char == "<":
            inside = True
            continue
        if char == ">":
            inside = False
            out.append(" ")
            continue
        if not inside:
            out.append(char)
    cleaned = " ".join("".join(out).split())
    return cleaned[:2000]


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _build_item(
    source_name: str,
    title: str,
    url: str,
    summary: str,
    author: str,
    published_at: datetime | None,
    weight: int,
    hn_score: int | None,
    fetched_at: str,
) -> dict | None:
    title = " ".join((title or "").split())[:500]
    url = (url or "").strip()
    if not title or not url.startswith("http"):
        return None
    return {
        "source_name": source_name,
        "title": title,
        "url": url,
        "summary": strip_html(summary),
        "author": " ".join((author or "").split())[:200],
        "published_at": _iso(published_at),
        "fetched_at": fetched_at,
        "content_hash": content_hash(title),
        "score": compute_score(weight, title, published_at, hn_score),
        "status": "new",
    }


async def _fetch_hn(client: httpx.AsyncClient, source: dict) -> tuple[list[dict], list[str]]:
    name = source["name"]
    try:
        response = await client.get(source["url"])
        response.raise_for_status()
        ids = response.json()
        if not isinstance(ids, list):
            return [], [f"{name}: 返回格式异常"]
    except Exception as exc:
        logger.warning("source failed: %s", name)
        return [], [f"{name}: {exc}"]

    semaphore = asyncio.Semaphore(8)
    fetched_at = datetime.now(timezone.utc).isoformat()

    async def one(item_id: int):
        async with semaphore:
            try:
                response = await client.get(HN_ITEM_URL.format(item_id=item_id))
                response.raise_for_status()
                return response.json()
            except Exception as exc:
                return exc

    rows = await asyncio.gather(*(one(item_id) for item_id in ids[:HN_LIMIT]))
    items = []
    failed = 0
    for row in rows:
        if isinstance(row, Exception) or not isinstance(row, dict):
            failed += 1
            continue
        published = None
        if row.get("time"):
            published = datetime.fromtimestamp(int(row["time"]), tz=timezone.utc)
        url = row.get("url") or ""
        if not url and row.get("id"):
            url = f"https://news.ycombinator.com/item?id={row['id']}"
        item = _build_item(
            source_name=name,
            title=str(row.get("title") or ""),
            url=url,
            summary=str(row.get("text") or ""),
            author=str(row.get("by") or ""),
            published_at=published,
            weight=int(source["weight"]),
            hn_score=row.get("score"),
            fetched_at=fetched_at,
        )
        if item:
            items.append(item)
    errors = []
    if failed:
        errors.append(f"{name}: {failed} 条详情拉取失败")
    return items, errors


def _entry_time(entry) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    try:
        return datetime(*parsed[:6], tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _entry_link(entry) -> str:
    link = entry.get("link") or ""
    if link:
        return link
    links = entry.get("links") or []
    if links:
        return links[0].get("href") or ""
    return ""


def _entry_author(entry) -> str:
    author = entry.get("author") or ""
    if author:
        return author
    authors = entry.get("authors") or []
    if authors:
        return authors[0].get("name") or ""
    return ""


async def _fetch_rss(client: httpx.AsyncClient, source: dict) -> tuple[list[dict], list[str]]:
    name = source["name"]
    try:
        response = await client.get(source["url"])
        response.raise_for_status()
        parsed = feedparser.parse(response.content)
    except Exception as exc:
        logger.warning("source failed: %s", name)
        return [], [f"{name}: {exc}"]

    if not parsed.entries:
        reason = getattr(parsed, "bozo_exception", None) or "无条目"
        return [], [f"{name}: {reason}"]

    fetched_at = datetime.now(timezone.utc).isoformat()
    items = []
    errors = []
    for entry in parsed.entries[:RSS_LIMIT]:
        try:
            item = _build_item(
                source_name=name,
                title=str(entry.get("title") or ""),
                url=_entry_link(entry),
                summary=str(entry.get("summary") or entry.get("description") or ""),
                author=_entry_author(entry),
                published_at=_entry_time(entry),
                weight=int(source["weight"]),
                hn_score=None,
                fetched_at=fetched_at,
            )
            if item:
                items.append(item)
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    return items, errors


async def collect() -> dict:
    sources = list_sources()
    inserted = 0
    skipped = 0
    errors: list[str] = []

    timeout = httpx.Timeout(20.0, connect=10.0)
    headers = {"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/xml, application/json, */*"}
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
        tasks = []
        for source in sources:
            if source["type"] == "hn":
                tasks.append(_fetch_hn(client, source))
            else:
                tasks.append(_fetch_rss(client, source))
        results = await asyncio.gather(*tasks, return_exceptions=True)

    for source, result in zip(sources, results):
        if isinstance(result, Exception):
            errors.append(f"{source['name']}: {result}")
            continue
        items, source_errors = result
        errors.extend(source_errors)
        for item in items:
            if insert_item(item):
                inserted += 1
            else:
                skipped += 1

    logger.info("collect inserted=%s skipped=%s errors=%s", inserted, skipped, len(errors))
    return {"inserted": inserted, "skipped": skipped, "errors": errors}
