import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from app.db import connect
from app.keywords import get_keyword_cluster

PAGE_TYPES = {"tutorial", "comparison", "tool", "api_docs", "listicle", "template", "landing", "unknown"}

PAGE_TYPE_SCORES = {
    "tutorial": 25,
    "api_docs": 25,
    "comparison": 22,
    "tool": 18,
    "listicle": 15,
    "template": 15,
    "landing": 10,
    "unknown": 5,
}


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", (value or "").lower()).strip()


def domain_of(url: str) -> str:
    host = (urlparse((url or "").strip()).netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _keyword_fit(title: str, h1: str, target_keyword: str, keywords: list[str]) -> int:
    hay = _norm(f"{title} {h1}")
    phrases = [keyword for keyword in keywords if keyword]
    if target_keyword:
        phrases.append(target_keyword)
    best = 5
    hay_tokens = set(hay.split())
    for phrase in phrases:
        norm = _norm(phrase)
        if not norm:
            continue
        if norm in hay:
            return 25
        tokens = [token for token in norm.split() if len(token) > 1]
        if not tokens:
            continue
        hit = sum(1 for token in tokens if token in hay_tokens)
        if hit == len(tokens):
            return 25
        if hit:
            best = max(best, 15)
    return best


def _conversion(cta_text: str, pricing_signal: str, signup_signal: str, payment_signal: str, geo_signal: str) -> int:
    points = 0
    signup_blob = _norm(f"{signup_signal} {cta_text}")
    if signup_signal.strip() or any(token in signup_blob for token in ("signup", "sign up", "register", "注册")):
        points += 10
    if pricing_signal.strip() or payment_signal.strip():
        points += 8
    entry_blob = _norm(f"{cta_text} {geo_signal}")
    if any(token in entry_blob for token in ("api key", "dashboard", "docs", "文档", "faq")):
        points += 7
    if points > 25:
        return 25
    return points


def _tokfai(cluster_name: str, keywords: list[str], title: str, h1: str, target_keyword: str) -> int:
    blob = _norm(" ".join([cluster_name, *keywords, title, h1, target_keyword]))
    if any(token in blob for token in ("openai compatible", "base url", "cherry studio", "cursor")) or (
        "sdk" in blob and "openai" in blob
    ):
        return 25
    if any(token in blob for token in ("cheap gpt", "cheap gemini", "gemini api", "gpt api")):
        return 20
    if "ai" in blob.split() or "api" in blob.split():
        return 10
    return 0


def _risk_level(page_type: str) -> str:
    if page_type in {"landing", "unknown"}:
        return "high"
    if page_type in {"tool", "listicle", "template"}:
        return "medium"
    return "low"


def copyability_score(page: dict, cluster_name: str, keywords: list[str]) -> tuple[int, str]:
    keyword_points = _keyword_fit(page.get("title") or "", page.get("h1") or "", page.get("target_keyword") or "", keywords)
    page_points = PAGE_TYPE_SCORES.get(page.get("page_type") or "", 0)
    conversion_points = _conversion(
        page.get("cta_text") or "",
        page.get("pricing_signal") or "",
        page.get("signup_signal") or "",
        page.get("payment_signal") or "",
        page.get("geo_signal") or "",
    )
    tokfai_points = _tokfai(
        cluster_name,
        keywords,
        page.get("title") or "",
        page.get("h1") or "",
        page.get("target_keyword") or "",
    )
    total = keyword_points + page_points + conversion_points + tokfai_points
    if total < 0:
        total = 0
    if total > 100:
        total = 100
    return total, _risk_level(page.get("page_type") or "")


def _row(row) -> dict:
    data = dict(row)
    for key in (
        "url",
        "domain",
        "title",
        "h1",
        "page_type",
        "target_keyword",
        "cta_text",
        "pricing_signal",
        "signup_signal",
        "payment_signal",
        "geo_signal",
        "risk_level",
        "notes",
    ):
        data[key] = data.get(key) or ""
    data["copyability_score"] = int(data.get("copyability_score") or 0)
    data["cluster_id"] = int(data["cluster_id"])
    return data


def list_competitors(cluster_id: int | None = None) -> list[dict]:
    conn = connect()
    try:
        if cluster_id is None:
            rows = conn.execute(
                """
                SELECT id, cluster_id, url, domain, title, h1, page_type, target_keyword,
                       cta_text, pricing_signal, signup_signal, payment_signal, geo_signal,
                       copyability_score, risk_level, notes, created_at, updated_at
                FROM competitor_pages
                ORDER BY copyability_score DESC, id DESC
                """
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, cluster_id, url, domain, title, h1, page_type, target_keyword,
                       cta_text, pricing_signal, signup_signal, payment_signal, geo_signal,
                       copyability_score, risk_level, notes, created_at, updated_at
                FROM competitor_pages
                WHERE cluster_id = ?
                ORDER BY copyability_score DESC, id DESC
                """,
                (cluster_id,),
            ).fetchall()
        return [_row(row) for row in rows]
    finally:
        conn.close()


def get_competitor(page_id: int) -> dict | None:
    conn = connect()
    try:
        row = conn.execute(
            """
            SELECT id, cluster_id, url, domain, title, h1, page_type, target_keyword,
                   cta_text, pricing_signal, signup_signal, payment_signal, geo_signal,
                   copyability_score, risk_level, notes, created_at, updated_at
            FROM competitor_pages
            WHERE id = ?
            """,
            (page_id,),
        ).fetchone()
        if row is None:
            return None
        return _row(row)
    finally:
        conn.close()


def create_competitor(payload: dict) -> dict | None:
    page_type = (payload.get("page_type") or "").strip()
    if page_type not in PAGE_TYPES:
        raise ValueError("page_type 不在允许列表中")
    url = (payload.get("url") or "").strip()
    if not url:
        raise ValueError("url 不能为空")
    cluster = get_keyword_cluster(int(payload["cluster_id"]))
    if cluster is None:
        return None
    keywords = [item.get("keyword") or "" for item in cluster.get("items") or []]
    page = {
        "title": payload.get("title") or "",
        "h1": payload.get("h1") or "",
        "page_type": page_type,
        "target_keyword": payload.get("target_keyword") or "",
        "cta_text": payload.get("cta_text") or "",
        "pricing_signal": payload.get("pricing_signal") or "",
        "signup_signal": payload.get("signup_signal") or "",
        "payment_signal": payload.get("payment_signal") or "",
        "geo_signal": payload.get("geo_signal") or "",
    }
    score, risk = copyability_score(page, cluster.get("name") or "", keywords)
    now = datetime.now(timezone.utc).isoformat()
    conn = connect()
    try:
        cur = conn.execute(
            """
            INSERT INTO competitor_pages (
                cluster_id, url, domain, title, h1, page_type, target_keyword,
                cta_text, pricing_signal, signup_signal, payment_signal, geo_signal,
                copyability_score, risk_level, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(payload["cluster_id"]),
                url,
                domain_of(url),
                page["title"],
                page["h1"],
                page_type,
                page["target_keyword"],
                page["cta_text"],
                page["pricing_signal"],
                page["signup_signal"],
                page["payment_signal"],
                page["geo_signal"],
                score,
                risk,
                payload.get("notes") or "",
                now,
                now,
            ),
        )
        conn.commit()
        page_id = int(cur.lastrowid)
    finally:
        conn.close()
    created = get_competitor(page_id)
    return created


def get_competitor_analysis(page_id: int) -> dict | None:
    conn = connect()
    try:
        row = conn.execute(
            """
            SELECT id, page_id, model, analysis, elapsed_seconds, created_at
            FROM competitor_page_analysis
            WHERE page_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (page_id,),
        ).fetchone()
        if row is None:
            return None
        return dict(row)
    finally:
        conn.close()


def save_competitor_analysis(page_id: int, model: str, analysis: str, elapsed_seconds: int) -> dict:
    created_at = datetime.now(timezone.utc).isoformat()
    conn = connect()
    try:
        cur = conn.execute(
            """
            INSERT INTO competitor_page_analysis (page_id, model, analysis, elapsed_seconds, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (page_id, model, analysis, elapsed_seconds, created_at),
        )
        conn.commit()
        return {
            "id": cur.lastrowid,
            "page_id": page_id,
            "model": model,
            "analysis": analysis,
            "elapsed_seconds": elapsed_seconds,
            "created_at": created_at,
        }
    finally:
        conn.close()


def _clip_field(value, limit: int) -> str:
    text = str(value or "").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[:limit]


def competitor_prompt(page: dict) -> str:
    lines = [
        "只写6句：1搜索意图 2页面类型 3转化路径 4可复制点 5不可复制点 6我们7天内应该做什么",
        f"url: {_clip_field(page.get('url'), 100)}",
        f"domain: {_clip_field(page.get('domain'), 40)}",
        f"title: {_clip_field(page.get('title'), 60)}",
        f"h1: {_clip_field(page.get('h1'), 60)}",
        f"page_type: {_clip_field(page.get('page_type'), 20)}",
        f"target_keyword: {_clip_field(page.get('target_keyword'), 40)}",
        f"cta_text: {_clip_field(page.get('cta_text'), 40)}",
        f"pricing_signal: {_clip_field(page.get('pricing_signal'), 30)}",
        f"signup_signal: {_clip_field(page.get('signup_signal'), 30)}",
        f"payment_signal: {_clip_field(page.get('payment_signal'), 30)}",
        f"notes: {_clip_field(page.get('notes'), 40)}",
    ]
    text = "\n".join(lines)
    if len(text) > 800:
        return text[:800]
    return text
