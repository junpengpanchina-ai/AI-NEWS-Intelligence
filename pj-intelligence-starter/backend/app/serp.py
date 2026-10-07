from app.google_search import (
    GOOGLE_CSE_BLOCKED,
    MANUAL_CSV_HINT,
    GoogleSearchError,
    google_cse_blocked,
    search_google,
    serp_provider,
)
from app.serper import search_serper


def _ranked(items: list[dict]) -> list[dict]:
    ranked = []
    for index, item in enumerate(items, start=1):
        row = {
            "title": item.get("title") or "",
            "link": item.get("link") or "",
            "displayLink": item.get("displayLink") or "",
            "snippet": item.get("snippet") or "",
            "rank": item.get("rank") or index,
        }
        ranked.append(row)
    return ranked


def search_serp(query: str, num: int = 10, gl: str = "us", hl: str = "en") -> dict:
    text = (query or "").strip()
    provider = serp_provider()
    if provider == "manual_csv":
        raise GoogleSearchError(MANUAL_CSV_HINT, 400)
    if provider == "google_cse":
        if google_cse_blocked():
            raise GoogleSearchError(GOOGLE_CSE_BLOCKED, 400)
        items = _ranked(search_google(text, num))
        return {
            "provider": "google_cse",
            "query": text,
            "count": len(items),
            "items": items,
        }
    if provider == "serper":
        return search_serper(text, num, gl, hl)
    raise GoogleSearchError(f"当前 SERP_PROVIDER={provider}，尚未接入。", 400)
