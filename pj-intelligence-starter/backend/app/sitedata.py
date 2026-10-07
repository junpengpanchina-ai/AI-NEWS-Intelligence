import json
import logging
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from app.db import connect, init_db, project_root
from app.trace import record_trace

logger = logging.getLogger("pj.sitedata")

RANKING_TYPES = ("traffic_growth", "domain_rating_growth", "payment_traffic")
_PROFILES = {
    "traffic_growth": {
        "dataset_type": "sitedata_traffic_growth",
        "record_type": "traffic_signal",
        "source_name": "SiteData Traffic",
        "source_type": "site_traffic",
        "ledger_name": "SiteData Traffic Growth",
        "feed_type": "traffic",
        "signal": "traffic_growth",
        "title": "{domain} appears in traffic growth ranking",
        "why": "该域名流量近期增长，可能存在可复制的 SEO / 分发路径。",
        "evidence_type": "traffic",
    },
    "domain_rating_growth": {
        "dataset_type": "sitedata_dr_growth",
        "record_type": "authority_signal",
        "source_name": "SiteData DR",
        "source_type": "dr_growth",
        "ledger_name": "SiteData DR Growth",
        "feed_type": "authority",
        "signal": "authority_growth",
        "title": "{domain} domain rating is rising",
        "why": "该域名权重增长，可能有外链、内容集群或 SEO 策略值得拆解。",
        "evidence_type": "authority",
    },
    "payment_traffic": {
        "dataset_type": "sitedata_payment_traffic",
        "record_type": "payment_signal",
        "source_name": "SiteData Payment",
        "source_type": "payment_ranking",
        "ledger_name": "SiteData Payment Traffic",
        "feed_type": "payment",
        "signal": "payment",
        "title": "{domain} appears in SiteData payment traffic ranking",
        "why": "该域名出现在支付流量榜，说明存在商业化信号，可进入支付验证池。",
        "evidence_type": "payment",
    },
}
_SECRET = re.compile(
    r"(?i)(bearer\s+\S+|access_token['\"\s:=]+[A-Za-z0-9._\-]{8,}|refresh_token['\"\s:=]+[A-Za-z0-9._\-]{8,}|api[_-]?key['\"\s:=]+[A-Za-z0-9._\-]{8,}|sk-[A-Za-z0-9]+)"
)
_JWT = re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")
_probe = {
    "configured": False,
    "status": "not_configured",
    "auth": "",
    "available_apis": [],
    "note": "尚未检测。打开 Provider Health 后才会调用 SiteData CLI。",
    "checked_at": "",
}


def sanitize(value: str, limit: int = 240) -> str:
    text = _JWT.sub("[redacted]", value or "")
    text = _SECRET.sub("[redacted]", text)
    return " ".join(text.split())[:limit]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _token_path() -> Path:
    return project_root() / "data" / "sitedata-bridge.token"


def _bridge_token() -> str:
    path = _token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        token = path.read_text(encoding="utf-8").strip()
        if token:
            return token
    token = os.urandom(24).hex()
    path.write_text(token, encoding="utf-8")
    return token


def _kebab(name: str) -> str:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", name or "")
    return text.replace("_", "-").lower()


