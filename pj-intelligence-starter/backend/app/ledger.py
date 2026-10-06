from datetime import datetime, timezone

from app.db import connect

SOURCE_TYPES = {
    "news",
    "google_trends",
    "search_console",
    "keyword_tool",
    "site_traffic",
    "new_site_growth",
    "dr_growth",
    "payment_ranking",
    "serp",
    "ai_search",
    "manual",
    "csv_import",
    "public_web",
    "rss",
    "website",
    "product_hunt",
    "hacker_news",
    "github",
}

RECORD_TYPES = {
    "item",
    "market_signal",
    "keyword",
    "competitor_page",
    "opportunity_card",
    "validation_metric",
}

PRESET_SOURCES = [
    ("Hacker News", "news", "Hacker News", "https://hacker-news.firebaseio.com/v0/topstories.json", "json"),
    ("RSS Feeds", "news", "RSS", "", "rss"),
    ("Google Trends", "google_trends", "Google", "", "manual"),
    ("Google Search Console", "search_console", "Google", "", "manual"),
    ("SiteData Traffic Growth", "site_traffic", "SiteData", "", "manual"),
    ("SiteData New Site Growth", "new_site_growth", "SiteData", "", "manual"),
    ("DR Growth", "dr_growth", "DR", "", "manual"),
    ("Stripe Payment Ranking", "payment_ranking", "Stripe", "", "manual"),
    ("Dodo Payment Ranking", "payment_ranking", "Dodo", "", "manual"),
    ("Manual Research", "manual", "Manual", "", "manual"),
    ("Product Hunt", "product_hunt", "Product Hunt", "https://www.producthunt.com/feed", "rss"),
    ("TechCrunch", "rss", "TechCrunch", "https://techcrunch.com/feed/", "rss"),
    ("The Verge", "rss", "The Verge", "https://www.theverge.com/rss/index.xml", "rss"),
    ("Ars Technica", "rss", "Ars Technica", "https://feeds.arstechnica.com/arstechnica/index", "rss"),
    ("OpenAI Blog", "rss", "OpenAI", "https://openai.com/news/rss.xml", "rss"),
    ("Google AI Blog", "rss", "Google", "https://blog.google/innovation-and-ai/technology/ai/rss/", "rss"),
    ("GitHub Trending", "github", "GitHub", "https://github.com/trending", "html"),
]


def seed_data_sources() -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn = connect()
    try:
        for name, source_type, provider, url, data_format in PRESET_SOURCES:
            conn.execute(
                """
                INSERT OR IGNORE INTO data_sources (
                    name, source_type, provider, url, region, time_range, data_format,
                    credibility, notes, enabled, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    source_type,
                    provider,
                    url,
                    "",
                    "",
                    data_format,
                    "preset",
                    "预置来源，不自动抓取。",
                    1,
                    now,
                    now,
                ),
            )
        conn.commit()
    finally:
        conn.close()
    ensure_google_search_source()


def ensure_serper_source() -> dict:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT id FROM data_sources WHERE name = ?",
            ("Serper Google SERP",),
        ).fetchone()
    finally:
        conn.close()
    if row is not None:
        found = get_source(int(row["id"]))
        if found is not None:
            return found
    return create_source({
        "name": "Serper Google SERP",
        "source_type": "serp",
        "provider": "Serper",
        "url": "https://google.serper.dev/search",
        "data_format": "json",
        "notes": "SERP results from Serper",
        "enabled": 1,
    })


def ensure_google_search_source() -> dict:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT id FROM data_sources WHERE name = ?",
            ("Google Programmable Search",),
        ).fetchone()
    finally:
        conn.close()
    if row is not None:
        found = get_source(int(row["id"]))
        if found is not None:
            return found
    return create_source({
        "name": "Google Programmable Search",
        "source_type": "serp",
        "provider": "Google",
        "url": "https://www.googleapis.com/customsearch/v1",
        "data_format": "json",
        "notes": "SERP results from Custom Search JSON API",
        "enabled": 1,
    })


def _source_row(row) -> dict:
    data = dict(row)
    data["enabled"] = int(data.get("enabled") or 0)
    for key in (
        "name",
        "source_type",
        "provider",
        "url",
        "region",
        "time_range",
        "data_format",
        "credibility",
        "notes",
        "created_at",
        "updated_at",
        "last_run_at",
        "last_status",
        "error_message",
    ):
        data[key] = data.get(key) or ""
    data["records_collected"] = int(data.get("records_collected") or 0)
    return data


def list_sources() -> list[dict]:
    conn = connect()
    try:
        rows = conn.execute(
            """
            SELECT d.id, d.name, d.source_type, d.provider, d.url, d.region, d.time_range, d.data_format,
                   d.credibility, d.notes, d.enabled, d.created_at, d.updated_at,
                   r.last_run_at, r.last_status, r.records_collected, r.error_message
            FROM data_sources d
            LEFT JOIN source_runs r ON r.source_name = d.name
            ORDER BY d.id ASC
            """
        ).fetchall()
        return [_source_row(row) for row in rows]
    finally:
        conn.close()


def get_source(source_id: int) -> dict | None:
    conn = connect()
    try:
        row = conn.execute(
            """
            SELECT d.id, d.name, d.source_type, d.provider, d.url, d.region, d.time_range, d.data_format,
                   d.credibility, d.notes, d.enabled, d.created_at, d.updated_at,
                   r.last_run_at, r.last_status, r.records_collected, r.error_message
            FROM data_sources d
            LEFT JOIN source_runs r ON r.source_name = d.name
            WHERE d.id = ?
            """,
            (source_id,),
        ).fetchone()
        if row is None:
            return None
        return _source_row(row)
    finally:
        conn.close()


def create_source(payload: dict) -> dict:
    name = (payload.get("name") or "").strip()
    source_type = (payload.get("source_type") or "").strip()
    if not name:
        raise ValueError("name 不能为空")
    if source_type not in SOURCE_TYPES:
        raise ValueError("source_type 不在允许列表中")
    enabled = int(payload.get("enabled") if payload.get("enabled") is not None else 1)
    if enabled not in (0, 1):
        raise ValueError("enabled 只能是 0 或 1")
    now = datetime.now(timezone.utc).isoformat()
    conn = connect()
    try:
        try:
            cur = conn.execute(
                """
                INSERT INTO data_sources (
                    name, source_type, provider, url, region, time_range, data_format,
                    credibility, notes, enabled, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    source_type,
                    (payload.get("provider") or "").strip(),
                    (payload.get("url") or "").strip(),
                    (payload.get("region") or "").strip(),
                    (payload.get("time_range") or "").strip(),
                    (payload.get("data_format") or "").strip(),
                    (payload.get("credibility") or "").strip(),
                    (payload.get("notes") or "").strip(),
                    enabled,
                    now,
                    now,
                ),
            )
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise ValueError("数据源已存在") from exc
            raise
        conn.commit()
        source_id = int(cur.lastrowid)
    finally:
        conn.close()
    created = get_source(source_id)
    if created is None:
        raise ValueError("数据源保存失败")
    return created


