import asyncio
from typing import Optional

from turbofetch.app.db.database import Database
from turbofetch.app.db.models import DownloadRecord, QueueRecord
from turbofetch.app.engine.downloader import DownloadEngine, DownloadStatus
from turbofetch.app.utils.config import ConfigManager
from turbofetch.app.utils.logger import get_logger

logger = get_logger("scheduler.queue")


class QueueManager:
    def __init__(
        self,
        db: Database,
        download_engine: DownloadEngine,
        config_manager: Optional[ConfigManager] = None,
    ) -> None:
        self.db = db
        self.download_engine = download_engine
        self.config_manager = config_manager
        self._ensure_default_queue()

    def _ensure_default_queue(self) -> None:
        if self.db.get_queue("default") is None:
            max_conc = 3
            if self.config_manager:
                max_conc = self.config_manager.get().max_concurrent_downloads
            self.db.create_queue(QueueRecord(name="default", max_concurrent=max_conc, is_active=False))

    def create_queue(self, name: str, max_concurrent: int = 3) -> QueueRecord:
        record = QueueRecord(name=name.strip(), max_concurrent=max(1, max_concurrent), is_active=False)
        self.db.create_queue(record)
        return record

    def delete_queue(self, name: str) -> None:
        if name == "default":
            return
        self.db.delete_queue(name)

    def get_queue(self, name: str) -> Optional[QueueRecord]:
        return self.db.get_queue(name)

    def get_all_queues(self) -> list[QueueRecord]:
        return self.db.get_all_queues()

    def add_to_queue(self, download_id: str, queue_name: str = "default", priority: int = 0) -> None:
        if self.db.get_queue(queue_name) is None:
            self.create_queue(queue_name)
        self.db.update_download_queue(download_id, queue_name, priority)
        task = self.download_engine.get_download(download_id)
        if task is not None:
            task.queue_name = queue_name
            task.priority = priority

    def remove_from_queue(self, download_id: str) -> None:
        self.add_to_queue(download_id, "default", 0)

    def reorder_queue(self, queue_name: str, download_ids: list[str]) -> None:
        for idx, dl_id in enumerate(download_ids):
            self.db.update_download_queue(dl_id, queue_name, idx)
            task = self.download_engine.get_download(dl_id)
            if task is not None:
                task.queue_name = queue_name
                task.priority = idx

    def get_queue_downloads(self, queue_name: str) -> list[DownloadRecord]:
        return self.db.get_downloads_by_queue(queue_name)

    async def start_queue(self, queue_name: str) -> None:
        queue = self.db.get_queue(queue_name)
        if queue is None:
            return
        queue.is_active = True
        self.db.update_queue(queue)
        await self._process_queue(queue_name)

    async def stop_queue(self, queue_name: str) -> None:
        queue = self.db.get_queue(queue_name)
        if queue is None:
            return
        queue.is_active = False
        self.db.update_queue(queue)
        records = self.db.get_downloads_by_queue(queue_name)
        for rec in records:
            task = self.download_engine.get_download(rec.id)
            if task and task.status in (DownloadStatus.DOWNLOADING, DownloadStatus.PROBING):
                await self.download_engine.pause_download(rec.id)

    async def _process_queue(self, queue_name: str) -> None:
        queue = self.db.get_queue(queue_name)
        if queue is None or not queue.is_active:
            return
        records = self.db.get_downloads_by_queue(queue_name)
        active_count = 0
        candidates: list[DownloadRecord] = []
        for rec in records:
            task = self.download_engine.get_download(rec.id)
            status = task.status.value if task else rec.status
            if status in (DownloadStatus.DOWNLOADING.value, DownloadStatus.PROBING.value):
                active_count += 1
            elif status in (DownloadStatus.QUEUED.value, DownloadStatus.PAUSED.value, DownloadStatus.STOPPED.value):
                candidates.append(rec)

        slots = max(0, queue.max_concurrent - active_count)
        for rec in candidates[:slots]:
            task = self.download_engine.get_download(rec.id)
            if task is None:
                task = rec.to_download_task()
                segs = [s.to_dict() for s in self.db.get_segments(rec.id)]
                self.download_engine.register_existing_task(task, segs)
            if task.downloaded > 0 and task.resumable:
                await self.download_engine.resume_download(task.id)
            else:
                await self.download_engine.start_download(task.id)

    async def on_download_complete(self, download_id: str) -> None:
        task = self.download_engine.get_download(download_id)
        queue_name = task.queue_name if task else "default"
        await self._process_queue(queue_name)
