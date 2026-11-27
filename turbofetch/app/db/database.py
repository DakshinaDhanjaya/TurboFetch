import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

from turbofetch.app.db.models import (
    DownloadRecord,
    HistoryRecord,
    QueueRecord,
    ScheduleRecord,
    SegmentRecord,
)
from turbofetch.app.utils.logger import get_logger

logger = get_logger("db")

_DOWNLOADS_TABLE = """
CREATE TABLE IF NOT EXISTS downloads (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    final_url TEXT NOT NULL,
    filename TEXT NOT NULL,
    save_path TEXT NOT NULL,
    size INTEGER DEFAULT -1,
    downloaded INTEGER DEFAULT 0,
    status TEXT DEFAULT 'queued',
    speed REAL DEFAULT 0.0,
    connections INTEGER DEFAULT 0,
    max_connections INTEGER DEFAULT 8,
    date_added REAL NOT NULL,
    date_completed REAL,
    error TEXT,
    etag TEXT,
    last_modified TEXT,
    headers_json TEXT DEFAULT '{}',
    cookies_json TEXT DEFAULT '{}',
    proxy TEXT,
    checksum TEXT,
    checksum_type TEXT,
    category TEXT DEFAULT 'other',
    queue_name TEXT DEFAULT 'default',
    priority INTEGER DEFAULT 0,
    resumable INTEGER DEFAULT 0
)
"""

_SEGMENTS_TABLE = """
CREATE TABLE IF NOT EXISTS segments (
    id INTEGER NOT NULL,
    download_id TEXT NOT NULL,
    start_byte INTEGER NOT NULL,
    end_byte INTEGER NOT NULL,
    downloaded INTEGER DEFAULT 0,
    state TEXT DEFAULT 'pending',
    error TEXT,
    PRIMARY KEY (download_id, id),
    FOREIGN KEY (download_id) REFERENCES downloads(id) ON DELETE CASCADE
)
"""

_QUEUES_TABLE = """
CREATE TABLE IF NOT EXISTS queues (
    name TEXT PRIMARY KEY,
    max_concurrent INTEGER DEFAULT 3,
    is_active INTEGER DEFAULT 0,
    priority INTEGER DEFAULT 0
)
"""

_SCHEDULES_TABLE = """
CREATE TABLE IF NOT EXISTS schedules (
    id TEXT PRIMARY KEY,
    queue_name TEXT NOT NULL,
    action TEXT NOT NULL,
    time TEXT NOT NULL,
    days TEXT DEFAULT 'daily',
    enabled INTEGER DEFAULT 1,
    on_completion TEXT DEFAULT 'nothing'
)
"""

_HISTORY_TABLE = """
CREATE TABLE IF NOT EXISTS history (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    filename TEXT NOT NULL,
    save_path TEXT NOT NULL,
    size INTEGER DEFAULT 0,
    date_completed REAL NOT NULL,
    category TEXT DEFAULT 'other'
)
"""


