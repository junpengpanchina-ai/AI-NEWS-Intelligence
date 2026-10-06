import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx

from app.competitors import create_competitor, domain_of
from app.db import connect, utc_today
from app.keywords import get_keyword_cluster
from app.ledger import create_source_record, ensure_google_search_source, ensure_serper_source
from app.trace import record_trace

GOOGLE_SEARCH_URL = "https://www.googleapis.com/customsearch/v1"
MANUAL_CSV_HINT = "当前 SERP_PROVIDER=manual_csv，请使用 Admin → Sources → Data Imports 导入 SERP CSV。"
GOOGLE_403_SUGGESTION = "切换 manual_csv / Serper / DataForSEO / SerpAPI"
_log = logging.getLogger("app.google_search")


def redact_google_url(url: str) -> str:
    text = str(url or "")
    secret = os.getenv("GOOGLE_CSE_API_KEY", "").strip()
    if secret:
        text = text.replace(secret, "[redacted]")
    return re.sub(r"(?i)([?&]key=)[^&#\s\"]*", r"\1[redacted]", text)


class GoogleKeyLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        secrets = [
            os.getenv(name, "").strip()
            for name in ("GOOGLE_CSE_API_KEY", "SERPER_API_KEY")
        ]
        secrets = [item for item in secrets if item]
        lowered = message.lower()
        if record.name.startswith(("httpx", "httpcore")) and (
            "key=" in lowered or "x-api-key" in lowered or any(secret in message for secret in secrets)
        ):
            return False
        redacted = redact_google_url(message)
        for secret in secrets:
            if secret in redacted:
                redacted = redacted.replace(secret, "[redacted]")
        if redacted != message:
            record.msg = redacted
            record.args = None
        return True


def install_google_log_redaction() -> None:
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    redactor = GoogleKeyLogFilter()
    for name in ("", "httpx", "httpcore", "app.google_search", "app.serper"):
        logger = logging.getLogger(name)
        if not any(isinstance(item, GoogleKeyLogFilter) for item in logger.filters):
            logger.addFilter(redactor)
        for handler in logger.handlers:
            if not any(isinstance(item, GoogleKeyLogFilter) for item in handler.filters):
                handler.addFilter(redactor)


install_google_log_redaction()


