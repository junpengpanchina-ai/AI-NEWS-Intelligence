from datetime import datetime, timezone

from app.competitors import list_competitors
from app.db import connect
from app.keywords import _conversion, _delivery, _tokfai, get_keyword_cluster

VERDICTS = ("Build", "Research", "Observe", "Reject")
SAMPLE_GAP = "竞品样本不足，当前只能 Research 或 Observe。"
BUILD_PAGE_TYPES = {"tutorial", "api_docs", "comparison"}
CLUSTER_PAGE_TYPES = {
    "教程页": "tutorial",
    "对比页": "comparison",
    "API 文档页": "api_docs",
    "工具页": "tool",
    "榜单页": "listicle",
}


def _clip(value, limit: int) -> str:
    text = str(value or "").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[:limit]


def _page_type(cluster: dict, page: dict | None) -> str:
    if page and page.get("page_type") in BUILD_PAGE_TYPES:
        return page["page_type"]
    mapped = CLUSTER_PAGE_TYPES.get(cluster.get("page_type") or "")
    if mapped:
        return mapped
    if page and page.get("page_type"):
        return page["page_type"]
    return "unknown"


def _target_keyword(cluster: dict, page: dict | None) -> str:
    if page and (page.get("target_keyword") or "").strip():
        return page["target_keyword"].strip()
    for item in cluster.get("items") or []:
        keyword = (item.get("keyword") or "").strip()
        if keyword:
            return keyword
    return cluster.get("name") or ""


def _summary(pages: list[dict]) -> str:
    if not pages:
        return "该关键词簇下还没有竞品页面。"
    parts = []
    for page in pages[:3]:
        parts.append(
            f"{page.get('title') or page.get('domain') or '未命名'} "
            f"{page.get('page_type') or 'unknown'} "
            f"可复制{int(page.get('copyability_score') or 0)} "
            f"风险{page.get('risk_level') or 'unknown'}"
        )
    extra = ""
    if len(pages) > 3:
        extra = f" 另有 {len(pages) - 3} 个页面。"
    return f"共 {len(pages)} 个竞品页。" + "；".join(parts) + "。" + extra