def _record_row(row) -> dict:
    data = dict(row)
    data["source_id"] = int(data["source_id"])
    data["linked_id"] = int(data["linked_id"])
    for key in ("record_type", "linked_table", "raw_ref", "confidence", "created_at", "source_name", "provider"):
        data[key] = data.get(key) or ""
    return data


def list_source_records(linked_table: str, linked_id: int) -> list[dict]:
    conn = connect()
    try:
        rows = conn.execute(
            """
            SELECT r.id, r.source_id, r.record_type, r.linked_table, r.linked_id,
                   r.raw_ref, r.confidence, r.created_at, s.name AS source_name, s.provider
            FROM source_records r
            JOIN data_sources s ON s.id = r.source_id
            WHERE r.linked_table = ? AND r.linked_id = ?
            ORDER BY r.id ASC
            """,
            (linked_table, linked_id),
        ).fetchall()
        return [_record_row(row) for row in rows]
    finally:
        conn.close()


def create_source_record(payload: dict) -> dict:
    record_type = (payload.get("record_type") or "").strip()
    linked_table = (payload.get("linked_table") or "").strip()
    if record_type not in RECORD_TYPES:
        raise ValueError("record_type 不在允许列表中")
    if not linked_table:
        raise ValueError("linked_table 不能为空")
    source = get_source(int(payload["source_id"]))
    if source is None:
        raise ValueError("数据源不存在")
    now = datetime.now(timezone.utc).isoformat()
    conn = connect()
    try:
        cur = conn.execute(
            """
            INSERT INTO source_records (
                source_id, record_type, linked_table, linked_id, raw_ref, confidence, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(payload["source_id"]),
                record_type,
                linked_table,
                int(payload["linked_id"]),
                (payload.get("raw_ref") or "").strip(),
                (payload.get("confidence") or "").strip(),
                now,
            ),
        )
        conn.commit()
        record_id = int(cur.lastrowid)
    finally:
        conn.close()
    conn = connect()
    try:
        row = conn.execute(
            """
            SELECT r.id, r.source_id, r.record_type, r.linked_table, r.linked_id,
                   r.raw_ref, r.confidence, r.created_at, s.name AS source_name, s.provider
            FROM source_records r
            JOIN data_sources s ON s.id = r.source_id
            WHERE r.id = ?
            """,
            (record_id,),
        ).fetchone()
        return _record_row(row)
    finally:
        conn.close()


def set_source_enabled(source_id: int, enabled: int) -> dict | None:
    if enabled not in (0, 1):
        raise ValueError("enabled 只能是 0 或 1")
    now = datetime.now(timezone.utc).isoformat()
    conn = connect()
    try:
        updated = conn.execute(
            "UPDATE data_sources SET enabled = ?, updated_at = ? WHERE id = ?",
            (enabled, now, source_id),
        )
        conn.commit()
        if updated.rowcount == 0:
            return None
    finally:
        conn.close()
    return get_source(source_id)
