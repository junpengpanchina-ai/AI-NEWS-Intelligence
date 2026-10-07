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
from app.llm import grsai_health
from app.keywords import get_keyword_cluster
from app.ledger import create_source_record, ensure_google_search_source, ensure_serper_source
from app.trace import record_trace

GOOGLE_SEARCH_URL = "https://www.googleapis.com/customsearch/v1"
MANUAL_CSV_HINT = "当前 SERP_PROVIDER=manual_csv，请使用 Admin → Sources → Data Imports 导入 SERP CSV。"
GOOGLE_CSE_REASON = "This Google Cloud project does not have access to Custom Search JSON API."
GOOGLE_CSE_FIX_STEPS = [
    "Custom Search API 已启用但项目仍被 Google 拒绝访问",
    "可等待 10–30 分钟后重试",
    "可换新 Google Cloud Project / 新 Key 测试",
    "当前主 SERP_PROVIDER 使用 Serper",
]
GOOGLE_CSE_FIX = "\n".join(GOOGLE_CSE_FIX_STEPS)
GOOGLE_CSE_SETUP = "请配置 GOOGLE_CSE_ENABLED=true, GOOGLE_CSE_API_KEY, GOOGLE_CSE_CX"
GOOGLE_CSE_BLOCKED = "Google CSE blocked_entitlement。这是项目访问资格，不是系统错误。SERP 继续使用 Serper。"
GOOGLE_CSE_STEPS = [
    "Google Cloud → API 和服务 → 库 → 搜索 Custom Search API",
    "启用 Custom Search API",
    "API 和服务 → 凭据 → 创建 API 密钥",
    "API 限制选择 Custom Search API",
    "Programmable Search Engine 复制搜索引擎 ID",
    "写入 .env 的 GOOGLE_CSE_API_KEY 和 GOOGLE_CSE_CX",
    "重启容器",
    "点击 Test Google CSE",
]
_CX_URL = re.compile(r"(?i)(?:https?://)?(?:www\.)?cse\.google\.com/cse(?:\.js)?\?.*?[?&]cx=([^&#\s]+)")
_CX_PARAM = re.compile(r"(?i)(?:^|[?&])cx=([^&#\s]+)")
_SERP_PROVIDERS = {"serper", "google_cse", "manual_csv"}
_TEST_FIELDS = ("provider", "status", "http_status", "items_count", "message", "google_reason", "fix_hint", "fix_steps", "cx_warning", "tested_at")
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
            for name in ("GOOGLE_CSE_API_KEY", "SERPER_API_KEY", "LLM_API_KEY")
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
    override = _serp_override()
    if override in _SERP_PROVIDERS:
        return override
    value = os.getenv("SERP_PROVIDER", "manual_csv").strip().lower() or "manual_csv"
    return value if value in _SERP_PROVIDERS else "manual_csv"


def resolve_cx(raw: str) -> tuple[str, str]:
    text = (raw or "").strip()
    if not text:
        return "", ""
    lowered = text.lower()
    if "cse.google.com" in lowered or lowered.startswith("http://") or lowered.startswith("https://"):
        match = _CX_URL.search(text) or _CX_PARAM.search(text)
        if match:
            return match.group(1).strip(), "GOOGLE_CSE_CX 填写了完整 URL，已自动截取搜索引擎 ID。"
    return text, ""


