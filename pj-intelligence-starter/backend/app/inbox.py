import csv
import io
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from urllib.parse import urlparse

from app.db import connect
from app.competitors import create_competitor
from app.keywords import get_keyword_cluster
from app.ledger import create_source_record, get_source

IMPORT_RECORD_TYPES = {
    "keyword_signal",
    "traffic_signal",
    "payment_signal",
    "competitor_url",
    "serp_result",
    "trend_signal",
    "manual_note",
    "crawl_signal",
    "authority_signal",
    "market_signal",
    "validation_signal",
}

_FIELD_ALIASES = {
    "url": "url",
    "link": "url",
    "page": "url",
    "page_url": "url",
    "domain": "domain",
    "host": "domain",
    "site": "domain",
    "website": "domain",
    "keyword": "keyword",
    "keywords": "keyword",
    "query": "keyword",
    "term": "keyword",
    "search_term": "keyword",
    "title": "title",
    "name": "title",
    "page_title": "title",
    "metric": "metric",
    "metric_name": "metric",
    "value": "value",
    "metric_value": "value",
    "date": "date",
    "time_range": "date",
    "period": "date",
    "month": "date",
}

_METRIC_COLUMNS = ("rank", "traffic", "score", "volume", "growth", "visits", "revenue")
_SOURCE_NAME_CHECKS = (
    ("dodo", "Import name mentions Dodo but selected source is not Dodo."),
    ("stripe", "Import name mentions Stripe but selected source is not Stripe."),
    ("nexi", "Import name mentions Nexi but selected source is not Nexi."),
)


def source_name_warning(import_name: str, source: dict) -> str:
    label = f"{source.get('name') or ''} {source.get('provider') or ''}".lower()
    text = (import_name or "").lower()
    messages = [message for token, message in _SOURCE_NAME_CHECKS if token in text and token not in label]
    return " ".join(messages)


def _header_key(value: str) -> str:
    return (value or "").strip().lower().replace(" ", "_").replace("-", "_")


def _first_value(raw: dict, names: tuple[str, ...]) -> str:
    for name in names:
        value = str(raw.get(name) or "").strip()
        if value:
            return value
    return ""


def site_fields(raw: dict, record_type: str = "") -> dict:
    url = _first_value(raw, ("url", "link", "page", "page_url"))
    domain = _first_value(raw, ("domain", "site", "website", "host")) or _domain_of(url)
    source = _first_value(raw, ("source",))
    if not source and record_type == "traffic_signal":
        source = "SiteData Manual Import"
    return {
        "domain": domain,
        "url": url,
        "traffic": _first_value(raw, ("traffic", "visits", "monthly_visits", "estimated_traffic")),
        "traffic_growth": _first_value(raw, ("traffic_growth", "growth", "growth_rate", "mom_growth")),
        "rank": _first_value(raw, ("rank", "ranking", "position")),
        "source": source,
        "month": _first_value(raw, ("month", "date", "period", "time_range")),
    }


