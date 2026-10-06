import json
import re
from datetime import datetime, timezone
from html import unescape
from urllib.parse import urlparse

import httpx

from app.crawler import USER_AGENT, _build_item, _fetch_hn, _fetch_rss
from app.db import connect, init_db, insert_item
from app.keywords import get_keyword_cluster
from app.opportunities import create_opportunity_from_keyword

_REPO = re.compile(r'href="(/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)"')
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_SKIP_REPOS = {
    "features", "topics", "collections", "events", "sponsors", "login", "signup",
    "settings", "explore", "trending", "marketplace", "codespaces", "issues",
    "pulls", "notifications", "new", "organizations", "users", "apps", "about",
    "pricing", "customer-stories", "readme", "security", "site", "orgs",
}
_TOPICS = ("AI video", "API tools", "SEO tools", "AI agent", "payment", "developer tools")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _host(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    parsed = urlparse(text if "://" in text else f"https://{text}")
    return (parsed.hostname or "").lower().removeprefix("www.")


def _sample(host: str) -> bool:
    return host in {"example.com", "test.com"} or host.endswith(".example.com") or host.endswith(".test.com")


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    return exc.__class__.__name__[:160]


def _public_error(message: str) -> str:
    text = (message or "").replace("\n", " ")[:160]
    lowered = text.lower()
    if "sk-" in lowered or "aiza" in lowered or "api_key" in lowered or "bearer " in lowered:
        return "请求失败"
    return text


def _kind(source_type: str, name: str, url: str) -> str:
    blob = f"{source_type} {name} {url}".lower()
    if "hacker-news" in blob or source_type in {"hn", "hacker_news"} or name.lower() == "hacker news":
        return "hn"
    if source_type == "github" or "github.com/trending" in blob:
        return "github"
    if source_type == "website":
        return "website"
    if source_type in {"rss", "news", "product_hunt"} or url.lower().endswith((".xml", ".rss")) or "feed" in url.lower():
        return "rss"
    return ""


def collect_targets() -> list[dict]:
    conn = connect()
    try:
        news = conn.execute(
            "SELECT name, type, url, weight FROM sources WHERE enabled = 1 ORDER BY id"
        ).fetchall()
        ledger = conn.execute(
            """
            SELECT name, source_type, url
            FROM data_sources
            WHERE enabled = 1 AND TRIM(COALESCE(url, '')) != ''
            ORDER BY id
            """
        ).fetchall()
    finally:
        conn.close()
    targets = []
    seen = set()
    for row in news:
        url = (row["url"] or "").strip()
        if not url.startswith("http") or url in seen:
            continue
        targets.append({"name": row["name"], "kind": row["type"], "url": url, "weight": int(row["weight"] or 1)})
        seen.add(url)
    for row in ledger:
        url = (row["url"] or "").strip()
        kind = _kind(row["source_type"] or "", row["name"] or "", url)
        if not kind or not url.startswith("http") or url in seen:
            continue
        if kind == "serp" or (row["source_type"] or "") == "serp":
            continue
        targets.append({"name": row["name"], "kind": kind, "url": url, "weight": 2})
        seen.add(url)
    return targets


def _record_run(name: str, status: str, count: int, error: str) -> None:
    conn = connect()
    try:
        conn.execute(
            """
            INSERT INTO source_runs (source_name, last_run_at, last_status, records_collected, error_message)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(source_name) DO UPDATE SET
                last_run_at = excluded.last_run_at,
                last_status = excluded.last_status,
                records_collected = excluded.records_collected,
                error_message = excluded.error_message
            """,
            (name, _now(), status, count, error[:300]),
        )
        conn.commit()
    finally:
        conn.close()


def _classify(source_name: str, title: str) -> tuple[str, str]:
    blob = f"{source_name} {title}".lower()
    if "product hunt" in source_name.lower():
        return "launch", "launch"
    if any(token in blob for token in ("funding", "raises", "raised", "series a", "series b", "seed round")):
        return "funding", "funding"
    if any(token in blob for token in ("launch", "launched", "introducing", "releases", "released")):
        return "launch", "launch"
    if any(token in blob for token in ("product", "tool", "app")):
        return "product", "product"
    return "news", "news"


def _why(feed_type: str, domain: str, title: str, source_name: str) -> str:
    label = domain or title or source_name
    if feed_type == "launch":
        return f"{label} launched, possible To C page pattern."
    if feed_type == "funding":
        return f"{label} has funding news, commercial activity."
    if feed_type == "product":
        return f"{label} is a product mention, worth a page teardown."
    if feed_type == "payment":
        return f"{label} has payment traffic, commercial proof."
    if feed_type == "traffic":
        return f"{label} traffic is growing."
    if feed_type == "authority":
        return f"{label} SEO authority is rising."
    if feed_type == "serp":
        return f"{label} appeared in SERP results."
    if feed_type == "crawl":
        return f"{label} has a public page worth reading."
    return f"{label} appeared in {source_name}."


def _add_feed(feed_type: str, title: str, domain: str, url: str, source_name: str, signal: str, why: str, keyword: str, created_at: str) -> None:
    key = f"{signal}|{url or domain}|{title[:80]}"
    conn = connect()
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO intelligence_feed (
                feed_type, title, domain, url, source_name, signal, why_it_matters,
                related_keyword, related_opportunity_id, created_at, dedupe_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
            """,
            (feed_type, title[:300], domain, url, source_name, signal, why[:400], keyword[:120], created_at, key),
        )
        conn.commit()
    finally:
        conn.close()


def _store_item(source_name: str, source_type: str, item: dict) -> bool:
    domain = _host(item.get("url") or "")
    if source_type == "github" and domain == "github.com":
        repo = urlparse(item.get("url") or "").path.strip("/")
        if repo:
            domain = repo
    payload = dict(item)
    payload["source_type"] = source_type
    payload["domain"] = domain
    payload["tags"] = source_type
    payload["raw_json"] = json.dumps(
        {
            "source_name": source_name,
            "source_type": source_type,
            "title": item.get("title") or "",
            "url": item.get("url") or "",
            "domain": domain,
        },
        ensure_ascii=False,
    )
    saved = insert_item(payload)
    if not saved:
        return False
    feed_type, signal = _classify(source_name, item.get("title") or "")
    _add_feed(
        feed_type,
        item.get("title") or "",
        domain,
        item.get("url") or "",
        source_name,
        signal,
        _why(feed_type, domain, item.get("title") or "", source_name),
        "",
        item.get("fetched_at") or _now(),
    )
    return True


async def _fetch_github(client: httpx.AsyncClient, source: dict) -> tuple[list[dict], list[str]]:
    name = source["name"]
    try:
        response = await client.get(source["url"])
        response.raise_for_status()
        html = response.text
    except Exception as exc:
        return [], [_safe_error(exc)]
    found = []
    seen = set()
    for match in _REPO.finditer(html):
        path = match.group(1).strip("/")
        owner, _, repo = path.partition("/")
        if not repo or owner.lower() in _SKIP_REPOS or repo.lower() in _SKIP_REPOS:
            continue
        if path in seen:
            continue
        seen.add(path)
        found.append(path)
        if len(found) >= 15:
            break
    if not found:
        return [], ["无条目"]
    fetched_at = _now()
    items = []
    for path in found:
        item = _build_item(name, path, f"https://github.com/{path}", "GitHub trending repository", "GitHub", None, int(source.get("weight") or 2), None, fetched_at)
        if item:
            items.append(item)
    return items, []


async def _fetch_website(client: httpx.AsyncClient, source: dict) -> tuple[list[dict], list[str]]:
    name = source["name"]
    try:
        response = await client.get(source["url"])
        response.raise_for_status()
        match = _TITLE.search(response.text or "")
        title = re.sub(r"\s+", " ", match.group(1)).strip() if match else name
    except Exception as exc:
        return [], [_safe_error(exc)]
    fetched_at = _now()
    item = _build_item(name, title[:180], source["url"], "", "", None, int(source.get("weight") or 1), None, fetched_at)
    return ([item] if item else []), []


async def _fetch_one(client: httpx.AsyncClient, source: dict):
    kind = source["kind"]
    adapted = {"name": source["name"], "url": source["url"], "weight": source.get("weight") or 1, "type": kind}
    if kind == "hn":
        return await _fetch_hn(client, adapted)
    if kind == "github":
        return await _fetch_github(client, adapted)
    if kind == "website":
        return await _fetch_website(client, adapted)
    return await _fetch_rss(client, adapted)


def _top_signal(titles: list[str]) -> str:
    counts = []
    for topic in _TOPICS:
        token = topic.lower()
        count = sum(1 for title in titles if token.split()[0] in title.lower() and (len(token.split()) == 1 or token in title.lower() or token.split()[-1] in title.lower()))
        if count:
            counts.append((count, topic))
    counts.sort(reverse=True)
    if not counts:
        return ""
    return " / ".join(topic for _count, topic in counts[:3])


def _local_rows(conn, record_type: str, limit: int = 6) -> list:
    month = conn.execute(
        """
        SELECT MAX(time_range) AS month
        FROM raw_source_records
        WHERE lower(COALESCE(status, '')) IN ('imported', 'confirmed')
          AND record_type = ?
          AND time_range GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]'
        """,
        (record_type,),
    ).fetchone()["month"]
    if not month:
        return conn.execute(
            """
            SELECT record_type, normalized_domain, normalized_title, normalized_url, time_range, created_at,
                   json_extract(raw_json, '$.payment_traffic') AS payment_traffic,
                   json_extract(raw_json, '$.traffic_growth') AS traffic_growth,
                   json_extract(raw_json, '$.dr_growth') AS dr_growth,
                   json_extract(raw_json, '$.rank') AS rank
            FROM raw_source_records
            WHERE lower(COALESCE(status, '')) IN ('imported', 'confirmed')
              AND record_type = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (record_type, limit),
        ).fetchall()
    return conn.execute(
        """
        SELECT record_type, normalized_domain, normalized_title, normalized_url, time_range, created_at,
               json_extract(raw_json, '$.payment_traffic') AS payment_traffic,
               json_extract(raw_json, '$.traffic_growth') AS traffic_growth,
               json_extract(raw_json, '$.dr_growth') AS dr_growth,
               json_extract(raw_json, '$.rank') AS rank
        FROM raw_source_records
        WHERE lower(COALESCE(status, '')) IN ('imported', 'confirmed')
          AND record_type = ?
          AND time_range = ?
        ORDER BY CAST(json_extract(raw_json, '$.rank') AS REAL) ASC
        LIMIT ?
        """,
        (record_type, month, limit),
    ).fetchall()


