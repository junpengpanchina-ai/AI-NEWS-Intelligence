import json
import re
from pathlib import Path
from urllib.parse import urlparse

from app.db import connect

_MONTH = re.compile(r"^\d{4}-\d{2}$")
_NOTE_VALUE = re.compile(r"([a-z_]+)=([^;]+)")
_IMPORTED = ("imported", "confirmed")


def _page(limit: int | None, offset: int | None) -> tuple[int, int]:
    size = 50 if limit is None else max(1, min(int(limit), 200))
    start = 0 if offset is None else max(0, int(offset))
    return size, start


def _host(value: str) -> str:
    text = (value or "").strip().lower()
    if not text:
        return ""
    if "://" not in text and "/" not in text:
        return text.removeprefix("www.")
    parsed = urlparse(text if "://" in text else f"https://{text}")
    return (parsed.hostname or "").removeprefix("www.")


def _sample_host(value: str) -> bool:
    host = _host(value)
    return host in {"example.com", "test.com"} or host.endswith(".example.com") or host.endswith(".test.com")


_NOISE_LABELS = {"demo", "sample", "test", "example", "localhost"}
_TIER_ORDER = {"P0_priority": 0, "P1_research": 1, "P2_watch": 2, "P3_noise": 3}


def _desk_noise(value: str) -> bool:
    host = _host(value)
    if not host or _sample_host(host):
        return True
    if host in {"localhost", "demo.com", "sample.com"} or host.endswith(".localhost"):
        return True
    return any(part in _NOISE_LABELS for part in host.split(".") if part)