def _domain_of(url: str) -> str:
    text = (url or "").strip()
    if not text:
        return ""
    parsed = urlparse(text if "://" in text else f"https://{text}")
    host = (parsed.netloc or parsed.path or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host.split("/")[0]


def parse_csv_rows(csv_text: str) -> list[dict]:
    text = (csv_text or "").lstrip("\ufeff")
    if not text.strip():
        return []
    sample = text.splitlines()[0]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        header_row = next(reader)
    except StopIteration:
        return []
    headers = [_header_key(cell) or f"column_{index + 1}" for index, cell in enumerate(header_row)]
    rows = []
    for cells in reader:
        if not any((cell or "").strip() for cell in cells):
            continue
        raw = {}
        for index, header in enumerate(headers):
            raw[header] = cells[index].strip() if index < len(cells) else ""
        extra = [cell.strip() for cell in cells[len(headers):] if cell.strip()]
        if extra:
            raw["_extra"] = extra
        rows.append(raw)
    return rows


def _normalize(raw: dict) -> dict:
    picked = {}
    for key, value in raw.items():
        alias = _FIELD_ALIASES.get(key)
        if alias and alias not in picked and str(value or "").strip():
            picked[alias] = str(value).strip()
    url = picked.get("url") or ""
    domain = picked.get("domain") or _domain_of(url)
    metric_name = picked.get("metric") or ""
    metric_value = picked.get("value") or ""
    if not metric_name:
        for key in _METRIC_COLUMNS:
            if str(raw.get(key) or "").strip():
                metric_name = key
                metric_value = str(raw.get(key)).strip()
                break
    return {
        "normalized_title": picked.get("title") or "",
        "normalized_url": url,
        "normalized_keyword": picked.get("keyword") or "",
        "normalized_domain": domain,
        "metric_name": metric_name,
        "metric_value": metric_value,
        "time_range": picked.get("date") or "",
    }


def _import_row(row) -> dict:
    data = dict(row)
    data["source_id"] = int(data.get("source_id") or 0)
    data["row_count"] = int(data.get("row_count") or 0)
    for key in (
        "import_name",
        "source_type",
        "record_type",
        "original_filename",
        "status",
        "notes",
        "created_at",
        "source_name",
        "provider",
    ):
        data[key] = data.get(key) or ""
    return data


def _raw_row(row) -> dict:
    data = dict(row)
    data["import_id"] = int(data.get("import_id") or 0)
    data["source_id"] = int(data.get("source_id") or 0)
    for key in (
        "record_type",
        "raw_json",
        "normalized_title",
        "normalized_url",
        "normalized_keyword",
        "normalized_domain",
        "metric_name",
        "metric_value",
        "time_range",
        "confidence",
        "status",
        "created_at",
        "source_name",
        "provider",
        "source_type",
    ):
        data[key] = data.get(key) or ""
    return data


def import_csv(payload: dict) -> dict:
    source = get_source(int(payload["source_id"]))
    if source is None:
        raise ValueError("数据源不存在")
    import_name = (payload.get("import_name") or "").strip()
    record_type = (payload.get("record_type") or "").strip()
    if not import_name:
        raise ValueError("import_name 不能为空")
    if record_type not in IMPORT_RECORD_TYPES:
        raise ValueError("record_type 不在允许列表中")
    rows = parse_csv_rows(payload.get("csv_text") or "")
    status = "imported" if rows else "empty"
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
                int(payload["source_id"]),
                import_name,
                source.get("source_type") or "",
                record_type,
                (payload.get("original_filename") or "").strip(),
                len(rows),
                status,
                (payload.get("notes") or "").strip(),
                now,
            ),
        )
        import_id = int(cur.lastrowid)
        for raw in rows:
            normalized = _normalize(raw)
            fields = site_fields(raw, record_type)
            if fields["domain"]:
                normalized["normalized_domain"] = fields["domain"]
            if fields["url"]:
                normalized["normalized_url"] = fields["url"]
            if fields["month"]:
                normalized["time_range"] = fields["month"]
            if fields["traffic"]:
                normalized["metric_name"] = "traffic"
                normalized["metric_value"] = fields["traffic"]
            stored = dict(raw)
            for key, value in fields.items():
                if value:
                    stored[key] = value
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
                    int(payload["source_id"]),
                    record_type,
                    json.dumps(stored, ensure_ascii=False),
                    normalized["normalized_title"],
                    normalized["normalized_url"],
                    normalized["normalized_keyword"],
                    normalized["normalized_domain"],
                    normalized["metric_name"],
                    normalized["metric_value"],
                    normalized["time_range"],
                    "imported",
                    "imported",
                    now,
                ),
            )
        conn.commit()
    finally:
        conn.close()
    return {
        "import_id": import_id,
        "row_count": len(rows),
        "status": status,
        "warning": source_name_warning(import_name, source),
    }


UPLOAD_RECORD_TYPES = {"traffic_signal", "payment_signal", "keyword_signal", "serp_result"}


def import_uploaded_csv(source_id: int, record_type: str, import_name: str, filename: str, raw_bytes: bytes) -> dict:
    kind = (record_type or "").strip()
    if kind not in UPLOAD_RECORD_TYPES:
        raise ValueError("record_type 不在允许列表中")
    if not raw_bytes:
        raise ValueError("CSV 文件为空")
    try:
        csv_text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("CSV 需要是 UTF-8 或 UTF-8-SIG") from exc
    name = (import_name or "").strip() or (filename or "").strip() or "CSV import"
    result = import_csv({
        "source_id": source_id,
        "import_name": name,
        "record_type": kind,
        "csv_text": csv_text,
        "original_filename": (filename or "").strip(),
    })
    return {
        "import_id": result["import_id"],
        "record_type": kind,
        "row_count": result["row_count"],
        "status": result["status"],
    }


def list_imports() -> list[dict]:
    conn = connect()
    try:
        rows = conn.execute(
            """
            SELECT i.id, i.source_id, i.import_name,
                   COALESCE(s.source_type, i.source_type) AS source_type, i.record_type,
                   i.original_filename, i.row_count, i.status, i.notes, i.created_at,
                   s.name AS source_name, s.provider AS provider
            FROM source_imports i
            LEFT JOIN data_sources s ON s.id = i.source_id
            ORDER BY i.id DESC
            """
        ).fetchall()
        return [_import_row(row) for row in rows]
    finally:
        conn.close()