def google_cse_card() -> dict:
    enabled = _enabled()
    key_present = _env_set("GOOGLE_CSE_API_KEY")
    cx_raw = os.getenv("GOOGLE_CSE_CX", "").strip()
    cx, warning = resolve_cx(cx_raw)
    cx_present = bool(cx)
    configured = enabled and key_present and cx_present
    last = _stored_test()
    last_status = str(last.get("status") or "")
    entitlement = last_status in {"blocked", "blocked_entitlement"} and _project_block_text(
        f"{last.get('google_reason') or ''} {last.get('message') or ''} {last_status}"
    )
    if entitlement:
        api_status = "blocked_entitlement"
        last_status = "blocked_entitlement"
    elif not configured:
        api_status = "unchecked"
    elif last_status in {"ready", "blocked", "error"}:
        api_status = last_status
    else:
        api_status = "unchecked"
    reason = GOOGLE_CSE_REASON if entitlement else ""
    fix_steps = list(GOOGLE_CSE_FIX_STEPS) if entitlement else []
    if entitlement:
        fix_hint = GOOGLE_CSE_FIX
        last_message = reason
    elif api_status == "blocked":
        fix_hint = str(last.get("fix_hint") or "")
        last_message = str(last.get("google_reason") or last.get("message") or GOOGLE_CSE_BLOCKED)
    elif not configured:
        fix_hint = GOOGLE_CSE_SETUP
        last_message = str(last.get("message") or "")
    else:
        fix_hint = ""
        last_message = str(last.get("message") or last.get("google_reason") or "")
    return {
        "provider": "google_cse",
        "enabled": enabled,
        "configured": configured,
        "api_key": "present" if key_present else "missing",
        "cx": "present" if cx_present else "missing",
        "cx_warning": warning,
        "api_status": api_status,
        "last_test_status": last_status,
        "last_test_message": last_message,
        "last_test_at": str(last.get("tested_at") or ""),
        "reason": reason,
        "fix_hint": fix_hint,
        "fix_steps": fix_steps,
        "steps": list(GOOGLE_CSE_STEPS),
    }


def google_cse_blocked() -> bool:
    card = google_cse_card()
    return card["api_status"] in {"blocked", "blocked_entitlement"} or card["last_test_status"] in {"blocked", "blocked_entitlement"}


def test_google_cse(query: str, num: int = 3) -> dict:
    text = (query or "").strip()
    if not text:
        return _finish_test({"provider": "google_cse", "status": "error", "message": "query 不能为空"})
    size = _clamp_num(num)
    payload: dict = {"provider": "google_cse", "status": "error", "message": "Google CSE 请求失败"}
    key, cx, warning, missing = _cse_config()
    if missing:
        payload = {
            "provider": "google_cse",
            "status": "not_configured",
            "fix_hint": GOOGLE_CSE_SETUP,
        }
        if warning:
            payload["cx_warning"] = warning
        return _finish_test(payload)
    try:
        _take_quota()
    except GoogleSearchError as exc:
        return _finish_test({"provider": "google_cse", "status": "error", "message": exc.message, "cx_warning": warning or None})
    started = time.perf_counter()
    status_code: int | None = None
    try:
        try:
            response = httpx.get(
                GOOGLE_SEARCH_URL,
                params={"key": key, "cx": cx, "q": text, "num": size},
                timeout=30,
            )
        except httpx.TimeoutException:
            payload = {"provider": "google_cse", "status": "error", "message": "Google CSE 超时"}
        except httpx.HTTPError:
            payload = {"provider": "google_cse", "status": "error", "http_status": 502, "message": "Google CSE 请求失败"}
        else:
            status_code = response.status_code
            if response.status_code == 200:
                try:
                    body = response.json()
                except ValueError:
                    body = {}
                items = body.get("items") if isinstance(body, dict) else None
                count = len(items) if isinstance(items, list) else 0
                payload = {
                    "provider": "google_cse",
                    "status": "ready",
                    "http_status": 200,
                    "items_count": count,
                    "message": "Google CSE ready",
                }
            elif response.status_code == 403:
                payload = _blocked_payload(_google_403_detail(response))
            else:
                payload = {
                    "provider": "google_cse",
                    "status": "error",
                    "http_status": response.status_code,
                    "message": "Google CSE 请求失败",
                }
    finally:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        host = urlsplit(GOOGLE_SEARCH_URL).hostname or "www.googleapis.com"
        known = payload.get("status") in {"blocked", "blocked_entitlement"}
        _log.info(
            "Google CSE status=%s http_status=%s elapsed_ms=%s host=%s cx_present=%s",
            payload.get("status") or "error",
            status_code if status_code is not None else "none",
            elapsed_ms,
            host,
            "true",
        )
        record_trace(
            "GET",
            "external_google_search",
            200 if known else (status_code if status_code is not None else 500),
            elapsed_ms,
            "external_google_search",
            f"status={payload.get('status')} http_status=403 host={host} cx_present=true" if known else f"query={text} num={size} host={host} cx_present=true",
        )
    if warning and payload.get("cx_warning") is None:
        payload["cx_warning"] = warning
    return _finish_test(payload)