def sync_local_feed() -> None:
    conn = connect()
    try:
        rows = []
        for record_type in ("payment_signal", "traffic_signal", "authority_signal", "serp_result", "crawl_signal"):
            rows.extend(_local_rows(conn, record_type))
    finally:
        conn.close()
    labels = {
        "payment_signal": ("payment", "Stripe", "payment"),
        "traffic_signal": ("traffic", "Traffic", "traffic"),
        "authority_signal": ("authority", "DR", "authority"),
        "serp_result": ("serp", "SERP", "serp"),
        "crawl_signal": ("crawl", "Crawl", "crawl"),
    }
    for row in rows:
        kind = row["record_type"]
        domain = _host(row["normalized_domain"] or row["normalized_url"] or "")
        if not domain or _sample(domain):
            continue
        feed_type, source_name, signal = labels[kind]
        month = row["time_range"] or ""
        if kind == "payment_signal":
            title = f"{domain} appeared in Stripe Payment Ranking {month}".strip()
            why = f"{domain} has payment traffic {row['payment_traffic'] or '--'}, commercial proof."
        elif kind == "traffic_signal":
            title = f"{domain} traffic growth {row['traffic_growth'] or '--'}"
            why = f"{domain} traffic is growing ({row['traffic_growth'] or '--'} in {month or '--'})."
        elif kind == "authority_signal":
            growth = row["dr_growth"] or "--"
            title = f"{domain} DR {growth} this month"
            shown = growth if str(growth).startswith(("+", "-")) or growth == "--" else f"+{growth}"
            why = f"{domain} DR {shown} in {month}, SEO authority rising."
        elif kind == "serp_result":
            title = row["normalized_title"] or domain
            why = _why("serp", domain, title, "SERP")
        else:
            title = row["normalized_title"] or domain
            why = _why("crawl", domain, title, "Crawl")
        _add_feed(feed_type, title, domain, row["normalized_url"] or "", source_name, signal, why, "", row["created_at"] or _now())


