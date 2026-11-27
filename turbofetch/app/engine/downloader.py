import asyncio
import ctypes
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import uuid
from collections import deque
from concurrent.futures.thread import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlparse

import httpx

from turbofetch.app.engine.protocols import (
    FileInfo,
    build_client_kwargs,
    is_resume_valid,
    probe_url,
    sanitize_filename,
)
from turbofetch.app.engine.segment import Segment, SegmentManager, SegmentState
from turbofetch.app.engine.speed_limiter import SpeedLimiter
from turbofetch.app.utils.checksum import verify_checksum
from turbofetch.app.utils.filename import categorize_file, resolve_conflict
from turbofetch.app.utils.logger import get_logger

logger = get_logger("engine.downloader")
_IO_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="turbofetch-io")


class DownloadStatus(str, Enum):
    QUEUED = "queued"
    PROBING = "probing"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"
    MERGING = "merging"


@dataclass
class DownloadTask:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    url: str = ""
    final_url: str = ""
    filename: str = ""
    save_path: str = ""
    size: int = -1
    downloaded: int = 0
    status: DownloadStatus = DownloadStatus.QUEUED
    speed: float = 0.0
    eta: float = 0.0
    connections: int = 0
    max_connections: int = 8
    date_added: float = field(default_factory=time.time)
    date_completed: Optional[float] = None
    error: Optional[str] = None
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    headers: dict[str, str] = field(default_factory=dict)
    cookies: dict[str, str] = field(default_factory=dict)
    proxy: Optional[str] = None
    auth: Optional[tuple[str, str]] = None
    checksum: Optional[str] = None
    checksum_type: Optional[str] = None
    category: str = "other"
    queue_name: str = "default"
    priority: int = 0
    resumable: bool = False
    conflict_mode: str = "auto_rename"
    file_info: Optional[FileInfo] = None
    ytdlp_options: Optional[dict[str, Any]] = None


