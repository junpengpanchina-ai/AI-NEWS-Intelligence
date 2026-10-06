import os
import re
import threading
from collections import deque
from datetime import datetime, timezone

_lock = threading.Lock()
_traces: deque[dict] = deque(maxlen=100)


def _safe_note(note: str) -> str:
    text = note or ""
    for env_name in ("LLM_API_KEY", "GOOGLE_CSE_API_KEY", "SERPER_API_KEY"):
        secret = os.getenv(env_name, "").strip()
        if secret:
            text = text.replace(secret, "[redacted]")
    text = re.sub(r"(?i)bearer\s+\S+", "Bearer [redacted]", text)
    text = re.sub(r"(?i)authorization\s*[:=]\s*\S+", "Authorization [redacted]", text)
    text = re.sub(r"(?i)x-api-key\s*[:=]\s*\S+", "X-API-KEY [redacted]", text)
    text = re.sub(r"(?i)([?&]key=)[^&\s]+", r"\1[redacted]", text)
    return text[:500]


def record_trace(method: str, path: str, status_code: int | str | None, elapsed_ms: int, kind: str, note: str = "") -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "method": method,
        "path": _safe_note(path),
        "status_code": status_code,
        "elapsed_ms": max(0, int(elapsed_ms)),
        "kind": kind,
        "note": _safe_note(note),
    }
    with _lock:
        _traces.append(entry)


def list_traces() -> list[dict]:
    with _lock:
        return list(reversed(_traces))


def clear_traces() -> None:
    with _lock:
        _traces.clear()