def backfill_item_feed() -> None:
    conn = connect()
    try:
        rows = conn.execute(
            """
            SELECT source_name, source_type, title, url, domain, fetched_at
            FROM raw_items
            ORDER BY id DESC
            LIMIT 400
            """
        ).fetchall()
    finally:
        conn.close()
    for row in rows:
        source_name = row["source_name"] or ""
        domain = row["domain"] or _host(row["url"] or "")
        if (row["source_type"] or "") == "github" and domain == "github.com":
            repo = urlparse(row["url"] or "").path.strip("/")
            if repo:
                domain = repo
        if _sample(domain):
            continue
        feed_type, signal = _classify(source_name, row["title"] or "")
        _add_feed(
            feed_type,
            row["title"] or "",
            domain,
            row["url"] or "",
            source_name,
            signal,
            _why(feed_type, domain, row["title"] or "", source_name),
            "",
            row["fetched_at"] or _now(),
        )


async def collect_now() -> dict:
    init_db()
    sync_local_feed()
    targets = collect_targets()
    inserted = 0
    skipped = 0
    errors = []
    titles = []
    timeout = httpx.Timeout(20.0, connect=10.0)
    headers = {"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/xml, application/json, text/html, */*"}
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
        for source in targets:
            try:
                items, source_errors = await _fetch_one(client, source)
            except Exception as exc:
                message = _safe_error(exc)
                errors.append({"source_name": source["name"], "status": "failed", "error_message": message})
                _record_run(source["name"], "failed", 0, message)
                continue
            if source_errors and not items:
                message = _public_error(str(source_errors[0]))
                errors.append({"source_name": source["name"], "status": "failed", "error_message": message, "last_run_at": _now()})
                _record_run(source["name"], "failed", 0, message)
                continue
            added = 0
            for item in items:
                if _store_item(source["name"], source["kind"], item):
                    inserted += 1
                    added += 1
                    titles.append(item.get("title") or "")
                else:
                    skipped += 1
            status = "partial" if source_errors else "ok"
            note = "" if not source_errors else _public_error(str(source_errors[0]))
            _record_run(source["name"], status, added, note)
            if source_errors:
                errors.append({"source_name": source["name"], "status": status, "error_message": note, "last_run_at": _now()})
    top = _top_signal(titles)
    finished = _now()
    conn = connect()
    try:
        conn.execute(
            """
            INSERT INTO collect_runs (finished_at, sources_checked, new_items, error_count, top_signal, errors_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (finished, len(targets), inserted, len(errors), top, json.dumps(errors, ensure_ascii=False)[:4000]),
        )
        conn.commit()
    finally:
        conn.close()
    return {
        "inserted": inserted,
        "skipped": skipped,
        "sources_checked": len(targets),
        "new_items": inserted,
        "errors": errors,
        "top_signal": top,
        "finished_at": finished,
    }


async def run_source(source_id: int) -> dict:
    from app.ledger import get_source

    source = get_source(source_id)
    if source is None:
        raise ValueError("数据源不存在")
    if not source.get("enabled"):
        raise ValueError("来源已停用")
    url = (source.get("url") or "").strip()
    kind = _kind(source.get("source_type") or "", source.get("name") or "", url)
    if (source.get("source_type") or "") == "serp" or kind == "serp":
        raise ValueError("SERP 只在明确搜索时调用")
    if not kind or not url.startswith("http"):
        raise ValueError("这个来源没有可采集的 URL")
    result = await collect_source({"name": source["name"], "kind": kind, "url": url, "weight": 2})
    return result


async def collect_source(source: dict) -> dict:
    timeout = httpx.Timeout(20.0, connect=10.0)
    headers = {"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/xml, application/json, text/html, */*"}
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
        try:
            items, source_errors = await _fetch_one(client, source)
        except Exception as exc:
            message = _safe_error(exc)
            _record_run(source["name"], "failed", 0, message)
            return {"source_name": source["name"], "status": "failed", "records_collected": 0, "error_message": message, "last_run_at": _now()}
    added = 0
    for item in items:
        if _store_item(source["name"], source["kind"], item):
            added += 1
    message = "" if not source_errors else str(source_errors[0])[:160]
    status = "failed" if source_errors and not items else "partial" if source_errors else "ok"
    _record_run(source["name"], status, added, message)
    return {
        "source_name": source["name"],
        "status": status,
        "records_collected": added,
        "error_message": message,
        "last_run_at": _now(),
    }


def collect_status() -> dict:
    conn = connect()
    try:
        row = conn.execute(
            """
            SELECT finished_at, sources_checked, new_items, error_count, top_signal
            FROM collect_runs
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return {"finished_at": "", "sources_checked": 0, "new_items": 0, "error_count": 0, "top_signal": ""}
    return {
        "finished_at": row["finished_at"] or "",
        "sources_checked": int(row["sources_checked"] or 0),
        "new_items": int(row["new_items"] or 0),
        "error_count": int(row["error_count"] or 0),
        "top_signal": row["top_signal"] or "",
    }


def _diverse(rows, limit: int) -> list:
    buckets: dict[str, list] = {}
    for row in rows:
        buckets.setdefault(row["source_name"] or "unknown", []).append(row)
    picked = []
    while len(picked) < limit and any(buckets.values()):
        for name in list(buckets):
            group = buckets[name]
            if not group:
                continue
            picked.append(group.pop(0))
            if len(picked) >= limit:
                break
    return picked


def list_feed(limit: int = 20) -> dict:
    sync_local_feed()
    backfill_item_feed()
    size = max(1, min(int(limit or 20), 100))
    conn = connect()
    try:
        names = conn.execute(
            "SELECT DISTINCT source_name FROM intelligence_feed ORDER BY source_name"
        ).fetchall()
        rows = []
        for name in names:
            rows.extend(
                conn.execute(
                    """
                    SELECT id, feed_type, title, domain, url, source_name, signal, why_it_matters,
                           related_keyword, related_opportunity_id, created_at
                    FROM intelligence_feed
                    WHERE source_name = ?
                    ORDER BY id DESC
                    LIMIT 4
                    """,
                    (name["source_name"],),
                ).fetchall()
            )
    finally:
        conn.close()
    items = []
    for row in _diverse(rows, size):
        items.append(
            {
                "id": int(row["id"]),
                "feed_type": row["feed_type"] or "",
                "title": unescape(row["title"] or ""),
                "domain": row["domain"] or "",
                "url": row["url"] or "",
                "source": row["source_name"] or "",
                "source_name": row["source_name"] or "",
                "signal": row["signal"] or "",
                "why": row["why_it_matters"] or "",
                "why_it_matters": row["why_it_matters"] or "",
                "related_keyword": row["related_keyword"] or "",
                "related_opportunity_id": row["related_opportunity_id"],
                "time": row["created_at"] or "",
                "created_at": row["created_at"] or "",
            }
        )
    return {"items": items}


def top_rankings(limit: int = 10) -> dict:
    size = max(1, min(int(limit or 10), 20))
    conn = connect()
    try:
        rows = conn.execute(
            """
            SELECT record_type, normalized_domain, normalized_title, time_range,
                   json_extract(raw_json, '$.rank') AS rank,
                   json_extract(raw_json, '$.payment_traffic') AS payment_traffic,
                   json_extract(raw_json, '$.traffic_growth') AS traffic_growth,
                   json_extract(raw_json, '$.current_traffic') AS current_traffic,
                   json_extract(raw_json, '$.dr_growth') AS dr_growth,
                   json_extract(raw_json, '$.current_dr') AS current_dr
            FROM raw_source_records
            WHERE lower(COALESCE(status, '')) IN ('imported', 'confirmed')
              AND record_type IN ('payment_signal', 'traffic_signal', 'authority_signal')
              AND time_range GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]'
            """
        ).fetchall()
    finally:
        conn.close()
    latest = {}
    for row in rows:
        month = row["time_range"] or ""
        if month > latest.get(row["record_type"], ""):
            latest[row["record_type"]] = month
    grouped = {"payment_signal": [], "traffic_signal": [], "authority_signal": []}
    for row in rows:
        if row["time_range"] != latest.get(row["record_type"]):
            continue
        domain = _host(row["normalized_domain"] or "")
        if not domain or _sample(domain):
            continue
        try:
            rank = int(float(row["rank"]))
        except (TypeError, ValueError):
            continue
        if rank <= 0 or rank > size:
            continue
        metric = {
            "payment_signal": row["payment_traffic"],
            "traffic_signal": row["traffic_growth"] or row["current_traffic"],
            "authority_signal": row["dr_growth"] or row["current_dr"],
        }[row["record_type"]]
        grouped[row["record_type"]].append(
            {
                "domain": domain,
                "title": row["normalized_title"] or "",
                "rank": rank,
                "period_month": row["time_range"] or "",
                "metric": str(metric or ""),
            }
        )
    for key in grouped:
        grouped[key].sort(key=lambda item: item["rank"])
        grouped[key] = grouped[key][:size]
    return {"payment": grouped["payment_signal"], "traffic": grouped["traffic_signal"], "authority": grouped["authority_signal"]}


def _ensure_cluster(name: str) -> int:
    label = " ".join((name or "").split())[:80] or "feed keyword"
    conn = connect()
    try:
        found = conn.execute("SELECT id FROM keyword_clusters WHERE name = ? ORDER BY id ASC LIMIT 1", (label,)).fetchone()
        if found is not None:
            return int(found["id"])
        now = _now()
        cur = conn.execute(
            """
            INSERT INTO keyword_clusters (
                name, category, search_intent, page_type, priority, status,
                score, notes, created_at, updated_at
            ) VALUES (?, 'feed', 'commercial', 'landing', 3, 'open', 0, 'from intelligence feed', ?, ?)
            """,
            (label, now, now),
        )
        cluster_id = int(cur.lastrowid)
        conn.execute(
            """
            INSERT OR IGNORE INTO keyword_items (
                cluster_id, keyword, intent, difficulty, source, status, created_at
            ) VALUES (?, ?, 'commercial', '', 'feed', 'open', ?)
            """,
            (cluster_id, label, now),
        )
        conn.commit()
        return cluster_id
    finally:
        conn.close()


def _feed_row(feed_id: int):
    conn = connect()
    try:
        return conn.execute("SELECT * FROM intelligence_feed WHERE id = ?", (feed_id,)).fetchone()
    finally:
        conn.close()


def apply_feed_action(feed_id: int, action: str) -> dict:
    row = _feed_row(feed_id)
    if row is None:
        raise ValueError("资讯不存在")
    action = (action or "").strip()
    domain = row["domain"] or ""
    title = row["title"] or domain or "feed item"
    url = row["url"] or ""
    if action == "keyword":
        cluster_id = _ensure_cluster(domain or title)
        return {"ok": True, "message": "已加入关键词池", "cluster_id": cluster_id}
    if action == "opportunity":
        cluster_id = _ensure_cluster(domain or title)
        card = create_opportunity_from_keyword(cluster_id)
        if card is None:
            raise ValueError("机会卡生成失败")
        conn = connect()
        try:
            conn.execute(
                "UPDATE intelligence_feed SET related_opportunity_id = ?, related_keyword = ? WHERE id = ?",
                (int(card["id"]), domain or title, feed_id),
            )
            conn.commit()
        finally:
            conn.close()
        return {"ok": True, "message": "已加入机会", "opportunity_id": int(card["id"])}
    if action == "competitor":
        if not url.startswith("http"):
            raise ValueError("这条资讯没有可打开的 URL")
        from app.competitors import create_competitor

        cluster_id = _ensure_cluster(domain or title)
        if get_keyword_cluster(cluster_id) is None:
            raise ValueError("关键词簇不存在")
        page = create_competitor(
            {
                "cluster_id": cluster_id,
                "url": url,
                "title": title,
                "page_type": "unknown",
                "target_keyword": domain or title,
            }
        )
        if page is None:
            raise ValueError("竞品页生成失败")
        return {"ok": True, "message": "已转成竞品页", "competitor_id": int(page["id"])}
    if action == "crawl":
        if not url.startswith("http"):
            raise ValueError("这条资讯没有可抓取的 URL")
        from app.intake import run_crawl

        result = run_crawl(url, domain, title, "landing_page")
        return {"ok": True, "message": "已抓取公开页面", "status": result.get("status") or ""}
    raise ValueError("不支持的操作")


def source_records(source_id: int, limit: int = 20) -> list[dict]:
    from app.ledger import get_source

    source = get_source(source_id)
    if source is None:
        raise ValueError("数据源不存在")
    conn = connect()
    try:
        rows = conn.execute(
            """
            SELECT id, source_name, title, url, domain, published_at, fetched_at, status
            FROM raw_items
            WHERE source_name = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (source["name"], max(1, min(limit, 50))),
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]
