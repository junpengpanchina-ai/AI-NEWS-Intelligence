import time
from datetime import datetime, timedelta, timezone

from app.db import connect
from app.explorer import _desk_noise, external_opportunities

_CACHE: dict = {"at": 0.0, "payload": None}
_TTL = 20
_BUCKETS = (
    "AI Agent",
    "AI Video",
    "SEO / GEO",
    "API Tools",
    "Image Tools",
    "Productivity",
    "Education",
    "Developer Tools",
)
_RULES = (
    ("AI Agent", ("agent", "agents", "智能体")),
    ("AI Video", ("video", "视频", "kling", "sora", "runway")),
    ("Image Tools", ("image", "图像", "图片", "midjourney")),
    ("SEO / GEO", ("seo", "geo", "搜索")),
    ("Developer Tools", ("developer", "devtools", "客户端", "cursor", "配置")),
    ("API Tools", ("api", "接入", "proxy", "兼容")),
    ("Productivity", ("productivity", "效率", "笔记")),
    ("Education", ("education", "教育", "课程")),
)
_SKIP_LABELS = {"", "traffic", "payment", "authority", "product", "news", "serp", "signal"}


def market_pulse() -> dict:
    now = time.time()
    cached = _CACHE.get("payload")
    if cached is not None and now - float(_CACHE.get("at") or 0) < _TTL:
        return cached
    payload = _compute()
    _CACHE["at"] = now
    _CACHE["payload"] = payload
    return payload


def _compute() -> dict:
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    week = (now - timedelta(days=7)).isoformat()
    month = (now - timedelta(days=30)).isoformat()
    conn = connect()
    try:
        feed = conn.execute(
            """
            SELECT
              SUM(CASE WHEN substr(created_at, 1, 10) = ? THEN 1 ELSE 0 END) AS today_count,
              SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) AS week_count
            FROM intelligence_feed
            """,
            (today, week),
        ).fetchone()
        raw_count = conn.execute(
            "SELECT COUNT(*) AS n FROM raw_source_records WHERE created_at >= ?",
            (month,),
        ).fetchone()
        traffic_top = _top_metric(conn, "traffic_signal", "$.traffic_growth", "$.growth_rate")
        authority_top = _top_metric(conn, "authority_signal", "$.dr_growth", "$.dr_growth")
        validated = _validated_domains(conn)
        categories = _categories(conn)
    finally:
        conn.close()
    opportunities = external_opportunities(all_rows=True).get("items") or []
    total = len(opportunities)
    payment = [row for row in opportunities if _has(row, "Payment")]
    traffic = [row for row in opportunities if _has(row, "Traffic")]
    authority = [row for row in opportunities if _has(row, "Authority")]
    serp = [row for row in opportunities if _has(row, "SERP")]
    quality = {"p0": 0, "p1": 0, "p2": 0, "p3": 0}
    missing_validation = 0
    build_candidate = False
    for row in opportunities:
        tier = row.get("opportunity_tier") or ""
        if tier == "P0_priority":
            quality["p0"] += 1
        elif tier == "P1_research":
            quality["p1"] += 1
        elif tier == "P2_watch":
            quality["p2"] += 1
        else:
            quality["p3"] += 1
        domain = (row.get("domain") or "").lower()
        if domain not in validated:
            missing_validation += 1
        elif _has(row, "Payment") and _has(row, "Traffic"):
            build_candidate = True
    ratio = round(len(payment) / total, 4) if total else 0
    gap_ratio = round(missing_validation / total, 4) if total else 1
    if gap_ratio >= 0.8:
        gap_status = "missing"
    elif gap_ratio > 0:
        gap_status = "partial"
    else:
        gap_status = "ready"
    covered = len(serp)
    missing = max(total - covered, 0)
    if covered == 0:
        serp_status = "missing"
    elif missing == 0:
        serp_status = "ready"
    else:
        serp_status = "partial"
    if quality["p0"] and gap_ratio > 0:
        readiness = {
            "status": "research_ready_not_build_ready",
            "reason": "Validation Evidence missing",
        }
    elif build_candidate:
        readiness = {
            "status": "build_candidate",
            "reason": "Validation, payment, and traffic are present",
        }
    else:
        readiness = {
            "status": "watch_research",
            "reason": "Only traffic or authority is present",
        }
    return {
        "signal_volume": {
            "today": int(feed["today_count"] or 0) if feed else 0,
            "last_7d": int(feed["week_count"] or 0) if feed else 0,
            "last_30d": int(raw_count["n"] or 0) if raw_count else 0,
        },
        "payment_density": {"domains": len(payment), "ratio": ratio},
        "traffic_momentum": {"domains": len(traffic), "top_domains": traffic_top},
        "authority_momentum": {"domains": len(authority), "top_domains": authority_top},
        "serp_coverage": {
            "covered_domains": covered,
            "missing_domains": missing,
            "status": serp_status,
        },
        "category_heat": _heat(_apply_flags(categories, opportunities)),
        "opportunity_quality": quality,
        "validation_gap": {"missing_ratio": gap_ratio, "status": gap_status},
        "build_readiness": readiness,
    }