class SegmentDownloader:
    def __init__(
        self,
        task: DownloadTask,
        speed_limiter: SpeedLimiter,
        max_connections: int = 8,
        max_retries: int = 10,
        retry_delay: float = 1.0,
        timeout: int = 30,
        on_progress: Optional[Callable[[DownloadTask], None]] = None,
        on_state_change: Optional[Callable[[DownloadTask], None]] = None,
        on_segment_progress: Optional[Callable[[str, list[dict[str, Any]]], None]] = None,
        on_persist: Optional[Callable[[DownloadTask, list[dict[str, Any]]], None]] = None,
    ) -> None:
        self.task = task
        self.speed_limiter = speed_limiter
        self.max_connections = max(1, min(32, max_connections))
        self.max_retries = max(0, max_retries)
        self.retry_delay = max(0.2, retry_delay)
        self.timeout = max(5, timeout)
        self.on_progress = on_progress
        self.on_state_change = on_state_change
        self.on_segment_progress = on_segment_progress
        self.on_persist = on_persist

        self._segment_manager: Optional[SegmentManager] = None
        self._file_lock = threading.Lock()
        self._file_handle: Optional[Any] = None
        self._stop_event = asyncio.Event()
        self._pause_requested = False
        self._cancel_requested = False
        self._worker_tasks: list[asyncio.Task] = []
        self._persist_task: Optional[asyncio.Task] = None
        self._main_task: Optional[asyncio.Task] = None
        self._speed_window: deque[tuple[float, int]] = deque()
        self._speed_lock = threading.Lock()
        self._active_workers = 0
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def part_path(self) -> Path:
        return Path(self.task.save_path) / f"{self.task.filename}.part"

    @property
    def final_path(self) -> Path:
        return Path(self.task.save_path) / self.task.filename

    @property
    def progress(self) -> float:
        if self.task.size <= 0:
            return 100.0 if self.task.status == DownloadStatus.COMPLETED else 0.0
        return min(100.0, (self.task.downloaded / self.task.size) * 100.0)

    @property
    def speed(self) -> float:
        now = time.monotonic()
        with self._speed_lock:
            while self._speed_window and now - self._speed_window[0][0] > 3.0:
                self._speed_window.popleft()
            if not self._speed_window:
                return 0.0
            total_bytes = sum(b for _, b in self._speed_window)
            span = max(0.5, now - self._speed_window[0][0])
            return total_bytes / span

    @property
    def eta(self) -> float:
        spd = self.speed
        if spd <= 0 or self.task.size <= 0:
            return 0.0
        remaining = max(0, self.task.size - self.task.downloaded)
        return remaining / spd

    @property
    def active_connections(self) -> int:
        return self._active_workers

    @property
    def segment_states(self) -> list[dict[str, Any]]:
        if self._segment_manager is None:
            return []
        return self._segment_manager.to_dict()

    def load_segments(self, segments_data: list[dict[str, Any]]) -> None:
        if segments_data:
            self._segment_manager = SegmentManager.from_dict(
                download_id=self.task.id,
                total_size=self.task.size,
                data=segments_data,
                num_connections=self.max_connections,
            )

    def _set_status(self, status: DownloadStatus, error: Optional[str] = None) -> None:
        self.task.status = status
        self.task.error = error
        if status != DownloadStatus.DOWNLOADING:
            self.task.speed = 0.0
            self.task.connections = 0
        if self.on_state_change:
            self.on_state_change(self.task)

    def _record_speed(self, num_bytes: int) -> None:
        if num_bytes <= 0:
            return
        now = time.monotonic()
        with self._speed_lock:
            self._speed_window.append((now, num_bytes))
            while self._speed_window and now - self._speed_window[0][0] > 3.0:
                self._speed_window.popleft()

    def _check_disk_space(self) -> None:
        target_dir = Path(self.task.save_path)
        target_dir.mkdir(parents=True, exist_ok=True)
        if self.task.size > 0:
            usage = shutil.disk_usage(target_dir)
            needed = max(0, self.task.size - self.task.downloaded)
            if usage.free < needed + 1024 * 1024:
                raise OSError("Insufficient disk space")

    def _preallocate_file(self) -> None:
        part = self.part_path
        part.parent.mkdir(parents=True, exist_ok=True)
        mode = "r+b" if part.exists() else "w+b"
        with open(part, mode) as f:
            if sys.platform == "win32":
                try:
                    import msvcrt

                    handle = msvcrt.get_osfhandle(f.fileno())
                    bytes_returned = ctypes.c_ulong(0)
                    ctypes.windll.kernel32.DeviceIoControl(
                        handle,
                        0x000900C4,
                        None,
                        0,
                        None,
                        0,
                        ctypes.byref(bytes_returned),
                        None,
                    )
                except Exception:
                    pass
            if self.task.size > 0:
                current_size = os.path.getsize(part)
                if current_size != self.task.size:
                    f.seek(self.task.size - 1)
                    f.write(b"\x00")
                    f.truncate(self.task.size)

    def _open_part_file(self) -> None:
        with self._file_lock:
            if self._file_handle is None or self._file_handle.closed:
                mode = "r+b" if self.part_path.exists() else "w+b"
                self._file_handle = open(self.part_path, mode)

    def _close_part_file(self) -> None:
        with self._file_lock:
            if self._file_handle is not None and not self._file_handle.closed:
                self._file_handle.flush()
                self._file_handle.close()
                self._file_handle = None

    def _write_at(self, offset: int, data: bytes) -> None:
        with self._file_lock:
            if self._file_handle is None or self._file_handle.closed:
                self._file_handle = open(self.part_path, "r+b")
            self._file_handle.seek(offset)
            self._file_handle.write(data)

    def _resolve_filename_conflict(self, target: Path) -> Path:
        if not target.exists():
            return target
        if self.task.conflict_mode == "overwrite":
            target.unlink(missing_ok=True)
            return target
        resolved = resolve_conflict(target)
        self.task.filename = resolved.name
        return resolved

    def _rename_on_complete(self) -> None:
        self._close_part_file()
        dest = self._resolve_filename_conflict(self.final_path)
        if not self.part_path.exists():
            return
        last_exc: Optional[OSError] = None
        for _attempt in range(10):
            try:
                self.part_path.replace(dest)
                return
            except OSError as exc:
                last_exc = exc
                time.sleep(0.25)
        if last_exc is not None:
            raise last_exc

    async def _verify_checksum(self) -> bool:
        if not self.task.checksum:
            return True
        algo = (self.task.checksum_type or "sha256").lower()
        target = self.part_path if self.part_path.exists() else self.final_path
        return await verify_checksum(target, self.task.checksum, algo)

    async def _persist_loop(self) -> None:
        try:
            loop = asyncio.get_running_loop()
            last_persisted = -1
            while not self._stop_event.is_set():
                await asyncio.sleep(1.0)
                if self._segment_manager is not None:
                    downloaded, _, _ = self._segment_manager.get_progress()
                    self.task.downloaded = downloaded
                    self.task.speed = self.speed
                    self.task.eta = self.eta
                    self.task.connections = self._active_workers
                    if self.on_progress:
                        self.on_progress(self.task)
                    snap = None
                    if self.on_segment_progress:
                        snap = self._segment_manager.to_dict()
                        self.on_segment_progress(self.task.id, snap)
                    if self.on_persist and downloaded != last_persisted:
                        last_persisted = downloaded
                        if snap is None:
                            snap = self._segment_manager.to_dict()
                        await loop.run_in_executor(_IO_EXECUTOR, self.on_persist, self.task, snap)
        except asyncio.CancelledError:
            pass

    async def _download_segment(self, segment: Segment) -> None:
        attempt = 0
        while not self._stop_event.is_set():
            if self._segment_manager is None or self._client is None:
                return
            if segment.end >= 0 and segment.remaining <= 0:
                self._segment_manager.mark_segment_state(segment.id, SegmentState.COMPLETED)
                return

            req_headers = {"Accept-Encoding": "identity", **self.task.headers}
            if self.task.resumable and segment.end >= 0:
                start_byte = segment.current_offset
                end_byte = segment.end
                req_headers["Range"] = f"bytes={start_byte}-{end_byte}"
            else:
                segment.downloaded = 0

            target_url = self.task.final_url or self.task.url
            buf = bytearray()
            write_batch_size = 1024 * 1024
            try:
                async with self._client.stream("GET", target_url, headers=req_headers) as resp:
                    if resp.status_code not in (200, 206):
                        raise httpx.HTTPStatusError(
                            f"HTTP {resp.status_code}",
                            request=resp.request,
                            response=resp,
                        )
                    if self.task.resumable and segment.end >= 0 and resp.status_code == 200 and segment.start > 0:
                        raise httpx.HTTPError("Server ignored Range header")

                    attempt = 0
                    last_tick = time.monotonic()
                    bytes_since_tick = 0
                    loop = asyncio.get_running_loop()
                    enc = resp.headers.get("content-encoding", "").lower()
                    stream_iter = (
                        resp.aiter_raw(chunk_size=524288)
                        if enc in ("", "identity")
                        else resp.aiter_bytes(chunk_size=524288)
                    )
                    async for chunk in stream_iter:
                        if self._stop_event.is_set():
                            break
                        if not chunk:
                            continue
                        if segment.end >= 0:
                            unwritten_remaining = segment.remaining - len(buf)
                            if unwritten_remaining <= 0:
                                break
                            if len(chunk) > unwritten_remaining:
                                chunk = chunk[:unwritten_remaining]
                        await self.speed_limiter.acquire(self.task.id, len(chunk))
                        if self._stop_event.is_set():
                            break
                        buf.extend(chunk)
                        now = time.monotonic()
                        bytes_since_tick += len(chunk)
                        dt = now - last_tick
                        seg_speed = bytes_since_tick / dt if dt >= 0.25 else segment.speed
                        if dt >= 0.25:
                            last_tick = now
                            bytes_since_tick = 0
                        self._record_speed(len(chunk))
                        if len(buf) >= write_batch_size or (segment.end >= 0 and segment.remaining - len(buf) <= 0):
                            payload = buf
                            buf = bytearray()
                            write_offset = segment.current_offset
                            await loop.run_in_executor(_IO_EXECUTOR, self._write_at, write_offset, payload)
                            self._segment_manager.add_segment_bytes(segment.id, len(payload), seg_speed)
                        if segment.end >= 0 and segment.remaining <= 0:
                            break

                if buf:
                    payload = buf
                    buf = bytearray()
                    write_offset = segment.current_offset
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(_IO_EXECUTOR, self._write_at, write_offset, payload)
                    self._segment_manager.add_segment_bytes(segment.id, len(payload), segment.speed)

                if self._stop_event.is_set():
                    return
                if segment.end >= 0 and segment.remaining > 0:
                    raise httpx.HTTPError("Incomplete segment transfer")
                self._segment_manager.mark_segment_state(segment.id, SegmentState.COMPLETED)
                return
            except asyncio.CancelledError:
                if buf:
                    payload = buf
                    buf = bytearray()
                    try:
                        self._write_at(segment.current_offset, payload)
                        self._segment_manager.add_segment_bytes(segment.id, len(payload), 0.0)
                    except Exception:
                        pass
                raise
            except Exception as exc:
                if buf:
                    payload = buf
                    buf = bytearray()
                    try:
                        self._write_at(segment.current_offset, payload)
                        self._segment_manager.add_segment_bytes(segment.id, len(payload), 0.0)
                    except Exception:
                        pass
                if self._stop_event.is_set():
                    return
                attempt += 1
                err_desc = f"{type(exc).__name__}: {exc}"
                if attempt > self.max_retries:
                    self._segment_manager.mark_segment_state(
                        segment.id, SegmentState.FAILED, err_desc
                    )
                    raise
                delay = min(15.0, 0.5 * (2 ** min(attempt - 1, 5)))
                logger.warning(
                    "Segment %s retry %d/%d after %.1fs: %s",
                    segment.id,
                    attempt,
                    self.max_retries,
                    delay,
                    err_desc,
                )
                await asyncio.sleep(delay)

    async def _worker_loop(self, worker_id: int) -> None:
        self._active_workers += 1
        try:
            while not self._stop_event.is_set() and self._segment_manager is not None:
                seg = self._segment_manager.claim_next_segment(worker_id)
                if seg is None:
                    break
                await self._download_segment(seg)
        finally:
            self._active_workers = max(0, self._active_workers - 1)

    async def start(self) -> None:
        self._stop_event.clear()
        self._pause_requested = False
        self._cancel_requested = False
        self._set_status(DownloadStatus.PROBING)

        try:
            info = await probe_url(
                url=self.task.url,
                headers=self.task.headers,
                cookies=self.task.cookies,
                proxy=self.task.proxy,
                auth=self.task.auth,
                timeout=self.timeout,
            )
            self.task.file_info = info
            self.task.final_url = info.final_url or self.task.url
            if not self.task.filename:
                self.task.filename = info.filename
            else:
                self.task.filename = sanitize_filename(self.task.filename)
            self.task.size = info.size
            self.task.resumable = info.resumable
            self.task.etag = info.etag
            self.task.last_modified = info.last_modified
            self.task.category = categorize_file(self.task.filename)

            target_path = Path(self.task.save_path) / self.task.filename
            if target_path.exists() and self.task.conflict_mode == "auto_rename":
                target_path = resolve_conflict(target_path)
                self.task.filename = target_path.name

            self._segment_manager = SegmentManager(
                download_id=self.task.id,
                total_size=self.task.size,
                num_connections=self.max_connections if self.task.resumable else 1,
            )
            self._segment_manager.create_segments()
            await self._run_transfer()
        except asyncio.CancelledError:
            self._handle_interrupted()
        except Exception as exc:
            logger.exception("Download failed for %s", self.task.url)
            self._close_part_file()
            self._set_status(DownloadStatus.FAILED, str(exc))

    async def resume(self) -> None:
        self._stop_event.clear()
        self._pause_requested = False
        self._cancel_requested = False
        self._set_status(DownloadStatus.PROBING)

        try:
            info = await probe_url(
                url=self.task.url,
                headers=self.task.headers,
                cookies=self.task.cookies,
                proxy=self.task.proxy,
                auth=self.task.auth,
                timeout=self.timeout,
            )
            orig_info = self.task.file_info or FileInfo(
                url=self.task.url,
                final_url=self.task.final_url or self.task.url,
                filename=self.task.filename,
                size=self.task.size,
                resumable=self.task.resumable,
                etag=self.task.etag,
                last_modified=self.task.last_modified,
            )
            can_resume = (
                self._segment_manager is not None
                and self.part_path.exists()
                and is_resume_valid(orig_info, info)
            )
            self.task.file_info = info
            self.task.final_url = info.final_url or self.task.url
            self.task.etag = info.etag
            self.task.last_modified = info.last_modified
            self.task.resumable = info.resumable

            if can_resume and self._segment_manager is not None:
                self._segment_manager.get_resumable_segments()
                downloaded, _, _ = self._segment_manager.get_progress()
                self.task.downloaded = downloaded
            else:
                self.task.size = info.size
                self.task.downloaded = 0
                self._segment_manager = SegmentManager(
                    download_id=self.task.id,
                    total_size=self.task.size,
                    num_connections=self.max_connections if self.task.resumable else 1,
                )
                self._segment_manager.create_segments()
            await self._run_transfer()
        except asyncio.CancelledError:
            self._handle_interrupted()
        except Exception as exc:
            logger.exception("Resume failed for %s", self.task.url)
            self._close_part_file()
            self._set_status(DownloadStatus.FAILED, str(exc))

    async def _run_transfer(self) -> None:
        if self._segment_manager is None:
            return
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(_IO_EXECUTOR, self._check_disk_space)
        await loop.run_in_executor(_IO_EXECUTOR, self._preallocate_file)
        await loop.run_in_executor(_IO_EXECUTOR, self._open_part_file)

        self._set_status(DownloadStatus.DOWNLOADING)
        if self.on_persist:
            self.on_persist(self.task, self._segment_manager.to_dict())

        client_kwargs = build_client_kwargs(
            headers=self.task.headers,
            cookies=self.task.cookies,
            proxy=self.task.proxy,
            auth=self.task.auth,
            timeout=self.timeout,
            url=self.task.final_url or self.task.url,
        )
        worker_count = self.max_connections if self.task.resumable else 1
        self._client = httpx.AsyncClient(
            limits=httpx.Limits(
                max_connections=max(worker_count * 2, 16),
                max_keepalive_connections=max(worker_count * 2, 16),
                keepalive_expiry=60.0,
            ),
            **client_kwargs,
        )
        self._persist_task = asyncio.create_task(self._persist_loop())
        self._worker_tasks = [
            asyncio.create_task(self._worker_loop(i)) for i in range(worker_count)
        ]

        try:
            results = await asyncio.gather(*self._worker_tasks, return_exceptions=True)
            errors = [r for r in results if isinstance(r, Exception) and not isinstance(r, asyncio.CancelledError)]
            if self._stop_event.is_set():
                self._handle_interrupted()
                return
            if errors:
                raise errors[0]

            if not self._segment_manager.all_completed():
                raise RuntimeError("Not all segments completed")

            downloaded, _, _ = self._segment_manager.get_progress()
            self.task.downloaded = downloaded
            if self.task.size <= 0:
                self.task.size = downloaded

            self._close_part_file()
            if self.task.checksum:
                self._set_status(DownloadStatus.MERGING)
                valid = await self._verify_checksum()
                if not valid:
                    raise ValueError("Checksum verification failed")

            await loop.run_in_executor(_IO_EXECUTOR, self._rename_on_complete)
            self.task.date_completed = time.time()
            self._set_status(DownloadStatus.COMPLETED)
            if self.on_progress:
                self.on_progress(self.task)
            if self.on_persist:
                self.on_persist(self.task, self._segment_manager.to_dict())
        finally:
            if self._persist_task and not self._persist_task.done():
                self._persist_task.cancel()
            await self._client.aclose()
            self._client = None
            self._close_part_file()

    def _handle_interrupted(self) -> None:
        self._close_part_file()
        if self._segment_manager is not None:
            for seg in self._segment_manager.get_active_segments():
                self._segment_manager.mark_segment_state(
                    seg.id,
                    SegmentState.PAUSED if self._pause_requested else SegmentState.PENDING,
                )
            downloaded, _, _ = self._segment_manager.get_progress()
            self.task.downloaded = downloaded
        if self._cancel_requested:
            self.part_path.unlink(missing_ok=True)
            self._set_status(DownloadStatus.STOPPED)
        elif self._pause_requested:
            self._set_status(DownloadStatus.PAUSED)
        else:
            self._set_status(DownloadStatus.STOPPED)
        if self.on_persist and self._segment_manager is not None:
            self.on_persist(self.task, self._segment_manager.to_dict())

    async def pause(self) -> None:
        self._pause_requested = True
        self._stop_event.set()
        for t in self._worker_tasks:
            if not t.done():
                t.cancel()
        if self._worker_tasks:
            await asyncio.gather(*self._worker_tasks, return_exceptions=True)
        self._handle_interrupted()

    async def stop(self) -> None:
        self._pause_requested = False
        self._stop_event.set()
        for t in self._worker_tasks:
            if not t.done():
                t.cancel()
        if self._worker_tasks:
            await asyncio.gather(*self._worker_tasks, return_exceptions=True)
        self._handle_interrupted()

    async def cancel(self) -> None:
        self._cancel_requested = True
        self._stop_event.set()
        for t in self._worker_tasks:
            if not t.done():
                t.cancel()
        if self._worker_tasks:
            await asyncio.gather(*self._worker_tasks, return_exceptions=True)
        self._handle_interrupted()


