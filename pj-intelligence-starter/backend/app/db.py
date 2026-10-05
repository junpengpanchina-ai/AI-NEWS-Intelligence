import hashlib
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SOURCES = [
    ("Hacker News", "hn", "https://hacker-news.firebaseio.com/v0/topstories.json", 3, 1),
    ("TechCrunch", "rss", "https://techcrunch.com/feed/", 2, 1),
    ("The Verge", "rss", "https://www.theverge.com/rss/index.xml", 2, 1),
    ("Ars Technica", "rss", "https://feeds.arstechnica.com/arstechnica/index", 2, 1),
    ("OpenAI Blog", "rss", "https://openai.com/news/rss.xml", 3, 1),
    ("Google AI Blog", "rss", "https://blog.google/innovation-and-ai/technology/ai/rss/", 3, 1),
    ("Product Hunt", "rss", "https://www.producthunt.com/feed", 2, 1),
]


def project_root() -> Path:
    here = Path(__file__).resolve()
    local_root = here.parents[2]
    if (local_root / "docker-compose.yml").exists() and (local_root / "frontend").exists():
        return local_root
    return here.parents[1]


def db_path() -> Path:
    return project_root() / "data" / "intelligence.db"


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                type TEXT NOT NULL,
                url TEXT NOT NULL,
                weight INTEGER NOT NULL,
                enabled INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS raw_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_name TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE,
                summary TEXT,
                author TEXT,
                published_at TEXT,
                fetched_at TEXT NOT NULL,
                content_hash TEXT NOT NULL UNIQUE,
                score INTEGER NOT NULL,
                status TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS ai_analysis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL,
                model TEXT NOT NULL,
                analysis TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS llm_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL UNIQUE,
                count INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                summary TEXT,
                primary_keyword TEXT,
                source_count INTEGER,
                item_count INTEGER,
                max_item_score INTEGER,
                event_score INTEGER,
                first_seen_at TEXT,
                last_seen_at TEXT,
                status TEXT,
                created_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS event_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER,
                item_id INTEGER,
                similarity_score REAL,
                created_at TEXT,
                UNIQUE(event_id, item_id)
            );

            CREATE TABLE IF NOT EXISTS event_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER,
                score INTEGER,
                reason TEXT,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS event_analysis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER,
                model TEXT,
                analysis TEXT,
                analysis_type TEXT,
                elapsed_seconds INTEGER,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS keyword_clusters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                category TEXT,
                search_intent TEXT,
                page_type TEXT,
                priority INTEGER,
                status TEXT,
                score INTEGER,
                notes TEXT,
                created_at TEXT,
                updated_at TEXT,
                UNIQUE(name)
            );

            CREATE TABLE IF NOT EXISTS keyword_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cluster_id INTEGER,
                keyword TEXT,
                intent TEXT,
                difficulty TEXT,
                source TEXT,
                status TEXT,
                created_at TEXT,
                UNIQUE(cluster_id, keyword)
            );

            CREATE TABLE IF NOT EXISTS keyword_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cluster_id INTEGER,
                score INTEGER,
                reason TEXT,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS keyword_analysis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cluster_id INTEGER,
                model TEXT,
                analysis TEXT,
                elapsed_seconds INTEGER,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS competitor_pages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cluster_id INTEGER,
                url TEXT,
                domain TEXT,
                title TEXT,
                h1 TEXT,
                page_type TEXT,
                target_keyword TEXT,
                cta_text TEXT,
                pricing_signal TEXT,
                signup_signal TEXT,
                payment_signal TEXT,
                geo_signal TEXT,
                copyability_score INTEGER,
                risk_level TEXT,
                notes TEXT,
                created_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS competitor_page_analysis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                page_id INTEGER,
                model TEXT,
                analysis TEXT,
                elapsed_seconds INTEGER,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS opportunity_cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cluster_id INTEGER,
                title TEXT,
                verdict TEXT,
                target_keyword TEXT,
                page_type TEXT,
                user_intent TEXT,
                competitor_summary TEXT,
                product_angle TEXT,
                first_page_plan TEXT,
                seven_day_action TEXT,
                fourteen_day_action TEXT,
                thirty_day_metric TEXT,
                sixty_day_stop_rule TEXT,
                score INTEGER,
                status TEXT,
                notes TEXT,
                keyword_score INTEGER,
                competitor_count INTEGER,
                best_competitor_score INTEGER,
                best_competitor_domain TEXT,
                verdict_reason TEXT,
                created_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS opportunity_analysis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_id INTEGER,
                model TEXT,
                analysis TEXT,
                elapsed_seconds INTEGER,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS data_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                source_type TEXT,
                provider TEXT,
                url TEXT,
                region TEXT,
                time_range TEXT,
                data_format TEXT,
                credibility TEXT,
                notes TEXT,
                enabled INTEGER,
                created_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS source_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER,
                record_type TEXT,
                linked_table TEXT,
                linked_id INTEGER,
                raw_ref TEXT,
                confidence TEXT,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS source_imports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER,
                import_name TEXT,
                source_type TEXT,
                record_type TEXT,
                original_filename TEXT,
                row_count INTEGER,
                status TEXT,
                notes TEXT,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS raw_source_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                import_id INTEGER,
                source_id INTEGER,
                record_type TEXT,
                raw_json TEXT,
                normalized_title TEXT,
                normalized_url TEXT,
                normalized_keyword TEXT,
                normalized_domain TEXT,
                metric_name TEXT,
                metric_value TEXT,
                time_range TEXT,
                confidence TEXT,
                status TEXT,
                created_at TEXT
            );
            """
        )
        conn.executemany(
            """
            INSERT OR IGNORE INTO sources (name, type, url, weight, enabled)
            VALUES (?, ?, ?, ?, ?)
            """,
            SOURCES,
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(opportunity_cards)")}
        additions = {
            "keyword_score": "INTEGER",
            "competitor_count": "INTEGER",
            "best_competitor_score": "INTEGER",
            "best_competitor_domain": "TEXT",
            "verdict_reason": "TEXT",
        }
        for name, ddl in additions.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE opportunity_cards ADD COLUMN {name} {ddl}")
        conn.commit()
    finally:
        conn.close()
    from app.ledger import seed_data_sources

    seed_data_sources()


def content_hash(title: str) -> str:
    normalized = re.sub(r"\s+", " ", (title or "").strip().lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def list_sources() -> list[dict]:
    conn = connect()
    try:
        rows = conn.execute(
            """
            SELECT id, name, type, url, weight, enabled
            FROM sources
            WHERE enabled = 1
            ORDER BY id
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def source_weight(name: str) -> int:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT weight FROM sources WHERE name = ?",
            (name,),
        ).fetchone()
        if row is None:
            return 1
        return int(row["weight"])
    finally:
        conn.close()