def _has(row: dict, tag: str) -> bool:
    return tag in (row.get("evidence_tags") or row.get("tags") or [])


def _validated_domains(conn) -> set[str]:
    rows = conn.execute(
        """
        SELECT lower(source_domain) AS domain
        FROM dossier_evidence_items
        WHERE lower(COALESCE(evidence_type, '')) LIKE '%validation%'
          AND COALESCE(source_domain, '') != ''
        UNION
        SELECT lower(normalized_domain)
        FROM raw_source_records
        WHERE record_type = 'validation_signal'
          AND COALESCE(normalized_domain, '') != ''
        UNION
        SELECT lower(domain)
        FROM intelligence_dossiers
        WHERE COALESCE(validation_score, 0) > 0
          AND COALESCE(domain, '') != ''
        """
    ).fetchall()
    return {row["domain"] for row in rows if row["domain"]}


def _top_metric(conn, record_type: str, primary: str, secondary: str) -> list[dict]:
    rows = conn.execute(
        f"""
        SELECT lower(normalized_domain) AS domain,
               MAX(
                 CAST(
                   replace(replace(COALESCE(json_extract(raw_json, ?), json_extract(raw_json, ?), '0'), '%', ''), ',', '')
                   AS REAL
                 )
               ) AS metric
        FROM raw_source_records
        WHERE record_type = ?
          AND lower(COALESCE(status, '')) IN ('imported', 'confirmed')
          AND COALESCE(normalized_domain, '') != ''
        GROUP BY lower(normalized_domain)
        ORDER BY metric DESC
        LIMIT 20
        """,
        (primary, secondary, record_type),
    ).fetchall()
    picked = []
    for row in rows:
        host = row["domain"] or ""
        if not host or _desk_noise(host):
            continue
        picked.append({"domain": host, "metric": _metric(row["metric"])})
        if len(picked) == 5:
            break
    return picked


def _metric(value) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return ""
    if number <= 0:
        return ""
    if number >= 10:
        return str(int(round(number)))
    return f"{number:.1f}"


def _blank_bucket() -> dict:
    return {
        "signal_count": 0,
        "payment_count": 0,
        "traffic_count": 0,
        "authority_count": 0,
        "opportunity_count": 0,
        "score_sum": 0,
        "score_n": 0,
        "top_domain": "",
        "top_score": -1,
        "domains": set(),
    }