def get_import(import_id: int) -> dict | None:
    conn = connect()
    try:
        row = conn.execute(
            """
            SELECT i.id, i.source_id, i.import_name,
                   COALESCE(s.source_type, i.source_type) AS source_type, i.record_type,
                   i.original_filename, i.row_count, i.status, i.notes, i.created_at,
                   s.name AS source_name, s.provider AS provider
            FROM source_imports i
            LEFT JOIN data_sources s ON s.id = i.source_id
            WHERE i.id = ?
            """,
            (import_id,),
        ).fetchone()
        if row is None:
            return None
        detail = _import_row(row)
        records = conn.execute(
            """
            SELECT r.id, r.import_id, r.source_id, r.record_type, r.raw_json, r.normalized_title,
                   r.normalized_url, r.normalized_keyword, r.normalized_domain, r.metric_name,
                   r.metric_value, r.time_range, r.confidence, r.status, r.created_at,
                   s.name AS source_name, s.provider AS provider, s.source_type AS source_type
            FROM raw_source_records r
            LEFT JOIN data_sources s ON s.id = r.source_id
            WHERE r.import_id = ?
            ORDER BY r.id ASC
            LIMIT 100
            """,
            (import_id,),
        ).fetchall()
        detail["records"] = [_raw_row(item) for item in records]
        return detail
    finally:
        conn.close()


def list_raw_records(source_id: int | None, record_type: str | None) -> list[dict]:
    clauses = []
    params: list = []
    if source_id is not None:
        clauses.append("r.source_id = ?")
        params.append(source_id)
    if record_type:
        clauses.append("r.record_type = ?")
        params.append(record_type.strip())
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    conn = connect()
    try:
        rows = conn.execute(
            f"""
            SELECT r.id, r.import_id, r.source_id, r.record_type, r.raw_json, r.normalized_title,
                   r.normalized_url, r.normalized_keyword, r.normalized_domain, r.metric_name,
                   r.metric_value, r.time_range, r.confidence, r.status, r.created_at,
                   s.name AS source_name, s.provider AS provider, s.source_type AS source_type
            FROM raw_source_records r
            LEFT JOIN data_sources s ON s.id = r.source_id
            {where}
            ORDER BY r.id DESC
            """,
            params,
        ).fetchall()
        return [_raw_row(row) for row in rows]
    finally:
        conn.close()


def update_import_source(import_id: int, source_id: int) -> dict | None:
    source = get_source(source_id)
    if source is None:
        raise ValueError("数据源不存在")
    conn = connect()
    try:
        current = conn.execute(
            "SELECT source_id FROM source_imports WHERE id = ?",
            (import_id,),
        ).fetchone()
        if current is None:
            return None
        old_source_id = int(current["source_id"] or 0)
        conn.execute(
            "UPDATE source_imports SET source_id = ? WHERE id = ?",
            (source_id, import_id),
        )
        updated = conn.execute(
            "UPDATE raw_source_records SET source_id = ? WHERE import_id = ?",
            (source_id, import_id),
        )
        conn.commit()
        updated_records = int(updated.rowcount or 0)
    finally:
        conn.close()
    return {
        "import_id": import_id,
        "old_source_id": old_source_id,
        "new_source_id": source_id,
        "updated_records": updated_records,
    }


def _serp_fields(row) -> dict:
    raw = {}
    try:
        parsed = json.loads(row["raw_json"] or "{}")
        if isinstance(parsed, dict):
            raw = parsed
    except (TypeError, ValueError):
        raw = {}
    url = str(row["normalized_url"] or raw.get("url") or raw.get("link") or "").strip()
    domain = str(row["normalized_domain"] or raw.get("domain") or raw.get("displayLink") or "").strip()
    title = str(row["normalized_title"] or raw.get("title") or "").strip()
    keyword = str(row["normalized_keyword"] or raw.get("keyword") or raw.get("query") or "").strip()
    snippet = str(raw.get("snippet") or "").strip()
    rank = ""
    if str(row["metric_name"] or "") == "rank" and str(row["metric_value"] or "").strip():
        rank = str(row["metric_value"]).strip()
    if not rank:
        rank = str(raw.get("rank") or "").strip()
    notes = "\n".join(part for part in (snippet, f"rank {rank}" if rank else "") if part)
    return {
        "url": url,
        "domain": domain,
        "title": title,
        "target_keyword": keyword,
        "notes": notes,
        "source_id": int(row["source_id"] or 0),
    }


