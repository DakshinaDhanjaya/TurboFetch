import argparse
import asyncio
import concurrent.futures
import signal
import sys
import threading
import time
import uuid
from concurrent.futures.thread import ThreadPoolExecutor
from typing import Any, Coroutine, Optional

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from turbofetch.app.db.database import Database
from turbofetch.app.db.models import DownloadRecord, HistoryRecord, SegmentRecord
from turbofetch.app.engine.downloader import DownloadEngine, DownloadStatus, DownloadTask
from turbofetch.app.engine.speed_limiter import SpeedLimiter
from turbofetch.app.scheduler.queue_manager import QueueManager
from turbofetch.app.scheduler.scheduler import DownloadScheduler
from turbofetch.app.server.server import LocalServer
from turbofetch.app.ui.main_window import MainWindow
from turbofetch.app.ui.theme import ThemeManager
from turbofetch.app.utils.config import ConfigManager
from turbofetch.app.utils.logger import get_logger, setup_logging
from turbofetch.app.utils.singleton import SingleInstance


class AsyncBridge(QObject):
    progress_updated = Signal(str, int, float)
    download_added = Signal(str)
    download_completed = Signal(str)
    download_failed = Signal(str, str)
    status_changed = Signal(str, str)
    video_requested = Signal(str, object)
    quick_video_requested = Signal(str, object)
    download_confirm_requested = Signal(dict)
    show_window_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        concurrent.futures.ThreadPoolExecutor = ThreadPoolExecutor
        self._loop = asyncio.new_event_loop()
        self._default_executor = ThreadPoolExecutor(
            max_workers=16, thread_name_prefix="turbofetch-async"
        )
        self._loop.set_default_executor(self._default_executor)
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def run_coroutine(self, coro: Coroutine[Any, Any, Any]) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def stop(self) -> None:
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5.0)
        self._default_executor.shutdown(wait=False)