def _run_cli(args: list[str], timeout: int = 60) -> tuple[int, str, str]:
    bridge = os.getenv("SITEDATA_BRIDGE_URL", "").strip().rstrip("/")
    if bridge and not shutil.which("sitedata"):
        return _run_bridge(bridge, args, timeout)
    if shutil.which("sitedata"):
        try:
            completed = subprocess.run(
                ["sitedata", *args],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return 124, "", "SiteData CLI 超时"
        except OSError:
            return 127, "", "SiteData CLI 无法启动"
        return completed.returncode, completed.stdout or "", sanitize(completed.stderr or "")
    if bridge:
        return _run_bridge(bridge, args, timeout)
    return 127, "", "SiteData CLI 未安装"


def _run_bridge(bridge: str, args: list[str], timeout: int) -> tuple[int, str, str]:
    payload = json.dumps({"args": args}).encode("utf-8")
    request = urllib.request.Request(
        bridge + "/v1/exec",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json", "X-Bridge-Token": _bridge_token()},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout + 5) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = sanitize(exc.read().decode("utf-8", "replace"))
        return exc.code, "", detail or "SiteData bridge 请求失败"
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return 503, "", "SiteData CLI 需要在已登录的本机运行"
    code = body.get("code")
    return int(code) if code is not None else 1, body.get("stdout") or "", sanitize(body.get("stderr") or "")


def _catalog() -> list[dict]:
    code, stdout, stderr = _run_cli(["list", "--output", "json", "--no-update"], timeout=30)
    if code != 0:
        raise ValueError(sanitize(stderr) or "SiteData catalog 读取失败")
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("SiteData catalog 无法解析") from exc
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        data = data["data"]
    if not isinstance(data, list):
        raise ValueError("SiteData catalog 无法解析")
    return [row for row in data if isinstance(row, dict)]


def _ranking_definition(catalog: list[dict]) -> dict:
    for row in catalog:
        if row.get("id") == "rankings":
            return row
    raise ValueError("Catalog 里没有 rankings")


def _property(definition: dict, *names: str) -> str:
    props = (definition.get("inputSchema") or {}).get("properties") or {}
    wanted = {name.lower().replace("_", "") for name in names}
    for key in props:
        if key.lower().replace("_", "") in wanted:
            return key
    return ""


_YYYY_MM = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])$")


def resolve_request(period: str, month: str = "") -> tuple[str, str]:
    text = (period or "").strip()
    extra = (month or "").strip()
    if text == "current":
        if extra:
            raise ValueError("current 不能带 month")
        return "current", ""
    if text == "archive":
        if not _YYYY_MM.fullmatch(extra):
            raise ValueError("month 必须是 YYYY-MM")
        return "archive", extra
    if _YYYY_MM.fullmatch(text) and not extra:
        return "archive", text
    raise ValueError("period 只允许 current 或 archive")


def _enum_value(enum: list, requested: str) -> str:
    wanted = (requested or "").strip()
    if wanted not in RANKING_TYPES:
        raise ValueError("ranking_type 不在允许列表中")
    for item in enum:
        text = str(item)
        if text == wanted or _kebab(text) == _kebab(wanted):
            return text
    if enum:
        raise ValueError("ranking_type 不在允许列表中")
    return wanted


def build_ranking_args(definition: dict, ranking_type: str, period: str, month: str = "") -> list[str]:
    rank_key = _property(definition, "rankingType", "ranking_type")
    period_key = _property(definition, "period")
    month_key = _property(definition, "month")
    if not rank_key or not period_key:
        raise ValueError("Catalog 里没有榜单参数")
    cli_period, cli_month = resolve_request(period, month)
    if cli_period not in {"current", "archive"}:
        raise ValueError("period 只允许 current 或 archive")
    if cli_period == "archive" and not _YYYY_MM.fullmatch(cli_month):
        raise ValueError("month 必须是 YYYY-MM")
    if cli_period == "current" and cli_month:
        raise ValueError("current 不能带 month")
    schema = ((definition.get("inputSchema") or {}).get("properties") or {}).get(rank_key) or {}
    enum = schema.get("enum") or []
    args = [
        "rankings",
        f"--{rank_key}",
        _enum_value(enum, ranking_type),
        f"--{period_key}",
        cli_period,
    ]
    if cli_period == "archive":
        if not month_key:
            raise ValueError("Catalog 里没有 month")
        args.extend([f"--{month_key}", cli_month])
    args.extend(["--output", "json", "--data-only", "--no-update", "--timeout", "50"])
    period_at = args.index(f"--{period_key}")
    if _YYYY_MM.fullmatch(args[period_at + 1] or ""):
        raise ValueError("period 只允许 current 或 archive")
    return args


def _rows_from_payload(payload) -> list[dict]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("data", "items", "rankings", "results", "rows"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
        if isinstance(value, dict):
            nested = _rows_from_payload(value)
            if nested:
                return nested
    return []


def _fold_key(key: str) -> str:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(key))
    return text.replace("-", "_").lower()