class YtDlpDownloader:
    def __init__(
        self,
        task: DownloadTask,
        on_progress: Optional[Callable[[DownloadTask], None]] = None,
        on_state_change: Optional[Callable[[DownloadTask], None]] = None,
        on_persist: Optional[Callable[[DownloadTask, list[dict[str, Any]]], None]] = None,
    ) -> None:
        self.task = task
        self.on_progress = on_progress
        self.on_state_change = on_state_change
        self.on_persist = on_persist
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._pause_requested = False
        self._cancel_requested = False
        self._stop_requested = False
        self._cookie_file: Optional[Path] = None

    @property
    def progress(self) -> float:
        if self.task.size <= 0:
            return 100.0 if self.task.status == DownloadStatus.COMPLETED else 0.0
        return min(100.0, (self.task.downloaded / self.task.size) * 100.0)

    @property
    def speed(self) -> float:
        return self.task.speed

    @property
    def eta(self) -> float:
        return self.task.eta

    @property
    def active_connections(self) -> int:
        return 1 if self.task.status == DownloadStatus.DOWNLOADING else 0

    @property
    def segment_states(self) -> list[dict[str, Any]]:
        if self.task.size <= 0:
            return []
        state = "completed" if self.task.status == DownloadStatus.COMPLETED else (
            "downloading" if self.task.status == DownloadStatus.DOWNLOADING else (
                "paused" if self.task.status == DownloadStatus.PAUSED else (
                    "failed" if self.task.status == DownloadStatus.FAILED else "pending"
                )
            )
        )
        return [{
            "id": 0,
            "start": 0,
            "end": max(0, self.task.size - 1),
            "downloaded": self.task.downloaded,
            "state": state,
        }]

    def load_segments(self, _segments_data: list[dict[str, Any]]) -> None:
        return

    def _set_status(self, status: DownloadStatus, error: Optional[str] = None) -> None:
        self.task.status = status
        self.task.error = error
        if status != DownloadStatus.DOWNLOADING:
            self.task.speed = 0.0
            self.task.connections = 0
        if self.on_state_change:
            self.on_state_change(self.task)

    def _ytdlp_cmd(self) -> Optional[list[str]]:
        exe = shutil.which("yt-dlp")
        if exe:
            return [exe]
        if importlib.util.find_spec("yt_dlp") is not None:
            if getattr(sys, "frozen", False):
                return [sys.executable, "--ytdlp-worker"]
            return [sys.executable, "-u", "-m", "yt_dlp"]
        return None

    def _find_ffmpeg(self) -> Optional[str]:
        exe = shutil.which("ffmpeg")
        if exe:
            return exe
        try:
            import imageio_ffmpeg

            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            return None

    def _cookie_args(self) -> list[str]:
        if not self.task.cookies:
            return []
        host = (urlparse(self.task.url).hostname or "").lower()
        parts = host.split(".")
        domain = f".{'.'.join(parts[-2:])}" if len(parts) >= 2 else host
        expires = int(time.time()) + 86400 * 30
        if self._cookie_file is None:
            fd, tmp_name = tempfile.mkstemp(prefix="tf_cookies_", suffix=".txt")
            with open(fd, "w", encoding="utf-8") as f:
                f.write("# Netscape HTTP Cookie File\n")
                for k, v in self.task.cookies.items():
                    ck = str(k).replace("\t", "").replace("\r", "").replace("\n", "")
                    cv = str(v).replace("\t", "").replace("\r", "").replace("\n", "")
                    if ck:
                        f.write(f"{domain}\tTRUE\t/\tTRUE\t{expires}\t{ck}\t{cv}\n")
            self._cookie_file = Path(tmp_name)
        return ["--cookies", str(self._cookie_file)]

    def _cleanup_cookies(self) -> None:
        if self._cookie_file is not None:
            self._cookie_file.unlink(missing_ok=True)
            self._cookie_file = None

    def _ytdlp_quality_tag(self, opts: dict[str, Any]) -> str:
        if bool(opts.get("audio_only", False)):
            return "Audio"
        fmt_id = str(opts.get("format_id") or "")
        resolution = str(opts.get("resolution") or "Best")
        if opts.get("quality_tag"):
            return sanitize_filename(str(opts["quality_tag"]))
        if fmt_id and not fmt_id.startswith("best"):
            res_tag = str(opts.get("resolution_tag") or f"fmt-{fmt_id}")
            return sanitize_filename(res_tag)
        if resolution and resolution != "Best":
            return sanitize_filename(resolution)
        return "Best"

    def _build_args(self, cmd_base: list[str]) -> list[str]:
        opts = self.task.ytdlp_options or {}
        Path(self.task.save_path).mkdir(parents=True, exist_ok=True)
        ffmpeg_exe = self._find_ffmpeg()
        q_tag = self._ytdlp_quality_tag(opts)
        suffix_str = str(opts.get("output_suffix") or "")
        out_tmpl = f"%(title).120s [{q_tag}]{suffix_str}.%(ext)s"
        args = [
            *cmd_base,
            "--progress",
            "--newline",
            "--continue",
            "--no-warnings",
            "-P",
            self.task.save_path,
            "-o",
            out_tmpl,
            "--print",
            "before_dl:TFMETA|%(title).120s|%(filesize,filesize_approx)s",
            "--progress-template",
            "download:TFPROG|%(progress.downloaded_bytes)s|%(progress.total_bytes)s|%(progress.total_bytes_estimate)s|%(progress.speed)s|%(progress.eta)s",
            "--print",
            "after_move:TFFILE|%(filepath)s",
        ]
        node_exe = shutil.which("node")
        if node_exe:
            args.extend(["--js-runtimes", f"node:{node_exe}", "--remote-components", "ejs:github"])
        args.extend(self._cookie_args())
        if self.task.proxy:
            args.extend(["--proxy", self.task.proxy])
        if ffmpeg_exe:
            args.extend(["--ffmpeg-location", ffmpeg_exe])

        audio_only = bool(opts.get("audio_only", False))
        fmt_id = str(opts.get("format_id") or "")
        resolution = str(opts.get("resolution") or "Best")

        if audio_only:
            if ffmpeg_exe:
                args.extend(["-x", "--audio-format", "mp3"])
            else:
                args.extend(["-f", "bestaudio[ext=m4a]/bestaudio/best"])
        else:
            if resolution != "Best" and (not fmt_id or fmt_id.startswith("best")):
                h = resolution.rstrip("p")
                args.extend(["-S", f"res:{h},vcodec:h264,ext:mp4:m4a,acodec:aac"])
            else:
                args.extend(["-S", "vcodec:h264,ext:mp4:m4a,acodec:aac"])
            if ffmpeg_exe:
                args.extend([
                    "--merge-output-format",
                    "mp4",
                    "--remux-video",
                    "mp4",
                    "--postprocessor-args",
                    "Merger+ffmpeg:-c:v copy -c:a aac -movflags +faststart",
                ])
            if fmt_id and not fmt_id.startswith("best"):
                if ffmpeg_exe and "+" not in fmt_id:
                    args.extend(["-f", f"{fmt_id}+bestaudio[acodec^=mp4a]/{fmt_id}+bestaudio/{fmt_id}"])
                else:
                    args.extend(["-f", fmt_id])
            else:
                if ffmpeg_exe:
                    args.extend(["-f", "bestvideo[vcodec^=avc1]+bestaudio[acodec^=mp4a]/bestvideo[vcodec^=avc1]+bestaudio/best[vcodec^=avc1][acodec!=none]/bestvideo+bestaudio/best"])
                else:
                    args.extend(["-f", "best[vcodec^=avc1][acodec!=none]/best[ext=mp4][acodec!=none][vcodec!=none]/best[acodec!=none][vcodec!=none]/best"])

        if not bool(opts.get("playlist", False)):
            args.append("--no-playlist")
        elif opts.get("playlist_range"):
            args.extend(["--playlist-items", str(opts["playlist_range"])])

        if bool(opts.get("subtitles", False)):
            args.extend(["--write-subs", "--write-auto-subs", "--sub-format", "srt"])
            if ffmpeg_exe:
                args.extend(["--convert-subs", "srt"])

        if bool(opts.get("embed_thumbnail", False)):
            can_embed = bool(shutil.which("ffprobe")) or (
                importlib.util.find_spec("mutagen") is not None
            )
            if ffmpeg_exe and can_embed:
                args.append("--embed-thumbnail")
            else:
                args.append("--write-thumbnail")

        args.append(self.task.url)
        return args

    @staticmethod
    def _parse_num(val: str, default: float = 0.0) -> float:
        try:
            if not val or val == "NA":
                return default
            return float(val)
        except ValueError:
            return default

    def _handle_ytdlp_line(self, line: str, opts: dict[str, Any], last_error: str, last_persist: float) -> tuple[str, float]:
        if line.startswith("ERROR:"):
            return line, last_persist
        if line.startswith("TFMETA|"):
            parts = line.split("|", 2)
            if len(parts) >= 3:
                raw_title = sanitize_filename(parts[1].strip())
                q_tag = self._ytdlp_quality_tag(opts)
                dup_suffix = str(opts.get("output_suffix") or "")
                ext = "mp3" if opts.get("audio_only") else "mp4"
                if raw_title:
                    self.task.filename = f"{raw_title} [{q_tag}]{dup_suffix}.{ext}"
                meta_size = int(self._parse_num(parts[2], 0.0))
                if meta_size > 0 and self.task.size <= 0:
                    self.task.size = meta_size
                if self.on_progress:
                    self.on_progress(self.task)
            return last_error, last_persist
        if line.startswith("TFPROG|"):
            parts = line.split("|")
            if len(parts) >= 6:
                dl_b = int(self._parse_num(parts[1], float(self.task.downloaded)))
                tot_b = int(self._parse_num(parts[2], 0.0))
                if tot_b <= 0:
                    tot_b = int(self._parse_num(parts[3], -1.0))
                spd = self._parse_num(parts[4], 0.0)
                eta = self._parse_num(parts[5], 0.0)
                self.task.downloaded = dl_b
                if tot_b > 0:
                    self.task.size = tot_b
                self.task.speed = spd
                self.task.eta = eta
                self.task.connections = 1
                now = time.monotonic()
                if self.on_progress:
                    self.on_progress(self.task)
                if now - last_persist >= 0.8:
                    last_persist = now
                    if self.on_persist:
                        self.on_persist(self.task, [])
            return last_error, last_persist
        if line.startswith("TFFILE|"):
            fpath = Path(line[7:].strip())
            if fpath.exists():
                self.task.filename = fpath.name
                self.task.save_path = str(fpath.parent)
                fsize = fpath.stat().st_size
                self.task.size = fsize
                self.task.downloaded = fsize
        return last_error, last_persist

    async def start(self) -> None:
        self._pause_requested = False
        self._cancel_requested = False
        self._stop_requested = False
        cmd_base = self._ytdlp_cmd()
        if cmd_base is None:
            self._set_status(DownloadStatus.FAILED, "yt-dlp not installed")
            return
        self._set_status(DownloadStatus.DOWNLOADING)
        self.task.connections = 1
        self.task.max_connections = 1
        opts = self.task.ytdlp_options or {}
        args = self._build_args(cmd_base)
        last_error = ""
        last_persist = 0.0
        proc_env = {
            **os.environ,
            "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        }
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=proc_env,
            )
            assert self._proc.stdout is not None
            buf = b""
            while True:
                chunk = await self._proc.stdout.read(4096)
                if not chunk:
                    break
                buf += chunk.replace(b"\r", b"\n")
                while b"\n" in buf:
                    raw_line, buf = buf.split(b"\n", 1)
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if line:
                        last_error, last_persist = self._handle_ytdlp_line(
                            line, opts, last_error, last_persist
                        )
            if buf.strip():
                line = buf.decode("utf-8", errors="replace").strip()
                last_error, last_persist = self._handle_ytdlp_line(
                    line, opts, last_error, last_persist
                )
            code = await self._proc.wait()
            self._proc = None
            if self._cancel_requested:
                self._cleanup_parts()
                self._set_status(DownloadStatus.STOPPED)
            elif self._pause_requested:
                self._set_status(DownloadStatus.PAUSED)
            elif self._stop_requested:
                self._set_status(DownloadStatus.STOPPED)
            elif code == 0:
                if self.task.size > 0:
                    self.task.downloaded = self.task.size
                self.task.date_completed = time.time()
                self._set_status(DownloadStatus.COMPLETED)
                if self.on_persist:
                    self.on_persist(self.task, [])
            else:
                self._set_status(DownloadStatus.FAILED, last_error or f"yt-dlp exited with code {code}")
        except asyncio.CancelledError:
            self._terminate_proc()
            self._set_status(DownloadStatus.PAUSED if self._pause_requested else DownloadStatus.STOPPED)
        except Exception as exc:
            self._set_status(DownloadStatus.FAILED, str(exc))
        finally:
            self._cleanup_cookies()

    async def resume(self) -> None:
        await self.start()

    def _terminate_proc(self) -> None:
        if self._proc is not None and self._proc.returncode is None:
            try:
                self._proc.terminate()
            except ProcessLookupError:
                pass

    def _cleanup_parts(self) -> None:
        if not self.task.save_path or not self.task.filename:
            return
        stem = Path(self.task.filename).stem
        folder = Path(self.task.save_path)
        if folder.exists():
            for p in folder.glob(f"{stem}*.part*"):
                p.unlink(missing_ok=True)

    async def pause(self) -> None:
        self._pause_requested = True
        self._terminate_proc()
        if self._proc is not None:
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                self._proc.kill()

    async def stop(self) -> None:
        self._stop_requested = True
        self._terminate_proc()
        if self._proc is not None:
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                self._proc.kill()

    async def cancel(self) -> None:
        self._cancel_requested = True
        self._terminate_proc()
        if self._proc is not None:
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                self._proc.kill()
        self._cleanup_parts()


