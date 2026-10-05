import re
from datetime import datetime, timedelta, timezone

from app.db import connect

STOPWORDS = {
    "the",
    "a",
    "an",
    "of",
    "to",
    "in",
    "for",
    "and",
    "or",
    "on",
    "with",
    "is",
    "are",
    "has",
    "have",
}

KEYWORDS = [
    "apple intelligence",
    "data center",
    "agents",
    "agent",
    "openai",
    "google",
    "anthropic",
    "coding",
    "developer",
    "startup",
    "funding",
    "automation",
    "robotics",
    "healthcare",
    "medical",
    "documentation",
    "memory",
    "product",
    "model",
    "saas",
    "api",
    "ai",
]


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _seen_at(item: dict) -> datetime | None:
    return _parse_time(item.get("published_at")) or _parse_time(item.get("fetched_at"))


def normalize_title(title: str) -> str:
    text = (title or "").lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def title_tokens(title: str) -> list[str]:
    return [token for token in normalize_title(title).split() if token and token not in STOPWORDS]


def extract_keywords(title: str) -> list[str]:
    text = normalize_title(title)
    found = []
    for keyword in KEYWORDS:
        if re.search(rf"\b{re.escape(keyword)}\b", text) and keyword not in found:
            found.append(keyword)
        if len(found) >= 5:
            break
    return found