class TurboFetchApp:
    def __init__(self, argv: Optional[list[str]] = None) -> None:
        parser = argparse.ArgumentParser(prog="TurboFetch")
        parser.add_argument("--port", type=int, default=None)
        parser.add_argument("--no-tray", action="store_true")
        parser.add_argument("--minimized", action="store_true")
        parser.add_argument("--debug", action="store_true")
        self.args = parser.parse_args(argv)

        self.config_manager = ConfigManager()
        cfg = self.config_manager.load()
        if self.args.port is not None:
            cfg.port = self.args.port

        setup_logging(level="DEBUG" if self.args.debug else "INFO")
        self.logger = get_logger("main")

        self.single_instance: Optional[SingleInstance] = None
        if cfg.single_instance:
            self.single_instance = SingleInstance("TurboFetch")
            if not self.single_instance.acquire():
                self.logger.warning("Another TurboFetch instance is already running.")
                self._wake_existing_instance(cfg.port, cfg.pairing_token)
                sys.exit(0)

        self.db = Database()
        self.db.initialize()

        self.speed_limiter = SpeedLimiter(global_limit=float(cfg.global_speed_limit))
        self.engine = DownloadEngine(
            speed_limiter=self.speed_limiter,
            max_concurrent=cfg.max_concurrent_downloads,
            max_retries=cfg.max_retries,
            retry_delay=cfg.retry_delay,
            timeout=cfg.timeout,
        )
        self.queue_manager = QueueManager(self.db, self.engine, self.config_manager)

        self.bridge = AsyncBridge()

        self.server = LocalServer(
            host=cfg.bind_address,
            port=cfg.port,
            pairing_token=cfg.pairing_token,
            download_engine=self.engine,
            config_manager=self.config_manager,
            queue_manager=self.queue_manager,
            on_video_request=self.bridge.video_requested.emit,
            on_download_confirm=self.bridge.download_confirm_requested.emit,
            on_quick_video=self.bridge.quick_video_requested.emit,
            on_show_window=self.bridge.show_window_requested.emit,
        )

        self.qt_app = QApplication(sys.argv if argv is None else [sys.argv[0], *argv])
        self.qt_app.setApplicationName("TurboFetch")
        self.qt_app.setOrganizationName("TurboFetch")

        self.theme_manager = ThemeManager(self.qt_app)
        self.theme_manager.set_font_size(cfg.font_size)
        self.theme_manager.set_theme(cfg.theme)

        self.scheduler = DownloadScheduler(
            db=self.db,
            download_engine=self.engine,
            queue_manager=self.queue_manager,
            config_manager=self.config_manager,
            on_close_app=self._request_close,
        )

        self._wire_callbacks()
        self._restore_downloads()

        self.window = MainWindow(
            engine=self.engine,
            db=self.db,
            config_manager=self.config_manager,
            queue_manager=self.queue_manager,
            scheduler=self.scheduler,
            theme_manager=self.theme_manager,
            run_coro=self.bridge.run_coroutine,
            on_settings_applied=self._on_settings_applied,
            enable_tray=not self.args.no_tray,
        )

        self.bridge.download_added.connect(self.window.on_download_added)
        self.bridge.download_completed.connect(self.window.on_download_completed)
        self.bridge.download_failed.connect(self.window.on_download_failed)
        self.bridge.status_changed.connect(self.window.on_status_changed)
        self.bridge.video_requested.connect(self.window.on_video_requested)
        self.bridge.quick_video_requested.connect(self.window.on_quick_video_requested)
        self.bridge.download_confirm_requested.connect(self.window.on_download_confirm_requested)
        self.bridge.show_window_requested.connect(self._show_main_window)

        self.bridge.run_coroutine(self.server.start())
        self.bridge.run_coroutine(self._start_scheduler())

        if not self.args.minimized:
            self.window.show()

    async def _start_scheduler(self) -> None:
        self.scheduler.start()

    def _show_main_window(self) -> None:
        self.window.showNormal()
        self.window.activateWindow()
        self.window.raise_()

    @staticmethod
    def _wake_existing_instance(port: int, token: str) -> None:
        try:
            import urllib.request

            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/show",
                data=b"{}",
                method="POST",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=1.5).close()
        except Exception:
            pass

    def _request_close(self) -> None:
        self.window._quit_app()

    def _on_settings_applied(self) -> None:
        cfg = self.config_manager.get()
        self.speed_limiter.set_global_limit(float(cfg.global_speed_limit))
        self.engine.max_concurrent = cfg.max_concurrent_downloads
        self.engine.max_retries = cfg.max_retries
        self.engine.retry_delay = cfg.retry_delay
        self.engine.timeout = cfg.timeout
        self.server.update_token(cfg.pairing_token)

    def _wire_callbacks(self) -> None:
        def on_progress(task: DownloadTask) -> None:
            self.bridge.progress_updated.emit(task.id, task.downloaded, task.speed)
            if self.server._ws_clients:
                self.bridge.run_coroutine(
                    self.server.broadcast_ws(
                        "progress",
                        {
                            "id": task.id,
                            "downloaded": task.downloaded,
                            "size": task.size,
                            "speed": task.speed,
                            "status": task.status.value,
                        },
                    )
                )

        def on_state_change(task: DownloadTask) -> None:
            self.db.upsert_download(DownloadRecord.from_download_task(task))
            self.bridge.status_changed.emit(task.id, task.status.value)
            if task.status == DownloadStatus.FAILED:
                self.bridge.download_failed.emit(task.id, task.error or "Failed")

        def on_complete(task: DownloadTask) -> None:
            self.db.upsert_download(DownloadRecord.from_download_task(task))
            self.db.add_to_history(
                HistoryRecord(
                    id=str(uuid.uuid4()),
                    url=task.url,
                    filename=task.filename,
                    save_path=task.save_path,
                    size=max(0, task.size),
                    date_completed=task.date_completed or time.time(),
                    category=task.category,
                )
            )
            self.bridge.download_completed.emit(task.id)
            self.bridge.run_coroutine(self.queue_manager.on_download_complete(task.id))

        def on_persist(task: DownloadTask, segments_data: list[dict[str, Any]]) -> None:
            self.db.upsert_download(DownloadRecord.from_download_task(task))
            if segments_data:
                records = [
                    SegmentRecord.from_dict({**s, "download_id": task.id})
                    for s in segments_data
                ]
                self.db.save_segments(task.id, records)

        def on_added(task: DownloadTask) -> None:
            self.bridge.download_added.emit(task.id)

        self.engine.set_on_progress(on_progress)
        self.engine.set_on_state_change(on_state_change)
        self.engine.set_on_complete(on_complete)
        self.engine.set_on_added(on_added)
        self.engine.set_on_persist(on_persist)

    def _restore_downloads(self) -> None:
        for rec in self.db.get_all_downloads():
            task = rec.to_download_task()
            if task.status in (DownloadStatus.DOWNLOADING, DownloadStatus.PROBING, DownloadStatus.MERGING):
                task.status = DownloadStatus.PAUSED
                rec.status = DownloadStatus.PAUSED.value
                self.db.update_download_status(rec.id, DownloadStatus.PAUSED.value)
            segs = [s.to_dict() for s in self.db.get_segments(rec.id)]
            self.engine.register_existing_task(task, segs)

    def run(self) -> int:
        sig_timer = QTimer()
        sig_timer.start(250)
        sig_timer.timeout.connect(lambda: None)
        signal.signal(signal.SIGINT, lambda *_: self._request_close())
        try:
            return self.qt_app.exec()
        finally:
            sig_timer.stop()
            self.shutdown()

    def shutdown(self) -> None:
        async def _stop_async() -> None:
            await self.scheduler.stop()
            await self.server.stop()
            await self.engine.shutdown()

        try:
            fut = self.bridge.run_coroutine(_stop_async())
            fut.result(timeout=5.0)
        except Exception:
            pass
        self.bridge.stop()
        self.db.close()
        if self.single_instance is not None:
            self.single_instance.release()


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--ytdlp-worker":
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", line_buffering=True, write_through=True)
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", line_buffering=True, write_through=True)
        import yt_dlp

        return int(yt_dlp.main(sys.argv[2:]) or 0)
    app = TurboFetchApp()
    return app.run()


if __name__ == "__main__":
    sys.exit(main())
