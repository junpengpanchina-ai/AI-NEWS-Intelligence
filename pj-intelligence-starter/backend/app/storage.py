import csv
import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.db import connect, db_path

logger = logging.getLogger("pj.storage")
_COUNT_TABLES = ("raw_source_records", "intelligence_feed", "intelligence_dossiers", "dossier_evidence_items")
_EXPORT_TABLES = (
    "raw_source_records",
    "intelligence_feed",
    "intelligence_dossiers",
    "dossier_evidence_items",
)
_SKIP_COLUMNS = {"raw_json", "errors_json"}
_COLUMN_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_BACKUP_NAME = re.compile(r"^pj_intelligence_(\d{8})_(\d{6})(?:_\d+)?\.db$")
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


def _backups_dir() -> Path:
    return db_path().parent / "backups"


def _exports_dir() -> Path:
    return db_path().parent / "exports"


def _backup_created(path: Path) -> str:
    match = _BACKUP_NAME.match(path.name)
    if match:
        stamp = datetime.strptime(match.group(1) + match.group(2), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        return stamp.isoformat()
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()


def list_backups() -> list[dict]:
    folder = _backups_dir()
    if not folder.exists():
        return []
    items = []
    for path in folder.iterdir():
        if not path.is_file() or not _BACKUP_NAME.match(path.name):
            continue
        items.append(
            {
                "file_name": path.name,
                "size_mb": _size_mb(path),
                "created_at": _backup_created(path),
                "path": str(path),
            }
        )
    items.sort(key=lambda item: item["created_at"], reverse=True)
    return items


def _export_files() -> list[Path]:
    folder = _exports_dir()
    if not folder.exists():
        return []
    return sorted((path for path in folder.iterdir() if path.is_file() and path.suffix == ".csv"), key=lambda item: item.name)


def _core_counts(conn: sqlite3.Connection) -> dict[str, int]:
    counts = {name: _table_count(conn, name) for name in _COUNT_TABLES}
    from app.explorer import external_opportunities

    counts["external_opportunities"] = int(external_opportunities(limit=1, offset=0).get("total") or 0)
    return counts


def storage_health() -> dict:
    path = db_path()
    facts = storage_facts()
    conn = connect()
    try:
        tables = _core_counts(conn)
        last_write_at = _last_write_at(conn, path)
    finally:
        conn.close()
    backups = list_backups()
    exports = _export_files()
    facts["tables"] = tables
    facts["last_write_at"] = last_write_at
    facts["backup_count"] = len(backups)
    facts["last_backup_at"] = backups[0]["created_at"] if backups else ""
    facts["export_count"] = len(exports)
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
    conn = connect()
    try:
        tables_count = _core_counts(conn)
    finally:
        conn.close()
    size_mb = _size_mb(dest)
    logger.info("backup_file=%s size_mb=%s table_count=%s", filename, size_mb, len(tables_count))
    return {
        "backup_file": filename,
        "size_mb": size_mb,
        "created_at": created_at,
        "tables_count": tables_count,
    }


def _export_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    names = []
    for row in conn.execute(f"PRAGMA table_info({table})"):
        name = row[1]
        if name in _SKIP_COLUMNS or not _COLUMN_NAME.match(name or ""):
            continue
        names.append(name)
    return names


def _csv_cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        text = " | ".join(str(item) for item in value)
    else:
        text = str(value)
    text = " ".join(text.split())
    if len(text) > 4000:
        return "[truncated]"
    return text


def _write_csv(path: Path, columns: list[str], rows) -> int:
    count = 0
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        for row in rows:
            if isinstance(row, dict):
                values = [_csv_cell(row.get(name, "")) for name in columns]
            else:
                values = [_csv_cell(row[index]) for index, _name in enumerate(columns)]
            writer.writerow(values)
            count += 1
    return count


def export_csv() -> dict:
    folder = _exports_dir()
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    created_at = datetime.now(timezone.utc).isoformat()
    files = []
    conn = connect()
    try:
        for table in _EXPORT_TABLES:
            columns = _export_columns(conn, table)
            filename = f"{table}_{stamp}.csv"
            dest = folder / filename
            if not columns:
                files.append({"table": table, "file_name": filename, "rows": 0, "size_mb": 0})
                dest.write_text("", encoding="utf-8")
                continue
            quoted = ", ".join(columns)
            cursor = conn.execute(f"SELECT {quoted} FROM {table}")
            rows = (dict(zip(columns, row)) for row in cursor)
            count = _write_csv(dest, columns, rows)
            files.append({"table": table, "file_name": filename, "rows": count, "size_mb": _size_mb(dest)})
            logger.info("export_table=%s export_rows=%s export_file=%s", table, count, filename)
    finally:
        conn.close()
    from app.explorer import external_opportunities

    page = external_opportunities(all_rows=True)
    items = page.get("items") or []
    columns = [
        "domain",
        "opportunity_score",
        "opportunity_tier",
        "evidence_count",
        "evidence_tags",
        "missing_evidence",
        "next_action",
        "reason",
        "latest_signal",
        "latest_month",
        "recommended_action",
    ]
    filename = f"external_opportunities_{stamp}.csv"
    dest = folder / filename
    count = _write_csv(dest, columns, items)
    files.append({"table": "external_opportunities", "file_name": filename, "rows": count, "size_mb": _size_mb(dest)})
    logger.info("export_table=external_opportunities export_rows=%s export_file=%s", count, filename)
    return {"files": files, "created_at": created_at}