def decide_opportunity(cluster: dict, pages: list[dict]) -> dict:
    keywords = [item.get("keyword") or "" for item in cluster.get("items") or []]
    name = cluster.get("name") or ""
    score = int(cluster.get("score") or 0)
    cluster_page = cluster.get("page_type") or ""
    tokfai_points, _tokfai_text = _tokfai(name, keywords)
    conv_points, _conv_text = _conversion(name, keywords, cluster_page)
    delivery_points, _delivery_text = _delivery(name, cluster_page)
    qualifying = [
        page
        for page in pages
        if int(page.get("copyability_score") or 0) >= 75 and page.get("page_type") in BUILD_PAGE_TYPES
    ]
    qualifying.sort(key=lambda page: int(page.get("copyability_score") or 0), reverse=True)
    ranked = sorted(pages, key=lambda page: int(page.get("copyability_score") or 0), reverse=True)
    best_any = ranked[0] if ranked else None
    best = qualifying[0] if qualifying else None
    payment_clear = any((page.get("pricing_signal") or "").strip() or (page.get("payment_signal") or "").strip() for page in pages)
    samples_ok = best is not None
    can_convert = conv_points >= 10
    high_delivery = delivery_points <= 6
    high_risk = bool(pages) and all((page.get("risk_level") or "") == "high" for page in pages)
    off_tokfai = tokfai_points == 0
    page_type = _page_type(cluster, best)
    keyword = _target_keyword(cluster, best)

    if not pages and score >= 50 and not off_tokfai:
        verdict = "Research" if score >= 70 else "Observe"
        reason = SAMPLE_GAP
    elif score >= 85 and samples_ok and can_convert and not high_delivery and not high_risk:
        verdict = "Build"
        reason = "关键词分不低于 85，已有可复制的教程、文档或对比页，并能导向 Tokfai 注册或 99 元体验包。"
    elif score >= 70 and (not samples_ok or not payment_clear) and not high_risk and not off_tokfai:
        verdict = "Research"
        missing = "竞品样本不足" if not samples_ok else "支付路径不清楚"
        reason = f"关键词分不低于 70，但{missing}。"
    elif 50 <= score <= 69 and not high_risk and not off_tokfai:
        verdict = "Observe"
        reason = "关键词分在 50–69，页面以后可以做，当前不优先。"
    elif 70 <= score < 85 and samples_ok and not high_risk and not off_tokfai:
        verdict = "Observe"
        reason = "页面可做，但分数还没到 Build，当前资源不优先。"
    else:
        verdict = "Reject"
        if high_risk:
            reason = "竞品页面风险高，不进入页面生产。"
        elif off_tokfai:
            reason = "不贴 Tokfai，不进入页面生产。"
        elif high_delivery:
            reason = "交付成本高，不进入页面生产。"
        else:
            reason = "无法导向注册或付费，不进入页面生产。"
    if not pages and SAMPLE_GAP not in reason:
        reason = f"{SAMPLE_GAP}{reason}"

    domain = (best_any or {}).get("domain") or ""
    page_label = f"{page_type}：{keyword}"
    actions = {
        "Build": (
            f"用 {page_label} 承接搜索，页内放 Tokfai 注册和 99 元体验包。",
            f"上线一页 {page_label}，参考 {domain or '已记录竞品'}，页内放注册和 99 元体验包。",
            f"7 天上线 {page_label}。",
            "14 天提交收录，补 FAQ，加 schema，加内链到注册页和 99 元体验包。",
            "30 天检查这页是否有收录、曝光、点击。",
            "60 天无注册、无付费、无有效询盘则暂停。",
        ),
        "Research": (
            f"先补竞品样本，再决定是否上线 {page_label}。",
            f"目标页是 {page_label}。样本不足前不发布。",
            f"7 天先不发布。补齐样本后才上线 {page_label}。",
            "14 天在页面存在后提交收录，补 FAQ，加 schema，加内链。样本不足则不做这四项。",
            "30 天检查是否有收录、曝光、点击。没有页面则三项都记为无。",
            "60 天无注册、无付费、无有效询盘则暂停。",
        ),
        "Observe": (
            f"先不排期。候选页是 {page_label}。",
            f"不上线 {page_label}。",
            f"7 天不上线 {page_label}。",
            "14 天不提交收录，不补 FAQ，不加 schema，不加内链。",
            "30 天先不把收录、曝光、点击当作目标。",
            "60 天无注册、无付费、无有效询盘则继续暂停。",
        ),
        "Reject": (
            "不制作页面。",
            f"不上线 {page_label}。",
            f"7 天不上线 {page_label}。",
            "14 天不提交收录，不补 FAQ，不加 schema，不加内链。",
            "30 天不追踪收录、曝光、点击。",
            "60 天无注册、无付费、无有效询盘则暂停。",
        ),
    }
    angle, first_page, seven, fourteen, thirty, sixty = actions[verdict]
    return {
        "title": name or keyword or "未命名项目卡",
        "verdict": verdict,
        "target_keyword": keyword,
        "page_type": page_type,
        "user_intent": cluster.get("search_intent") or "",
        "competitor_summary": _summary(pages),
        "product_angle": angle,
        "first_page_plan": first_page,
        "seven_day_action": seven,
        "fourteen_day_action": fourteen,
        "thirty_day_metric": thirty,
        "sixty_day_stop_rule": sixty,
        "score": score,
        "keyword_score": score,
        "competitor_count": len(pages),
        "best_competitor_score": int((best_any or {}).get("copyability_score") or 0),
        "best_competitor_domain": domain,
        "verdict_reason": reason,
        "status": "open",
        "notes": reason,
    }