def serp_choices() -> dict:
    serper_ready = _env_flag("SERPER_ENABLED") and _env_set("SERPER_API_KEY")
    card = google_cse_card()
    warning = GOOGLE_CSE_BLOCKED if serp_provider() == "google_cse" and google_cse_blocked() else ""
    return {
        "provider": serp_provider(),
        "warning": warning,
        "options": [
            {
                "id": "serper",
                "available": serper_ready,
                "reason": "Serper 已配置" if serper_ready else "需要 SERPER_ENABLED=true 和 SERPER_API_KEY",
            },
            {
                "id": "google_cse",
                "available": bool(card["configured"]),
                "reason": "Google CSE 已配置" if card["configured"] else GOOGLE_CSE_SETUP,
            },
            {"id": "manual_csv", "available": True, "reason": "始终可用，用 CSV 导入搜索结果"},
        ],
    }


def set_serp_provider(name: str) -> dict:
    provider = (name or "").strip().lower()
    if provider not in _SERP_PROVIDERS:
        raise ValueError("SERP_PROVIDER 只能是 serper、google_cse 或 manual_csv")
    choices = serp_choices()
    option = next(item for item in choices["options"] if item["id"] == provider)
    if not option["available"]:
        raise ValueError(option["reason"])
    _write_setting("serp_provider", provider)
    global _serp_cached, _serp_loaded
    _serp_cached = provider
    _serp_loaded = True
    return serp_choices()


_serp_cached = ""
_serp_loaded = False


def _serp_override() -> str:
    global _serp_cached, _serp_loaded
    if not _serp_loaded:
        _serp_cached = _setting("serp_provider")
        _serp_loaded = True
    return _serp_cached


def _cse_config() -> tuple[str, str, str, bool]:
    enabled = _enabled()
    key = os.getenv("GOOGLE_CSE_API_KEY", "").strip()
    cx, warning = resolve_cx(os.getenv("GOOGLE_CSE_CX", ""))
    missing = not enabled or not key or not cx
    return key, cx, warning, missing


def _stored_test() -> dict:
    raw = _setting("google_cse_last_test")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    clean = {}
    for key in _TEST_FIELDS:
        if key not in data or data[key] is None:
            continue
        value = data[key]
        if isinstance(value, str):
            value = _safe_upstream_text(value)
        clean[key] = value
    return clean


def _finish_test(payload: dict) -> dict:
    clean = {"provider": "google_cse"}
    for key in _TEST_FIELDS:
        if key not in payload or payload[key] is None or payload[key] == "":
            continue
        value = payload[key]
        if isinstance(value, str):
            value = _safe_upstream_text(value)
        clean[key] = value
    stored = dict(clean)
    stored["tested_at"] = datetime.now(timezone.utc).isoformat()
    _write_setting("google_cse_last_test", json.dumps(stored, ensure_ascii=False))
    return clean


def _setting(key: str) -> str:
    try:
        conn = connect()
    except Exception:
        return ""
    try:
        row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    except Exception:
        return ""
    finally:
        conn.close()
    if row is None or row["value"] is None:
        return ""
    return str(row["value"])


