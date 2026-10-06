import csv
import io
import json
from datetime import datetime, timezone
from urllib.parse import urlparse

from app.db import connect
from app.ledger import create_source_record, get_source

IMPORT_RECORD_TYPES = {
    "keyword_signal",
    "traffic_signal",
    "payment_signal",
    "competitor_url",
    "serp_result",
    "trend_signal",
    "manual_note",
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
                    json.dumps(raw, ensure_ascii=False),
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
        clauses.append("source_id = ?")
        params.append(source_id)
    if record_type:
        clauses.append("record_type = ?")
        params.append(record_type.strip())
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    conn = connect()
    try:
        rows = conn.execute(
            f"""
            SELECT id, import_id, source_id, record_type, raw_json, normalized_title,
                   normalized_url, normalized_keyword, normalized_domain, metric_name,
                   metric_value, time_range, confidence, status, created_at
            FROM raw_source_records
            {where}
            ORDER BY id DESC
            LIMIT 500
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