def _row(row) -> dict:
    data = dict(row)
    data["score"] = int(data.get("score") or 0)
    data["keyword_score"] = int(data.get("keyword_score") or data["score"] or 0)
    data["competitor_count"] = int(data.get("competitor_count") or 0)
    data["best_competitor_score"] = int(data.get("best_competitor_score") or 0)
    data["best_competitor_domain"] = data.get("best_competitor_domain") or ""
    data["verdict_reason"] = data.get("verdict_reason") or data.get("notes") or ""
    for key in (
        "title",
        "verdict",
        "target_keyword",
        "page_type",
        "user_intent",
        "competitor_summary",
        "product_angle",
        "first_page_plan",
        "seven_day_action",
        "fourteen_day_action",
        "thirty_day_metric",
        "sixty_day_stop_rule",
        "status",
        "notes",
        "created_at",
        "updated_at",
    ):
        data[key] = data.get(key) or ""
    data["cluster_id"] = int(data["cluster_id"])
    return data


def list_opportunities() -> list[dict]:
    conn = connect()
    try:
        rows = conn.execute(
            """
            SELECT id, cluster_id, title, verdict, target_keyword, page_type, user_intent,
                   competitor_summary, product_angle, first_page_plan, seven_day_action,
                   fourteen_day_action, thirty_day_metric, sixty_day_stop_rule,
                   score, keyword_score, competitor_count, best_competitor_score,
                   best_competitor_domain, verdict_reason, status, notes, created_at, updated_at
            FROM opportunity_cards
            ORDER BY score DESC, id ASC
            """
        ).fetchall()
        return [_row(row) for row in rows]
    finally:
        conn.close()


def get_opportunity(card_id: int) -> dict | None:
    conn = connect()
    try:
        row = conn.execute(
            """
            SELECT id, cluster_id, title, verdict, target_keyword, page_type, user_intent,
                   competitor_summary, product_angle, first_page_plan, seven_day_action,
                   fourteen_day_action, thirty_day_metric, sixty_day_stop_rule,
                   score, keyword_score, competitor_count, best_competitor_score,
                   best_competitor_domain, verdict_reason, status, notes, created_at, updated_at
            FROM opportunity_cards
            WHERE id = ?
            """,
            (card_id,),
        ).fetchone()
        if row is None:
            return None
        return _row(row)
    finally:
        conn.close()


_CARD_FIELDS = (
    "title",
    "verdict",
    "target_keyword",
    "page_type",
    "user_intent",
    "competitor_summary",
    "product_angle",
    "first_page_plan",
    "seven_day_action",
    "fourteen_day_action",
    "thirty_day_metric",
    "sixty_day_stop_rule",
    "score",
    "keyword_score",
    "competitor_count",
    "best_competitor_score",
    "best_competitor_domain",
    "verdict_reason",
    "status",
    "notes",
)


def _same_card(current: dict, fields: dict) -> bool:
    for key in _CARD_FIELDS:
        if str(current.get(key) or "") != str(fields.get(key) or ""):
            return False
    return True