def _write_setting(key: str, value: str) -> None:
    conn = connect()
    try:
        conn.execute(
            """
            INSERT INTO app_settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        conn.commit()
    finally:
        conn.close()


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() == "true"


def _env_set(name: str) -> bool:
    return bool(os.getenv(name, "").strip())


def _google_provider_row() -> dict:
    card = google_cse_card()
    status = "not_configured" if not card["configured"] else card["api_status"]
    if not card["configured"]:
        message = GOOGLE_CSE_SETUP
    elif card["api_status"] == "unchecked":
        message = "尚未检测。点击 Test Google CSE 后才会请求 Google。"
    elif card["api_status"] in {"blocked", "blocked_entitlement"}:
        message = card["reason"] or card["last_test_message"] or GOOGLE_CSE_BLOCKED
    elif card["api_status"] == "ready":
        message = card["last_test_message"] or "Google CSE ready"
    else:
        message = card["last_test_message"] or "Google CSE 请求失败"
    details = [
        f"GOOGLE_CSE_ENABLED={str(card['enabled']).lower()}",
        f"GOOGLE_CSE_API_KEY={card['api_key']}",
        f"GOOGLE_CSE_CX={card['cx']}",
        f"last_test_status={card['last_test_status'] or 'none'}",
        f"last_test_at={card['last_test_at'] or 'none'}",
    ]
    if card["cx_warning"]:
        details.append(card["cx_warning"])
    return {
        "name": "Google CSE",
        "type": "serp",
        "enabled": card["enabled"],
        "configured": card["configured"],
        "status": status,
        "message": message,
        "details": details,
    }


def provider_health(probe_sitedata: bool = False) -> dict:
    serper_enabled = _env_flag("SERPER_ENABLED")
    serper_configured = _env_set("SERPER_API_KEY")
    serper_ready = serp_provider() == "serper" and serper_enabled and serper_configured
    if serper_ready:
        serper_message = "Serper is the active SERP provider"
    elif serper_enabled and serper_configured:
        serper_message = "Set SERP_PROVIDER=serper"
    else:
        serper_message = "Set SERPER_ENABLED=true and SERPER_API_KEY"
    from app.serper import serper_snapshot

    snap = serper_snapshot()
    last_code = snap.get("status_code")
    site = _sitedata_health(probe_sitedata)
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
                "details": [
                    f"daily_limit={os.getenv('SERPER_DAILY_LIMIT', '100').strip() or '100'}",
                    f"last_status={last_code if last_code is not None else 'none'}",
                    f"last_run_at={snap.get('ran_at') or 'none'}",
                ],
            },
            _planned_gsc_row(),
            _planned_ga4_row(),
            _planned_dataforseo_row(),
            grsai_health(),
            _sitedata_provider_row(site),
        ],
        "sitedata": site,
    }


def _sitedata_health(probe: bool) -> dict:
    from app.sitedata import health_view, probe as probe_sitedata

    site = probe_sitedata() if probe else health_view()
    return site


def _sitedata_provider_row(site: dict) -> dict:
    apis = ", ".join(site.get("available_apis") or []) or "--"
    return {
        "name": "SiteData",
        "type": "rankings",
        "enabled": True,
        "configured": bool(site.get("configured")),
        "status": site.get("status") or "not_configured",
        "message": site.get("note") or "",
        "details": [
            f"OAuth status: {site.get('auth') or 'missing'}",
            f"Available APIs: {apis}",
            f"Last run time: {site.get('last_run_at') or '--'}",
            f"Last status: {site.get('last_status') or '--'}",
            f"Last error: {site.get('last_error') or '--'}",
        ],
    }


def _planned_gsc_row() -> dict:
    enabled = _env_flag("GSC_ENABLED")
    site = os.getenv("GSC_SITE_URL", "").strip()
    mode = os.getenv("GSC_AUTH_MODE", "manual_or_service_account").strip() or "manual_or_service_account"
    return {
        "name": "GSC",
        "type": "validation",
        "enabled": enabled,
        "configured": enabled and bool(site),
        "status": "not_configured",
        "message": "planned connector",
        "details": [f"auth_mode={mode}", f"site_url={site or 'empty'}"],
    }


def _planned_ga4_row() -> dict:
    enabled = _env_flag("GA4_ENABLED")
    property_id = os.getenv("GA4_PROPERTY_ID", "").strip()
    mode = os.getenv("GA4_AUTH_MODE", "manual_or_service_account").strip() or "manual_or_service_account"
    return {
        "name": "GA4",
        "type": "validation",
        "enabled": enabled,
        "configured": enabled and bool(property_id),
        "status": "not_configured",
        "message": "planned connector",
        "details": [f"auth_mode={mode}", f"property_id={property_id or 'empty'}"],
    }


def _planned_dataforseo_row() -> dict:
    enabled = _env_flag("DATAFORSEO_ENABLED")
    login_present = _env_set("DATAFORSEO_LOGIN")
    password_present = _env_set("DATAFORSEO_PASSWORD")
    location = os.getenv("DATAFORSEO_LOCATION_CODE", "2840").strip() or "2840"
    language = os.getenv("DATAFORSEO_LANGUAGE_CODE", "en").strip() or "en"
    return {
        "name": "DataForSEO",
        "type": "serp",
        "enabled": enabled,
        "configured": enabled and login_present and password_present,
        "status": "not_configured",
        "message": "planned connector",
        "details": [
            f"login_present={str(login_present).lower()}",
            f"password_present={str(password_present).lower()}",
            f"location_code={location}",
            f"language_code={language}",
        ],
    }


def check_google_cse() -> dict:
    return _google_provider_row()


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
        "suggestion": GOOGLE_CSE_FIX,
    }


def _project_block_text(text: str) -> bool:
    lowered = (text or "").lower()
    return (
        "custom search json api" in lowered
        or "does not have the access" in lowered
        or "does not have access" in lowered
        or "permission_denied" in lowered
    )


def _blocked_payload(detail: dict) -> dict:
    blob = f"{detail.get('google_status') or ''} {detail.get('google_message') or ''}"
    project = _project_block_text(blob) or not blob.strip()
    reason = GOOGLE_CSE_REASON if project else _safe_upstream_text(detail.get("google_message") or GOOGLE_CSE_BLOCKED)
    payload = {
        "provider": "google_cse",
        "status": "blocked_entitlement" if project else "blocked",
        "http_status": 403,
        "google_reason": reason,
        "message": reason,
        "fix_hint": GOOGLE_CSE_FIX if project else "",
    }
    if project:
        payload["fix_steps"] = list(GOOGLE_CSE_FIX_STEPS)
    return payload


def _enabled() -> bool:
    return os.getenv("GOOGLE_CSE_ENABLED", "").strip().lower() == "true"


def _daily_limit() -> int:
    raw = os.getenv("GOOGLE_CSE_DAILY_LIMIT", "80").strip() or "80"
    try:
        return max(0, int(raw))
    except ValueError:
        return 80


def _require_config() -> tuple[str, str]:
    key, cx, _warning, missing = _cse_config()
    if missing:
        raise GoogleSearchError(GOOGLE_CSE_SETUP)
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
            _finish_test(_blocked_payload(detail))
            raise GoogleSearchError(GOOGLE_CSE_BLOCKED, 400) from None
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
        known = status_code == 403
        _log.info(
            "Google Search status=%s http_status=%s elapsed_ms=%s host=%s cx_present=%s",
            "blocked_entitlement" if known else status_code,
            status_code,
            elapsed_ms,
            host,
            cx_present,
        )
        record_trace(
            "GET",
            "external_google_search",
            200 if known else status_code,
            elapsed_ms,
            "external_google_search",
            f"status=blocked_entitlement http_status=403 host={host} cx_present={cx_present}" if known else f"query={text} num={size} host={host} cx_present={cx_present}",
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
