import logging
import os
import time
from urllib.parse import urlparse

import httpx

from app.competitors import domain_of
from app.db import connect, utc_today
from app.google_search import GoogleSearchError, install_google_log_redaction
from app.trace import record_trace

install_google_log_redaction()
_log = logging.getLogger("app.serper")


def _enabled() -> bool:
    return os.getenv("SERPER_ENABLED", "").strip().lower() == "true"


def _base_url() -> str:
    return os.getenv("SERPER_BASE_URL", "https://google.serper.dev").strip().rstrip("/") or "https://google.serper.dev"


def _daily_limit() -> int:
    raw = os.getenv("SERPER_DAILY_LIMIT", "100").strip() or "100"
    try:
        return max(0, int(raw))
    except ValueError:
        return 100


def _clamp_num(num: int) -> int:
    try:
        value = int(num)
    except (TypeError, ValueError):
        value = 10
    if value < 1:
        return 1
    if value > 10:
        return 10
    return value


def _locale(value: str, default: str) -> str:
    text = (value or "").strip().lower()
    if not text or len(text) > 12 or any(char not in "abcdefghijklmnopqrstuvwxyz-" for char in text):
        return default
    return text


def _display_link(row: dict, link: str) -> str:
    domain = str(row.get("domain") or "").strip()
    if not domain:
        domain = domain_of(link)
    if not domain:
        parsed = urlparse(link if "://" in link else f"https://{link}")
        domain = (parsed.netloc or "").lower()
    if domain.lower().startswith("www."):
        domain = domain[4:]
    return domain


def _take_quota() -> None:
    limit = _daily_limit()
    day = utc_today()
    conn = connect()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS serper_usage (
                date TEXT PRIMARY KEY,
                count INTEGER NOT NULL
            )
            """
        )
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT count FROM serper_usage WHERE date = ?",
            (day,),
        ).fetchone()
        current = int(row["count"]) if row else 0
        if current >= limit:
            conn.rollback()
            raise GoogleSearchError("Serper 今日额度已用完", 429)
        if row:
            conn.execute(
                "UPDATE serper_usage SET count = count + 1 WHERE date = ?",
                (day,),
            )
        else:
            conn.execute(
                "INSERT INTO serper_usage (date, count) VALUES (?, 1)",
                (day,),
            )
        conn.commit()
    except GoogleSearchError:
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _items(payload: dict, size: int) -> list[dict]:
    organic = payload.get("organic") if isinstance(payload, dict) else None
    if not isinstance(organic, list):
        return []
    items = []
    for index, row in enumerate(organic):
        if not isinstance(row, dict) or len(items) >= size:
            continue
        link = str(row.get("link") or "").strip()
        try:
            rank = int(row.get("position"))
        except (TypeError, ValueError):
            rank = index + 1
        items.append({
            "title": str(row.get("title") or ""),
            "link": link,
            "displayLink": _display_link(row, link),
            "snippet": str(row.get("snippet") or ""),
            "rank": rank if rank > 0 else index + 1,
        })
    return items


def search_serper(query: str, num: int = 10, gl: str = "us", hl: str = "en") -> dict:
    text = (query or "").strip()
    if not text:
        raise GoogleSearchError("query 不能为空")
    if not _enabled():
        raise GoogleSearchError("Serper 未启用。请在 .env 设置 SERPER_ENABLED=true")
    key = os.getenv("SERPER_API_KEY", "").strip()
    if not key:
        raise GoogleSearchError("未配置 SERPER_API_KEY")
    size = _clamp_num(num)
    region = _locale(gl, "us")
    language = _locale(hl, "en")
    _take_quota()
    started = time.perf_counter()
    status: int | str | None = None
    try:
        try:
            response = httpx.post(
                f"{_base_url()}/search",
                headers={"X-API-KEY": key, "Content-Type": "application/json"},
                json={"q": text, "num": size, "gl": region, "hl": language},
                timeout=30,
            )
        except httpx.TimeoutException:
            status = "timeout"
            raise GoogleSearchError("Serper 超时", 504) from None
        except httpx.HTTPError:
            status = 502
            raise GoogleSearchError("Serper 请求失败", 502) from None
        status = response.status_code
        if response.status_code != 200:
            raise GoogleSearchError("Serper 请求失败", 502 if response.status_code >= 500 else response.status_code) from None
        try:
            payload = response.json()
        except ValueError:
            raise GoogleSearchError("Serper 返回无法解析", 502) from None
        if not isinstance(payload, dict):
            payload = {}
        found = _items(payload, size)
        return {
            "provider": "serper",
            "query": text,
            "count": len(found),
            "items": found,
        }
    finally:
        if status is not None:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            _log.info(
                "provider=serper query=%s num=%s gl=%s hl=%s status_code=%s elapsed_ms=%s",
                text,
                size,
                region,
                language,
                status,
                elapsed_ms,
            )
            record_trace(
                "POST",
                "external_serper",
                status,
                elapsed_ms,
                "external_serper",
                f"provider=serper query={text} num={size} gl={region} hl={language} status_code={status} elapsed_ms={elapsed_ms}",
            )