def create_opportunity_from_keyword(cluster_id: int) -> dict | None:
    cluster = get_keyword_cluster(cluster_id)
    if cluster is None:
        return None
    pages = list_competitors(cluster_id)
    fields = decide_opportunity(cluster, pages)
    if fields["verdict"] not in VERDICTS:
        raise ValueError("verdict 不在允许列表中")
    now = datetime.now(timezone.utc).isoformat()
    conn = connect()
    try:
        existing = conn.execute(
            """
            SELECT id FROM opportunity_cards
            WHERE cluster_id = ? AND COALESCE(status, '') != 'archived'
            ORDER BY id ASC
            LIMIT 1
            """,
            (cluster_id,),
        ).fetchone()
        if existing is None:
            cur = conn.execute(
                """
                INSERT INTO opportunity_cards (
                    cluster_id, title, verdict, target_keyword, page_type, user_intent,
                    competitor_summary, product_angle, first_page_plan, seven_day_action,
                    fourteen_day_action, thirty_day_metric, sixty_day_stop_rule,
                    score, keyword_score, competitor_count, best_competitor_score,
                    best_competitor_domain, verdict_reason, status, notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cluster_id,
                    fields["title"],
                    fields["verdict"],
                    fields["target_keyword"],
                    fields["page_type"],
                    fields["user_intent"],
                    fields["competitor_summary"],
                    fields["product_angle"],
                    fields["first_page_plan"],
                    fields["seven_day_action"],
                    fields["fourteen_day_action"],
                    fields["thirty_day_metric"],
                    fields["sixty_day_stop_rule"],
                    fields["score"],
                    fields["keyword_score"],
                    fields["competitor_count"],
                    fields["best_competitor_score"],
                    fields["best_competitor_domain"],
                    fields["verdict_reason"],
                    fields["status"],
                    fields["notes"],
                    now,
                    now,
                ),
            )
            card_id = int(cur.lastrowid)
            mode = "created"
            conn.commit()
        else:
            card_id = int(existing["id"])
            conn.close()
            conn = None
            current = get_opportunity(card_id)
            if current and _same_card(current, fields):
                current["mode"] = "existing"
                return current
            conn = connect()
            conn.execute(
                """
                UPDATE opportunity_cards
                SET title = ?, verdict = ?, target_keyword = ?, page_type = ?, user_intent = ?,
                    competitor_summary = ?, product_angle = ?, first_page_plan = ?,
                    seven_day_action = ?, fourteen_day_action = ?, thirty_day_metric = ?,
                    sixty_day_stop_rule = ?, score = ?, keyword_score = ?, competitor_count = ?,
                    best_competitor_score = ?, best_competitor_domain = ?, verdict_reason = ?,
                    status = ?, notes = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    fields["title"],
                    fields["verdict"],
                    fields["target_keyword"],
                    fields["page_type"],
                    fields["user_intent"],
                    fields["competitor_summary"],
                    fields["product_angle"],
                    fields["first_page_plan"],
                    fields["seven_day_action"],
                    fields["fourteen_day_action"],
                    fields["thirty_day_metric"],
                    fields["sixty_day_stop_rule"],
                    fields["score"],
                    fields["keyword_score"],
                    fields["competitor_count"],
                    fields["best_competitor_score"],
                    fields["best_competitor_domain"],
                    fields["verdict_reason"],
                    fields["status"],
                    fields["notes"],
                    now,
                    card_id,
                ),
            )
            mode = "updated"
            conn.commit()
    finally:
        if conn is not None:
            conn.close()
    card = get_opportunity(card_id)
    if card is None:
        return None
    card["mode"] = mode
    return card


def get_opportunity_analysis(card_id: int) -> dict | None:
    conn = connect()
    try:
        row = conn.execute(
            """
            SELECT id, card_id, model, analysis, elapsed_seconds, created_at
            FROM opportunity_analysis
            WHERE card_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (card_id,),
        ).fetchone()
        if row is None:
            return None
        return dict(row)
    finally:
        conn.close()


def save_opportunity_analysis(card_id: int, model: str, analysis: str, elapsed_seconds: int) -> dict:
    created_at = datetime.now(timezone.utc).isoformat()
    conn = connect()
    try:
        cur = conn.execute(
            """
            INSERT INTO opportunity_analysis (card_id, model, analysis, elapsed_seconds, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (card_id, model, analysis, elapsed_seconds, created_at),
        )
        conn.commit()
        return {
            "id": cur.lastrowid,
            "card_id": card_id,
            "model": model,
            "analysis": analysis,
            "elapsed_seconds": elapsed_seconds,
            "created_at": created_at,
        }
    finally:
        conn.close()


def opportunity_prompt(card: dict) -> str:
    lines = [
        "只写6句：1是否维持verdict 2第一页 3七天 4十四天 5三十天 6六十天止损",
        f"title: {_clip(card.get('title'), 40)}",
        f"verdict: {_clip(card.get('verdict'), 12)}",
        f"target_keyword: {_clip(card.get('target_keyword'), 40)}",
        f"page_type: {_clip(card.get('page_type'), 16)}",
        f"score: {int(card.get('score') or 0)}",
        f"user_intent: {_clip(card.get('user_intent'), 40)}",
        f"competitor_summary: {_clip(card.get('competitor_summary'), 80)}",
        f"notes: {_clip(card.get('notes'), 60)}",
    ]
    text = "\n".join(lines)
    if len(text) > 800:
        return text[:800]
    return text
