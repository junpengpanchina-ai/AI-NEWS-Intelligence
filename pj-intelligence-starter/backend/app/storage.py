import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.db import connect, db_path

logger = logging.getLogger("pj.storage")
_COUNT_TABLES = ("raw_source_records", "intelligence_feed", "intelligence_dossiers")
_WRITE_STAMPS = (
    ("raw_source_records", "created_at"),
    ("intelligence_feed", "created_at"),
    ("intelligence_dossiers", "updated_at"),
)


def _size_mb(path: Path) -> float:
    total = path.stat().st_size if path.exists() else 0
    for suffix in ("-wal", "-shm"):
        extra = Path(f"{path}{suffix}")
        if extra.exists():
            total += extra.stat().st_size
    return round(total / (1024 * 1024), 1)


def _writable(directory: Path) -> bool:
    probe = directory / ".storage-write-probe"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _volume_mounted(directory: Path) -> bool:
    try:
        target = directory.resolve()
        if target.is_mount():
            return True
    except OSError:
        return False
    mounts = Path("/proc/mounts")
    if not mounts.exists():
        return False
    try:
        text = mounts.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    wanted = str(target)
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1].replace("\\040", " ") == wanted:
            return True
    return False


def _table_count(conn: sqlite3.Connection, name: str) -> int:
    found = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    if found is None:
        return 0
    return int(conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])


def _last_write_at(conn: sqlite3.Connection, path: Path) -> str:
    stamps = []
    if path.exists():
        stamps.append(datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat())
    for table, column in _WRITE_STAMPS:
        found = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")} if found else set()
        if column not in columns:
            continue
        row = conn.execute(f"SELECT MAX({column}) FROM {table}").fetchone()
        if row and row[0]:
            stamps.append(str(row[0]))
    return max(stamps) if stamps else ""


def storage_facts() -> dict:
    path = db_path()
    mounted = _volume_mounted(path.parent)
    return {
        "database_type": "sqlite",
        "database_path": str(path),
        "database_exists": path.exists(),
        "database_size_mb": _size_mb(path) if path.exists() else 0,
        "writable": _writable(path.parent),
        "persistent_volume": mounted,
    }


def log_storage_startup() -> None:
    facts = storage_facts()
    logger.info(
        "database_type=%s database_path=%s database_exists=%s database_size_mb=%s writable=%s mounted_volume_detected=%s",
        facts["database_type"],
        facts["database_path"],
        str(facts["database_exists"]).lower(),
        facts["database_size_mb"],
        str(facts["writable"]).lower(),
        str(facts["persistent_volume"]).lower(),
    )


def storage_health() -> dict:
    path = db_path()
    facts = storage_facts()
    conn = connect()
    try:
        tables = {name: _table_count(conn, name) for name in _COUNT_TABLES}
        last_write_at = _last_write_at(conn, path)
    finally:
        conn.close()
    from app.explorer import external_opportunities

    tables["external_opportunities"] = int(external_opportunities(limit=1, offset=0).get("total") or 0)
    facts["tables"] = tables
    facts["last_write_at"] = last_write_at
    return facts


def backup_database() -> dict:
    source_path = db_path()
    if not source_path.exists():
        raise ValueError("数据库文件不存在")
    folder = source_path.parent / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"pj_intelligence_{stamp}.db"
    dest = folder / filename
    if dest.exists():
        filename = f"pj_intelligence_{stamp}_{datetime.now(timezone.utc).strftime('%f')}.db"
        dest = folder / filename
    source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True, timeout=30)
    try:
        target = sqlite3.connect(dest, timeout=30)
        try:
            source.backup(target)
        finally:
            target.close()
    except Exception:
        if dest.exists():
            dest.unlink()
        raise
    finally:
        source.close()
    created_at = datetime.now(timezone.utc).isoformat()
    logger.info("backup_filename=%s backup_size_mb=%s", filename, _size_mb(dest))
    return {"filename": filename, "size_mb": _size_mb(dest), "created_at": created_at}