def _pick(row: dict, *names: str):
    folded = {}
    for key, value in row.items():
        folded[_fold_key(key)] = value
    for name in names:
        value = folded.get(_fold_key(name))
        if value not in (None, ""):
            return value
    return ""


def _yyyy_mm(value) -> str:
    match = re.match(r"^(\d{4}-(?:0[1-9]|1[0-2]))", str(value or "").strip())
    return match.group(1) if match else ""


def _reported_window(payload) -> tuple[str, str]:
    if not isinstance(payload, dict):
        return "", ""
    raw = payload.get("period")
    period_name = ""
    month = ""
    if isinstance(raw, dict):
        kind = str(raw.get("type") or "").strip()
        if kind in {"current", "archive"}:
            period_name = kind
        month = _yyyy_mm(raw.get("month"))
    elif isinstance(raw, str) and raw.strip() in {"current", "archive"}:
        period_name = raw.strip()
    if not month:
        month = _yyyy_mm(payload.get("month"))
    return period_name, month


def _host(value: str) -> str:
    text = str(value or "").strip().lower()
    if "://" in text:
        text = text.split("://", 1)[1]
    text = text.split("/")[0].split("?")[0]
    return text.removeprefix("www.")


def _sample(host: str) -> bool:
    return host in {"example.com", "test.com"} or host.endswith(".example.com") or host.endswith(".test.com")


def _clean_row(row: dict) -> dict:
    cleaned = {}
    for key, value in row.items():
        name = str(key).lower()
        if any(token in name for token in ("token", "secret", "authorization", "password", "api_key", "apikey")):
            continue
        cleaned[key] = value
    return cleaned


def _normalize(ranking_type: str, row: dict, reported_period: str, reported_month: str, request_period: str) -> dict | None:
    profile = _PROFILES[ranking_type]
    domain = _host(_pick(row, "domain", "site", "website", "host", "url"))
    if not domain or _sample(domain):
        return None
    url = str(_pick(row, "url", "website", "link") or "")
    if url and "://" not in url:
        url = ""
    if not url:
        url = f"https://{domain}/"
    title = str(_pick(row, "title", "name", "site_name", "website_name") or domain)
    rank = str(_pick(row, "rank", "position", "ranking") or "")
    month = _yyyy_mm(_pick(row, "month", "period_month")) or reported_month
    payload = {
        "provider": "SiteData",
        "dataset_type": profile["dataset_type"],
        "ranking_type": ranking_type,
        "request_period": request_period,
        "period": reported_period,
        "period_month": month,
        "category": str(_pick(row, "category") or ""),
        "domain": domain,
        "url": url,
        "title": title,
        "rank": rank,
        "current_traffic": str(_pick(row, "current_traffic", "currentTraffic", "traffic", "visits") or ""),
        "monthly_traffic": str(_pick(row, "monthly_traffic", "monthlyTraffic", "monthly_visits") or ""),
        "traffic_growth": str(_pick(row, "traffic_growth", "trafficGrowth", "growth", "visits_growth") or ""),
        "growth_rate": str(_pick(row, "growth_rate", "growthRate", "growth_percent") or ""),
        "current_dr": str(_pick(row, "current_dr", "currentDr", "domain_rating", "domainRating", "dr") or ""),
        "previous_dr": str(_pick(row, "previous_dr", "previousDr", "last_month_dr", "previous_domain_rating") or ""),
        "dr_growth": str(_pick(row, "dr_growth", "drGrowth", "domain_rating_growth", "rating_growth") or ""),
        "domain_rating": str(_pick(row, "domain_rating", "domainRating", "current_dr", "dr") or ""),
        "payment_traffic": str(_pick(row, "payment_traffic", "paymentTraffic", "total_visits", "totalVisits", "stripe_traffic") or ""),
        "source_row": _clean_row(row),
    }
    return payload


def _source_id(profile: dict) -> int:
    from app.ledger import create_source

    conn = connect()
    try:
        row = conn.execute("SELECT id FROM data_sources WHERE name = ?", (profile["ledger_name"],)).fetchone()
    finally:
        conn.close()
    if row is not None:
        return int(row["id"])
    created = create_source(
        {
            "name": profile["ledger_name"],
            "source_type": profile["source_type"],
            "provider": "SiteData",
            "data_format": "json",
            "notes": "SiteData rankings connector. Manual run only.",
            "enabled": 1,
        }
    )
    return int(created["id"])