def jaccard(left: list[str], right: list[str]) -> float:
    a = set(left)
    b = set(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _within_72h(left: datetime | None, right: datetime | None) -> bool:
    if left is None or right is None:
        return False
    return abs((left - right).total_seconds()) < 72 * 3600


def _join_similarity(item: dict, cluster: list[dict]) -> float | None:
    best = 0.0
    matched = False
    for member in cluster:
        score = jaccard(item["tokens"], member["tokens"])
        if score > best:
            best = score
        if score >= 0.35:
            matched = True
        elif item["primary"] and item["primary"] == member["primary"] and _within_72h(item["seen"], member["seen"]):
            matched = True
    if not matched:
        return None
    return best


def cluster_items(items: list[dict]) -> list[list[dict]]:
    prepared = []
    for item in items:
        keywords = extract_keywords(item.get("title") or "")
        prepared.append(
            {
                **item,
                "tokens": title_tokens(item.get("title") or ""),
                "keywords": keywords,
                "primary": keywords[0] if keywords else "",
                "seen": _seen_at(item),
            }
        )
    prepared.sort(key=lambda row: (-int(row.get("score") or 0), row["id"]))
    clusters: list[list[dict]] = []
    for item in prepared:
        best_index = None
        best_score = -1.0
        for index, cluster in enumerate(clusters):
            similarity = _join_similarity(item, cluster)
            if similarity is None:
                continue
            if similarity > best_score:
                best_index = index
                best_score = similarity
        if best_index is None:
            item["similarity"] = 1.0
            clusters.append([item])
        else:
            item["similarity"] = best_score
            clusters[best_index].append(item)
    return clusters


def _recency_bonus(last_seen: datetime | None, now: datetime) -> int:
    if last_seen is None:
        return 0
    hours = (now - last_seen).total_seconds() / 3600
    if hours <= 24:
        return 15
    if hours <= 72:
        return 8
    if hours <= 24 * 7:
        return 3
    return 0


def _event_score(max_item_score: int, item_count: int, source_count: int, bonus: int) -> int:
    raw = max_item_score * 0.5 + item_count * 8 + source_count * 10 + bonus
    if raw < 0:
        return 0
    if raw > 100:
        return 100
    return int(round(raw))


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat()


def _load_recent(now: datetime) -> list[dict]:
    cutoff = (now - timedelta(days=7)).isoformat()
    conn = connect()
    try:
        rows = conn.execute(
            """
            SELECT id, source_name, title, url, summary, published_at, fetched_at, score
            FROM raw_items
            WHERE COALESCE(published_at, fetched_at) >= ?
            ORDER BY score DESC, id DESC
            """,
            (cutoff,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _existing_event_id(item_ids: list[int]) -> int | None:
    if not item_ids:
        return None
    placeholders = ",".join("?" for _ in item_ids)
    conn = connect()
    try:
        row = conn.execute(
            f"""
            SELECT event_id, COUNT(*) AS n
            FROM event_items
            WHERE item_id IN ({placeholders})
            GROUP BY event_id
            ORDER BY n DESC, event_id ASC
            LIMIT 1
            """,
            item_ids,
        ).fetchone()
        if row is None:
            return None
        return int(row["event_id"])
    finally:
        conn.close()


def _save_cluster(cluster: list[dict], now: datetime) -> tuple[bool, int]:
    ranked = sorted(cluster, key=lambda row: (-int(row.get("score") or 0), row["id"]))
    lead = ranked[0]
    seen_times = [row["seen"] for row in cluster if row.get("seen")]
    first_seen = min(seen_times) if seen_times else None
    last_seen = max(seen_times) if seen_times else None
    sources = {row.get("source_name") or "" for row in cluster if row.get("source_name")}
    item_count = len(cluster)
    source_count = len(sources)
    max_item_score = int(lead.get("score") or 0)
    bonus = _recency_bonus(last_seen, now)
    score = _event_score(max_item_score, item_count, source_count, bonus)
    primary = lead.get("primary") or ""
    summary = (
        f"这个事件由 {item_count} 条资讯组成，涉及 {primary or '未识别关键词'}，"
        f"来源数 {source_count}，最高单条分数 {max_item_score}。"
    )
    reason = (
        f"max_item_score({max_item_score})*0.5"
        f" + item_count({item_count})*8"
        f" + source_count({source_count})*10"
        f" + recency_bonus({bonus})"
    )
    now_text = now.isoformat()
    item_ids = [int(row["id"]) for row in cluster]
    event_id = _existing_event_id(item_ids)
    created = event_id is None
    conn = connect()
    try:
        if created:
            cur = conn.execute(
                """
                INSERT INTO events (
                    title, summary, primary_keyword, source_count, item_count,
                    max_item_score, event_score, first_seen_at, last_seen_at,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lead.get("title") or "",
                    summary,
                    primary,
                    source_count,
                    item_count,
                    max_item_score,
                    score,
                    _iso(first_seen),
                    _iso(last_seen),
                    "open",
                    now_text,
                    now_text,
                ),
            )
            event_id = int(cur.lastrowid)
        else:
            conn.execute(
                """
                UPDATE events
                SET title = ?, summary = ?, primary_keyword = ?, source_count = ?,
                    item_count = ?, max_item_score = ?, event_score = ?,
                    first_seen_at = ?, last_seen_at = ?, status = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    lead.get("title") or "",
                    summary,
                    primary,
                    source_count,
                    item_count,
                    max_item_score,
                    score,
                    _iso(first_seen),
                    _iso(last_seen),
                    "open",
                    now_text,
                    event_id,
                ),
            )
        linked = 0
        for row in cluster:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO event_items (event_id, item_id, similarity_score, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (event_id, int(row["id"]), float(row.get("similarity") or 0), now_text),
            )
            linked += cur.rowcount
        conn.execute(
            """
            INSERT INTO event_scores (event_id, score, reason, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (event_id, score, reason, now_text),
        )
        conn.commit()
        return created, linked
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def build_events() -> dict:
    now = datetime.now(timezone.utc)
    created = 0
    updated = 0
    linked = 0
    errors: list[str] = []
    try:
        clusters = cluster_items(_load_recent(now))
    except Exception as exc:
        return {
            "events_created": 0,
            "events_updated": 0,
            "linked_items": 0,
            "errors": [str(exc)],
        }
    for cluster in clusters:
        try:
            is_new, linked_count = _save_cluster(cluster, now)
            if is_new:
                created += 1
            else:
                updated += 1
            linked += linked_count
        except Exception as exc:
            errors.append(str(exc))
    return {
        "events_created": created,
        "events_updated": updated,
        "linked_items": linked,
        "errors": errors,
    }


def list_events(limit: int) -> list[dict]:
    conn = connect()
    try:
        rows = conn.execute(
            """
            SELECT id, title, summary, primary_keyword, item_count, source_count,
                   event_score, first_seen_at, last_seen_at
            FROM events
            ORDER BY event_score DESC, last_seen_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_event(event_id: int) -> dict | None:
    conn = connect()
    try:
        row = conn.execute(
            """
            SELECT id, title, summary, primary_keyword, item_count, source_count,
                   event_score, first_seen_at, last_seen_at
            FROM events
            WHERE id = ?
            """,
            (event_id,),
        ).fetchone()
        if row is None:
            return None
        event = dict(row)
        items = conn.execute(
            """
            SELECT r.id, r.title, r.source_name, r.score, r.url, r.published_at, r.summary
            FROM event_items ei
            JOIN raw_items r ON r.id = ei.item_id
            WHERE ei.event_id = ?
            ORDER BY r.score DESC, r.id DESC
            """,
            (event_id,),
        ).fetchall()
        event["items"] = [dict(item) for item in items]
        return event
    finally:
        conn.close()


def get_event_analysis(event_id: int) -> dict | None:
    conn = connect()
    try:
        row = conn.execute(
            """
            SELECT id, event_id, model, analysis, analysis_type, elapsed_seconds, created_at
            FROM event_analysis
            WHERE event_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (event_id,),
        ).fetchone()
        if row is None:
            return None
        return dict(row)
    finally:
        conn.close()


def save_event_analysis(
    event_id: int,
    model: str,
    analysis: str,
    elapsed_seconds: int,
) -> dict:
    created_at = datetime.now(timezone.utc).isoformat()
    conn = connect()
    try:
        cur = conn.execute(
            """
            INSERT INTO event_analysis (
                event_id, model, analysis, analysis_type, elapsed_seconds, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (event_id, model, analysis, "manual", elapsed_seconds, created_at),
        )
        conn.commit()
        return {
            "id": cur.lastrowid,
            "event_id": event_id,
            "model": model,
            "analysis": analysis,
            "analysis_type": "manual",
            "elapsed_seconds": elapsed_seconds,
            "created_at": created_at,
        }
    finally:
        conn.close()


def event_prompt(event: dict) -> str:
    lines = [
        f"event title: {event.get('title') or ''}",
        f"event summary: {event.get('summary') or ''}",
        f"primary_keyword: {event.get('primary_keyword') or ''}",
        f"item_count: {event.get('item_count') or 0}",
        f"source_count: {event.get('source_count') or 0}",
        "top items:",
    ]
    for item in (event.get("items") or [])[:8]:
        title = (item.get("title") or "")[:200]
        summary = (item.get("summary") or "")[:300]
        lines.append(f"- {title}")
        if summary:
            lines.append(f"  summary: {summary}")
    return "\n".join(lines)