def _competitor_url_exists(url: str) -> bool:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT id FROM competitor_pages WHERE url = ?",
            (url,),
        ).fetchone()
    finally:
        conn.close()
    return row is not None


def promote_serp_competitors(import_id: int, cluster_id: int) -> dict | None:
    if get_keyword_cluster(int(cluster_id)) is None:
        raise ValueError("关键词簇不存在")
    conn = connect()
    try:
        batch = conn.execute(
            "SELECT id FROM source_imports WHERE id = ?",
            (import_id,),
        ).fetchone()
        if batch is None:
            return None
        rows = conn.execute(
            """
            SELECT id, source_id, raw_json, normalized_title, normalized_url,
                   normalized_keyword, normalized_domain, metric_name, metric_value
            FROM raw_source_records
            WHERE import_id = ? AND record_type = ?
            ORDER BY id ASC
            """,
            (import_id, "serp_result"),
        ).fetchall()
    finally:
        conn.close()
    created = 0
    skipped = 0
    seen: set[str] = set()
    for row in rows:
        fields = _serp_fields(row)
        url = fields["url"]
        if not url or url in seen or _competitor_url_exists(url):
            skipped += 1
            continue
        seen.add(url)
        page = create_competitor({
            "cluster_id": int(cluster_id),
            "url": url,
            "domain": fields["domain"],
            "title": fields["title"],
            "h1": "",
            "page_type": "unknown",
            "target_keyword": fields["target_keyword"],
            "notes": fields["notes"],
        })
        if page is None:
            skipped += 1
            continue
        if fields["source_id"] and get_source(fields["source_id"]) is not None:
            create_source_record({
                "source_id": fields["source_id"],
                "record_type": "competitor_page",
                "linked_table": "competitor_pages",
                "linked_id": int(page["id"]),
                "raw_ref": url,
                "confidence": "medium",
            })
        created += 1
    return {
        "import_id": import_id,
        "cluster_id": int(cluster_id),
        "created": created,
        "skipped": skipped,
    }


_MONTH = re.compile(r"^\d{4}-\d{2}$")
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
_SAMPLE_TOKENS = ("sample", "demo", "draft check", "browser form")


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


def _sample_text(value: str) -> bool:
    text = (value or "").lower()
    return any(token in text for token in _SAMPLE_TOKENS)


def _parsed_raw(value: str) -> dict:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _period_month(time_range: str, raw: dict) -> str:
    for value in (time_range, raw.get("period_month")):
        text = str(value or "")
        if _MONTH.match(text):
            return text
    return ""


def _validation_day(time_range: str, raw: dict) -> str:
    match = _DAY.search(str(raw.get("date") or time_range or ""))
    return match.group(0) if match else ""


def _day_streak(days: set[str]) -> int:
    unique = sorted(days)
    if not unique:
        return 0
    best = streak = 1
    for previous, current in zip(unique, unique[1:]):
        gap = (date.fromisoformat(current) - date.fromisoformat(previous)).days
        streak = streak + 1 if gap == 1 else 1
        if streak > best:
            best = streak
    return best


def _fresh_bucket() -> dict:
    return {
        "row_count": 0,
        "sample_count": 0,
        "real_count": 0,
        "months": set(),
        "sources": set(),
        "domains": Counter(),
        "source_names": Counter(),
        "keywords": Counter(),
        "days": set(),
    }


def _is_serper(record_type: str, provider: str, source_name: str, confidence: str) -> bool:
    if record_type != "serp_result":
        return False
    label = f"{provider or ''} {source_name or ''} {confidence or ''}".lower()
    return "serper" in label


def _sample_row(row, raw: dict) -> bool:
    if _is_serper(row["record_type"] or "", row["provider"] or "", row["source_name"] or "", row["confidence"] or ""):
        return False
    notes = " ".join(
        str(part or "")
        for part in (
            row["normalized_title"],
            raw.get("title"),
            raw.get("notes"),
            raw.get("source_note"),
        )
    )
    return (
        _sample_host(row["normalized_domain"] or "")
        or _sample_host(row["normalized_url"] or "")
        or _sample_host(str(raw.get("domain") or ""))
        or _sample_host(str(raw.get("url") or ""))
        or _sample_text(notes)
    )


