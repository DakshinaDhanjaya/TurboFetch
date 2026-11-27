import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from turbofetch.app.engine.downloader import DownloadStatus, DownloadTask
from turbofetch.app.engine.segment import Segment, SegmentState


@dataclass
class DownloadRecord:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    url: str = ""
    final_url: str = ""
    filename: str = ""
    save_path: str = ""
    size: int = -1
    downloaded: int = 0
    status: str = DownloadStatus.QUEUED.value
    speed: float = 0.0
    connections: int = 0
    max_connections: int = 8
    date_added: float = field(default_factory=time.time)
    date_completed: Optional[float] = None
    error: Optional[str] = None
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    headers_json: str = "{}"
    cookies_json: str = "{}"
    proxy: Optional[str] = None
    checksum: Optional[str] = None
    checksum_type: Optional[str] = None
    category: str = "other"
    queue_name: str = "default"
    priority: int = 0
    resumable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DownloadRecord":
        valid = {f: data[f] for f in cls.__dataclass_fields__ if f in data}
        if "resumable" in valid:
            valid["resumable"] = bool(valid["resumable"])
        return cls(**valid)

    def to_download_task(self) -> DownloadTask:
        try:
            headers = json.loads(self.headers_json) if self.headers_json else {}
        except json.JSONDecodeError:
            headers = {}
        try:
            cookies = json.loads(self.cookies_json) if self.cookies_json else {}
        except json.JSONDecodeError:
            cookies = {}
        return DownloadTask(
            id=self.id,
            url=self.url,
            final_url=self.final_url or self.url,
            filename=self.filename,
            save_path=self.save_path,
            size=self.size,
            downloaded=self.downloaded,
            status=DownloadStatus(self.status),
            speed=self.speed,
            connections=self.connections,
            max_connections=self.max_connections,
            date_added=self.date_added,
            date_completed=self.date_completed,
            error=self.error,
            etag=self.etag,
            last_modified=self.last_modified,
            headers=headers,
            cookies=cookies,
            proxy=self.proxy,
            checksum=self.checksum,
            checksum_type=self.checksum_type,
            category=self.category,
            queue_name=self.queue_name,
            priority=self.priority,
            resumable=self.resumable,
        )

    @classmethod
    def from_download_task(cls, task: DownloadTask) -> "DownloadRecord":
        return cls(
            id=task.id,
            url=task.url,
            final_url=task.final_url or task.url,
            filename=task.filename,
            save_path=task.save_path,
            size=task.size,
            downloaded=task.downloaded,
            status=task.status.value,
            speed=task.speed,
            connections=task.connections,
            max_connections=task.max_connections,
            date_added=task.date_added,
            date_completed=task.date_completed,
            error=task.error,
            etag=task.etag,
            last_modified=task.last_modified,
            headers_json=json.dumps(task.headers),
            cookies_json=json.dumps(task.cookies),
            proxy=task.proxy,
            checksum=task.checksum,
            checksum_type=task.checksum_type,
            category=task.category,
            queue_name=task.queue_name,
            priority=task.priority,
            resumable=task.resumable,
        )


@dataclass
class SegmentRecord:
    id: int
    download_id: str
    start_byte: int
    end_byte: int
    downloaded: int = 0
    state: str = SegmentState.PENDING.value
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "download_id": self.download_id,
            "start": self.start_byte,
            "end": self.end_byte,
            "downloaded": self.downloaded,
            "state": self.state,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SegmentRecord":
        return cls(
            id=int(data["id"]),
            download_id=str(data["download_id"]),
            start_byte=int(data.get("start_byte", data.get("start", 0))),
            end_byte=int(data.get("end_byte", data.get("end", -1))),
            downloaded=int(data.get("downloaded", 0)),
            state=str(data.get("state", SegmentState.PENDING.value)),
            error=data.get("error"),
        )

    @classmethod
    def from_segment(cls, seg: Segment) -> "SegmentRecord":
        return cls(
            id=seg.id,
            download_id=seg.download_id,
            start_byte=seg.start,
            end_byte=seg.end,
            downloaded=seg.downloaded,
            state=seg.state.value,
            error=seg.error,
        )


@dataclass
class QueueRecord:
    name: str
    max_concurrent: int = 3
    is_active: bool = False
    priority: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "QueueRecord":
        return cls(
            name=str(data["name"]),
            max_concurrent=int(data.get("max_concurrent", 3)),
            is_active=bool(data.get("is_active", False)),
            priority=int(data.get("priority", 0)),
        )


@dataclass
class ScheduleRecord:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    queue_name: str = "default"
    action: str = "start"
    time: str = "00:00"
    days: str = "daily"
    enabled: bool = True
    on_completion: str = "nothing"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScheduleRecord":
        return cls(
            id=str(data.get("id") or uuid.uuid4()),
            queue_name=str(data.get("queue_name", "default")),
            action=str(data.get("action", "start")),
            time=str(data.get("time", "00:00")),
            days=str(data.get("days", "daily")),
            enabled=bool(data.get("enabled", True)),
            on_completion=str(data.get("on_completion", "nothing")),
        )


@dataclass
class HistoryRecord:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    url: str = ""
    filename: str = ""
    save_path: str = ""
    size: int = 0
    date_completed: float = field(default_factory=time.time)
    category: str = "other"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HistoryRecord":
        return cls(
            id=str(data.get("id") or uuid.uuid4()),
            url=str(data.get("url", "")),
            filename=str(data.get("filename", "")),
            save_path=str(data.get("save_path", "")),
            size=int(data.get("size", 0)),
            date_completed=float(data.get("date_completed", time.time())),
            category=str(data.get("category", "other")),
        )