def _categories(conn) -> dict[str, dict]:
    buckets = {name: _blank_bucket() for name in _BUCKETS}
    clusters = conn.execute("SELECT name, category FROM keyword_clusters").fetchall()
    for row in clusters:
        name = _match(f"{row['name'] or ''} {row['category'] or ''}")
        if not name:
            continue
        bucket = buckets[name]
        bucket["signal_count"] += 1
        bucket["opportunity_count"] += 1
    dossiers = conn.execute(
        """
        SELECT domain, category, product_name, evidence_score, payment_score, traffic_score, authority_score
        FROM intelligence_dossiers
        """
    ).fetchall()
    for row in dossiers:
        label = f"{row['domain'] or ''} {row['category'] or ''} {row['product_name'] or ''}"
        name = _match(label)
        if not name:
            continue
        _add_domain(buckets[name], row["domain"], int(row["evidence_score"] or 0))
    labeled = conn.execute(
        """
        SELECT
          COALESCE(json_extract(raw_json, '$.category'), '') AS category,
          COALESCE(json_extract(raw_json, '$.tag'), '') AS tag,
          COALESCE(json_extract(raw_json, '$.source_category'), '') AS source_category,
          record_type,
          lower(normalized_domain) AS domain,
          COUNT(*) AS n
        FROM raw_source_records
        WHERE lower(COALESCE(status, '')) IN ('imported', 'confirmed')
          AND (
            COALESCE(json_extract(raw_json, '$.category'), '') != ''
            OR COALESCE(json_extract(raw_json, '$.tag'), '') != ''
            OR COALESCE(json_extract(raw_json, '$.source_category'), '') != ''
          )
        GROUP BY 1, 2, 3, 4, 5
        """
    ).fetchall()
    for row in labeled:
        label = f"{row['category']} {row['tag']} {row['source_category']}"
        if label.strip().lower() in _SKIP_LABELS:
            continue
        name = _match(label)
        if not name:
            continue
        bucket = buckets[name]
        bucket["signal_count"] += int(row["n"] or 0)
        kind = row["record_type"] or ""
        if kind == "payment_signal":
            bucket["payment_count"] += 1
        elif kind == "traffic_signal":
            bucket["traffic_count"] += 1
        elif kind == "authority_signal":
            bucket["authority_count"] += 1
        _add_domain(bucket, row["domain"], 0)
    return buckets


def _add_domain(bucket: dict, domain: str, score: int) -> None:
        host = (domain or "").strip().lower()
        if not host or _desk_noise(host) or host in bucket["domains"]:
            return
        bucket["domains"].add(host)
        bucket["opportunity_count"] += 1
        if score >= bucket["top_score"]:
            bucket["top_score"] = score
            bucket["top_domain"] = host
        if score:
            bucket["score_sum"] += score
            bucket["score_n"] += 1


def _match(label: str) -> str:
    text = (label or "").lower()
    if not text.strip() or text.strip() in _SKIP_LABELS:
        return ""
    for name, words in _RULES:
        if any(word in text for word in words):
            return name
    return ""


def _apply_flags(buckets: dict[str, dict], opportunities: list[dict]) -> dict[str, dict]:
    by_domain = {(row.get("domain") or "").lower(): row for row in opportunities}
    for bucket in buckets.values():
        for host in bucket["domains"]:
            row = by_domain.get(host)
            if row is None:
                continue
            if _has(row, "Payment"):
                bucket["payment_count"] += 1
            if _has(row, "Traffic"):
                bucket["traffic_count"] += 1
            if _has(row, "Authority"):
                bucket["authority_count"] += 1
            score = int(row.get("opportunity_score") or 0)
            if score >= bucket["top_score"]:
                bucket["top_score"] = score
                bucket["top_domain"] = host
    return buckets


def _heat(buckets: dict[str, dict]) -> list[dict]:
    rows = []
    for name in _BUCKETS:
        bucket = buckets[name]
        avg = round(bucket["score_sum"] / bucket["score_n"], 1) if bucket["score_n"] else 0
        heat = min(
            100,
            int(
                bucket["signal_count"] * 12
                + bucket["payment_count"] * 8
                + bucket["traffic_count"] * 4
                + bucket["authority_count"] * 4
                + bucket["opportunity_count"] * 6
                + avg * 0.2
            ),
        )
        rows.append(
            {
                "category": name,
                "heat_score": heat,
                "signal_count": bucket["signal_count"],
                "payment_count": bucket["payment_count"],
                "traffic_count": bucket["traffic_count"],
                "authority_count": bucket["authority_count"],
                "opportunity_count": bucket["opportunity_count"],
                "avg_score": avg,
                "top_domain": bucket["top_domain"],
            }
        )
    rows.sort(key=lambda item: (-item["heat_score"], item["category"]))
    return rows[:10]