def insert_item(item: dict) -> bool:
    conn = connect()
    try:
        conn.execute(
            """
            INSERT INTO raw_items (
                source_name, title, url, summary, author,
                published_at, fetched_at, content_hash, score, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["source_name"],
                item["title"],
                item["url"],
                item.get("summary") or "",
                item.get("author") or "",
                item.get("published_at"),
                item["fetched_at"],
                item["content_hash"],
                int(item["score"]),
                item.get("status") or "new",
            ),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def _item(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "source_name": row["source_name"],
        "title": row["title"],
        "url": row["url"],
        "summary": row["summary"] or "",
        "author": row["author"] or "",
        "published_at": row["published_at"],
        "fetched_at": row["fetched_at"],
        "score": row["score"],
        "status": row["status"],
    }


def list_items(limit: int) -> list[dict]:
    conn = connect()
    try:
        rows = conn.execute(
            """
            SELECT id, source_name, title, url, summary, author,
                   published_at, fetched_at, score, status
            FROM raw_items
            ORDER BY score DESC, published_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_item(row) for row in rows]
    finally:
        conn.close()


def get_item(item_id: int) -> dict | None:
    conn = connect()
    try:
        row = conn.execute(
            """
            SELECT id, source_name, title, url, summary, author,
                   published_at, fetched_at, score, status
            FROM raw_items
            WHERE id = ?
            """,
            (item_id,),
        ).fetchone()
        if row is None:
            return None
        return _item(row)
    finally:
        conn.close()


def utc_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def usage_count(day: str | None = None) -> int:
    day = day or utc_today()
    conn = connect()
    try:
        row = conn.execute(
            "SELECT count FROM llm_usage WHERE date = ?",
            (day,),
        ).fetchone()
        if row is None:
            return 0
        return int(row["count"])
    finally:
        conn.close()


def reserve_quota(limit: int, day: str | None = None) -> bool:
    day = day or utc_today()
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT count FROM llm_usage WHERE date = ?",
            (day,),
        ).fetchone()
        current = int(row["count"]) if row else 0
        if current >= limit:
            conn.rollback()
            return False
        if row:
            conn.execute(
                "UPDATE llm_usage SET count = count + 1 WHERE date = ?",
                (day,),
            )
        else:
            conn.execute(
                "INSERT INTO llm_usage (date, count) VALUES (?, 1)",
                (day,),
            )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def release_quota(day: str | None = None) -> None:
    day = day or utc_today()
    conn = connect()
    try:
        conn.execute(
            """
            UPDATE llm_usage
            SET count = CASE WHEN count > 0 THEN count - 1 ELSE 0 END
            WHERE date = ?
            """,
            (day,),
        )
        conn.commit()
    finally:
        conn.close()


def save_analysis(item_id: int, model: str, analysis: str) -> dict:
    created_at = datetime.now(timezone.utc).isoformat()
    conn = connect()
    try:
        cur = conn.execute(
            """
            INSERT INTO ai_analysis (item_id, model, analysis, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (item_id, model, analysis, created_at),
        )
        conn.commit()
        return {
            "id": cur.lastrowid,
            "item_id": item_id,
            "model": model,
            "analysis": analysis,
            "created_at": created_at,
        }
    finally:
        conn.close()


def get_analysis(item_id: int) -> dict | None:
    conn = connect()
    try:
        row = conn.execute(
            """
            SELECT id, item_id, model, analysis, created_at
            FROM ai_analysis
            WHERE item_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (item_id,),
        ).fetchone()
        if row is None:
            return None
        return dict(row)
    finally:
        conn.close()