class Database:
    def __init__(self, db_path: Optional[Path] = None) -> None:
        if db_path is None:
            db_path = Path.home() / "AppData" / "Local" / "TurboFetch" / "turbofetch.db"
        self._db_path = db_path
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            conn = sqlite3.connect(str(self._db_path), timeout=30, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA temp_store=MEMORY")
            conn.execute("PRAGMA cache_size=-4000")
            conn.execute("PRAGMA foreign_keys=ON")
            self._conn = conn
        return self._conn

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = self._get_conn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def initialize(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as conn:
            conn.execute(_DOWNLOADS_TABLE)
            conn.execute(_SEGMENTS_TABLE)
            conn.execute(_QUEUES_TABLE)
            conn.execute(_SCHEDULES_TABLE)
            conn.execute(_HISTORY_TABLE)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_downloads_status ON downloads(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_downloads_category ON downloads(category)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_downloads_queue ON downloads(queue_name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_segments_download ON segments(download_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_history_date ON history(date_completed)")
            self._run_migrations(conn)
            conn.execute(
                "INSERT OR IGNORE INTO queues (name, max_concurrent, is_active, priority) VALUES (?, ?, ?, ?)",
                ("default", 3, 0, 0),
            )
        logger.info("Database initialized at %s", self._db_path)

    def _run_migrations(self, conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)")
        row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
        current_version = row["v"] if row and row["v"] is not None else 0
        migrations: list[tuple[int, list[str]]] = []
        for version, statements in migrations:
            if version > current_version:
                for stmt in statements:
                    conn.execute(stmt)
                conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))

    def _row_to_download(self, row: sqlite3.Row) -> DownloadRecord:
        d = dict(row)
        d["resumable"] = bool(d.get("resumable", 0))
        return DownloadRecord(**d)

    def _row_to_segment(self, row: sqlite3.Row) -> SegmentRecord:
        return SegmentRecord(**dict(row))

    def _row_to_queue(self, row: sqlite3.Row) -> QueueRecord:
        d = dict(row)
        d["is_active"] = bool(d.get("is_active", 0))
        return QueueRecord(**d)

    def _row_to_schedule(self, row: sqlite3.Row) -> ScheduleRecord:
        d = dict(row)
        d["enabled"] = bool(d.get("enabled", 1))
        return ScheduleRecord(**d)

    def _row_to_history(self, row: sqlite3.Row) -> HistoryRecord:
        return HistoryRecord(**dict(row))

    def insert_download(self, record: DownloadRecord) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO downloads (
                    id, url, final_url, filename, save_path, size, downloaded,
                    status, speed, connections, max_connections, date_added,
                    date_completed, error, etag, last_modified, headers_json,
                    cookies_json, proxy, checksum, checksum_type, category,
                    queue_name, priority, resumable
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.id,
                    record.url,
                    record.final_url,
                    record.filename,
                    record.save_path,
                    record.size,
                    record.downloaded,
                    record.status,
                    record.speed,
                    record.connections,
                    record.max_connections,
                    record.date_added,
                    record.date_completed,
                    record.error,
                    record.etag,
                    record.last_modified,
                    record.headers_json,
                    record.cookies_json,
                    record.proxy,
                    record.checksum,
                    record.checksum_type,
                    record.category,
                    record.queue_name,
                    record.priority,
                    int(record.resumable),
                ),
            )

    def upsert_download(self, record: DownloadRecord) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO downloads (
                    id, url, final_url, filename, save_path, size, downloaded,
                    status, speed, connections, max_connections, date_added,
                    date_completed, error, etag, last_modified, headers_json,
                    cookies_json, proxy, checksum, checksum_type, category,
                    queue_name, priority, resumable
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.id,
                    record.url,
                    record.final_url,
                    record.filename,
                    record.save_path,
                    record.size,
                    record.downloaded,
                    record.status,
                    record.speed,
                    record.connections,
                    record.max_connections,
                    record.date_added,
                    record.date_completed,
                    record.error,
                    record.etag,
                    record.last_modified,
                    record.headers_json,
                    record.cookies_json,
                    record.proxy,
                    record.checksum,
                    record.checksum_type,
                    record.category,
                    record.queue_name,
                    record.priority,
                    int(record.resumable),
                ),
            )

    def update_download(self, record: DownloadRecord) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """UPDATE downloads SET
                    url=?, final_url=?, filename=?, save_path=?, size=?, downloaded=?,
                    status=?, speed=?, connections=?, max_connections=?, date_added=?,
                    date_completed=?, error=?, etag=?, last_modified=?, headers_json=?,
                    cookies_json=?, proxy=?, checksum=?, checksum_type=?, category=?,
                    queue_name=?, priority=?, resumable=?
                WHERE id=?""",
                (
                    record.url,
                    record.final_url,
                    record.filename,
                    record.save_path,
                    record.size,
                    record.downloaded,
                    record.status,
                    record.speed,
                    record.connections,
                    record.max_connections,
                    record.date_added,
                    record.date_completed,
                    record.error,
                    record.etag,
                    record.last_modified,
                    record.headers_json,
                    record.cookies_json,
                    record.proxy,
                    record.checksum,
                    record.checksum_type,
                    record.category,
                    record.queue_name,
                    record.priority,
                    int(record.resumable),
                    record.id,
                ),
            )

    def update_download_status(
        self, download_id: str, status: str, error: Optional[str] = None
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE downloads SET status=?, error=? WHERE id=?",
                (status, error, download_id),
            )

    def update_download_progress(
        self, download_id: str, downloaded: int, speed: float
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE downloads SET downloaded=?, speed=? WHERE id=?",
                (downloaded, speed, download_id),
            )

    def get_download(self, download_id: str) -> Optional[DownloadRecord]:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM downloads WHERE id=?", (download_id,)).fetchone()
            return self._row_to_download(row) if row else None

    def get_all_downloads(self) -> list[DownloadRecord]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM downloads ORDER BY date_added DESC").fetchall()
            return [self._row_to_download(r) for r in rows]

    def get_downloads_by_status(self, status: str) -> list[DownloadRecord]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM downloads WHERE status=? ORDER BY date_added DESC",
                (status,),
            ).fetchall()
            return [self._row_to_download(r) for r in rows]

    def get_downloads_by_category(self, category: str) -> list[DownloadRecord]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM downloads WHERE category=? ORDER BY date_added DESC",
                (category,),
            ).fetchall()
            return [self._row_to_download(r) for r in rows]

    def get_downloads_by_queue(self, queue_name: str) -> list[DownloadRecord]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM downloads WHERE queue_name=? ORDER BY priority ASC, date_added ASC",
                (queue_name,),
            ).fetchall()
            return [self._row_to_download(r) for r in rows]

    def update_download_queue(
        self, download_id: str, queue_name: str, priority: int = 0
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE downloads SET queue_name=?, priority=? WHERE id=?",
                (queue_name, priority, download_id),
            )

    def delete_download(self, download_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM downloads WHERE id=?", (download_id,))

    def search_downloads(self, query: str) -> list[DownloadRecord]:
        with self._lock, self._connect() as conn:
            pattern = f"%{query}%"
            rows = conn.execute(
                """SELECT * FROM downloads
                WHERE filename LIKE ? OR url LIKE ? OR category LIKE ?
                ORDER BY date_added DESC""",
                (pattern, pattern, pattern),
            ).fetchall()
            return [self._row_to_download(r) for r in rows]

    def save_segments(self, download_id: str, segments: list[SegmentRecord]) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM segments WHERE download_id=?", (download_id,))
            conn.executemany(
                """INSERT INTO segments (
                    id, download_id, start_byte, end_byte, downloaded, state, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        s.id,
                        download_id,
                        s.start_byte,
                        s.end_byte,
                        s.downloaded,
                        s.state,
                        s.error,
                    )
                    for s in segments
                ],
            )

    def get_segments(self, download_id: str) -> list[SegmentRecord]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM segments WHERE download_id=? ORDER BY id ASC",
                (download_id,),
            ).fetchall()
            return [self._row_to_segment(r) for r in rows]

    def update_segment(self, segment: SegmentRecord) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """UPDATE segments SET
                    start_byte=?, end_byte=?, downloaded=?, state=?, error=?
                WHERE download_id=? AND id=?""",
                (
                    segment.start_byte,
                    segment.end_byte,
                    segment.downloaded,
                    segment.state,
                    segment.error,
                    segment.download_id,
                    segment.id,
                ),
            )

    def delete_segments(self, download_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM segments WHERE download_id=?", (download_id,))

    def bulk_update_segments(self, segments: list[SegmentRecord]) -> None:
        with self._lock, self._connect() as conn:
            conn.executemany(
                """UPDATE segments SET
                    start_byte=?, end_byte=?, downloaded=?, state=?, error=?
                WHERE download_id=? AND id=?""",
                [
                    (
                        s.start_byte,
                        s.end_byte,
                        s.downloaded,
                        s.state,
                        s.error,
                        s.download_id,
                        s.id,
                    )
                    for s in segments
                ],
            )

    def create_queue(self, record: QueueRecord) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO queues (name, max_concurrent, is_active, priority)
                VALUES (?, ?, ?, ?)""",
                (record.name, record.max_concurrent, int(record.is_active), record.priority),
            )

    def get_queue(self, name: str) -> Optional[QueueRecord]:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM queues WHERE name=?", (name,)).fetchone()
            return self._row_to_queue(row) if row else None

    def get_all_queues(self) -> list[QueueRecord]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM queues ORDER BY priority ASC, name ASC").fetchall()
            return [self._row_to_queue(r) for r in rows]

    def update_queue(self, record: QueueRecord) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """UPDATE queues SET max_concurrent=?, is_active=?, priority=? WHERE name=?""",
                (record.max_concurrent, int(record.is_active), record.priority, record.name),
            )

    def delete_queue(self, name: str) -> None:
        if name == "default":
            return
        with self._lock, self._connect() as conn:
            conn.execute("UPDATE downloads SET queue_name='default' WHERE queue_name=?", (name,))
            conn.execute("DELETE FROM queues WHERE name=?", (name,))

    def save_schedule(self, record: ScheduleRecord) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO schedules (
                    id, queue_name, action, time, days, enabled, on_completion
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.id,
                    record.queue_name,
                    record.action,
                    record.time,
                    record.days,
                    int(record.enabled),
                    record.on_completion,
                ),
            )

    def get_all_schedules(self) -> list[ScheduleRecord]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM schedules ORDER BY time ASC").fetchall()
            return [self._row_to_schedule(r) for r in rows]

    def update_schedule(self, record: ScheduleRecord) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """UPDATE schedules SET
                    queue_name=?, action=?, time=?, days=?, enabled=?, on_completion=?
                WHERE id=?""",
                (
                    record.queue_name,
                    record.action,
                    record.time,
                    record.days,
                    int(record.enabled),
                    record.on_completion,
                    record.id,
                ),
            )

    def delete_schedule(self, schedule_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM schedules WHERE id=?", (schedule_id,))

    def add_to_history(self, record: HistoryRecord) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO history (
                    id, url, filename, save_path, size, date_completed, category
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.id,
                    record.url,
                    record.filename,
                    record.save_path,
                    record.size,
                    record.date_completed,
                    record.category,
                ),
            )

    def get_history(self, limit: int = 100, offset: int = 0) -> list[HistoryRecord]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM history ORDER BY date_completed DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return [self._row_to_history(r) for r in rows]

    def search_history(self, query: str) -> list[HistoryRecord]:
        with self._lock, self._connect() as conn:
            pattern = f"%{query}%"
            rows = conn.execute(
                """SELECT * FROM history
                WHERE filename LIKE ? OR url LIKE ?
                ORDER BY date_completed DESC""",
                (pattern, pattern),
            ).fetchall()
            return [self._row_to_history(r) for r in rows]

    def clear_history(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM history")

    def export_downloads(self, path: Path) -> None:
        downloads = self.get_all_downloads()
        data = []
        for dl in downloads:
            entry = dl.to_dict()
            entry["segments"] = [s.to_dict() for s in self.get_segments(dl.id)]
            data.append(entry)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        logger.info("Exported %d downloads to %s", len(data), path)

    def import_downloads(self, path: Path) -> int:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        imported = 0
        for entry in data:
            segments_data = entry.pop("segments", [])
            record = DownloadRecord.from_dict(entry)
            if self.get_download(record.id) is not None:
                continue
            self.insert_download(record)
            if segments_data:
                segments = [SegmentRecord.from_dict({**s, "download_id": record.id}) for s in segments_data]
                self.save_segments(record.id, segments)
            imported += 1
        logger.info("Imported %d downloads from %s", imported, path)
        return imported

    def get_total_downloaded_bytes(self) -> int:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(downloaded), 0) AS total FROM downloads"
            ).fetchone()
            return int(row["total"])

    def get_download_count_by_status(self) -> dict[str, int]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS cnt FROM downloads GROUP BY status"
            ).fetchall()
            return {row["status"]: int(row["cnt"]) for row in rows}