def _apply_row(bucket: dict, row, raw: dict, sample: bool) -> None:
    bucket["row_count"] += 1
    source_id = row["source_id"]
    if source_id is not None:
        bucket["sources"].add(int(source_id))
    source_name = (row["source_name"] or "").strip()
    if source_name:
        bucket["source_names"][source_name] += 1
    if sample:
        bucket["sample_count"] += 1
        return
    bucket["real_count"] += 1
    month = _period_month(row["time_range"] or "", raw)
    if month:
        bucket["months"].add(month)
    domain = (row["normalized_domain"] or str(raw.get("domain") or "")).strip().lower()
    if domain:
        bucket["domains"][domain] += 1
    keyword = str(row["normalized_keyword"] or raw.get("keyword") or "").strip().lower()
    bucket["keywords"][keyword or "__missing__"] += 1
    day = _validation_day(row["time_range"] or "", raw)
    if day:
        bucket["days"].add(day)


def _bucket_out(record_type: str, dataset_type: str, bucket: dict, detailed: bool) -> dict:
    months = sorted(bucket["months"])
    payload = {
        "record_type": record_type,
        "dataset_type": dataset_type,
        "row_count": bucket["row_count"],
        "month_count": len(months),
        "latest_month": months[-1] if months else "",
        "source_count": len(bucket["sources"]),
        "sample_count": bucket["sample_count"],
        "real_count": bucket["real_count"],
    }
    if not detailed:
        return payload
    keywords = bucket["keywords"]
    named = [count for key, count in keywords.items() if key != "__missing__"]
    payload.update(
        {
            "top_domains": [domain for domain, _count in bucket["domains"].most_common(3)],
            "source_name": bucket["source_names"].most_common(1)[0][0] if bucket["source_names"] else "",
            "keyword_count": len(named),
            "best_keyword_count": max(keywords.values(), default=0),
            "validation_streak": _day_streak(bucket["days"]),
        }
    )
    return payload


def evidence_stats() -> dict:
    conn = connect()
    try:
        rows = conn.execute(
            """
            SELECT r.record_type, r.normalized_domain, r.normalized_url, r.normalized_keyword,
                   r.normalized_title, r.time_range, r.confidence, r.raw_json, r.source_id,
                   s.name AS source_name, s.provider AS provider
            FROM raw_source_records r
            LEFT JOIN data_sources s ON s.id = r.source_id
            WHERE lower(COALESCE(r.status, '')) IN ('imported', 'confirmed')
            """
        ).fetchall()
    finally:
        conn.close()
    groups: dict[tuple[str, str], dict] = defaultdict(_fresh_bucket)
    record_types: dict[str, dict] = defaultdict(_fresh_bucket)
    serp_urls: list[str] = []
    for row in rows:
        raw = _parsed_raw(row["raw_json"] or "")
        record_type = (row["record_type"] or "").strip()
        dataset_type = str(raw.get("dataset_type") or "").strip()
        sample = _sample_row(row, raw)
        _apply_row(groups[(record_type, dataset_type)], row, raw, sample)
        _apply_row(record_types[record_type], row, raw, sample)
        if _is_serper(record_type, row["provider"] or "", row["source_name"] or "", row["confidence"] or ""):
            url = (row["normalized_url"] or "").strip()
            if url and url not in serp_urls:
                serp_urls.append(url)
    group_rows = [
        _bucket_out(record_type, dataset_type, bucket, False)
        for (record_type, dataset_type), bucket in sorted(groups.items())
    ]
    type_rows = []
    for record_type, bucket in sorted(record_types.items()):
        related = [item for item in group_rows if item["record_type"] == record_type and item["dataset_type"]]
        dataset_type = max(related, key=lambda item: item["row_count"])["dataset_type"] if related else ""
        type_rows.append(_bucket_out(record_type, dataset_type, bucket, True))
    return {"groups": group_rows, "record_types": type_rows, "serp_urls": serp_urls}


def bind_raw_record(payload: dict) -> dict:
    conn = connect()
    try:
        row = conn.execute(
            """
            SELECT id, source_id, normalized_title, normalized_keyword, normalized_domain, metric_name
            FROM raw_source_records
            WHERE id = ?
            """,
            (int(payload["raw_record_id"]),),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise ValueError("原始记录不存在")
    raw_ref = next(
        (
            text
            for text in (
                row["normalized_keyword"],
                row["normalized_domain"],
                row["normalized_title"],
                row["metric_name"],
            )
            if text
        ),
        f"raw {row['id']}",
    )
    return create_source_record(
        {
            "source_id": int(row["source_id"]),
            "record_type": payload.get("record_type") or "",
            "linked_table": payload.get("linked_table") or "",
            "linked_id": int(payload["linked_id"]),
            "raw_ref": raw_ref,
            "confidence": payload.get("confidence") or "medium",
        }
    )
