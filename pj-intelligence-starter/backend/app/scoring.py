import re
from datetime import datetime, timezone

KEYWORDS = [
    "ai",
    "agent",
    "openai",
    "google",
    "anthropic",
    "model",
    "coding",
    "developer",
    "product",
    "startup",
    "funding",
    "saas",
    "api",
    "automation",
    "robotics",
    "medical",
    "healthcare",
]

KEYWORD_POINTS = 5


def title_keyword_score(title: str) -> int:
    text = title or ""
    score = 0
    for word in KEYWORDS:
        if re.search(rf"\b{re.escape(word)}s?\b", text, flags=re.IGNORECASE):
            score += KEYWORD_POINTS
    return score


def _as_utc(published_at: datetime | None) -> datetime | None:
    if published_at is None:
        return None
    if published_at.tzinfo is None:
        return published_at.replace(tzinfo=timezone.utc)
    return published_at.astimezone(timezone.utc)


def recency_score(published_at: datetime | None, now: datetime | None = None) -> int:
    published = _as_utc(published_at)
    if published is None:
        return 0
    current = _as_utc(now) or datetime.now(timezone.utc)
    age_hours = (current - published).total_seconds() / 3600
    if age_hours <= 24:
        return 20
    if age_hours <= 24 * 3:
        return 10
    if age_hours <= 24 * 7:
        return 5
    return 0


def hn_points(hn_score: int | float | None) -> float:
    if hn_score is None:
        return 0
    try:
        value = float(hn_score)
    except (TypeError, ValueError):
        return 0
    if value <= 0:
        return 0
    return min(value / 10, 30)


def compute_score(
    source_weight: int | float,
    title: str,
    published_at: datetime | None,
    hn_score: int | float | None = None,
    now: datetime | None = None,
) -> int:
    raw = (
        float(source_weight) * 10
        + title_keyword_score(title)
        + recency_score(published_at, now=now)
        + hn_points(hn_score)
    )
    if raw < 0:
        return 0
    if raw > 100:
        return 100
    return int(round(raw))