def _metric(payload: dict, ranking_type: str) -> tuple[str, str]:
    if ranking_type == "traffic_growth":
        for key in ("traffic_growth", "growth_rate", "current_traffic", "monthly_traffic"):
            if payload.get(key):
                return key, str(payload[key])
    elif ranking_type == "domain_rating_growth":
        for key in ("dr_growth", "current_dr", "domain_rating"):
            if payload.get(key):
                return key, str(payload[key])
    else:
        for key in ("payment_traffic", "monthly_traffic", "domain_rating"):
            if payload.get(key):
                return key, str(payload[key])
    return "rank", str(payload.get("rank") or "")


def _store(profile: dict, ranking_type: str, payload: dict, source_id: int, import_id: int) -> tuple[int | None, bool]:
    metric_name, metric_value = _metric(payload, ranking_type)
    conn = connect()
    try:
        found = conn.execute(
            """
            SELECT id FROM raw_source_records
            WHERE source_id = ? AND record_type = ? AND normalized_domain = ?
              AND COALESCE(time_range, '') = ? AND COALESCE(json_extract(raw_json, '$.rank'), '') = ?
              AND COALESCE(json_extract(raw_json, '$.dataset_type'), '') = ?
            """,
            (
                source_id,
                profile["record_type"],
                payload["domain"],
                payload["period_month"],
                str(payload.get("rank") or ""),
                profile["dataset_type"],
            ),
        ).fetchone()
        if found is not None:
            existing = conn.execute("SELECT raw_json, time_range FROM raw_source_records WHERE id = ?", (int(found["id"]),)).fetchone()
            stored = {}
            try:
                stored = json.loads(existing["raw_json"] or "{}")
            except json.JSONDecodeError:
                stored = {}
            if isinstance(stored, dict) and (payload.get("period") or payload.get("period_month")):
                if payload.get("request_period"):
                    stored["request_period"] = payload["request_period"]
                if payload.get("period"):
                    stored["period"] = payload["period"]
                if payload.get("period_month"):
                    stored["period_month"] = payload["period_month"]
                if payload.get("category"):
                    stored["category"] = payload["category"]
                conn.execute(
                    "UPDATE raw_source_records SET raw_json = ?, time_range = ? WHERE id = ?",
                    (json.dumps(stored, ensure_ascii=False), payload.get("period_month") or existing["time_range"] or "", int(found["id"])),
                )
                conn.commit()
            return int(found["id"]), False
        cur = conn.execute(
            """
            INSERT INTO raw_source_records (
                import_id, source_id, record_type, raw_json, normalized_title,
                normalized_url, normalized_keyword, normalized_domain, metric_name,
                metric_value, time_range, confidence, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                import_id,
                source_id,
                profile["record_type"],
                json.dumps(payload, ensure_ascii=False),
                payload["title"],
                payload["url"],
                "",
                payload["domain"],
                metric_name,
                metric_value,
                payload["period_month"],
                "medium",
                "imported",
                _now(),
            ),
        )
        conn.commit()
        return int(cur.lastrowid), True
    finally:
        conn.close()


def _feed(profile: dict, payload: dict, record_id: int) -> bool:
    title = profile["title"].format(domain=payload["domain"])
    key = f"{profile['signal']}|{payload['domain']}|{payload['period_month']}|{payload.get('rank') or ''}"
    conn = connect()
    try:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO intelligence_feed (
                feed_type, title, domain, url, source_name, signal, why_it_matters,
                related_keyword, related_opportunity_id, created_at, dedupe_key, provider, related_record_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, '', NULL, ?, ?, 'SiteData', ?)
            """,
            (
                profile["feed_type"],
                title,
                payload["domain"],
                payload["url"],
                profile["source_name"],
                profile["signal"],
                profile["why"],
                _now(),
                key,
                record_id,
            ),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def _action(types: set[str]) -> str:
    payment = "payment" in types
    traffic = "traffic" in types
    authority = "authority" in types
    if payment and traffic and authority:
        return "Priority Research"
    if payment and traffic:
        return "Commercial Research"
    if traffic and authority:
        return "SEO Teardown"
    if payment:
        return "Payment Signal Review"
    if traffic:
        return "Traffic Growth Watch"
    if authority:
        return "Authority Growth Watch"
    return "Review Signals"


def _setting(key: str, default: str = "") -> str:
    conn = connect()
    try:
        row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    finally:
        conn.close()
    if row is None or row["value"] is None:
        return default
    return str(row["value"])


def auto_create_enabled() -> bool:
    init_db()
    return _setting("auto_create_dossier", "false").lower() in {"1", "true", "yes"}


def set_auto_create(enabled: bool) -> dict:
    init_db()
    conn = connect()
    try:
        conn.execute(
            """
            INSERT INTO app_settings (key, value) VALUES ('auto_create_dossier', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            ("true" if enabled else "false",),
        )
        conn.commit()
    finally:
        conn.close()
    return {"auto_create_dossier": bool(enabled)}


def get_settings() -> dict:
    init_db()
    return {"auto_create_dossier": auto_create_enabled()}


def _record_run(ranking_type: str, period: str, status: str, created: int, skipped: int, feeds: int, domains: int, error: str, elapsed_ms: int) -> None:
    conn = connect()
    try:
        conn.execute(
            """
            INSERT INTO sitedata_runs (
                ranking_type, period, status, records_created, records_skipped,
                feed_created, opportunities_updated, error_message, elapsed_ms, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (ranking_type, period, status, created, skipped, feeds, domains, sanitize(error), elapsed_ms, _now()),
        )
        conn.commit()
    finally:
        conn.close()


def latest_run() -> dict:
    init_db()
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM sitedata_runs ORDER BY id DESC LIMIT 1").fetchone()
    finally:
        conn.close()
    if row is None:
        return {"last_run_at": "", "last_status": "", "last_error": ""}
    return {
        "last_run_at": row["created_at"] or "",
        "last_status": row["status"] or "",
        "last_error": row["error_message"] or "",
    }


def probe() -> dict:
    started = time.perf_counter()
    auth_code, auth_out, auth_err = _run_cli(["auth", "status", "--no-update"], timeout=20)
    authenticated = auth_code == 0 and "authenticated" in auth_out.lower() and "not authenticated" not in auth_out.lower()
    apis = []
    note = "SiteData CLI authenticated" if authenticated else sanitize(auth_err or auth_out or "SiteData CLI 未登录")
    status = "ready" if authenticated else "not_configured"
    if auth_code == 127:
        status = "not_configured"
        note = "SiteData CLI 未安装或本机 bridge 未启动"
    elif not authenticated:
        status = "error" if auth_code not in {0} else "not_configured"
    else:
        try:
            catalog = _catalog()
            apis = [str(row.get("id")) for row in catalog if row.get("id")]
        except ValueError as exc:
            status = "error"
            note = sanitize(str(exc))
    result = {
        "provider": "sitedata",
        "configured": authenticated,
        "status": status,
        "auth": "oauth" if authenticated else "",
        "available_apis": apis,
        "note": note,
    }
    result.update(latest_run())
    _probe.update({key: result[key] for key in ("configured", "status", "auth", "available_apis", "note")})
    _probe["checked_at"] = _now()
    record_trace("GET", "/api/providers/health", 200 if status == "ready" else 503, int((time.perf_counter() - started) * 1000), "sitedata", sanitize(note))
    return result


def health_view() -> dict:
    latest = latest_run()
    cached = {
        "provider": "sitedata",
        "configured": bool(_probe.get("configured")),
        "status": _probe.get("status") or "not_configured",
        "auth": _probe.get("auth") or "",
        "available_apis": list(_probe.get("available_apis") or []),
        "note": _probe.get("note") or "",
        "last_run_at": latest["last_run_at"],
        "last_status": latest["last_status"],
        "last_error": latest["last_error"],
    }
    return cached


def _run_note(kind: str, period: str, month: str, status: str, item_count: int, elapsed_ms: int) -> str:
    return (
        f"rankingType={kind} period={period or '-'} month={month or '-'} "
        f"status={status} item_count={item_count} elapsed_ms={elapsed_ms} provider=SiteData"
    )


def _log_run(kind: str, period: str, month: str, status: str, item_count: int, elapsed_ms: int) -> None:
    note = _run_note(kind, period, month, status, item_count, elapsed_ms)
    logger.info(note)
    record_trace("POST", "/api/sitedata/rankings/run", 200, elapsed_ms, "sitedata", note)


def _is_provider_error(stderr: str, stdout: str) -> bool:
    sample = sanitize(f"{stderr or ''} {(stdout or '')[:300]}")
    lowered = sample.lower()
    return "internal server error" in lowered or "internal_error" in lowered


def _run_payload(kind: str, period: str, month: str, status: str, message: str, created: int, skipped: int, feeds: int, domains: int, elapsed_ms: int) -> dict:
    return {
        "provider": "SiteData",
        "ranking_type": kind,
        "rankingType": kind,
        "period": period,
        "month": month,
        "status": status,
        "message": message,
        "records_created": created,
        "records_skipped": skipped,
        "feed_created": feeds,
        "opportunities_updated": domains,
        "elapsed_ms": elapsed_ms,
    }


def run_rankings(ranking_type: str, period: str, limit: int = 100, month: str = "") -> dict:
    init_db()
    started = time.perf_counter()
    kind = (ranking_type or "").strip()
    if kind not in RANKING_TYPES:
        raise ValueError("ranking_type 不在允许列表中")
    cli_period, cli_month = resolve_request(period, month)
    size = max(1, min(int(limit or 100), 500))
    profile = _PROFILES[kind]
    created = skipped = feeds = 0
    domains = set()
    try:
        definition = _ranking_definition(_catalog())
        args = build_ranking_args(definition, kind, cli_period, cli_month)
        code, stdout, stderr = _run_cli(args, timeout=60)
        if code != 0:
            elapsed = int((time.perf_counter() - started) * 1000)
            if _is_provider_error(stderr, stdout):
                message = "SiteData provider returned internal error"
                status_name = "provider_error"
            else:
                message = sanitize(stderr) or "SiteData 榜单请求失败"
                status_name = "error"
            _record_run(kind, cli_month or cli_period, status_name, 0, 0, 0, 0, message, elapsed)
            _log_run(kind, cli_period, cli_month, status_name, 0, elapsed)
            return _run_payload(kind, cli_period, cli_month, status_name, message, 0, 0, 0, 0, elapsed)
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            elapsed = int((time.perf_counter() - started) * 1000)
            message = "SiteData 返回无法解析"
            _record_run(kind, cli_month or cli_period, "error", 0, 0, 0, 0, message, elapsed)
            _log_run(kind, cli_period, cli_month, "error", 0, elapsed)
            return _run_payload(kind, cli_period, cli_month, "error", message, 0, 0, 0, 0, elapsed)
        stdout = ""
        reported_period, reported_month = _reported_window(payload)
        rows = _rows_from_payload(payload)
        if not rows:
            elapsed = int((time.perf_counter() - started) * 1000)
            message = "No ranking data for this period"
            _record_run(kind, reported_month or cli_month or cli_period, "empty", 0, 0, 0, 0, message, elapsed)
            _log_run(kind, cli_period, reported_month or cli_month, "empty", 0, elapsed)
            return _run_payload(kind, cli_period, reported_month or cli_month, "empty", message, 0, 0, 0, 0, elapsed)
        item_count = len(rows)
        rows = rows[:size]
        source_id = _source_id(profile)
        conn = connect()
        try:
            cur = conn.execute(
                """
                INSERT INTO source_imports (
                    source_id, import_name, source_type, record_type, original_filename,
                    row_count, status, notes, created_at
                ) VALUES (?, ?, 'sitedata', ?, '', ?, 'imported', ?, ?)
                """,
                (
                    source_id,
                    f"SiteData {kind} {reported_period or cli_period} {reported_month}",
                    profile["record_type"],
                    len(rows),
                    f"dataset_type={profile['dataset_type']}; provider=SiteData; period={reported_period or cli_period}; month={reported_month}",
                    _now(),
                ),
            )
            import_id = int(cur.lastrowid)
            conn.commit()
        finally:
            conn.close()
        from app.dossiers import attach_sitedata_evidence

        auto_create = auto_create_enabled()
        for raw in rows:
            normalized = _normalize(kind, raw, reported_period, reported_month, cli_period)
            if normalized is None:
                skipped += 1
                continue
            record_id, inserted = _store(profile, kind, normalized, source_id, import_id)
            if not inserted or record_id is None:
                skipped += 1
                continue
            created += 1
            domains.add(normalized["domain"])
            if _feed(profile, normalized, record_id):
                feeds += 1
            attach_sitedata_evidence(
                normalized["domain"],
                {
                    "evidence_type": profile["evidence_type"],
                    "source_name": profile["source_name"],
                    "source_url": normalized["url"],
                    "title": profile["title"].format(domain=normalized["domain"]),
                    "content": profile["why"],
                    "metric_name": _metric(normalized, kind)[0],
                    "metric_value": _metric(normalized, kind)[1],
                    "period_month": normalized["period_month"],
                },
                auto_create,
            )
    except ValueError as exc:
        elapsed = int((time.perf_counter() - started) * 1000)
        message = sanitize(str(exc))
        _record_run(kind, cli_month or cli_period, "error", created, skipped, feeds, len(domains), message, elapsed)
        _log_run(kind, cli_period, cli_month, "error", 0, elapsed)
        return _run_payload(kind, cli_period, cli_month, "error", message, created, skipped, feeds, len(domains), elapsed)
    elapsed = int((time.perf_counter() - started) * 1000)
    _record_run(kind, reported_month or cli_period, "ok", created, skipped, feeds, len(domains), "", elapsed)
    _log_run(kind, cli_period, reported_month, "ok", item_count, elapsed)
    return _run_payload(kind, cli_period, reported_month, "ok", "", created, skipped, feeds, len(domains), elapsed)


def run_all(period: str, month: str = "", limit: int = 100) -> dict:
    cli_period, cli_month = resolve_request(period, month)
    results = []
    for kind in RANKING_TYPES:
        try:
            results.append(run_rankings(kind, cli_period, limit, cli_month))
        except ValueError as exc:
            message = sanitize(str(exc))
            results.append(_run_payload(kind, cli_period, cli_month, "error", message, 0, 0, 0, 0, 0))
    statuses = [item.get("status") or "" for item in results]
    if statuses and all(item == "ok" for item in statuses):
        overall = "ok"
    elif any(item == "ok" for item in statuses) or len(set(statuses)) > 1:
        overall = "partial_success"
    else:
        overall = statuses[0] if statuses else "error"
    logger.info("provider=SiteData rankingType=all period=%s month=%s status=%s item_count=%s elapsed_ms=0", cli_period, cli_month or "-", overall, len(results))
    record_trace(
        "POST",
        "/api/sitedata/rankings/run-all",
        200,
        sum(int(item.get("elapsed_ms") or 0) for item in results),
        "sitedata",
        f"rankingType=all period={cli_period} month={cli_month or '-'} status={overall} item_count={len(results)} provider=SiteData",
    )
    return {"status": overall, "results": results}


def _domain_types() -> dict[str, set[str]]:
    conn = connect()
    try:
        rows = conn.execute(
            """
            SELECT normalized_domain, record_type
            FROM raw_source_records
            WHERE lower(COALESCE(json_extract(raw_json, '$.provider'), '')) = 'sitedata'
              AND lower(COALESCE(status, '')) IN ('imported', 'confirmed')
            """
        ).fetchall()
    finally:
        conn.close()
    found = {}
    labels = {"payment_signal": "payment", "traffic_signal": "traffic", "authority_signal": "authority"}
    for row in rows:
        host = _host(row["normalized_domain"] or "")
        label = labels.get(row["record_type"] or "")
        if host and label and not _sample(host):
            found.setdefault(host, set()).add(label)
    return found


def recent_signals(limit: int = 20) -> dict:
    init_db()
    conn = connect()
    try:
        rows = conn.execute(
            """
            SELECT normalized_domain AS domain,
                   json_extract(raw_json, '$.ranking_type') AS ranking_type,
                   COALESCE(json_extract(raw_json, '$.period_month'), time_range, '') AS period_month,
                   json_extract(raw_json, '$.rank') AS rank
            FROM raw_source_records
            WHERE lower(COALESCE(json_extract(raw_json, '$.provider'), '')) = 'sitedata'
              AND json_extract(raw_json, '$.dataset_type') LIKE 'sitedata_%'
              AND lower(COALESCE(status, '')) IN ('imported', 'confirmed')
            """
        ).fetchall()
    finally:
        conn.close()
    labels = {
        "traffic_growth": "Traffic Growth",
        "domain_rating_growth": "DR Growth",
        "payment_traffic": "Payment Traffic",
    }
    grouped = {kind: [] for kind in RANKING_TYPES}
    for row in rows:
        kind = row["ranking_type"] or ""
        host = _host(row["domain"] or "")
        if kind not in grouped or not host or _sample(host):
            continue
        grouped[kind].append(row)
    items = []
    for kind in RANKING_TYPES:
        bucket = grouped[kind]
        months = [row["period_month"] or "" for row in bucket if row["period_month"]]
        latest = max(months) if months else ""
        current = [row for row in bucket if (row["period_month"] or "") == latest] if latest else bucket
        def rank_value(row):
            try:
                return int(float(row["rank"]))
            except (TypeError, ValueError):
                return 10**9
        current.sort(key=rank_value)
        seen = []
        for row in current:
            host = _host(row["domain"] or "")
            if host and host not in seen:
                seen.append(host)
            if len(seen) == 3:
                break
        items.append(
            {
                "ranking_type": kind,
                "label": labels[kind],
                "period_month": latest,
                "count": len(current),
                "top_domains": seen,
            }
        )
    return {"items": items}


def _score(types: set[str], top: bool) -> int:
    score = 0
    if "traffic" in types:
        score += 20
    if "authority" in types:
        score += 15
    if "payment" in types:
        score += 30
    if top:
        score += 10
    if len(types) >= 3:
        score += 25
    elif len(types) >= 2:
        score += 15
    return min(score, 100)


def top_opportunities(limit: int = 10) -> dict:
    init_db()
    size = max(1, min(int(limit or 10), 20))
    conn = connect()
    try:
        rows = conn.execute(
            """
            SELECT normalized_domain, record_type, time_range,
                   json_extract(raw_json, '$.rank') AS rank
            FROM raw_source_records
            WHERE lower(COALESCE(json_extract(raw_json, '$.provider'), '')) = 'sitedata'
              AND lower(COALESCE(status, '')) IN ('imported', 'confirmed')
            """
        ).fetchall()
    finally:
        conn.close()
    labels = {"payment_signal": "payment", "traffic_signal": "traffic", "authority_signal": "authority"}
    buckets = {}
    for row in rows:
        host = _host(row["normalized_domain"] or "")
        label = labels.get(row["record_type"] or "")
        if not host or not label or _sample(host):
            continue
        bucket = buckets.setdefault(host, {"types": set(), "top": False, "period": ""})
        bucket["types"].add(label)
        month = row["time_range"] or ""
        if month > bucket["period"]:
            bucket["period"] = month
        try:
            rank = int(float(row["rank"]))
        except (TypeError, ValueError):
            rank = None
        if rank is not None and 0 < rank <= 100:
            bucket["top"] = True
    items = []
    for host, bucket in buckets.items():
        action = _action(bucket["types"])
        items.append(
            {
                "domain": host,
                "score": _score(bucket["types"], bucket["top"]),
                "signals": sorted(bucket["types"]),
                "latest_period": bucket["period"],
                "next_action": action,
                "recommended_action": action,
            }
        )
    items.sort(key=lambda item: (-item["score"], item["domain"]))
    return {"items": items[:size]}
