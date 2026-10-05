from datetime import datetime, timezone

from app.db import connect

PAGE_TYPES = {"教程页", "对比页", "工具页"}

SEED_CLUSTERS = [
    {
        "name": "OpenAI Compatible API",
        "category": "API 接入",
        "search_intent": "寻找可替换 OpenAI 的兼容接口",
        "page_type": "对比页",
        "priority": 1,
        "notes": "用户要换 base URL，适合把兼容接口和注册入口写在同一页。",
        "keywords": [
            "OpenAI compatible API",
            "OpenAI SDK base URL",
            "OpenAI API alternative",
            "OpenAI API proxy",
        ],
    },
    {
        "name": "Cheap GPT API",
        "category": "低价 API",
        "search_intent": "寻找更便宜的 GPT 接口",
        "page_type": "对比页",
        "priority": 1,
        "notes": "价格词明确，适合对比页和低价体验入口。",
        "keywords": [
            "cheap GPT API",
            "cheapest GPT API",
            "GPT API alternative",
            "low cost GPT API",
        ],
    },
    {
        "name": "Gemini API Proxy",
        "category": "API 接入",
        "search_intent": "寻找 Gemini 的代理或替代入口",
        "page_type": "教程页",
        "priority": 2,
        "notes": "代理和 base URL 是长尾配置需求，可以做成接入教程。",
        "keywords": [
            "Gemini API proxy",
            "cheap Gemini API",
            "Gemini API alternative",
            "Gemini API base URL",
        ],
    },
    {
        "name": "Cursor API Setup",
        "category": "客户端配置",
        "search_intent": "把 Cursor 接到自定义 API",
        "page_type": "教程页",
        "priority": 1,
        "notes": "配置步骤短，七天内可以做出一页教程。",
        "keywords": [
            "Cursor API setup",
            "Cursor OpenAI compatible API",
            "Cursor custom API endpoint",
            "Cursor base URL setup",
        ],
    },
    {
        "name": "Cherry Studio API Setup",
        "category": "客户端配置",
        "search_intent": "把 Cherry Studio 接到兼容接口",
        "page_type": "教程页",
        "priority": 2,
        "notes": "客户端填 base URL 和 key，适合教程页带注册入口。",
        "keywords": [
            "Cherry Studio API setup",
            "Cherry Studio OpenAI compatible API",
            "Cherry Studio base URL",
            "Cherry Studio API key",
        ],
    },
    {
        "name": "AI Image API",
        "category": "生成 API",
        "search_intent": "寻找图像生成接口",
        "page_type": "工具页",
        "priority": 3,
        "notes": "含低价和替代词，可以做工具页对比现有图像接口。",
        "keywords": [
            "AI image API",
            "cheap AI image API",
            "image generation API",
            "AI image API alternative",
        ],
    },
    {
        "name": "AI Video API",
        "category": "生成 API",
        "search_intent": "寻找视频生成接口",
        "page_type": "工具页",
        "priority": 3,
        "notes": "含低价和替代词，可以做工具页对比现有视频接口。",
        "keywords": [
            "AI video API",
            "cheap AI video API",
            "video generation API",
            "AI video API alternative",
        ],
    },
]


def score_cluster(name: str, page_type: str, keywords: list[str]) -> tuple[int, str]:
    blob = " ".join([name, *keywords]).lower()
    points: list[tuple[str, int]] = []
    if any(token in blob for token in ("api", "cheap", "proxy", "alternative", "setup", "compatible", "base url")):
        points.append(("明确商业意图", 25))
    if page_type in PAGE_TYPES:
        points.append(("适合教程页/对比页/工具页", 20))
    if any(token in blob for token in ("api", "compatible", "proxy", "base url", "gpt", "gemini", "openai")):
        points.append(("可导向 Tokfai / API 注册", 20))
    long_tail = any(
        token in blob for token in ("setup", "base url", "compatible", "proxy", "cheapest", "low cost", "sdk", "endpoint")
    ) or any(len(keyword.split()) >= 4 for keyword in keywords)
    if long_tail:
        points.append(("长尾低竞争入口", 15))
    if page_type in PAGE_TYPES and 1 <= len(keywords) <= 8:
        points.append(("7天内可做页面", 10))
    if any(token in blob for token in ("cheap", "cheapest", "low cost", "alternative", "proxy", "compatible", "base url")):
        points.append(("99元体验包或低价转化路径", 10))
    total = sum(value for _label, value in points)
    if total < 0:
        total = 0
    if total > 100:
        total = 100
    reason = " + ".join(f"{label}(+{value})" for label, value in points) or "无匹配因素"
    return total, reason