class DownloadEngine:
    def __init__(
        self,
        speed_limiter: Optional[SpeedLimiter] = None,
        max_concurrent: int = 3,
        max_retries: int = 10,
        retry_delay: float = 2.0,
        timeout: int = 30,
    ) -> None:
        self.speed_limiter = speed_limiter or SpeedLimiter()
        self.max_concurrent = max(1, max_concurrent)
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.timeout = timeout
        self._tasks: dict[str, DownloadTask] = {}
        self._downloaders: dict[str, SegmentDownloader] = {}
        self._running_futures: dict[str, asyncio.Task] = {}
        self._on_progress: Optional[Callable[[DownloadTask], None]] = None
        self._on_state_change: Optional[Callable[[DownloadTask], None]] = None
        self._on_complete: Optional[Callable[[DownloadTask], None]] = None
        self._on_added: Optional[Callable[[DownloadTask], None]] = None
        self._on_segment_progress: Optional[Callable[[str, list[dict[str, Any]]], None]] = None
        self._on_persist: Optional[Callable[[DownloadTask, list[dict[str, Any]]], None]] = None

    def set_on_progress(self, callback: Callable[[DownloadTask], None]) -> None:
        self._on_progress = callback

    def set_on_state_change(self, callback: Callable[[DownloadTask], None]) -> None:
        self._on_state_change = callback

    def set_on_complete(self, callback: Callable[[DownloadTask], None]) -> None:
        self._on_complete = callback

    def set_on_added(self, callback: Callable[[DownloadTask], None]) -> None:
        self._on_added = callback

    def set_on_segment_progress(
        self, callback: Callable[[str, list[dict[str, Any]]], None]
    ) -> None:
        self._on_segment_progress = callback

    def set_on_persist(
        self, callback: Callable[[DownloadTask, list[dict[str, Any]]], None]
    ) -> None:
        self._on_persist = callback

    def _handle_state_change(self, task: DownloadTask) -> None:
        if self._on_state_change:
            self._on_state_change(task)
        if task.status == DownloadStatus.COMPLETED and self._on_complete:
            self._on_complete(task)

    def _create_downloader(self, task: DownloadTask) -> Any:
        if task.ytdlp_options is not None or "__ytdlp__" in task.headers:
            if task.ytdlp_options is None and "__ytdlp__" in task.headers:
                try:
                    task.ytdlp_options = json.loads(task.headers["__ytdlp__"])
                except json.JSONDecodeError:
                    task.ytdlp_options = {}
            dl: Any = YtDlpDownloader(
                task=task,
                on_progress=self._on_progress,
                on_state_change=self._handle_state_change,
                on_persist=self._on_persist,
            )
            self._downloaders[task.id] = dl
            return dl
        dl = SegmentDownloader(
            task=task,
            speed_limiter=self.speed_limiter,
            max_connections=task.max_connections,
            max_retries=self.max_retries,
            retry_delay=self.retry_delay,
            timeout=self.timeout,
            on_progress=self._on_progress,
            on_state_change=self._handle_state_change,
            on_segment_progress=self._on_segment_progress,
            on_persist=self._on_persist,
        )
        self._downloaders[task.id] = dl
        return dl

    def register_existing_task(
        self, task: DownloadTask, segments_data: Optional[list[dict[str, Any]]] = None
    ) -> None:
        self._tasks[task.id] = task
        dl = self._create_downloader(task)
        if segments_data:
            dl.load_segments(segments_data)

    async def add_download(
        self,
        url: str,
        save_path: str,
        filename: Optional[str] = None,
        headers: Optional[dict[str, str]] = None,
        cookies: Optional[dict[str, str]] = None,
        proxy: Optional[str] = None,
        auth: Optional[tuple[str, str]] = None,
        connections: int = 8,
        checksum: Optional[str] = None,
        checksum_type: Optional[str] = None,
        category: Optional[str] = None,
        queue_name: str = "default",
        conflict_mode: str = "auto_rename",
        start_now: bool = True,
    ) -> DownloadTask:
        task = DownloadTask(
            url=url,
            final_url=url,
            filename=sanitize_filename(filename) if filename else "",
            save_path=save_path,
            max_connections=max(1, min(32, connections)),
            headers=dict(headers) if headers else {},
            cookies=dict(cookies) if cookies else {},
            proxy=proxy,
            auth=auth,
            checksum=checksum,
            checksum_type=checksum_type,
            category=category or (categorize_file(filename) if filename else "other"),
            queue_name=queue_name,
            conflict_mode=conflict_mode,
        )
        self._tasks[task.id] = task
        dl = self._create_downloader(task)
        if self._on_persist:
            self._on_persist(task, [])
        if self._on_added:
            self._on_added(task)
        if start_now:
            self._running_futures[task.id] = asyncio.create_task(dl.start())
        else:
            self._handle_state_change(task)
        return task

    async def add_video_download(
        self,
        url: str,
        save_path: str,
        title: str = "",
        cookies: Optional[dict[str, str]] = None,
        proxy: Optional[str] = None,
        ytdlp_options: Optional[dict[str, Any]] = None,
        queue_name: str = "default",
    ) -> DownloadTask:
        opts = dict(ytdlp_options) if ytdlp_options else {}
        has_ffmpeg = bool(shutil.which("ffmpeg"))
        if not has_ffmpeg:
            try:
                import imageio_ffmpeg

                has_ffmpeg = bool(imageio_ffmpeg.get_ffmpeg_exe())
            except Exception:
                has_ffmpeg = False
        ext = "mp3" if (opts.get("audio_only") and has_ffmpeg) else ("m4a" if opts.get("audio_only") else "mp4")
        raw_title = sanitize_filename(title) if title else "video"
        for suffix_ext in (".mp4", ".mkv", ".webm", ".mp3", ".m4a"):
            if raw_title.lower().endswith(suffix_ext):
                raw_title = raw_title[: -len(suffix_ext)]
                break

        if bool(opts.get("audio_only", False)):
            q_tag = "Audio"
        elif opts.get("format_id") and not str(opts.get("format_id")).startswith("best"):
            q_tag = sanitize_filename(str(opts.get("resolution_tag") or f"fmt-{opts['format_id']}"))
        elif opts.get("resolution") and str(opts["resolution"]) != "Best":
            q_tag = sanitize_filename(str(opts["resolution"]))
        else:
            q_tag = "Best"

        existing_names = {
            t.filename.lower()
            for t in self._tasks.values()
            if t.save_path == save_path and t.filename
        }
        same_video_tag_count = sum(
            1
            for t in self._tasks.values()
            if t.url == url
            and (t.ytdlp_options or {}).get("quality_tag") == q_tag
        )
        folder = Path(save_path)
        idx = max(1, same_video_tag_count + 1)
        while True:
            dup_suffix = "" if idx == 1 else f" ({idx})"
            candidate = f"{raw_title} [{q_tag}]{dup_suffix}.{ext}"
            candidate_on_disk = folder / candidate
            if candidate.lower() not in existing_names and not candidate_on_disk.exists():
                break
            idx += 1

        opts["quality_tag"] = q_tag
        opts["output_suffix"] = dup_suffix
        base_name = candidate
        task = DownloadTask(
            url=url,
            final_url=url,
            filename=base_name,
            save_path=save_path,
            max_connections=1,
            headers={"__ytdlp__": json.dumps(opts)},
            cookies=dict(cookies) if cookies else {},
            proxy=proxy,
            category="video",
            queue_name=queue_name,
            resumable=True,
            ytdlp_options=opts,
        )
        self._tasks[task.id] = task
        dl = self._create_downloader(task)
        if self._on_persist:
            self._on_persist(task, [])
        if self._on_added:
            self._on_added(task)
        self._running_futures[task.id] = asyncio.create_task(dl.start())
        return task

    async def start_download(self, download_id: str) -> None:
        dl = self._downloaders.get(download_id)
        if dl is None:
            return
        existing = self._running_futures.get(download_id)
        if existing and not existing.done():
            return
        self._running_futures[download_id] = asyncio.create_task(dl.start())

    async def pause_download(self, download_id: str) -> None:
        dl = self._downloaders.get(download_id)
        if dl:
            await dl.pause()

    async def resume_download(self, download_id: str) -> None:
        dl = self._downloaders.get(download_id)
        if dl is None:
            return
        existing = self._running_futures.get(download_id)
        if existing and not existing.done():
            return
        self._running_futures[download_id] = asyncio.create_task(dl.resume())

    async def stop_download(self, download_id: str) -> None:
        dl = self._downloaders.get(download_id)
        if dl:
            await dl.stop()

    async def cancel_download(self, download_id: str) -> None:
        dl = self._downloaders.get(download_id)
        if dl:
            await dl.cancel()

    def set_download_speed_limit(self, download_id: str, bytes_per_sec: float) -> None:
        self.speed_limiter.set_download_limit(download_id, bytes_per_sec)

    def get_download_speed_limit(self, download_id: str) -> float:
        return self.speed_limiter.get_download_limit(download_id)

    async def retry_download(self, download_id: str) -> None:
        task = self._tasks.get(download_id)
        if task is None:
            return
        if task.status in (DownloadStatus.PAUSED, DownloadStatus.STOPPED, DownloadStatus.FAILED):
            await self.resume_download(download_id)

    def update_url(self, download_id: str, new_url: str) -> bool:
        task = self._tasks.get(download_id)
        if task is None or not new_url.strip():
            return False
        cleaned = new_url.strip()
        task.url = cleaned
        task.final_url = cleaned
        if task.file_info is not None:
            task.file_info.url = cleaned
            task.file_info.final_url = cleaned
        if self._on_state_change:
            self._on_state_change(task)
        return True

    def remove_download(self, download_id: str) -> None:
        self._downloaders.pop(download_id, None)
        self._tasks.pop(download_id, None)
        fut = self._running_futures.pop(download_id, None)
        if fut and not fut.done():
            fut.cancel()
        self.speed_limiter.remove_download_limit(download_id)

    def get_download(self, download_id: str) -> Optional[DownloadTask]:
        return self._tasks.get(download_id)

    def get_downloader(self, download_id: str) -> Optional[SegmentDownloader]:
        return self._downloaders.get(download_id)

    def get_all_downloads(self) -> list[DownloadTask]:
        return list(self._tasks.values())

    async def shutdown(self) -> None:
        active_ids = [
            tid
            for tid, task in self._tasks.items()
            if task.status in (DownloadStatus.DOWNLOADING, DownloadStatus.PROBING)
        ]
        await asyncio.gather(
            *(self.pause_download(tid) for tid in active_ids),
            return_exceptions=True,
        )
