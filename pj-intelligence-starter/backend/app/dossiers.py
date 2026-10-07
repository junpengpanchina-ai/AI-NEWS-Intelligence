import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from app.db import connect, init_db, project_root

STATUSES = {"watch", "research", "priority_research", "validation_needed", "teardown", "build_candidate", "rejected"}
EVIDENCE_TYPES = {
    "news", "chat_note", "screenshot", "traffic", "payment", "authority", "serp",
    "competitor_page", "crawl", "gsc", "ga4", "manual_note", "trend",
}
_POINTS = {
    "trend": 15,
    "payment": 25,
    "traffic": 20,
    "authority": 15,
    "serp": 15,
    "competitor": 10,
    "validation": 20,
    "manual": 5,
}
_GROUPS = {
    "trend": {"trend"},
    "payment": {"payment"},
    "traffic": {"traffic"},
    "authority": {"authority"},
    "serp": {"serp"},
    "competitor": {"competitor_page"},
    "validation": {"gsc", "ga4", "validation"},
    "manual": {"manual_note", "chat_note"},
    "crawl": {"crawl"},
}
_SIGNAL_TYPE = {
    "payment": "payment",
    "traffic": "traffic",
    "authority": "authority",
    "serp": "serp",
    "crawl": "crawl",
    "launch": "news",
    "funding": "news",
    "product": "news",
    "competitor": "competitor_page",
}
_RECORD_TYPE = {
    "payment_signal": ("payment", "Stripe Ranking", "payment_traffic"),
    "traffic_signal": ("traffic", "Traffic Ranking", "traffic_growth"),
    "authority_signal": ("authority", "DR Ranking", "dr_growth"),
    "serp_result": ("serp", "Serper", "rank"),
    "crawl_signal": ("crawl", "Crawl", ""),
    "trend_signal": ("trend", "Google Trends", "search_volume"),
    "validation_signal": ("validation", "Validation", ""),
}
_SUMMARY = (
    ("payment", "Payment Evidence"),
    ("traffic", "Traffic Evidence"),
    ("authority", "Authority Evidence"),
    ("serp", "SERP Evidence"),
    ("competitor", "Competitor Evidence"),
    ("validation", "Validation Evidence"),
)
_MISSING = {
    "serp": "没有 SERP Top 10",
    "competitor": "没有真实竞品页面",
    "payment": "没有 payment signal",
    "traffic": "没有 traffic signal",
    "authority": "没有 authority signal",
    "validation": "没有 validation signal",
    "pricing": "没有价格页",
    "conversion": "没有转化路径",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _host(value: str) -> str:
    text = (value or "").strip().lower()
    if not text:
        return ""
    parsed = urlparse(text if "://" in text else f"https://{text}")
    return (parsed.hostname or text.split("/")[0]).removeprefix("www.")


def _loads(value: str, fallback):
    try:
        parsed = json.loads(value or "")
    except (TypeError, ValueError):
        return fallback
    return parsed if isinstance(parsed, type(fallback)) else fallback


def _public(message: str) -> str:
    text = (message or "").replace("\n", " ")[:180]
    lowered = text.lower()
    if "sk-" in lowered or "aiza" in lowered or "api_key" in lowered or "bearer " in lowered or "x-api-key" in lowered:
        return "请求失败"
    return text


def _find(domain: str):
    host = _host(domain)
    if not host:
        return None
    conn = connect()
    try:
        return conn.execute("SELECT * FROM intelligence_dossiers WHERE domain = ?", (host,)).fetchone()
    finally:
        conn.close()


def _evidence_rows(dossier_id: int) -> list:
    conn = connect()
    try:
        return conn.execute(
            """
            SELECT * FROM dossier_evidence_items
            WHERE dossier_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (dossier_id,),
        ).fetchall()
    finally:
        conn.close()


def _present(rows) -> dict[str, bool]:
    types = {row["evidence_type"] or "" for row in rows}
    return {name: bool(types & group) for name, group in _GROUPS.items()}


def _score_of(flags: dict[str, bool]) -> tuple[int, dict[str, int]]:
    parts = {name: _POINTS[name] if flags.get(name) else 0 for name in _POINTS}
    total = sum(parts.values())
    if not flags.get("payment") and not flags.get("traffic"):
        total -= 20
    if not flags.get("validation") and not flags.get("crawl"):
        total -= 15
    return max(0, min(total, 100)), parts


def _priority(score: int) -> str:
    if score >= 85:
        return "P0"
    if score >= 70:
        return "P1"
    if score >= 50:
        return "P2"
    return "P3"


def _stated_confidence(rows, score: int) -> str:
    for row in reversed(rows):
        text = (row["confidence"] or "").strip().lower()
        if text in {"high", "medium", "low"}:
            return text.capitalize()
    return _confidence(score)


def _confidence(score: int) -> str:
    if score >= 85:
        return "High"
    if score >= 50:
        return "Medium"
    return "Low"


def _auto_status(score: int, flags: dict[str, bool]) -> str:
    market = sum(1 for name in ("payment", "traffic", "authority") if flags.get(name))
    if score >= 85 and market >= 2:
        return "build_candidate"
    if score >= 70:
        return "validation_needed" if not flags.get("validation") else "research"
    return "watch"


def _missing(flags: dict[str, bool]) -> list[str]:
    gaps = []
    if not flags.get("serp"):
        gaps.append(_MISSING["serp"])
    if not flags.get("competitor"):
        gaps.append(_MISSING["competitor"])
        gaps.append(_MISSING["pricing"])
        gaps.append(_MISSING["conversion"])
    if not flags.get("payment"):
        gaps.append(_MISSING["payment"])
    if not flags.get("traffic"):
        gaps.append(_MISSING["traffic"])
    if not flags.get("authority"):
        gaps.append(_MISSING["authority"])
    if not flags.get("validation"):
        gaps.append(_MISSING["validation"])
    return gaps


def _next_actions(flags: dict[str, bool]) -> list[str]:
    actions = []
    if not flags.get("serp"):
        actions.append("Run SERP")
    if not flags.get("competitor"):
        actions.append("Crawl Domain")
        actions.append("Add Competitor Page")
    if not flags.get("manual"):
        actions.append("Add Manual Note")
    if not flags.get("screenshot"):
        actions.append("Upload Screenshot")
    if not actions:
        actions.append("Mark as Priority Research")
    return actions


def _judgment(domain: str, flags: dict[str, bool], note: str) -> str:
    text = " ".join((note or "").split())
    if text:
        return text[:240]
    labels = [name for name in ("payment", "traffic", "authority", "serp", "competitor") if flags.get(name)]
    if labels:
        return f"{domain} has {', '.join(labels)} evidence. Worth a closer page teardown. Not a formal Build."
    return f"{domain} is a new lead. Evidence is still thin."


def _tags(flags: dict[str, bool], rows) -> list[str]:
    labels = {
        "payment": "Payment",
        "traffic": "Traffic",
        "authority": "Authority",
        "serp": "SERP",
        "competitor": "Competitor",
        "validation": "Validation",
        "manual": "Manual Note",
        "screenshot": "Screenshot",
    }
    tags = [labels[name] for name in labels if flags.get(name)]
    if any((row["evidence_type"] or "") == "news" for row in rows):
        tags.append("News")
    if any((row["evidence_type"] or "") in {"launch"} for row in rows):
        tags.append("Launch")
    return tags


def recompute(dossier_id: int, note: str = "") -> None:
    conn = connect()
    try:
        dossier = conn.execute("SELECT * FROM intelligence_dossiers WHERE id = ?", (dossier_id,)).fetchone()
        if dossier is None:
            return
        rows = conn.execute(
            "SELECT evidence_type, content, confidence FROM dossier_evidence_items WHERE dossier_id = ?",
            (dossier_id,),
        ).fetchall()
        flags = _present(rows)
        score, parts = _score_of(flags)
        status = dossier["opportunity_status"] or "watch"
        if not int(dossier["status_locked"] or 0) and status != "rejected":
            status = _auto_status(score, flags)
        judgment = dossier["one_line_judgment"] or ""
        if note and not judgment:
            judgment = _judgment(dossier["domain"], flags, note)
        elif not judgment:
            judgment = _judgment(dossier["domain"], flags, "")
        confidence = _stated_confidence(rows, score)
        priority = _priority(score)
        missing = json.dumps(_missing(flags), ensure_ascii=False)
        actions = json.dumps(_next_actions(flags), ensure_ascii=False)
        unchanged = (
            (dossier["one_line_judgment"] or "") == judgment
            and (dossier["opportunity_status"] or "") == status
            and (dossier["priority_level"] or "") == priority
            and (dossier["confidence"] or "") == confidence
            and int(dossier["evidence_score"] or 0) == score
            and (dossier["missing_evidence"] or "") == missing
            and (dossier["recommended_next_actions"] or "") == actions
        )
        if unchanged:
            return
        now = _now()
        conn.execute(
            """
            UPDATE intelligence_dossiers SET
                one_line_judgment = ?, opportunity_status = ?, priority_level = ?, confidence = ?,
                evidence_score = ?, payment_score = ?, traffic_score = ?, authority_score = ?,
                serp_score = ?, competitor_score = ?, validation_score = ?,
                missing_evidence = ?, recommended_next_actions = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                judgment,
                status,
                priority,
                confidence,
                score,
                parts["payment"],
                parts["traffic"],
                parts["authority"],
                parts["serp"],
                parts["competitor"],
                parts["validation"],
                missing,
                actions,
                now,
                dossier_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_dossier(domain: str, title: str, judgment: str, category: str) -> tuple[int, bool]:
    host = _host(domain)
    if not host:
        raise ValueError("domain 不能为空")
    existing = _find(host)
    if existing is not None:
        return int(existing["id"]), False
    now = _now()
    product = title.strip() or host.split(".")[0]
    conn = connect()
    try:
        try:
            cur = conn.execute(
            """
            INSERT INTO intelligence_dossiers (
                title, domain, product_name, category, one_line_judgment, opportunity_status,
                priority_level, confidence, evidence_score, payment_score, traffic_score,
                authority_score, serp_score, competitor_score, validation_score,
                missing_evidence, recommended_next_actions, status_locked, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'watch', 'P3', 'Low', 0, 0, 0, 0, 0, 0, 0, '[]', '[]', 0, ?, ?)
            """,
            (title[:180] or host, host, product[:120], (category or "product")[:80], judgment[:240], now, now),
        )
            conn.commit()
            return int(cur.lastrowid), True
        except sqlite3.IntegrityError:
            found = conn.execute("SELECT id FROM intelligence_dossiers WHERE domain = ?", (host,)).fetchone()
            if found is None:
                raise
            return int(found["id"]), False
    finally:
        conn.close()


def _add_item(dossier_id: int, item: dict) -> bool:
    evidence_type = (item.get("evidence_type") or "manual_note").strip()
    if evidence_type not in EVIDENCE_TYPES:
        evidence_type = "manual_note"
    title = (item.get("title") or "")[:300]
    source_url = (item.get("source_url") or "")[:500]
    metric_name = (item.get("metric_name") or "")[:80]
    conn = connect()
    try:
        found = conn.execute(
            """
            SELECT id FROM dossier_evidence_items
            WHERE dossier_id = ? AND evidence_type = ? AND source_url = ? AND title = ? AND metric_name = ?
            """,
            (dossier_id, evidence_type, source_url, title, metric_name),
        ).fetchone()
        if found is not None:
            return False
        conn.execute(
            """
            INSERT INTO dossier_evidence_items (
                dossier_id, evidence_type, source_name, source_url, source_domain, title, content,
                metric_name, metric_value, metric_unit, period_month, screenshot_path, raw_json,
                confidence, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                dossier_id,
                evidence_type,
                (item.get("source_name") or "")[:120],
                source_url,
                _host(item.get("source_domain") or item.get("source_url") or ""),
                title,
                (item.get("content") or "")[:2000],
                metric_name,
                (item.get("metric_value") or "")[:80],
                (item.get("metric_unit") or "")[:40],
                (item.get("period_month") or "")[:20],
                (item.get("screenshot_path") or "")[:300],
                item.get("raw_json") or "",
                (item.get("confidence") or "")[:40],
                item.get("created_at") or _now(),
            ),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def _card(row, rows=None) -> dict:
    evidence = rows if rows is not None else _evidence_rows(int(row["id"]))
    flags = _present(evidence)
    actions = _loads(row["recommended_next_actions"], [])
    return {
        "id": int(row["id"]),
        "title": row["title"] or "",
        "domain": row["domain"] or "",
        "product_name": row["product_name"] or "",
        "category": row["category"] or "",
        "one_line_judgment": row["one_line_judgment"] or "",
        "opportunity_status": row["opportunity_status"] or "watch",
        "priority_level": row["priority_level"] or "P3",
        "confidence": row["confidence"] or "Low",
        "evidence_score": int(row["evidence_score"] or 0),
        "payment_score": int(row["payment_score"] or 0),
        "traffic_score": int(row["traffic_score"] or 0),
        "authority_score": int(row["authority_score"] or 0),
        "serp_score": int(row["serp_score"] or 0),
        "competitor_score": int(row["competitor_score"] or 0),
        "validation_score": int(row["validation_score"] or 0),
        "evidence_tags": _tags(flags, evidence),
        "missing_evidence": _loads(row["missing_evidence"], []),
        "recommended_next_actions": actions,
        "next_action": actions[0] if actions else "",
        "evidence_count": len(evidence),
        "created_at": row["created_at"] or "",
        "updated_at": row["updated_at"] or "",
        "formal_build": False,
    }


def list_dossiers(limit: int = 10) -> dict:
    init_db()
    size = max(1, min(int(limit or 10), 50))
    conn = connect()
    try:
        rows = conn.execute(
            """
            SELECT * FROM intelligence_dossiers
            ORDER BY evidence_score DESC, updated_at DESC, id DESC
            LIMIT ?
            """,
            (size,),
        ).fetchall()
    finally:
        conn.close()
    return {"items": [_card(row) for row in rows]}


def _summary_cards(rows) -> list[dict]:
    cards = []
    for key, label in _SUMMARY:
        group = _GROUPS[key]
        matched = [row for row in rows if (row["evidence_type"] or "") in group]
        latest = ""
        metric = ""
        source = ""
        for row in matched:
            month = row["period_month"] or ""
            if month > latest:
                latest = month
            if row["metric_name"] and not metric:
                metric = f"{row['metric_name']} {row['metric_value']}".strip()
            if row["source_name"] and not source:
                source = row["source_name"]
        status = "Missing"
        if matched and metric:
            status = "Ready"
        elif matched:
            status = "Partial"
        cards.append({
            "name": label,
            "key": key,
            "status": status,
            "count": len(matched),
            "latest_month": latest,
            "metric": metric,
            "source": source,
        })
    return cards


def _timeline(rows) -> list[dict]:
    items = []
    for row in rows:
        items.append({
            "id": int(row["id"]),
            "created_at": row["created_at"] or "",
            "evidence_type": row["evidence_type"] or "",
            "source_name": row["source_name"] or "",
            "source_url": row["source_url"] or "",
            "title": row["title"] or "",
            "content": row["content"] or "",
            "metric_name": row["metric_name"] or "",
            "metric_value": row["metric_value"] or "",
            "metric_unit": row["metric_unit"] or "",
            "period_month": row["period_month"] or "",
            "screenshot_path": row["screenshot_path"] or "",
            "confidence": row["confidence"] or "",
        })
    return items


def _trust(evidence_type: str, source_name: str) -> str:
    if evidence_type in {"payment", "traffic", "authority"}:
        return "high"
    if evidence_type in {"manual_note", "chat_note", "screenshot", "serp", "crawl"}:
        return "medium"
    if "serper" in (source_name or "").lower():
        return "medium"
    return "low"


def _sources(rows) -> list[dict]:
    seen = set()
    items = []
    for row in rows:
        raw = _loads(row["raw_json"], {})
        original = ""
        if isinstance(raw, dict):
            original = str(raw.get("original_file") or raw.get("original_filename") or "")
        key = (row["source_name"] or "", row["source_url"] or "", row["evidence_type"] or "")
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "source_name": row["source_name"] or "",
            "source_type": row["evidence_type"] or "",
            "trust_level": _trust(row["evidence_type"] or "", row["source_name"] or ""),
            "captured_at": row["created_at"] or "",
            "original_file": original,
            "original_url": row["source_url"] or "",
        })
    return items


def get_dossier(dossier_id: int) -> dict | None:
    init_db()
    recompute(dossier_id)
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM intelligence_dossiers WHERE id = ?", (dossier_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    evidence = _evidence_rows(dossier_id)
    flags = _present(evidence)
    card = _card(row, evidence)
    return {
        "dossier": card,
        "summary": _summary_cards(evidence),
        "timeline": _timeline(evidence),
        "sources": _sources(evidence),
        "missing_evidence": card["missing_evidence"],
        "next_actions": card["recommended_next_actions"],
        "build_note": "" if flags.get("validation") else "Validation 缺失，不能正式 Build。当前只能是 Build Candidate 或 Evidence Partial。",
    }


def annotate_feed(items: list[dict]) -> None:
    init_db()
    domains = sorted({_host(item.get("domain") or "") for item in items if _host(item.get("domain") or "")})
    found = {}
    if domains:
        conn = connect()
        try:
            marks = ",".join("?" for _ in domains)
            rows = conn.execute(
                f"SELECT * FROM intelligence_dossiers WHERE domain IN ({marks})",
                domains,
            ).fetchall()
        finally:
            conn.close()
        found = {row["domain"]: row for row in rows}
    for item in items:
        host = _host(item.get("domain") or "")
        row = found.get(host)
        if row is None:
            item["dossier_id"] = None
            item["evidence_count"] = 0
            item["missing_evidence"] = "Payment, Traffic, Authority, SERP, Competitor, Validation"
            item["next_action"] = "Create Dossier"
            continue
        actions = _loads(row["recommended_next_actions"], [])
        missing = _loads(row["missing_evidence"], [])
        item["dossier_id"] = int(row["id"])
        item["evidence_count"] = int(row["evidence_score"] and 1)
        conn = connect()
        try:
            count = conn.execute(
                "SELECT COUNT(*) AS n FROM dossier_evidence_items WHERE dossier_id = ?",
                (int(row["id"]),),
            ).fetchone()["n"]
        finally:
            conn.close()
        item["evidence_count"] = int(count or 0)
        item["missing_evidence"] = "；".join(missing) if missing else ""
        item["next_action"] = actions[0] if actions else ""


def _attach_feed_row(dossier_id: int, row) -> None:
    signal = row["signal"] or "news"
    _add_item(dossier_id, {
        "evidence_type": _SIGNAL_TYPE.get(signal, "news"),
        "source_name": row["source_name"] or "",
        "source_url": row["url"] or "",
        "source_domain": row["domain"] or "",
        "title": row["title"] or "",
        "content": row["why_it_matters"] or "",
        "created_at": row["created_at"] or _now(),
    })


def from_feed(feed_id: int, action: str) -> dict:
    init_db()
    name = (action or "").strip().lower()
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM intelligence_feed WHERE id = ?", (feed_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise ValueError("资讯不存在")
    if name == "ignore":
        conn = connect()
        try:
            conn.execute("UPDATE intelligence_feed SET ignored = 1 WHERE id = ?", (feed_id,))
            conn.commit()
        finally:
            conn.close()
        return {"dossier_id": 0, "created": False, "message": "已忽略", "opportunity_status": ""}
    if name not in {"create", "attach", "add", "research"}:
        raise ValueError("不支持的操作")
    domain = row["domain"] or _host(row["url"] or "")
    dossier_id, created = _insert_dossier(domain, row["title"] or domain, row["why_it_matters"] or "", row["signal"] or "news")
    _attach_feed_row(dossier_id, row)
    recompute(dossier_id, row["why_it_matters"] or "")
    if name == "research":
        conn = connect()
        try:
            conn.execute(
                "UPDATE intelligence_dossiers SET opportunity_status = 'research', status_locked = 1, updated_at = ? WHERE id = ?",
                (_now(), dossier_id),
            )
            conn.commit()
        finally:
            conn.close()
    detail = get_dossier(dossier_id)
    status = detail["dossier"]["opportunity_status"] if detail else ""
    message = "已创建案卷" if created else "已追加证据"
    if name == "research":
        message = "已标为下一步研究"
    return {
        "dossier_id": dossier_id,
        "created": created,
        "message": message,
        "opportunity_status": status,
    }


def _domain_records(domain: str) -> list[dict]:
    host = _host(domain)
    items = []
    conn = connect()
    try:
        for record_type, (evidence_type, source_name, metric_key) in _RECORD_TYPE.items():
            rows = conn.execute(
                """
                SELECT r.normalized_title, r.normalized_url, r.normalized_domain, r.time_range, r.raw_json,
                       r.metric_name, r.metric_value, r.created_at, s.name AS source_name, i.original_filename
                FROM raw_source_records r
                LEFT JOIN data_sources s ON s.id = r.source_id
                LEFT JOIN source_imports i ON i.id = r.import_id
                WHERE lower(COALESCE(r.normalized_domain, '')) = ?
                  AND r.record_type = ?
                  AND lower(COALESCE(r.status, '')) IN ('imported', 'confirmed')
                ORDER BY CAST(json_extract(r.raw_json, '$.rank') AS REAL) ASC, r.id DESC
                LIMIT 5
                """,
                (host, record_type),
            ).fetchall()
            for row in rows:
                raw = _loads(row["raw_json"], {})
                metric_name = metric_key or row["metric_name"] or ""
                metric_value = ""
                if isinstance(raw, dict) and metric_key:
                    metric_value = str(raw.get(metric_key) or "")
                if not metric_value:
                    metric_value = row["metric_value"] or ""
                items.append({
                    "evidence_type": evidence_type,
                    "source_name": row["source_name"] or source_name,
                    "source_url": row["normalized_url"] or "",
                    "source_domain": host,
                    "title": row["normalized_title"] or host,
                    "content": f"{host} {evidence_type} evidence",
                    "metric_name": metric_name,
                    "metric_value": metric_value,
                    "period_month": row["time_range"] if re.match(r"^\d{4}-\d{2}$", row["time_range"] or "") else "",
                    "raw_json": json.dumps({"original_file": row["original_filename"] or ""}, ensure_ascii=False),
                    "created_at": row["created_at"] or _now(),
                })
        pages = conn.execute(
            """
            SELECT domain, url, title, page_type, target_keyword, created_at
            FROM competitor_pages
            WHERE lower(COALESCE(domain, '')) = ?
            ORDER BY id DESC
            LIMIT 5
            """,
            (host,),
        ).fetchall()
        news = conn.execute(
            """
            SELECT title, url, source_name, why_it_matters, signal, created_at
            FROM intelligence_feed
            WHERE lower(COALESCE(domain, '')) = ? AND COALESCE(ignored, 0) = 0
            ORDER BY id DESC
            LIMIT 5
            """,
            (host,),
        ).fetchall()
    finally:
        conn.close()
    for page in pages:
        items.append({
            "evidence_type": "competitor_page",
            "source_name": "Competitor",
            "source_url": page["url"] or "",
            "source_domain": host,
            "title": page["title"] or page["page_type"] or host,
            "content": page["target_keyword"] or "",
            "created_at": page["created_at"] or _now(),
        })
    for row in news:
        items.append({
            "evidence_type": _SIGNAL_TYPE.get(row["signal"] or "", "news"),
            "source_name": row["source_name"] or "",
            "source_url": row["url"] or "",
            "source_domain": host,
            "title": row["title"] or "",
            "content": row["why_it_matters"] or "",
            "created_at": row["created_at"] or _now(),
        })
    return items


def from_domain(domain: str, action: str) -> dict:
    init_db()
    name = (action or "create").strip().lower()
    if name not in {"open", "create", "watch", "research"}:
        raise ValueError("不支持的操作")
    host = _host(domain)
    existing = _find(host)
    created = False
    if existing is None:
        dossier_id, created = _insert_dossier(host, host, "", "product")
        for item in _domain_records(host):
            _add_item(dossier_id, item)
        recompute(dossier_id)
    else:
        dossier_id = int(existing["id"])
        if name == "create":
            for item in _domain_records(host):
                _add_item(dossier_id, item)
            recompute(dossier_id)
    if name in {"watch", "research"}:
        status = "watch" if name == "watch" else "research"
        conn = connect()
        try:
            conn.execute(
                "UPDATE intelligence_dossiers SET opportunity_status = ?, status_locked = 1, updated_at = ? WHERE id = ?",
                (status, _now(), dossier_id),
            )
            conn.commit()
        finally:
            conn.close()
    detail = get_dossier(dossier_id)
    status = detail["dossier"]["opportunity_status"] if detail else ""
    message = "已打开案卷" if not created else "已创建案卷并挂上该域名的证据"
    if name == "watch":
        message = "已加入 Watchlist"
    if name == "research":
        message = "已标为 Research"
    return {"dossier_id": dossier_id, "created": created, "message": message, "opportunity_status": status}


def from_record(record_id: int) -> dict:
    init_db()
    conn = connect()
    try:
        row = conn.execute(
            """
            SELECT r.*, s.name AS source_name, i.original_filename
            FROM raw_source_records r
            LEFT JOIN data_sources s ON s.id = r.source_id
            LEFT JOIN source_imports i ON i.id = r.import_id
            WHERE r.id = ?
            """,
            (record_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise ValueError("记录不存在")
    mapped = _RECORD_TYPE.get(row["record_type"] or "")
    evidence_type, fallback, metric_key = mapped or ("manual_note", row["source_name"] or "Data Explorer", row["metric_name"] or "")
    host = _host(row["normalized_domain"] or "")
    if not host:
        raise ValueError("这条记录没有 domain")
    raw = _loads(row["raw_json"], {})
    metric_value = row["metric_value"] or ""
    if isinstance(raw, dict) and metric_key and raw.get(metric_key):
        metric_value = str(raw.get(metric_key))
    dossier_id, created = _insert_dossier(host, row["normalized_title"] or host, "", evidence_type)
    _add_item(dossier_id, {
        "evidence_type": evidence_type,
        "source_name": row["source_name"] or fallback,
        "source_url": row["normalized_url"] or "",
        "source_domain": host,
        "title": row["normalized_title"] or host,
        "content": f"Attached from Data Explorer #{record_id}",
        "metric_name": metric_key or row["metric_name"] or "",
        "metric_value": metric_value,
        "period_month": row["time_range"] if re.match(r"^\d{4}-\d{2}$", row["time_range"] or "") else "",
        "raw_json": json.dumps({"original_file": row["original_filename"] or "", "record_id": record_id}, ensure_ascii=False),
        "created_at": row["created_at"] or _now(),
    })
    recompute(dossier_id)
    return {"dossier_id": dossier_id, "created": created, "message": "已挂到案卷", "opportunity_status": ""}


def attach_sitedata_evidence(domain: str, item: dict, auto_create: bool) -> str:
    init_db()
    host = _host(domain)
    if not host:
        return "skipped"
    existing = _find(host)
    created = False
    if existing is None:
        if not auto_create:
            return "skipped"
        dossier_id, created = _insert_dossier(host, item.get("title") or host, item.get("content") or "", "sitedata")
        conn = connect()
        try:
            conn.execute(
                """
                UPDATE intelligence_dossiers
                SET opportunity_status = 'watch', status_locked = 1, updated_at = ?
                WHERE id = ?
                """,
                (_now(), dossier_id),
            )
            conn.commit()
        finally:
            conn.close()
    else:
        dossier_id = int(existing["id"])
    _add_item(dossier_id, item)
    recompute(dossier_id, item.get("content") or "")
    return "created" if created else "attached"


def manual_intake(payload: dict) -> dict:
    init_db()
    domain = _host(payload.get("domain") or "")
    if not domain:
        raise ValueError("domain 不能为空")
    note = (payload.get("note") or "").strip()
    title = (payload.get("title") or domain).strip()
    evidence_type = (payload.get("evidence_type") or "manual_note").strip()
    if evidence_type not in EVIDENCE_TYPES:
        evidence_type = "manual_note"
    dossier_id, created = _insert_dossier(domain, title, note, evidence_type)
    _add_item(dossier_id, {
        "evidence_type": evidence_type,
        "source_name": payload.get("source_name") or "Manual",
        "source_url": payload.get("source_url") or "",
        "source_domain": domain,
        "title": title,
        "content": note,
        "metric_name": payload.get("metric_name") or "",
        "metric_value": payload.get("metric_value") or "",
        "period_month": payload.get("period_month") or "",
        "confidence": payload.get("confidence") or "",
    })
    recompute(dossier_id, note)
    return {"dossier_id": dossier_id, "created": created, "message": "已写入案卷", "opportunity_status": ""}


def add_evidence(dossier_id: int, payload: dict) -> dict:
    init_db()
    if get_dossier(dossier_id) is None:
        raise ValueError("案卷不存在")
    evidence_type = (payload.get("evidence_type") or "manual_note").strip()
    if evidence_type not in EVIDENCE_TYPES:
        evidence_type = "manual_note"
    _add_item(dossier_id, {
        "evidence_type": evidence_type,
        "source_name": payload.get("source_name") or "Manual",
        "source_url": payload.get("source_url") or "",
        "title": payload.get("title") or evidence_type,
        "content": payload.get("note") or payload.get("content") or "",
        "metric_name": payload.get("metric_name") or "",
        "metric_value": payload.get("metric_value") or "",
        "period_month": payload.get("period_month") or "",
        "confidence": payload.get("confidence") or "",
    })
    recompute(dossier_id, payload.get("note") or "")
    return {"dossier_id": dossier_id, "created": False, "message": "已追加证据", "opportunity_status": ""}


def _safe_name(name: str) -> str:
    base = Path(name or "screenshot").name
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", base)[:80] or "screenshot"
    return cleaned


def add_screenshot(dossier_id: int, filename: str, content: bytes, fields: dict) -> dict:
    init_db()
    dossier = get_dossier(dossier_id)
    if dossier is None:
        raise ValueError("案卷不存在")
    if not content:
        raise ValueError("截图为空")
    if len(content) > 8_000_000:
        raise ValueError("截图超过 8MB")
    folder = project_root() / "data" / "screenshots"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    stored = f"{dossier_id}-{stamp}-{_safe_name(filename)}"
    path = folder / stored
    path.write_bytes(content)
    note = (fields.get("note") or "").strip()
    _add_item(dossier_id, {
        "evidence_type": "screenshot",
        "source_name": fields.get("source_name") or "Screenshot",
        "source_url": "",
        "source_domain": dossier["dossier"]["domain"],
        "title": fields.get("title") or filename or "screenshot",
        "content": note,
        "metric_name": fields.get("metric_name") or "",
        "metric_value": fields.get("metric_value") or "",
        "period_month": fields.get("period_month") or "",
        "screenshot_path": f"screenshots/{stored}",
        "raw_json": json.dumps({"file_name": _safe_name(filename), "linked_domain": dossier["dossier"]["domain"]}, ensure_ascii=False),
    })
    recompute(dossier_id, note)
    return {"dossier_id": dossier_id, "created": False, "message": "已保存截图证据", "opportunity_status": ""}


def screenshot_path(dossier_id: int, evidence_id: int) -> Path | None:
    conn = connect()
    try:
        row = conn.execute(
            """
            SELECT screenshot_path FROM dossier_evidence_items
            WHERE id = ? AND dossier_id = ?
            """,
            (evidence_id, dossier_id),
        ).fetchone()
    finally:
        conn.close()
    if row is None or not row["screenshot_path"]:
        return None
    root = (project_root() / "data").resolve()
    path = (root / row["screenshot_path"]).resolve()
    if root not in path.parents or not path.is_file():
        return None
    return path


def _set_status(dossier_id: int, status: str) -> None:
    if status not in STATUSES:
        raise ValueError("状态不在允许列表中")
    conn = connect()
    try:
        conn.execute(
            """
            UPDATE intelligence_dossiers
            SET opportunity_status = ?, status_locked = 1, updated_at = ?
            WHERE id = ?
            """,
            (status, _now(), dossier_id),
        )
        conn.commit()
    finally:
        conn.close()


def _ensure_cluster(name: str) -> int:
    label = " ".join((name or "").split())[:80] or "dossier keyword"
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
            ) VALUES (?, 'dossier', 'commercial', 'landing', 3, 'open', 0, 'from dossier', ?, ?)
            """,
            (label, now, now),
        )
        cluster_id = int(cur.lastrowid)
        conn.execute(
            """
            INSERT OR IGNORE INTO keyword_items (
                cluster_id, keyword, intent, difficulty, source, status, created_at
            ) VALUES (?, ?, 'commercial', '', 'dossier', 'open', ?)
            """,
            (cluster_id, label, now),
        )
        conn.commit()
        return cluster_id
    finally:
        conn.close()


def run_action(dossier_id: int, action: str) -> dict:
    init_db()
    detail = get_dossier(dossier_id)
    if detail is None:
        raise ValueError("案卷不存在")
    domain = detail["dossier"]["domain"]
    name = (action or "").strip().lower()
    if name == "watch":
        _set_status(dossier_id, "watch")
        return {"dossier_id": dossier_id, "created": False, "message": "已标为 Watch", "opportunity_status": "watch"}
    if name == "research":
        _set_status(dossier_id, "research")
        return {"dossier_id": dossier_id, "created": False, "message": "已标为 Research", "opportunity_status": "research"}
    if name == "validation_needed":
        _set_status(dossier_id, "validation_needed")
        return {"dossier_id": dossier_id, "created": False, "message": "已标为 Validation Needed", "opportunity_status": "validation_needed"}
    if name == "build_candidate":
        _set_status(dossier_id, "build_candidate")
        return {"dossier_id": dossier_id, "created": False, "message": "已标为 Build Candidate。仍缺 Validation 时不能正式 Build。", "opportunity_status": "build_candidate"}
    if name == "priority":
        _set_status(dossier_id, "priority_research")
        return {"dossier_id": dossier_id, "created": False, "message": "已标为 Priority Research", "opportunity_status": "priority_research"}
    if name == "reject":
        _set_status(dossier_id, "rejected")
        return {"dossier_id": dossier_id, "created": False, "message": "已拒绝", "opportunity_status": "rejected"}
    if name == "keyword":
        _ensure_cluster(domain)
        _add_item(dossier_id, {
            "evidence_type": "manual_note",
            "source_name": "Keyword",
            "title": domain,
            "content": f"{domain} added to the keyword pool.",
            "source_domain": domain,
        })
        recompute(dossier_id)
        return {"dossier_id": dossier_id, "created": False, "message": "已加入关键词池", "opportunity_status": ""}
    if name == "competitor":
        from app.competitors import create_competitor

        cluster_id = _ensure_cluster(domain)
        url = f"https://{domain}/"
        create_competitor({
            "cluster_id": cluster_id,
            "url": url,
            "domain": domain,
            "title": domain,
            "page_type": "unknown",
            "target_keyword": domain,
            "notes": "from dossier",
        })
        _add_item(dossier_id, {
            "evidence_type": "competitor_page",
            "source_name": "Competitor",
            "source_url": url,
            "source_domain": domain,
            "title": domain,
            "content": "Competitor page placeholder from dossier.",
        })
        recompute(dossier_id)
        return {"dossier_id": dossier_id, "created": False, "message": "已添加竞品页", "opportunity_status": ""}
    if name == "crawl":
        from app.intake import run_crawl

        result = run_crawl("", domain, domain, "landing_page")
        record = (result.get("records") or [{}])[0]
        _add_item(dossier_id, {
            "evidence_type": "crawl",
            "source_name": "Crawl",
            "source_url": record.get("url") or f"https://{domain}/",
            "source_domain": domain,
            "title": record.get("title") or domain,
            "content": f"Crawl {result.get('status') or ''} pages {result.get('pages') or 0}",
        })
        recompute(dossier_id)
        return {"dossier_id": dossier_id, "created": False, "message": "已抓取页面", "opportunity_status": ""}
    if name == "run_serp":
        from app.google_search import GoogleSearchError
        from app.serp import search_serp

        try:
            result = search_serp(domain, 10, "us", "en")
        except GoogleSearchError as exc:
            raise ValueError(_public(str(exc.detail if hasattr(exc, "detail") else exc))) from exc
        provider_name = {"google_cse": "Google CSE", "serper": "Serper"}.get(result.get("provider") or "", "SERP")
        for item in result.get("items") or []:
            _add_item(dossier_id, {
                "evidence_type": "serp",
                "source_name": provider_name,
                "source_url": item.get("link") or "",
                "source_domain": item.get("displayLink") or domain,
                "title": item.get("title") or domain,
                "content": item.get("snippet") or "",
                "metric_name": "rank",
                "metric_value": str(item.get("rank") or ""),
            })
        recompute(dossier_id)
        return {"dossier_id": dossier_id, "created": False, "message": f"SERP {result.get('count') or 0}", "opportunity_status": ""}
    raise ValueError("不支持的操作")