def _difficulty(keyword: str) -> str:
    text = keyword.lower()
    if any(token in text for token in ("setup", "base url", "endpoint", "sdk", "cheapest", "low cost", "proxy")):
        return "low"
    if len(keyword.split()) >= 4:
        return "low"
    return "medium"


def seed_keywords() -> dict:
    now = datetime.now(timezone.utc).isoformat()
    created = 0
    skipped = 0
    keywords_created = 0
    conn = connect()
    try:
        for cluster in SEED_CLUSTERS:
            existing = conn.execute(
                "SELECT id FROM keyword_clusters WHERE name = ?",
                (cluster["name"],),
            ).fetchone()
            if existing is not None:
                skipped += 1
                continue
            score, reason = score_cluster(cluster["name"], cluster["page_type"], cluster["keywords"])
            cur = conn.execute(
                """
                INSERT INTO keyword_clusters (
                    name, category, search_intent, page_type, priority, status,
                    score, notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cluster["name"],
                    cluster["category"],
                    cluster["search_intent"],
                    cluster["page_type"],
                    cluster["priority"],
                    "open",
                    score,
                    cluster["notes"],
                    now,
                    now,
                ),
            )
            cluster_id = int(cur.lastrowid)
            created += 1
            for keyword in cluster["keywords"]:
                item = conn.execute(
                    """
                    INSERT OR IGNORE INTO keyword_items (
                        cluster_id, keyword, intent, difficulty, source, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cluster_id,
                        keyword,
                        cluster["search_intent"],
                        _difficulty(keyword),
                        "seed",
                        "open",
                        now,
                    ),
                )
                keywords_created += item.rowcount if item.rowcount > 0 else 0
            conn.execute(
                """
                INSERT INTO keyword_scores (cluster_id, score, reason, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (cluster_id, score, reason, now),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {
        "clusters_created": created,
        "clusters_skipped": skipped,
        "keywords_created": keywords_created,
    }


def list_keywords() -> list[dict]:
    conn = connect()
    try:
        rows = conn.execute(
            """
            SELECT id, name, category, search_intent, page_type, priority, status, score, notes
            FROM keyword_clusters
            ORDER BY score DESC, priority ASC, id ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_keyword_cluster(cluster_id: int) -> dict | None:
    conn = connect()
    try:
        row = conn.execute(
            """
            SELECT id, name, category, search_intent, page_type, priority, status, score, notes
            FROM keyword_clusters
            WHERE id = ?
            """,
            (cluster_id,),
        ).fetchone()
        if row is None:
            return None
        cluster = dict(row)
        items = conn.execute(
            """
            SELECT id, keyword, intent, difficulty, source, status
            FROM keyword_items
            WHERE cluster_id = ?
            ORDER BY id ASC
            """,
            (cluster_id,),
        ).fetchall()
        cluster["items"] = [dict(item) for item in items]
        return cluster
    finally:
        conn.close()


def get_keyword_analysis(cluster_id: int) -> dict | None:
    conn = connect()
    try:
        row = conn.execute(
            """
            SELECT id, cluster_id, model, analysis, elapsed_seconds, created_at
            FROM keyword_analysis
            WHERE cluster_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (cluster_id,),
        ).fetchone()
        if row is None:
            return None
        return dict(row)
    finally:
        conn.close()


def save_keyword_analysis(cluster_id: int, model: str, analysis: str, elapsed_seconds: int) -> dict:
    created_at = datetime.now(timezone.utc).isoformat()
    conn = connect()
    try:
        cur = conn.execute(
            """
            INSERT INTO keyword_analysis (cluster_id, model, analysis, elapsed_seconds, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (cluster_id, model, analysis, elapsed_seconds, created_at),
        )
        conn.commit()
        return {
            "id": cur.lastrowid,
            "cluster_id": cluster_id,
            "model": model,
            "analysis": analysis,
            "elapsed_seconds": elapsed_seconds,
            "created_at": created_at,
        }
    finally:
        conn.close()


def keyword_prompt(cluster: dict) -> str:
    lines = [
        f"name: {cluster.get('name') or ''}",
        f"category: {cluster.get('category') or ''}",
        f"search_intent: {cluster.get('search_intent') or ''}",
        f"page_type: {cluster.get('page_type') or ''}",
        f"score: {cluster.get('score') or 0}",
        f"notes: {cluster.get('notes') or ''}",
        "keywords:",
    ]
    for item in cluster.get("items") or []:
        keyword = (item.get("keyword") or "")[:200]
        intent = item.get("intent") or ""
        difficulty = item.get("difficulty") or ""
        lines.append(f"- {keyword} | intent: {intent} | difficulty: {difficulty}")
    return "\n".join(lines)
