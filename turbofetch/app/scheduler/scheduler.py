import asyncio
import ctypes
import sys
import uuid
from datetime import datetime
from typing import Callable, Optional

from turbofetch.app.db.database import Database
from turbofetch.app.db.models import ScheduleRecord
from turbofetch.app.engine.downloader import DownloadEngine
from turbofetch.app.scheduler.queue_manager import QueueManager
from turbofetch.app.utils.config import ConfigManager
from turbofetch.app.utils.logger import get_logger

logger = get_logger("scheduler")

_DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class DownloadScheduler:
    def __init__(
        self,
        db: Database,
        download_engine: DownloadEngine,
        queue_manager: QueueManager,
        config_manager: Optional[ConfigManager] = None,
        on_close_app: Optional[Callable[[], None]] = None,
    ) -> None:
        self.db = db
        self.download_engine = download_engine
        self.queue_manager = queue_manager
        self.config_manager = config_manager
        self.on_close_app = on_close_app
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_triggered: dict[str, str] = {}

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    def add_schedule(
        self,
        queue_name: str,
        action: str,
        time_str: str,
        days: str = "daily",
        on_completion: str = "nothing",
        enabled: bool = True,
    ) -> str:
        rec = ScheduleRecord(
            id=str(uuid.uuid4()),
            queue_name=queue_name,
            action=action,
            time=time_str,
            days=days,
            enabled=enabled,
            on_completion=on_completion,
        )
        self.db.save_schedule(rec)
        return rec.id

    def remove_schedule(self, schedule_id: str) -> None:
        self.db.delete_schedule(schedule_id)

    def get_schedules(self) -> list[ScheduleRecord]:
        return self.db.get_all_schedules()

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._check_schedules()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Scheduler check error")
            await asyncio.sleep(30.0)

    def _matches_now(self, schedule: ScheduleRecord, now: datetime) -> bool:
        if not schedule.enabled:
            return False
        current_hm = now.strftime("%H:%M")
        if schedule.time != current_hm:
            return False
        day_token = _DAY_NAMES[now.weekday()]
        days_norm = schedule.days.strip().lower()
        if days_norm != "daily":
            allowed = {d.strip() for d in days_norm.split(",") if d.strip()}
            if day_token not in allowed:
                return False
        minute_key = now.strftime("%Y-%m-%d %H:%M")
        if self._last_triggered.get(schedule.id) == minute_key:
            return False
        self._last_triggered[schedule.id] = minute_key
        return True

    async def _check_schedules(self, now: Optional[datetime] = None) -> None:
        current = now or datetime.now()
        for sched in self.get_schedules():
            if self._matches_now(sched, current):
                await self._execute_action(sched)

    async def _execute_action(self, schedule: ScheduleRecord) -> None:
        logger.info(
            "Executing schedule %s: %s queue=%s",
            schedule.id,
            schedule.action,
            schedule.queue_name,
        )
        if schedule.action == "start":
            await self.queue_manager.start_queue(schedule.queue_name)
        elif schedule.action == "stop":
            await self.queue_manager.stop_queue(schedule.queue_name)
        if schedule.on_completion and schedule.on_completion != "nothing":
            self._execute_completion_action(schedule.on_completion)

    def _execute_completion_action(self, action: str) -> None:
        act = action.lower().strip()
        if act == "close" and self.on_close_app:
            self.on_close_app()
            return
        if sys.platform != "win32":
            return
        if act == "sleep":
            ctypes.windll.powrprof.SetSuspendState(False, True, False)
        elif act == "hibernate":
            ctypes.windll.powrprof.SetSuspendState(True, True, False)
        elif act == "shutdown":
            ctypes.windll.user32.ExitWindowsEx(0x00000001 | 0x00000004, 0)
