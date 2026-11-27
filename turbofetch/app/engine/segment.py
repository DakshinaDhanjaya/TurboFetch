import threading
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


class SegmentState(str, Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


@dataclass
class Segment:
    id: int
    download_id: str
    start: int
    end: int
    downloaded: int = 0
    state: SegmentState = SegmentState.PENDING
    worker_id: Optional[int] = None
    speed: float = 0.0
    error: Optional[str] = None

    @property
    def length(self) -> int:
        if self.end < 0:
            return -1
        return max(0, self.end - self.start + 1)

    @property
    def remaining(self) -> int:
        if self.end < 0:
            return -1
        return max(0, self.length - self.downloaded)

    @property
    def current_offset(self) -> int:
        return self.start + self.downloaded

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "download_id": self.download_id,
            "start": self.start,
            "end": self.end,
            "downloaded": self.downloaded,
            "state": self.state.value,
            "worker_id": self.worker_id,
            "speed": self.speed,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Segment":
        return cls(
            id=int(data["id"]),
            download_id=str(data["download_id"]),
            start=int(data["start"]),
            end=int(data["end"]),
            downloaded=int(data.get("downloaded", 0)),
            state=SegmentState(data.get("state", SegmentState.PENDING.value)),
            worker_id=data.get("worker_id"),
            speed=float(data.get("speed", 0.0)),
            error=data.get("error"),
        )


class SegmentManager:
    def __init__(
        self,
        download_id: str,
        total_size: int,
        num_connections: int = 8,
        minimum_segment_size: int = 256 * 1024,
    ) -> None:
        self.download_id = download_id
        self.total_size = total_size
        self.num_connections = max(1, min(32, num_connections))
        self.minimum_segment_size = max(1024, minimum_segment_size)
        self._segments: list[Segment] = []
        self._lock = threading.Lock()
        self._next_id = 0

    @property
    def segments(self) -> list[Segment]:
        with self._lock:
            return list(self._segments)

    def create_segments(self) -> list[Segment]:
        with self._lock:
            self._segments.clear()
            self._next_id = 0
            if self.total_size <= 0:
                seg = Segment(
                    id=self._next_id,
                    download_id=self.download_id,
                    start=0,
                    end=-1,
                    downloaded=0,
                    state=SegmentState.PENDING,
                )
                self._next_id += 1
                self._segments.append(seg)
                return list(self._segments)

            max_possible = max(1, self.total_size // self.minimum_segment_size)
            count = min(self.num_connections, max_possible)
            base_size = self.total_size // count
            remainder = self.total_size % count
            offset = 0
            for i in range(count):
                seg_size = base_size + (1 if i < remainder else 0)
                start = offset
                end = offset + seg_size - 1
                self._segments.append(
                    Segment(
                        id=self._next_id,
                        download_id=self.download_id,
                        start=start,
                        end=end,
                        downloaded=0,
                        state=SegmentState.PENDING,
                    )
                )
                self._next_id += 1
                offset = end + 1
            return list(self._segments)

    def split_largest_segment(self) -> Optional[Segment]:
        with self._lock:
            if self.total_size <= 0:
                return None
            candidates = [
                s
                for s in self._segments
                if s.state in (SegmentState.PENDING, SegmentState.DOWNLOADING)
                and s.end >= 0
                and s.remaining >= 2 * self.minimum_segment_size
            ]
            if not candidates:
                return None
            largest = max(candidates, key=lambda s: s.remaining)
            current_pos = largest.current_offset
            rem = largest.remaining
            first_half = rem // 2
            if first_half < self.minimum_segment_size:
                return None
            old_end = largest.end
            new_end_for_largest = current_pos + first_half - 1
            new_start = new_end_for_largest + 1
            if new_start > old_end:
                return None
            largest.end = new_end_for_largest
            new_seg = Segment(
                id=self._next_id,
                download_id=self.download_id,
                start=new_start,
                end=old_end,
                downloaded=0,
                state=SegmentState.PENDING,
            )
            self._next_id += 1
            self._segments.append(new_seg)
            self._segments.sort(key=lambda s: s.start)
            return new_seg

    def get_pending_segments(self) -> list[Segment]:
        with self._lock:
            return [s for s in self._segments if s.state == SegmentState.PENDING]

    def get_active_segments(self) -> list[Segment]:
        with self._lock:
            return [s for s in self._segments if s.state == SegmentState.DOWNLOADING]

    def claim_next_segment(self, worker_id: int) -> Optional[Segment]:
        with self._lock:
            for seg in self._segments:
                if seg.state == SegmentState.PENDING:
                    seg.state = SegmentState.DOWNLOADING
                    seg.worker_id = worker_id
                    return seg
        new_seg = self.split_largest_segment()
        if new_seg is None:
            return None
        with self._lock:
            if new_seg.state == SegmentState.PENDING:
                new_seg.state = SegmentState.DOWNLOADING
                new_seg.worker_id = worker_id
                return new_seg
            return None

    def update_segment_progress(
        self, segment_id: int, downloaded_bytes: int, speed: float = 0.0
    ) -> None:
        with self._lock:
            for seg in self._segments:
                if seg.id == segment_id:
                    if seg.end >= 0:
                        seg.downloaded = min(downloaded_bytes, seg.length)
                    else:
                        seg.downloaded = downloaded_bytes
                    seg.speed = speed
                    break

    def add_segment_bytes(
        self, segment_id: int, delta: int, speed: float = 0.0
    ) -> int:
        with self._lock:
            for seg in self._segments:
                if seg.id == segment_id:
                    if seg.end >= 0:
                        allowed = min(delta, seg.remaining)
                        seg.downloaded += allowed
                        seg.speed = speed
                        return allowed
                    seg.downloaded += delta
                    seg.speed = speed
                    return delta
            return 0

    def mark_segment_state(
        self,
        segment_id: int,
        state: SegmentState,
        error: Optional[str] = None,
    ) -> None:
        with self._lock:
            for seg in self._segments:
                if seg.id == segment_id:
                    seg.state = state
                    seg.error = error
                    if state != SegmentState.DOWNLOADING:
                        seg.worker_id = None
                        seg.speed = 0.0
                    break

    def get_progress(self) -> tuple[int, int, float]:
        with self._lock:
            total_downloaded = sum(s.downloaded for s in self._segments)
            if self.total_size <= 0:
                return total_downloaded, self.total_size, 0.0
            pct = min(100.0, (total_downloaded / self.total_size) * 100.0)
            return total_downloaded, self.total_size, pct

    def all_completed(self) -> bool:
        with self._lock:
            if not self._segments:
                return False
            return all(s.state == SegmentState.COMPLETED for s in self._segments)

    def get_resumable_segments(self) -> list[Segment]:
        with self._lock:
            resumable: list[Segment] = []
            for seg in self._segments:
                if seg.state != SegmentState.COMPLETED:
                    if seg.end >= 0 and seg.downloaded >= seg.length:
                        seg.state = SegmentState.COMPLETED
                        continue
                    seg.state = SegmentState.PENDING
                    seg.worker_id = None
                    seg.speed = 0.0
                    seg.error = None
                    resumable.append(seg)
            return resumable

    def to_dict(self) -> list[dict[str, Any]]:
        with self._lock:
            return [s.to_dict() for s in self._segments]

    @classmethod
    def from_dict(
        cls,
        download_id: str,
        total_size: int,
        data: list[dict[str, Any]],
        num_connections: int = 8,
        minimum_segment_size: int = 256 * 1024,
    ) -> "SegmentManager":
        mgr = cls(
            download_id=download_id,
            total_size=total_size,
            num_connections=num_connections,
            minimum_segment_size=minimum_segment_size,
        )
        mgr._segments = [Segment.from_dict(item) for item in data]
        mgr._segments.sort(key=lambda s: s.start)
        mgr._next_id = max((s.id for s in mgr._segments), default=-1) + 1
        return mgr