class GoogleSearchError(Exception):
    def __init__(self, message: str, status_code: int = 400, detail=None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.detail = message if detail is None else detail


def serp_provider() -> str:
    return os.getenv("SERP_PROVIDER", "manual_csv").strip().lower() or "manual_csv"


_last_google_health: dict | None = None


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() == "true"


def _env_set(name: str) -> bool:
    return bool(os.getenv(name, "").strip())


def _google_provider_row() -> dict:
    enabled = _enabled()
    configured = _env_set("GOOGLE_CSE_API_KEY") and _env_set("GOOGLE_CSE_CX")
    if enabled and configured and _last_google_health:
        row = dict(_last_google_health)
        row["enabled"] = True
        row["configured"] = True
        return row
    if not enabled or not configured:
        return {
            "name": "Google CSE",
            "type": "serp",
            "enabled": enabled,
            "configured": configured,
            "status": "not_configured",
            "message": "Set GOOGLE_CSE_ENABLED=true, GOOGLE_CSE_API_KEY and GOOGLE_CSE_CX",
        }
    return {
        "name": "Google CSE",
        "type": "serp",
        "enabled": True,
        "configured": True,
        "status": "unchecked",
        "message": "尚未检测。点击检测后才会请求 Google。",
    }


def provider_health() -> dict:
    serper_enabled = _env_flag("SERPER_ENABLED")
    serper_configured = _env_set("SERPER_API_KEY")
    serper_ready = serp_provider() == "serper" and serper_enabled and serper_configured
    if serper_ready:
        serper_message = "Serper is the active SERP provider"
    elif serper_enabled and serper_configured:
        serper_message = "Set SERP_PROVIDER=serper"
    else:
        serper_message = "Set SERPER_ENABLED=true and SERPER_API_KEY"
    return {
        "serp_provider": serp_provider(),
        "providers": [
            _google_provider_row(),
            {
                "name": "Manual CSV",
                "type": "serp",
                "enabled": True,
                "configured": True,
                "status": "ready",
                "message": "Use Admin → Sources → Data Imports to import SERP CSV",
            },
            {
                "name": "Serper",
                "type": "serp",
                "enabled": serper_enabled,
                "configured": serper_configured,
                "status": "ready" if serper_ready else "not_configured",
                "message": serper_message,
            },
            {
                "name": "GSC",
                "type": "validation",
                "enabled": False,
                "configured": False,
                "status": "planned",
                "message": "planned",
            },
            {
                "name": "GA4",
                "type": "validation",
                "enabled": False,
                "configured": False,
                "status": "planned",
                "message": "planned",
            },
        ],
    }


def check_google_cse() -> dict:
    global _last_google_health
    enabled = _enabled()
    key = os.getenv("GOOGLE_CSE_API_KEY", "").strip()
    cx = os.getenv("GOOGLE_CSE_CX", "").strip()
    if not enabled or not key or not cx:
        _last_google_health = None
        return _google_provider_row()
    started = time.perf_counter()
    status_code: int | str | None = None
    row = {
        "name": "Google CSE",
        "type": "serp",
        "enabled": True,
        "configured": True,
        "status": "blocked",
        "message": "Google Search 请求失败",
        "action": "Use manual_csv or configure Serper/DataForSEO/SerpAPI",
    }
    try:
        try:
            response = httpx.get(
                GOOGLE_SEARCH_URL,
                params={"key": key, "cx": cx, "q": "healthcheck", "num": 1},
                timeout=30,
            )
        except httpx.TimeoutException:
            status_code = "timeout"
            row["message"] = "Google Search 超时"
            row["last_status_code"] = None
        except httpx.HTTPError:
            status_code = 502
            row["last_status_code"] = 502
        else:
            status_code = response.status_code
            row["last_status_code"] = response.status_code
            if response.status_code == 200:
                row["status"] = "ready"
                row["message"] = "Google CSE responded"
                row.pop("action", None)
            elif response.status_code == 403:
                detail = _google_403_detail(response)
                row["status"] = "blocked"
                row["message"] = str(detail["google_message"])
            else:
                row["status"] = "blocked"
    finally:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        host = urlsplit(GOOGLE_SEARCH_URL).hostname or "www.googleapis.com"
        _log.info(
            "Google Search query=%s num=%s status_code=%s elapsed_ms=%s host=%s cx_present=%s",
            "healthcheck",
            1,
            status_code if status_code is not None else 500,
            elapsed_ms,
            host,
            "true",
        )
        record_trace(
            "GET",
            "external_google_search",
            status_code if status_code is not None else 500,
            elapsed_ms,
            "external_google_search",
            f"query=healthcheck num=1 host={host} cx_present=true",
        )
    _last_google_health = row
    return row


def _require_google_provider() -> None:
    provider = serp_provider()
    if provider == "manual_csv":
        raise GoogleSearchError(MANUAL_CSV_HINT, 400)
    if provider != "google_cse":
        raise GoogleSearchError(f"当前 SERP_PROVIDER={provider}，尚未接入。", 400)


def _safe_upstream_text(value: str) -> str:
    text = str(value or "")
    for env_name in ("GOOGLE_CSE_API_KEY", "GOOGLE_CSE_CX", "SERPER_API_KEY"):
        secret = os.getenv(env_name, "").strip()
        if secret:
            text = text.replace(secret, "[redacted]")
    return redact_google_url(text)


def _google_403_detail(response: httpx.Response) -> dict:
    status_name = ""
    message = ""
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            status_name = _safe_upstream_text(error.get("status") or "")
            message = _safe_upstream_text(error.get("message") or "")
    return {
        "provider": "google_cse",
        "status_code": 403,
        "google_status": status_name or "PERMISSION_DENIED",
        "google_message": message or "This project does not have the access to Custom Search JSON API.",
        "suggestion": GOOGLE_403_SUGGESTION,
    }


def _enabled() -> bool:
    return os.getenv("GOOGLE_CSE_ENABLED", "").strip().lower() == "true"


def _daily_limit() -> int:
    raw = os.getenv("GOOGLE_CSE_DAILY_LIMIT", "80").strip() or "80"
    try:
        return max(0, int(raw))
    except ValueError:
        return 80


def _require_config() -> tuple[str, str]:
    if not _enabled():
        raise GoogleSearchError("Google Search 未启用。请在 .env 设置 GOOGLE_CSE_ENABLED=true")
    key = os.getenv("GOOGLE_CSE_API_KEY", "").strip()
    cx = os.getenv("GOOGLE_CSE_CX", "").strip()
    missing = []
    if not key:
        missing.append("GOOGLE_CSE_API_KEY")
    if not cx:
        missing.append("GOOGLE_CSE_CX")
    if missing:
        raise GoogleSearchError("未配置 " + "、".join(missing))
    return key, cx


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


def _take_quota() -> None:
    limit = _daily_limit()
    day = utc_today()
    conn = connect()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS google_cse_usage (
                date TEXT PRIMARY KEY,
                count INTEGER NOT NULL
            )
            """
        )
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT count FROM google_cse_usage WHERE date = ?",
            (day,),
        ).fetchone()
        current = int(row["count"]) if row else 0
        if current >= limit:
            conn.rollback()
            raise GoogleSearchError("Google Search 今日额度已用完", 429)
        if row:
            conn.execute(
                "UPDATE google_cse_usage SET count = count + 1 WHERE date = ?",
                (day,),
            )
        else:
            conn.execute(
                "INSERT INTO google_cse_usage (date, count) VALUES (?, 1)",
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


def _public_item(item: dict) -> dict:
    return {
        "title": item.get("title") or "",
        "link": item.get("link") or "",
        "displayLink": item.get("displayLink") or "",
        "snippet": item.get("snippet") or "",
    }


def search_google(query: str, num: int = 10) -> list[dict]:
    text = (query or "").strip()
    if not text:
        raise GoogleSearchError("query 不能为空")
    size = _clamp_num(num)
    _require_google_provider()
    key, cx = _require_config()
    _take_quota()
    started = time.perf_counter()
    status: int | str | None = None
    try:
        try:
            response = httpx.get(
                GOOGLE_SEARCH_URL,
                params={"key": key, "cx": cx, "q": text, "num": size},
                timeout=30,
            )
        except httpx.TimeoutException:
            status = "timeout"
            raise GoogleSearchError("Google Search 超时", 504) from None
        except httpx.HTTPError:
            status = 502
            raise GoogleSearchError("Google Search 请求失败", 502) from None
        status = response.status_code
        if response.status_code == 403:
            detail = _google_403_detail(response)
            raise GoogleSearchError(str(detail["google_message"]), 403, detail=detail) from None
        if response.status_code != 200:
            raise GoogleSearchError("Google Search 请求失败", 502) from None
        try:
            payload = response.json()
        except ValueError:
            raise GoogleSearchError("Google Search 返回无法解析", 502) from None
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return []
        return [_public_item(item) for item in items if isinstance(item, dict)]
    finally:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        status_code = status if status is not None else 500
        host = urlsplit(GOOGLE_SEARCH_URL).hostname or "www.googleapis.com"
        cx_present = "true" if cx else "false"
        _log.info(
            "Google Search query=%s num=%s status_code=%s elapsed_ms=%s host=%s cx_present=%s",
            text,
            size,
            status_code,
            elapsed_ms,
            host,
            cx_present,
        )
        record_trace(
            "GET",
            "external_google_search",
            status_code,
            elapsed_ms,
            "external_google_search",
            f"query={text} num={size} host={host} cx_present={cx_present}",
        )


def _url_exists(url: str) -> bool:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT id FROM competitor_pages WHERE url = ?",
            (url,),
        ).fetchone()
    finally:
        conn.close()
    return row is not None


def _draft_notes(item: dict) -> str:
    snippet = (item.get("snippet") or "").strip()
    rank = item.get("rank")
    if not rank:
        return snippet
    rank_line = f"rank {rank}"
    return f"{snippet}\n{rank_line}" if snippet else rank_line


def import_competitors(cluster_id: int, query: str, num: int = 10, gl: str = "us", hl: str = "en") -> dict:
    from app.serp import search_serp

    text = (query or "").strip()
    cluster = get_keyword_cluster(int(cluster_id))
    if cluster is None:
        raise GoogleSearchError("关键词簇不存在", 404)
    result = search_serp(text, num, gl, hl)
    items = result.get("items") or []
    provider = str(result.get("provider") or "")
    if provider == "serper":
        source = ensure_serper_source()
    elif provider == "google_cse":
        source = ensure_google_search_source()
    else:
        raise GoogleSearchError(f"当前 SERP_PROVIDER={provider}，尚未接入。", 400)
    now = datetime.now(timezone.utc).isoformat()
    conn = connect()
    try:
        cur = conn.execute(
            """
            INSERT INTO source_imports (
                source_id, import_name, source_type, record_type, original_filename,
                row_count, status, notes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(source["id"]),
                text,
                "serp",
                "serp_result",
                "",
                len(items),
                "imported" if items else "empty",
                "",
                now,
            ),
        )
        import_id = int(cur.lastrowid)
        for item in items:
            link = (item.get("link") or "").strip()
            domain = (item.get("displayLink") or "").strip() or domain_of(link)
            rank = item.get("rank")
            conn.execute(
                """
                INSERT INTO raw_source_records (
                    import_id, source_id, record_type, raw_json, normalized_title,
                    normalized_url, normalized_keyword, normalized_domain, metric_name,
                    metric_value, time_range, confidence, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    import_id,
                    int(source["id"]),
                    "serp_result",
                    json.dumps(item, ensure_ascii=False),
                    item.get("title") or "",
                    link,
                    text,
                    domain,
                    "rank" if rank else "",
                    str(rank) if rank else "",
                    "",
                    provider or "serp",
                    "imported",
                    now,
                ),
            )
        conn.commit()
    finally:
        conn.close()

    created = 0
    skipped = 0
    seen = set()
    for item in items:
        link = (item.get("link") or "").strip()
        if not link or link in seen or _url_exists(link):
            skipped += 1
            continue
        seen.add(link)
        page = create_competitor({
            "cluster_id": int(cluster_id),
            "url": link,
            "domain": (item.get("displayLink") or "").strip(),
            "title": item.get("title") or "",
            "h1": "",
            "page_type": "unknown",
            "target_keyword": text,
            "notes": _draft_notes(item),
        })
        if page is None:
            skipped += 1
            continue
        create_source_record({
            "source_id": int(source["id"]),
            "record_type": "competitor_page",
            "linked_table": "competitor_pages",
            "linked_id": int(page["id"]),
            "raw_ref": link,
            "confidence": provider or "serp",
        })
        created += 1
    return {
        "provider": provider,
        "query": text,
        "raw_records_created": len(items),
        "competitors_created": created,
        "skipped": skipped,
    }