def _num(value) -> float | None:
    text = str(value or "").strip().replace(",", "").replace("%", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _text(value) -> str:
    if value is None:
        return ""
    return str(value)


def _parsed(value: str) -> dict:
    try:
        loaded = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _note_map(notes: str) -> dict[str, str]:
    return {match.group(1): match.group(2).strip() for match in _NOTE_VALUE.finditer(notes or "")}


def _file_name(original_filename: str, import_name: str) -> str:
    path = (original_filename or "").strip()
    if path:
        return Path(path).name or path
    parts = (import_name or "").split(" / ")
    return parts[-1].strip() if parts else ""


def _like(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped.lower()}%"


def _batch_windows(conn) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, preview_id, import_name, status, file_count, notes, created_at, confirmed_at
        FROM import_batches
        ORDER BY id ASC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def _import_rows(conn) -> list[dict]:
    rows = conn.execute(
        """
        SELECT i.id, i.source_id, i.import_name, i.record_type, i.original_filename,
               i.row_count, i.status, i.notes, i.created_at,
               s.name AS source_name, s.provider AS provider
        FROM source_imports i
        LEFT JOIN data_sources s ON s.id = i.source_id
        ORDER BY i.id ASC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def _assign_batches(batches: list[dict], imports: list[dict]) -> dict[int, int]:
    assigned: dict[int, int] = {}
    for item in imports:
        created = item.get("created_at") or ""
        if not created:
            continue
        matches = []
        for batch in batches:
            start = batch.get("created_at") or ""
            end = batch.get("confirmed_at") or ""
            if not start or not end:
                continue
            if start <= created <= end:
                matches.append(batch)
        if not matches:
            continue
        chosen = max(matches, key=lambda batch: batch.get("created_at") or "")
        assigned[int(item["id"])] = int(chosen["id"])
    return assigned


def _imports_for_batch(batch_id: int) -> tuple[dict | None, list[dict]]:
    conn = connect()
    try:
        batches = _batch_windows(conn)
        imports = _import_rows(conn)
    finally:
        conn.close()
    batch = next((item for item in batches if int(item["id"]) == int(batch_id)), None)
    if batch is None:
        return None, []
    assigned = _assign_batches(batches, imports)
    files = [item for item in imports if assigned.get(int(item["id"])) == int(batch_id)]
    return batch, files


def _previous_dr(raw: dict) -> str:
    stored = _text(raw.get("previous_dr"))
    if stored:
        return stored
    current = _num(raw.get("current_dr"))
    growth = _num(raw.get("dr_growth"))
    if current is None or growth is None:
        return ""
    value = current - growth
    if value.is_integer():
        return str(int(value))
    return str(value)


def _record_item(row, batch_id: int | None) -> dict:
    raw = _parsed(row["raw_json"] or "")
    provider = _text(raw.get("provider")) or _text(row["provider"])
    domain = _text(row["normalized_domain"] or raw.get("domain"))
    normalized = {
        "domain": domain,
        "title": _text(row["normalized_title"] or raw.get("title")),
        "keyword": _text(row["normalized_keyword"] or raw.get("keyword")),
        "url": _text(row["normalized_url"] or raw.get("url")),
        "rank": _text(raw.get("rank")),
        "payment_traffic": _text(raw.get("payment_traffic")),
        "monthly_traffic": _text(raw.get("monthly_traffic")),
        "current_traffic": _text(raw.get("current_traffic")),
        "traffic_growth": _text(raw.get("traffic_growth")),
        "growth_rate": _text(raw.get("growth_rate")),
        "current_dr": _text(raw.get("current_dr")),
        "previous_dr": _previous_dr(raw),
        "dr_growth": _text(raw.get("dr_growth")),
        "domain_rating": _text(raw.get("domain_rating") or raw.get("domain_score")),
        "period_month": _text(raw.get("period_month") or row["time_range"]),
        "dataset_type": _text(raw.get("dataset_type")),
        "provider": provider,
        "ranking_type": _text(raw.get("ranking_type")),
        "category": _text(raw.get("category") or (raw.get("source_row") or {}).get("category") if isinstance(raw.get("source_row"), dict) else raw.get("category")),
    }
    kind = normalized["ranking_type"]
    if kind == "domain_rating_growth":
        metric_keys = ("dr_growth", "current_dr", "domain_rating")
    elif kind == "payment_traffic":
        metric_keys = ("payment_traffic", "monthly_traffic", "domain_rating")
    else:
        metric_keys = ("traffic_growth", "growth_rate", "current_traffic", "monthly_traffic")
    main_metric = ""
    for key in metric_keys:
        if normalized.get(key):
            main_metric = f"{key} {normalized[key]}"
            break
    return {
        "id": int(row["id"]),
        "domain": domain,
        "title": normalized["title"],
        "dataset_type": normalized["dataset_type"],
        "record_type": _text(row["record_type"]),
        "provider": provider,
        "period_month": normalized["period_month"],
        "rank": normalized["rank"],
        "payment_traffic": normalized["payment_traffic"],
        "monthly_traffic": normalized["monthly_traffic"],
        "current_traffic": normalized["current_traffic"],
        "traffic_growth": normalized["traffic_growth"],
        "growth_rate": normalized["growth_rate"],
        "current_dr": normalized["current_dr"],
        "previous_dr": normalized["previous_dr"],
        "dr_growth": normalized["dr_growth"],
        "domain_rating": normalized["domain_rating"],
        "ranking_type": normalized["ranking_type"],
        "category": normalized["category"],
        "main_metric": main_metric,
        "source_name": _text(row["source_name"]),
        "original_file_name": _text(raw.get("original_file_name")),
        "batch_id": batch_id,
        "imported_at": _text(row["created_at"]),
        "sample": _sample_host(domain) or _sample_host(normalized["url"]),
        "raw_json": row["raw_json"] or "",
        "normalized": normalized,
    }


def list_explorer_records(
    dataset_type: str | None = None,
    record_type: str | None = None,
    provider: str | None = None,
    batch_id: int | None = None,
    period_month: str | None = None,
    domain: str | None = None,
    keyword: str | None = None,
    source_name: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> dict:
    size, start = _page(limit, offset)
    clauses = ["lower(COALESCE(r.status, '')) IN ('imported', 'confirmed')"]
    params: list = []
    if dataset_type:
        clauses.append("json_extract(r.raw_json, '$.dataset_type') = ?")
        params.append(dataset_type.strip())
    if record_type:
        clauses.append("r.record_type = ?")
        params.append(record_type.strip())
    if provider:
        clauses.append(
            "(lower(COALESCE(json_extract(r.raw_json, '$.provider'), '')) = ? OR lower(COALESCE(s.provider, '')) = ?)"
        )
        token = provider.strip().lower()
        params.extend([token, token])
    if period_month:
        clauses.append("r.time_range = ?")
        params.append(period_month.strip())
    if domain:
        clauses.append("lower(COALESCE(r.normalized_domain, '')) LIKE ? ESCAPE '\\'")
        params.append(_like(domain.strip()))
    else:
        clauses.append(
            """
            lower(COALESCE(r.normalized_domain, '')) NOT IN ('example.com', 'test.com', 'www.example.com', 'www.test.com')
            AND lower(COALESCE(r.normalized_domain, '')) NOT LIKE '%.example.com'
            AND lower(COALESCE(r.normalized_domain, '')) NOT LIKE '%.test.com'
            """
        )
    if keyword:
        clauses.append("lower(COALESCE(r.normalized_keyword, '')) LIKE ? ESCAPE '\\'")
        params.append(_like(keyword.strip()))
    if source_name:
        clauses.append("lower(COALESCE(s.name, '')) LIKE ? ESCAPE '\\'")
        params.append(_like(source_name.strip()))
    import_ids: list[int] | None = None
    assigned: dict[int, int] = {}
    conn = connect()
    try:
        assigned = _assign_batches(_batch_windows(conn), _import_rows(conn))
        if batch_id is not None:
            import_ids = [import_id for import_id, owner in assigned.items() if owner == int(batch_id)]
            if not import_ids:
                return {"total": 0, "limit": size, "offset": start, "items": []}
            marks = ",".join("?" for _ in import_ids)
            clauses.append(f"r.import_id IN ({marks})")
            params.extend(import_ids)
        where = " AND ".join(clauses)
        total = conn.execute(
            f"""
            SELECT COUNT(*) AS n
            FROM raw_source_records r
            LEFT JOIN data_sources s ON s.id = r.source_id
            WHERE {where}
            """,
            params,
        ).fetchone()
        rows = conn.execute(
            f"""
            SELECT r.id, r.import_id, r.record_type, r.raw_json, r.normalized_title,
                   r.normalized_url, r.normalized_keyword, r.normalized_domain,
                   r.time_range, r.created_at, s.name AS source_name, s.provider AS provider
            FROM raw_source_records r
            LEFT JOIN data_sources s ON s.id = r.source_id
            WHERE {where}
            ORDER BY r.id DESC
            LIMIT ? OFFSET ?
            """,
            [*params, size, start],
        ).fetchall()
    finally:
        conn.close()
    items = []
    for row in rows:
        owner = assigned.get(int(row["import_id"])) if row["import_id"] is not None else None
        items.append(_record_item(row, owner))
    return {"total": int(total["n"] or 0), "limit": size, "offset": start, "items": items}


def _batch_summary(batch: dict, files: list[dict]) -> dict:
    notes = [_note_map(item.get("notes") or "") for item in files]
    dataset = next((item.get("dataset_type") or "" for item in notes if item.get("dataset_type")), "")
    record_type = next((item.get("record_type") or "" for item in files if item.get("record_type")), "")
    provider = next((item.get("provider") or "" for item in files if item.get("provider")), "")
    source_name = next((item.get("source_name") or "" for item in files if item.get("source_name")), "")
    row_count = sum(int(item.get("row_count") or 0) for item in files)
    return {
        "batch_id": int(batch["id"]),
        "import_name": batch.get("import_name") or "",
        "status": batch.get("status") or "",
        "dataset_type": dataset,
        "record_type": record_type,
        "provider": provider,
        "file_count": int(batch.get("file_count") or len(files) or 0),
        "row_count": row_count,
        "created_at": batch.get("created_at") or "",
        "source_name": source_name,
    }


def list_import_batches() -> list[dict]:
    conn = connect()
    try:
        batches = _batch_windows(conn)
        imports = _import_rows(conn)
    finally:
        conn.close()
    assigned = _assign_batches(batches, imports)
    grouped: dict[int, list[dict]] = {}
    for item in imports:
        owner = assigned.get(int(item["id"]))
        if owner is not None:
            grouped.setdefault(owner, []).append(item)
    return [_batch_summary(batch, grouped.get(int(batch["id"]), [])) for batch in batches]


def get_import_batch(batch_id: int) -> dict | None:
    batch, files = _imports_for_batch(batch_id)
    if batch is None:
        return None
    summary = _batch_summary(batch, files)
    import_ids = [int(item["id"]) for item in files]
    months: set[str] = set()
    samples: list[dict] = []
    failed = []
    imported_rows = 0
    file_rows = []
    for item in files:
        meta = _note_map(item.get("notes") or "")
        status = item.get("status") or ""
        warnings = []
        if status not in _IMPORTED and status != "empty":
            warnings.append(status or "failed")
            failed.append(_file_name(item.get("original_filename") or "", item.get("import_name") or ""))
        else:
            imported_rows += int(item.get("row_count") or 0)
        month = meta.get("period_month") or ""
        if _MONTH.match(month):
            months.add(month)
        file_rows.append(
            {
                "import_id": int(item["id"]),
                "original_file_name": _file_name(item.get("original_filename") or "", item.get("import_name") or ""),
                "period_month": month,
                "row_count": int(item.get("row_count") or 0),
                "status": status,
                "warnings": warnings,
            }
        )
    if import_ids:
        conn = connect()
        try:
            marks = ",".join("?" for _ in import_ids)
            month_rows = conn.execute(
                f"""
                SELECT DISTINCT time_range
                FROM raw_source_records
                WHERE import_id IN ({marks})
                  AND time_range GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]'
                """,
                import_ids,
            ).fetchall()
            months.update(row["time_range"] for row in month_rows if row["time_range"])
            sample_rows = conn.execute(
                f"""
                SELECT r.id, r.import_id, r.record_type, r.raw_json, r.normalized_title,
                       r.normalized_url, r.normalized_keyword, r.normalized_domain,
                       r.time_range, r.created_at, s.name AS source_name, s.provider AS provider
                FROM raw_source_records r
                LEFT JOIN data_sources s ON s.id = r.source_id
                WHERE r.import_id IN ({marks})
                ORDER BY r.id ASC
                LIMIT 8
                """,
                import_ids,
            ).fetchall()
        finally:
            conn.close()
        for row in sample_rows:
            item = _record_item(row, int(batch_id))
            samples.append(
                {
                    "domain": item["domain"],
                    "rank": item["rank"],
                    "title": item["title"],
                    "normalized": item["normalized"],
                }
            )
    ordered_months = sorted(months)
    summary.update(
        {
            "month_count": len(ordered_months),
            "latest_month": ordered_months[-1] if ordered_months else "",
            "imported_rows": imported_rows,
            "skipped_rows": 0,
            "failed_files": [name for name in failed if name],
            "files": file_rows,
            "sample_rows": samples,
        }
    )
    return summary


def _blank_domain() -> dict:
    return {
        "payment_months": set(),
        "payment_best": None,
        "payment_label": "",
        "traffic": False,
        "traffic_top": False,
        "traffic_best": None,
        "traffic_label": "",
        "authority": False,
        "authority_top": False,
        "dr_best": None,
        "dr_label": "",
        "serp": False,
        "serp_rank": None,
        "serp_keyword": "",
        "competitor": False,
        "news": False,
        "product_hunt": False,
        "sitedata": set(),
        "sitedata_top": False,
        "latest": "",
    }


def _keep_max(current, label, value, text):
    number = _num(value)
    if number is None:
        return current, label
    if current is None or number > current:
        return number, _text(text or value)
    return current, label


def _keep_month(bucket: dict, month: str) -> None:
    if _MONTH.match(month or "") and month > bucket["latest"]:
        bucket["latest"] = month


def _opportunity_tier(score: int, payment: bool, traffic: bool, authority: bool, noise: bool) -> tuple[str, str]:
    if noise:
        return "P3_noise", "样例、演示或本地域名，不进入首页机会榜"
    pair = (payment and traffic) or (payment and authority) or (traffic and authority)
    if score >= 85 and pair:
        return "P0_priority", "分数达到 85，且支付、流量、权重里至少两类同时存在"
    if score >= 70 or payment or (traffic and authority):
        return "P1_research", "达到研究线，或已有支付信号，或流量与权重同时存在"
    single = sum(1 for present in (payment, traffic, authority) if present) == 1
    if score >= 50 or single:
        return "P2_watch", "分数达到 50，或只有单一强信号"
    return "P3_noise", "分数低或关键信息缺失"


def _next_action(action: str, missing: list[str]) -> str:
    mapped = {
        "Traffic Growth Watch": "抓页面、查关键词、看是否有注册和付费入口。",
        "Traffic Signal Only": "抓页面、查关键词、看是否有注册和付费入口。",
        "Watch / Research": "抓页面、查关键词、看是否有注册和付费入口。",
        "Authority Growth Watch": "查反链、抓页面、补 SERP。",
        "Authority Signal Only": "查反链、抓页面、补 SERP。",
        "SEO Teardown": "查反链、抓页面、补 SERP。",
        "Payment Signal Review": "抓取首页和 pricing 页面，补 SERP Top 10，确认是否适合拆解。",
        "Payment Signal Only": "抓取首页和 pricing 页面，补 SERP Top 10，确认是否适合拆解。",
        "Commercial Research": "抓取首页和 pricing 页面，补 SERP Top 10，确认是否适合拆解。",
        "Priority Research": "抓取首页和 pricing 页面，补 SERP Top 10，确认是否适合拆解。",
        "Page Teardown": "抓取首页和 pricing 页面，补 SERP Top 10，确认是否适合拆解。",
    }
    if action in mapped:
        return mapped[action]
    if missing:
        return f"先补齐{'、'.join(missing[:3])}，再决定是否拆解。"
    return "打开案卷核对证据。"


def external_opportunities(
    min_score: int | None = None,
    evidence_type: str | None = None,
    domain: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    home: bool = False,
) -> dict:
    size, start = _page(limit, offset)
    conn = connect()
    try:
        rows = conn.execute(
            """
            SELECT normalized_domain, record_type, time_range, normalized_keyword,
                   json_extract(raw_json, '$.rank') AS rank,
                   json_extract(raw_json, '$.payment_traffic') AS payment_traffic,
                   json_extract(raw_json, '$.traffic_growth') AS traffic_growth,
                   json_extract(raw_json, '$.growth_rate') AS growth_rate,
                   json_extract(raw_json, '$.dr_growth') AS dr_growth,
                   json_extract(raw_json, '$.keyword') AS keyword,
                   json_extract(raw_json, '$.provider') AS provider
            FROM raw_source_records
            WHERE lower(COALESCE(status, '')) IN ('imported', 'confirmed')
              AND record_type IN ('payment_signal', 'traffic_signal', 'authority_signal', 'serp_result')
            """
        ).fetchall()
        pages = conn.execute(
            """
            SELECT domain, title, target_keyword
            FROM competitor_pages
            """
        ).fetchall()
        news_rows = conn.execute(
            """
            SELECT source_name, url, domain
            FROM raw_items
            """
        ).fetchall()
    finally:
        conn.close()
    domains: dict[str, dict] = {}
    for row in rows:
        host = _host(row["normalized_domain"] or "")
        if not host or _sample_host(host):
            continue
        bucket = domains.setdefault(host, _blank_domain())
        month = row["time_range"] or ""
        _keep_month(bucket, month)
        kind = row["record_type"]
        rank = _num(row["rank"])
        if kind == "payment_signal":
            if _MONTH.match(month):
                bucket["payment_months"].add(month)
            bucket["payment_best"], bucket["payment_label"] = _keep_max(
                bucket["payment_best"], bucket["payment_label"], row["payment_traffic"], row["payment_traffic"]
            )
        elif kind == "traffic_signal":
            bucket["traffic"] = True
            if rank is not None and rank <= 100:
                bucket["traffic_top"] = True
            growth = row["traffic_growth"] if _num(row["traffic_growth"]) is not None else row["growth_rate"]
            bucket["traffic_best"], bucket["traffic_label"] = _keep_max(
                bucket["traffic_best"], bucket["traffic_label"], growth, growth
            )
        elif kind == "authority_signal":
            bucket["authority"] = True
            if rank is not None and rank <= 100:
                bucket["authority_top"] = True
            bucket["dr_best"], bucket["dr_label"] = _keep_max(
                bucket["dr_best"], bucket["dr_label"], row["dr_growth"], row["dr_growth"]
            )
        if (row["provider"] or "").lower() == "sitedata":
            label = {"payment_signal": "payment", "traffic_signal": "traffic", "authority_signal": "authority"}.get(kind)
            if label:
                bucket["sitedata"].add(label)
            if rank is not None and 0 < rank <= 100:
                bucket["sitedata_top"] = True
        elif kind == "serp_result":
            bucket["serp"] = True
            keyword = _text(row["normalized_keyword"] or row["keyword"])
            if keyword and (bucket["serp_rank"] is None or (rank is not None and rank < bucket["serp_rank"])):
                bucket["serp_rank"] = rank if rank is not None else bucket["serp_rank"]
                bucket["serp_keyword"] = keyword
    for page in pages:
        host = _host(page["domain"] or "")
        if not host or _sample_host(host):
            continue
        bucket = domains.setdefault(host, _blank_domain())
        bucket["competitor"] = True
        if not bucket["serp_keyword"]:
            bucket["serp_keyword"] = _text(page["target_keyword"])
    for row in news_rows:
        host = _host(row["domain"] or row["url"] or "")
        if not host or _sample_host(host):
            continue
        bucket = domains.setdefault(host, _blank_domain())
        if "product hunt" in (row["source_name"] or "").lower():
            bucket["product_hunt"] = True
        else:
            bucket["news"] = True
    wanted = (evidence_type or "").strip().lower()
    needle = (domain or "").strip().lower()
    floor = int(min_score) if min_score is not None else None
    items = []
    for host, bucket in domains.items():
        if needle and needle not in host:
            continue
        payment = bool(bucket["payment_months"]) or bucket["payment_best"] is not None
        traffic = bucket["traffic"]
        authority = bucket["authority"]
        serp = bucket["serp"]
        competitor = bucket["competitor"]
        news = bucket["news"]
        product_hunt = bucket["product_hunt"]
        flags = {
            "payment": payment,
            "traffic": traffic,
            "authority": authority,
            "serp": serp,
            "competitor": competitor,
            "news": news,
            "product_hunt": product_hunt,
        }
        if wanted and not flags.get(wanted):
            continue
        score = 0
        if news:
            score += 10
        if product_hunt:
            score += 15
        if payment:
            score += 30
        if traffic:
            score += 20
        if authority:
            score += 15
        if serp:
            score += 15
        if competitor:
            score += 10
        evidence_count = sum(1 for present in flags.values() if present)
        if evidence_count >= 3:
            score += 20
        sitedata = bucket["sitedata"]
        if bucket["sitedata_top"]:
            score += 10
        if len(sitedata) >= 3:
            score += 25
        elif len(sitedata) >= 2:
            score += 15
        score = min(score, 100)
        if floor is not None and score < floor:
            continue
        if sitedata:
            site_payment = "payment" in sitedata
            site_traffic = "traffic" in sitedata
            site_authority = "authority" in sitedata
            if site_payment and site_traffic and site_authority:
                action = "Priority Research"
            elif site_payment and site_traffic:
                action = "Commercial Research"
            elif site_traffic and site_authority:
                action = "SEO Teardown"
            elif site_payment:
                action = "Payment Signal Review"
            elif site_traffic:
                action = "Traffic Growth Watch"
            else:
                action = "Authority Growth Watch"
        elif payment and traffic and authority:
            action = "Priority Research"
        elif payment and serp and competitor:
            action = "Page Teardown"
        elif traffic and authority and not payment:
            action = "Watch / Research"
        elif authority and not payment and not traffic:
            action = "Authority Signal Only"
        elif payment and not traffic and not authority:
            action = "Payment Signal Only"
        elif traffic and not payment and not authority:
            action = "Traffic Signal Only"
        else:
            action = "Review Signals"
        tags = []
        if news:
            tags.append("News")
        if product_hunt:
            tags.append("Product Hunt")
        if payment:
            tags.append("Payment")
        if traffic:
            tags.append("Traffic")
        if authority:
            tags.append("Authority")
        if serp:
            tags.append("SERP")
        if competitor:
            tags.append("Competitor")
        missing = []
        if not payment:
            missing.append("Payment")
        if not traffic:
            missing.append("Traffic")
        if not authority:
            missing.append("Authority")
        if not serp:
            missing.append("SERP")
        if not competitor:
            missing.append("Competitor")
        missing.append("Validation")
        noise = _desk_noise(host)
        tier, reason = _opportunity_tier(score, payment, traffic, authority, noise)
        latest_signal = ""
        if bucket["payment_label"]:
            latest_signal = f"payment {bucket['payment_label']}"
        elif bucket["traffic_label"]:
            latest_signal = f"traffic {bucket['traffic_label']}"
        elif bucket["dr_label"]:
            latest_signal = f"authority {bucket['dr_label']}"
        elif bucket["serp_keyword"]:
            latest_signal = f"serp {bucket['serp_keyword']}"
        items.append(
            {
                "domain": host,
                "opportunity_score": score,
                "evidence_count": evidence_count,
                "payment_status": "Ready" if len(bucket["payment_months"]) >= 3 else "Partial" if payment else "Missing",
                "traffic_status": "Ready" if bucket["traffic_top"] else "Partial" if traffic else "Missing",
                "authority_status": "Ready" if bucket["authority_top"] else "Partial" if authority else "Missing",
                "serp_status": "Partial" if serp else "Missing",
                "competitor_status": "Partial" if competitor else "Missing",
                "latest_month": bucket["latest"],
                "top_keyword": bucket["serp_keyword"],
                "best_payment_traffic": bucket["payment_label"],
                "best_traffic_growth": bucket["traffic_label"],
                "best_dr_growth": bucket["dr_label"],
                "recommended_action": action,
                "tags": tags,
                "opportunity_tier": tier,
                "evidence_tags": list(tags),
                "missing_evidence": missing,
                "next_action": _next_action(action, missing),
                "reason": reason,
                "latest_signal": latest_signal,
                "_pay": bucket["payment_best"] or 0,
            }
        )
    if home:
        items = [item for item in items if item["opportunity_tier"] != "P3_noise" and not _desk_noise(item["domain"])]
    items.sort(
        key=lambda item: (
            _TIER_ORDER.get(item["opportunity_tier"], 9),
            -item["opportunity_score"],
            -item["evidence_count"],
            -item["_pay"],
            item["domain"],
        )
    )
    total = len(items)
    page = []
    for item in items[start : start + size]:
        item.pop("_pay", None)
        page.append(item)
    return {"total": total, "limit": size, "offset": start, "items": page}


def _feed_rows(record_type: str, limit: int = 3) -> list:
    conn = connect()
    try:
        return conn.execute(
            """
            SELECT r.normalized_domain, r.normalized_title, r.normalized_keyword, r.time_range, r.created_at,
                   json_extract(r.raw_json, '$.payment_traffic') AS payment_traffic,
                   json_extract(r.raw_json, '$.traffic_growth') AS traffic_growth,
                   json_extract(r.raw_json, '$.growth_rate') AS growth_rate,
                   json_extract(r.raw_json, '$.dr_growth') AS dr_growth,
                   json_extract(r.raw_json, '$.current_dr') AS current_dr,
                   json_extract(r.raw_json, '$.rank') AS rank
            FROM raw_source_records r
            WHERE r.record_type = ?
              AND lower(COALESCE(r.status, '')) IN ('imported', 'confirmed')
            ORDER BY r.id DESC
            LIMIT ?
            """,
            (record_type, limit * 4),
        ).fetchall()
    finally:
        conn.close()


def _real_feed(rows, limit: int) -> list:
    chosen = []
    for row in rows:
        if _sample_host(row["normalized_domain"] or ""):
            continue
        chosen.append(row)
        if len(chosen) >= limit:
            break
    return chosen


def intelligence_feed() -> dict:
    items = []
    for row in _real_feed(_feed_rows("payment_signal"), 3):
        domain = _host(row["normalized_domain"] or "")
        month = row["time_range"] or "--"
        traffic = _text(row["payment_traffic"]) or "--"
        items.append(
            {
                "time": row["created_at"] or "",
                "source": "Stripe",
                "domain": domain,
                "title": row["normalized_title"] or "",
                "signal": "payment_signal",
                "why": f"{domain} appeared in Stripe Payment Ranking {month}, payment traffic {traffic}.",
            }
        )
    for row in _real_feed(_feed_rows("authority_signal"), 3):
        domain = _host(row["normalized_domain"] or "")
        month = row["time_range"] or "--"
        growth = _text(row["dr_growth"]) or "--"
        prefix = f"+{growth}" if growth not in {"", "--"} and not growth.startswith(("+", "-")) else growth
        items.append(
            {
                "time": row["created_at"] or "",
                "source": "DR",
                "domain": domain,
                "title": row["normalized_title"] or "",
                "signal": "authority_signal",
                "why": f"{domain} DR {prefix} in {month}.",
            }
        )
    for row in _real_feed(_feed_rows("traffic_signal"), 3):
        domain = _host(row["normalized_domain"] or "")
        month = row["time_range"] or "--"
        growth = _text(row["traffic_growth"] or row["growth_rate"]) or "--"
        items.append(
            {
                "time": row["created_at"] or "",
                "source": "Traffic",
                "domain": domain,
                "title": row["normalized_title"] or "",
                "signal": "traffic_signal",
                "why": f"{domain} traffic growth {growth} in {month}.",
            }
        )
    conn = connect()
    try:
        pages = conn.execute(
            """
            SELECT domain, title, page_type, copyability_score, created_at
            FROM competitor_pages
            ORDER BY id DESC
            """
        ).fetchall()
        crawls = conn.execute(
            """
            SELECT normalized_domain, normalized_title, normalized_url, created_at
            FROM raw_source_records
            WHERE record_type = 'crawl_signal'
              AND lower(COALESCE(status, '')) IN ('imported', 'confirmed')
            ORDER BY id DESC
            LIMIT 8
            """
        ).fetchall()
    finally:
        conn.close()
    shown = 0
    for page in pages:
        if _sample_host(page["domain"] or ""):
            continue
        domain = _host(page["domain"] or "")
        title = page["title"] or domain
        items.append(
            {
                "time": page["created_at"] or "",
                "source": "SERP",
                "domain": domain,
                "title": title,
                "signal": "competitor_page",
                "why": f"{domain} competitor page {title}, copyability {page['copyability_score']}.",
            }
        )
        shown += 1
        if shown >= 3:
            break
    shown = 0
    for row in crawls:
        if _sample_host(row["normalized_domain"] or ""):
            continue
        domain = _host(row["normalized_domain"] or "") or (row["normalized_url"] or "")
        title = row["normalized_title"] or row["normalized_url"] or domain
        items.append(
            {
                "time": row["created_at"] or "",
                "source": "Crawl",
                "domain": domain,
                "title": title,
                "signal": "crawl_signal",
                "why": f"{domain} public crawl {title}.",
            }
        )
        shown += 1
        if shown >= 3:
            break
    return {"items": items}
