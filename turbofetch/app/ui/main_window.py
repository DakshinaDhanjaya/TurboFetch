import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QDragEnterEvent, QDropEvent, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from turbofetch.app.db.database import Database
from turbofetch.app.db.models import HistoryRecord
from turbofetch.app.engine.downloader import DownloadEngine, DownloadStatus, DownloadTask
from turbofetch.app.scheduler.queue_manager import QueueManager
from turbofetch.app.scheduler.scheduler import DownloadScheduler
from turbofetch.app.ui.add_url_dialog import AddUrlDialog
from turbofetch.app.ui.download_table import DownloadTableView, format_eta, format_size, format_speed
from turbofetch.app.ui.drop_basket import DropBasketWidget
from turbofetch.app.ui.properties_dialog import PropertiesDialog
from turbofetch.app.ui.scheduler_dialog import SchedulerDialog
from turbofetch.app.ui.segment_bar import SegmentBar
from turbofetch.app.ui.settings_dialog import SettingsDialog
from turbofetch.app.ui.sidebar import CategorySidebar
from turbofetch.app.ui.site_grabber_dialog import SiteGrabberDialog
from turbofetch.app.ui.speed_graph import SpeedGraphWidget
from turbofetch.app.ui.theme import ThemeManager
from turbofetch.app.ui.toast_popup import DownloadToastPopup, play_notification_sound
from turbofetch.app.ui.toolbar import DownloadToolbar
from turbofetch.app.ui.tray import SystemTray
from turbofetch.app.ui.ytdlp_panel import YtDlpPanel
from turbofetch.app.utils.clipboard import ClipboardMonitor
from turbofetch.app.utils.config import ConfigManager
from turbofetch.app.utils.defender import scan_file_with_defender
from turbofetch.app.utils.filename import categorize_file, is_video_page_url
from turbofetch.app.utils.i18n import _, set_language
from turbofetch.app.utils.updater import UpdateChecker


class _HistoryDialog(QDialog):
    def __init__(self, db: Database, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Download History")
        self.resize(700, 420)
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.edt_search = QLineEdit()
        self.edt_search.setPlaceholderText("Search history...")
        self.edt_search.textChanged.connect(self._reload)
        btn_clear = QPushButton("Clear History")
        btn_clear.clicked.connect(self._clear)
        top.addWidget(self.edt_search)
        top.addWidget(btn_clear)
        layout.addLayout(top)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Filename", "Size", "Category", "Completed", "URL"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close, alignment=Qt.AlignmentFlag.AlignRight)
        self._reload()

    def _reload(self) -> None:
        q = self.edt_search.text().strip()
        items: list[HistoryRecord] = self.db.search_history(q) if q else self.db.get_history(200)
        self.table.setRowCount(0)
        for row, h in enumerate(items):
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(h.filename))
            self.table.setItem(row, 1, QTableWidgetItem(format_size(h.size)))
            self.table.setItem(row, 2, QTableWidgetItem(h.category))
            self.table.setItem(
                row,
                3,
                QTableWidgetItem(datetime.fromtimestamp(h.date_completed).strftime("%Y-%m-%d %H:%M")),
            )
            self.table.setItem(row, 4, QTableWidgetItem(h.url))

    def _clear(self) -> None:
        self.db.clear_history()
        self._reload()


class MainWindow(QMainWindow):
    _updateCheckReady = Signal(bool, str, str)
    _defenderScanFinished = Signal(str, bool, str)

    def __init__(
        self,
        engine: DownloadEngine,
        db: Database,
        config_manager: ConfigManager,
        queue_manager: QueueManager,
        scheduler: DownloadScheduler,
        theme_manager: ThemeManager,
        run_coro: Callable[[Any], Any],
        on_settings_applied: Optional[Callable[[], None]] = None,
        enable_tray: bool = True,
    ) -> None:
        super().__init__()
        self.engine = engine
        self.db = db
        self.config_manager = config_manager
        self.queue_manager = queue_manager
        self.scheduler = scheduler
        self.theme_manager = theme_manager
        self.run_coro = run_coro
        self.on_settings_applied = on_settings_applied
        self._force_quit = False
        self._completion_action = "nothing"
        self._last_sidebar_counts: dict[str, int] = {}
        self._last_selected_id: str = ""

        cfg = self.config_manager.get()
        set_language(cfg.language)

        self.setWindowTitle(_("app.title"))
        self.resize(1220, 740)
        self.setAcceptDrops(True)

        icon_path = Path(__file__).parent / "icon.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._build_menu_bar()
        self._build_ui()
        self._build_shortcuts()

        self.tray: Optional[SystemTray] = None
        if enable_tray and SystemTray.isSystemTrayAvailable():
            self.tray = SystemTray(self, self.windowIcon())
            self.tray.showHideRequested.connect(self._toggle_visibility)
            self.tray.addUrlRequested.connect(lambda: self._show_add_url_dialog())
            self.tray.pauseAllRequested.connect(self._pause_all)
            self.tray.resumeAllRequested.connect(self._resume_all)
            self.tray.settingsRequested.connect(self._show_settings)
            self.tray.exitRequested.connect(self._quit_app)
            self.tray.show()

        self.clipboard_monitor = ClipboardMonitor(self._on_clipboard_url)
        if cfg.clipboard_monitoring:
            self.clipboard_monitor.start()

        self._updateCheckReady.connect(self._on_update_result)
        self._defenderScanFinished.connect(self._on_defender_scan_finished)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(500)
        self._refresh_timer.timeout.connect(self._on_tick)
        self._refresh_timer.start()

        self.toast_popup = DownloadToastPopup(
            get_task=self.engine.get_download,
            on_open_app=self._focus_download_in_window,
            on_toggle_pause=self._toggle_pause_by_id,
        )
        self.drop_basket = DropBasketWidget(
            on_urls_dropped=lambda urls: self._show_add_url_dialog("\n".join(urls)),
            on_toggle_main=self._toggle_visibility,
        )
        self._was_active_tick = False

        self._reload_queues_sidebar()
        self._refresh_downloads()

    def _build_menu_bar(self) -> None:
        mb = self.menuBar()
        mb.clear()

        m_file = mb.addMenu(_("menu.file"))
        m_file.addAction(_("action.add_url"), self._show_add_url_dialog, QKeySequence("Ctrl+N"))
        m_file.addAction(_("action.video_grab"), self._show_ytdlp)
        m_file.addAction(_("action.site_grabber"), self._show_site_grabber)
        m_file.addSeparator()
        m_file.addAction(_("action.import"), self._import_downloads)
        m_file.addAction(_("action.export"), self._export_downloads)
        m_file.addAction(_("action.export_txt"), self._export_urls_txt)
        m_file.addAction(_("action.history"), self._show_history)
        m_file.addSeparator()
        m_file.addAction(_("action.settings"), self._show_settings, QKeySequence("Ctrl+,"))
        m_file.addSeparator()
        m_file.addAction(_("action.exit"), self._quit_app)

        m_edit = mb.addMenu(_("menu.edit"))
        m_edit.addAction(_("action.select_all"), lambda: self.table.selectAll(), QKeySequence("Ctrl+A"))
        m_edit.addAction(_("action.find"), lambda: self.search_box.setFocus(), QKeySequence("Ctrl+F"))

        m_dl = mb.addMenu(_("menu.downloads"))
        m_dl.addAction(_("action.resume_all"), self._resume_all)
        m_dl.addAction(_("action.pause_all"), self._pause_all)
        m_dl.addAction(_("action.stop_all"), self._stop_all)
        m_dl.addAction(_("action.retry_all"), self._retry_all_failed)
        m_dl.addSeparator()
        m_clear = m_dl.addMenu("Clear List")
        m_clear.addAction(_("action.clear_completed"), self._clear_completed)
        m_clear.addAction("Clear Failed", self._clear_failed)
        m_clear.addAction("Clear Stopped", self._clear_stopped)
        m_clear.addAction("Clear Failed & Stopped", self._clear_failed_and_stopped)
        m_clear.addSeparator()
        m_clear.addAction("Clear Entire List...", self._clear_all)
        m_dl.addSeparator()
        m_done = m_dl.addMenu("When All Downloads Finish")
        done_group = QActionGroup(self)
        done_group.setExclusive(True)
        for key, label in (
            ("nothing", "Do Nothing"),
            ("sleep", "Sleep PC"),
            ("hibernate", "Hibernate PC"),
            ("shutdown", "Shutdown PC"),
            ("close", "Close TurboFetch"),
        ):
            act = QAction(label, self, checkable=True, checked=(key == self._completion_action))
            act.triggered.connect(lambda _=False, k=key: setattr(self, "_completion_action", k))
            done_group.addAction(act)
            m_done.addAction(act)
        m_dl.addSeparator()
        m_dl.addAction("Create Queue...", self._create_queue)
        m_dl.addAction("Start Active Queue", self._start_selected_queue)
        m_dl.addAction("Scheduler...", self._show_scheduler)

        m_view = mb.addMenu(_("menu.view"))
        m_view.addAction(_("action.toggle_theme"), self._toggle_theme)
        seg_checked = self.segment_bar.isVisible() if hasattr(self, "segment_bar") else True
        graph_checked = self.speed_graph.isVisible() if hasattr(self, "speed_graph") else True
        basket_checked = self.drop_basket.isVisible() if hasattr(self, "drop_basket") else False
        self._act_segbar = QAction(_("action.show_segbar"), self, checkable=True, checked=seg_checked)
        self._act_segbar.toggled.connect(lambda on: self.segment_bar.setVisible(on))
        m_view.addAction(self._act_segbar)
        self._act_speed_graph = QAction(_("action.show_speed_graph"), self, checkable=True, checked=graph_checked)
        self._act_speed_graph.toggled.connect(lambda on: self.speed_graph.setVisible(on))
        m_view.addAction(self._act_speed_graph)
        self._act_drop_basket = QAction(_("action.drop_basket"), self, checkable=True, checked=basket_checked)
        self._act_drop_basket.toggled.connect(self._toggle_drop_basket)
        m_view.addAction(self._act_drop_basket)

        m_help = mb.addMenu(_("menu.help"))
        m_help.addAction(_("action.check_updates"), self._check_updates)
        m_help.addAction(_("app.about"), self._show_about)

        mb.addAction(_("app.settings"), self._show_settings)

    def _build_ui(self) -> None:
        self.toolbar = DownloadToolbar(self)
        self.addToolBar(self.toolbar)

        self.toolbar.addUrlRequested.connect(lambda: self._show_add_url_dialog())
        self.toolbar.resumeRequested.connect(self._resume_selected)
        self.toolbar.pauseRequested.connect(self._pause_selected)
        self.toolbar.stopRequested.connect(self._stop_selected)
        self.toolbar.deleteRequested.connect(self._delete_selected)
        self.toolbar.openFileRequested.connect(self._open_selected_file)
        self.toolbar.openFolderRequested.connect(self._open_selected_folder)
        self.toolbar.scheduleRequested.connect(self._show_scheduler)
        self.toolbar.ytdlpRequested.connect(self._show_ytdlp)
        self.toolbar.settingsRequested.connect(self._show_settings)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.sidebar = CategorySidebar(splitter)
        self.sidebar.categoryChanged.connect(self._filter_by_category)

        right = QWidget(splitter)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(12, 10, 12, 10)
        right_layout.setSpacing(8)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        self.search_box = QLineEdit()
        self.search_box.setMinimumHeight(32)
        self.search_box.setPlaceholderText("Search downloads by name, URL, or category...")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._search_downloads)
        search_row.addWidget(self.search_box)

        self.btn_clear_list = QToolButton()
        self.btn_clear_list.setObjectName("clearListBtn")
        self.btn_clear_list.setMinimumHeight(32)
        self.btn_clear_list.setText("Clear List")
        self.btn_clear_list.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        clear_menu = QMenu(self.btn_clear_list)
        clear_menu.addAction("Clear Completed", self._clear_completed)
        clear_menu.addAction("Clear Failed", self._clear_failed)
        clear_menu.addAction("Clear Stopped", self._clear_stopped)
        clear_menu.addAction("Clear Failed & Stopped", self._clear_failed_and_stopped)
        clear_menu.addSeparator()
        clear_menu.addAction("Clear Entire List...", self._clear_all)
        self.btn_clear_list.setMenu(clear_menu)
        search_row.addWidget(self.btn_clear_list)

        right_layout.addLayout(search_row)

        self.table = DownloadTableView(right)
        self.table.selectionModel().selectionChanged.connect(self._update_toolbar_and_segments)
        self.table.contextMenuRequested.connect(self._show_context_menu)
        self.table.openFileRequested.connect(self._open_file_by_id)
        self.table.queueReordered.connect(self._on_queue_reordered)
        right_layout.addWidget(self.table)

        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(0, 0, 0, 0)
        bottom_row.setSpacing(6)
        self.segment_bar = SegmentBar(right)
        self.speed_graph = SpeedGraphWidget(parent=right)
        bottom_row.addWidget(self.segment_bar, 3)
        bottom_row.addWidget(self.speed_graph, 2)
        right_layout.addLayout(bottom_row)

        splitter.addWidget(self.sidebar)
        splitter.addWidget(right)
        splitter.setHandleWidth(2)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([220, 1000])
        self.setCentralWidget(splitter)

        self.status_bar = QStatusBar(self)
        self.setStatusBar(self.status_bar)
        self.cmb_speed_limit = QComboBox()
        self.cmb_speed_limit.addItem("Speed Limit: Unlimited", 0)
        self.cmb_speed_limit.addItem("Speed Limit: 1 MB/s", 1024 * 1024)
        self.cmb_speed_limit.addItem("Speed Limit: 5 MB/s", 5 * 1024 * 1024)
        self.cmb_speed_limit.addItem("Speed Limit: 10 MB/s", 10 * 1024 * 1024)
        self.cmb_speed_limit.addItem("Speed Limit: 25 MB/s", 25 * 1024 * 1024)
        self.cmb_speed_limit.addItem("Speed Limit: 50 MB/s", 50 * 1024 * 1024)
        self._sync_speed_combo()
        self.cmb_speed_limit.currentIndexChanged.connect(self._on_quick_speed_changed)
        self.status_bar.addWidget(self.cmb_speed_limit)
        self.lbl_status_summary = QLabel("Ready")
        self.status_bar.addPermanentWidget(self.lbl_status_summary)

    def _build_shortcuts(self) -> None:
        QShortcut(QKeySequence("Delete"), self, self._delete_selected)
        QShortcut(QKeySequence("F5"), self, self._refresh_downloads)

    def _on_tick(self) -> None:
        tasks = self.engine.get_all_downloads()
        has_active = any(
            t.status in (DownloadStatus.DOWNLOADING, DownloadStatus.PROBING, DownloadStatus.MERGING)
            for t in tasks
        )
        if not has_active:
            if self._was_active_tick:
                self._was_active_tick = False
                if self.speed_graph.isVisible():
                    self.speed_graph.push_speed(0.0)
                if self.drop_basket.isVisible():
                    self.drop_basket.set_status(0, 0.0)
            return
        self._was_active_tick = True
        if not self.isVisible():
            active = [t for t in tasks if t.status == DownloadStatus.DOWNLOADING]
            total_speed = sum(t.speed for t in active)
            if self.tray is not None:
                self.tray.set_status(len(active), total_speed)
            if self.drop_basket.isVisible():
                self.drop_basket.set_status(len(active), total_speed)
            return
        self.table.download_model.refresh_visible()
        self._update_status_bar()
        self._update_sidebar_counts()
        self._update_toolbar_and_segments(live_only=True)

    def _refresh_downloads(self) -> None:
        tasks = self.engine.get_all_downloads()
        self.table.download_model.set_downloads(tasks)
        self._update_sidebar_counts()
        self._update_status_bar()
        self._update_toolbar_and_segments(live_only=False)

    def _reload_queues_sidebar(self) -> None:
        queues = [q.name for q in self.queue_manager.get_all_queues()]
        self.sidebar.set_queues(queues)

    def _update_sidebar_counts(self) -> None:
        tasks = self.engine.get_all_downloads()
        counts: dict[str, int] = {"all": len(tasks), "unfinished": 0, "finished": 0}
        for t in tasks:
            if t.status == DownloadStatus.COMPLETED:
                counts["finished"] += 1
            else:
                counts["unfinished"] += 1
            counts[t.category] = counts.get(t.category, 0) + 1
            counts[t.status.value] = counts.get(t.status.value, 0) + 1
            qkey = f"queue:{t.queue_name}"
            counts[qkey] = counts.get(qkey, 0) + 1
        if counts != self._last_sidebar_counts:
            self._last_sidebar_counts = counts
            self.sidebar.set_counts(counts)

    def _update_status_bar(self) -> None:
        tasks = self.engine.get_all_downloads()
        active = [t for t in tasks if t.status == DownloadStatus.DOWNLOADING]
        total_speed = sum(t.speed for t in active)
        total_bytes = sum(t.downloaded for t in tasks)
        remaining_bytes = sum(max(0, t.size - t.downloaded) for t in active if t.size > 0)
        eta_str = format_eta(remaining_bytes / total_speed) if total_speed > 0 and remaining_bytes > 0 else "-"
        free_str = "-"
        try:
            probe = Path(self.config_manager.get().download_dir)
            while not probe.exists() and probe.parent != probe:
                probe = probe.parent
            free_str = format_size(shutil.disk_usage(probe).free)
        except OSError:
            pass
        self.lbl_status_summary.setText(
            f"Active: {len(active)} | Speed: {format_speed(total_speed)} | ETA: {eta_str} | Total: {format_size(total_bytes)} | Free: {free_str}"
        )
        if self.speed_graph.isVisible() and active:
            self.speed_graph.push_speed(total_speed)
        if self.drop_basket.isVisible():
            self.drop_basket.set_status(len(active), total_speed)
        if self.tray is not None:
            self.tray.set_status(len(active), total_speed)

    def _update_toolbar_and_segments(self, live_only: bool = False) -> None:
        selected = self.table.selected_tasks()
        if not selected:
            self._last_selected_id = ""
            self.toolbar.set_button_states(False, None)
            self.segment_bar.set_segments([])
            return
        first = selected[0]
        self.toolbar.set_button_states(True, first.status.value)
        dl = self.engine.get_downloader(first.id)
        if dl is not None and dl.segment_states:
            self.segment_bar.set_segments(dl.segment_states)
        elif not live_only or first.id != self._last_selected_id:
            self._last_selected_id = first.id
            segs = [s.to_dict() for s in self.db.get_segments(first.id)]
            self.segment_bar.set_segments(segs)

    def _filter_by_category(self, category: str) -> None:
        self.table.download_model.filter_by_category(category)

    def _search_downloads(self, query: str) -> None:
        self.table.download_model.filter_by_search(query)

    def _resolve_save_dir(self, base_dir: str, url_or_name: str, auto_cat: bool) -> tuple[str, str]:
        cfg = self.config_manager.get()
        cat = categorize_file(url_or_name, cfg.file_types)
        if auto_cat and cat in cfg.save_locations and base_dir == cfg.download_dir:
            return cfg.save_locations[cat], cat
        return base_dir, cat

    def _proxy_url(self) -> Optional[str]:
        cfg = self.config_manager.get()
        if not cfg.proxy_enabled or not cfg.proxy_host:
            return None
        creds = f"{cfg.proxy_username}:{cfg.proxy_password}@" if cfg.proxy_username else ""
        return f"{cfg.proxy_type}://{creds}{cfg.proxy_host}:{cfg.proxy_port}"

    def _show_add_url_dialog(self, url: str = "") -> None:
        queues = [q.name for q in self.queue_manager.get_all_queues()]
        dlg = AddUrlDialog(
            config_manager=self.config_manager,
            queues=queues,
            run_coro=self.run_coro,
            initial_url=url,
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        res = dlg.get_result()
        urls = res["urls"]
        if not urls:
            return
        video_urls = [u for u in urls if is_video_page_url(u)]
        file_urls = [u for u in urls if not is_video_page_url(u)]
        start_now = res["action"] == "start"
        cfg = self.config_manager.get()
        proxy = self._proxy_url()

        if file_urls:
            headers = {"User-Agent": cfg.user_agent}
            if res.get("referer"):
                headers["Referer"] = str(res["referer"])

            async def add_all() -> None:
                for idx, u in enumerate(file_urls):
                    fname = res["filename"] if idx == 0 and len(file_urls) == 1 else None
                    save_dir, cat = self._resolve_save_dir(
                        res["save_path"] or cfg.download_dir,
                        fname or u,
                        res["auto_categorize"],
                    )
                    await self.engine.add_download(
                        url=u,
                        save_path=save_dir,
                        filename=fname,
                        headers=headers,
                        proxy=proxy,
                        auth=res.get("auth"),
                        connections=res["connections"],
                        checksum=res["checksum"] if len(file_urls) == 1 else None,
                        checksum_type=res["checksum_type"],
                        category=cat,
                        queue_name=res["queue_name"],
                        conflict_mode=cfg.conflict_resolution,
                        start_now=start_now,
                    )

            self.run_coro(add_all())
        if res["action"] == "schedule":
            self._show_scheduler()
        if video_urls:
            self._show_ytdlp(video_urls[0])

    def _show_context_menu(self, global_pos: Any, tasks: list[DownloadTask]) -> None:
        menu = QMenu(self)
        first = tasks[0]
        menu.addAction("Resume", self._resume_selected)
        menu.addAction("Pause", self._pause_selected)
        menu.addAction("Stop", self._stop_selected)
        menu.addAction("Retry", self._retry_selected)
        menu.addSeparator()
        menu.addAction("Open File", self._open_selected_file)
        menu.addAction("Open Folder", self._open_selected_folder)
        menu.addSeparator()
        menu.addAction("Copy Link", lambda: self._copy_link(first.url))
        menu.addAction("Update Expired URL...", lambda: self._update_expired_url(first))
        menu.addAction("Set Speed Limit...", lambda: self._prompt_speed_limit(first))
        menu.addAction("Redownload", lambda: self._redownload(first))
        menu.addAction("Properties", lambda: self._show_properties(first))
        menu.addSeparator()
        menu.addAction("Remove from List", self._delete_selected)
        menu.addAction("Delete with File(s)", self._delete_selected_with_files)
        menu.exec(global_pos)

    def _resume_selected(self) -> None:
        for t in self.table.selected_tasks():
            self.run_coro(self.engine.resume_download(t.id))

    def _pause_selected(self) -> None:
        for t in self.table.selected_tasks():
            self.run_coro(self.engine.pause_download(t.id))

    def _stop_selected(self) -> None:
        for t in self.table.selected_tasks():
            self.run_coro(self.engine.stop_download(t.id))

    def _retry_selected(self) -> None:
        for t in self.table.selected_tasks():
            self.run_coro(self.engine.retry_download(t.id))

    def _delete_selected(self) -> None:
        tasks = self.table.selected_tasks()
        if not tasks:
            return
        reply = QMessageBox.question(
            self,
            "Remove from List",
            f"Remove {len(tasks)} selected download(s) from the list?\n(Completed files on disk will be kept.)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._remove_tasks(tasks, delete_files=False)

    def _delete_selected_with_files(self) -> None:
        tasks = self.table.selected_tasks()
        if not tasks:
            return
        reply = QMessageBox.question(
            self,
            "Delete Files",
            f"Remove {len(tasks)} selected download(s) AND delete their file(s) from disk?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._remove_tasks(tasks, delete_files=True)

    def _remove_tasks(self, tasks: list[DownloadTask], delete_files: bool = False) -> None:
        for t in tasks:
            if t.status in (DownloadStatus.DOWNLOADING, DownloadStatus.PROBING):
                self.run_coro(self.engine.cancel_download(t.id))
            if t.save_path and t.filename:
                part_file = Path(t.save_path) / f"{t.filename}.part"
                part_file.unlink(missing_ok=True)
                if delete_files:
                    final_file = Path(t.save_path) / t.filename
                    final_file.unlink(missing_ok=True)
            self.engine.remove_download(t.id)
            self.db.delete_download(t.id)
        self._refresh_downloads()

    def _clear_by_statuses(self, statuses: set[DownloadStatus]) -> None:
        targets = [t for t in self.engine.get_all_downloads() if t.status in statuses]
        if targets:
            self._remove_tasks(targets, delete_files=False)

    def _clear_completed(self) -> None:
        self._clear_by_statuses({DownloadStatus.COMPLETED})

    def _clear_failed(self) -> None:
        self._clear_by_statuses({DownloadStatus.FAILED})

    def _clear_stopped(self) -> None:
        self._clear_by_statuses({DownloadStatus.STOPPED})

    def _clear_failed_and_stopped(self) -> None:
        self._clear_by_statuses({DownloadStatus.FAILED, DownloadStatus.STOPPED})

    def _clear_all(self) -> None:
        tasks = self.engine.get_all_downloads()
        if not tasks:
            return
        reply = QMessageBox.question(
            self,
            "Clear Entire List",
            f"Remove all {len(tasks)} item(s) from the download list?\n(Active downloads will be stopped; completed files stay on disk.)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._remove_tasks(tasks, delete_files=False)

    def _retry_all_failed(self) -> None:
        for t in self.engine.get_all_downloads():
            if t.status == DownloadStatus.FAILED:
                self.run_coro(self.engine.retry_download(t.id))

    def _update_expired_url(self, task: DownloadTask) -> None:
        new_url, ok = QInputDialog.getText(
            self,
            "Update Expired URL",
            "Paste the fresh download URL (existing progress will be kept):",
            text=task.url,
        )
        if ok and new_url.strip():
            if self.engine.update_url(task.id, new_url.strip()):
                self.run_coro(self.engine.resume_download(task.id))

    def _sync_speed_combo(self) -> None:
        limit = self.config_manager.get().global_speed_limit
        idx = self.cmb_speed_limit.findData(limit)
        self.cmb_speed_limit.blockSignals(True)
        self.cmb_speed_limit.setCurrentIndex(idx if idx >= 0 else 0)
        self.cmb_speed_limit.blockSignals(False)

    def _on_quick_speed_changed(self) -> None:
        limit = int(self.cmb_speed_limit.currentData() or 0)
        self.config_manager.update(global_speed_limit=limit)
        if self.on_settings_applied:
            self.on_settings_applied()

    def _pause_all(self) -> None:
        for t in self.engine.get_all_downloads():
            if t.status in (DownloadStatus.DOWNLOADING, DownloadStatus.PROBING):
                self.run_coro(self.engine.pause_download(t.id))

    def _resume_all(self) -> None:
        for t in self.engine.get_all_downloads():
            if t.status in (DownloadStatus.PAUSED, DownloadStatus.STOPPED, DownloadStatus.QUEUED):
                self.run_coro(self.engine.resume_download(t.id))

    def _stop_all(self) -> None:
        for t in self.engine.get_all_downloads():
            if t.status in (DownloadStatus.DOWNLOADING, DownloadStatus.PROBING, DownloadStatus.PAUSED):
                self.run_coro(self.engine.stop_download(t.id))

    def _open_selected_file(self) -> None:
        tasks = self.table.selected_tasks()
        if tasks:
            self._open_file_by_id(tasks[0].id)

    def _open_file_by_id(self, download_id: str) -> None:
        task = self.engine.get_download(download_id)
        if task is None:
            return
        path = Path(task.save_path) / task.filename
        if not path.exists():
            QMessageBox.warning(self, "File Not Found", f"{path} does not exist.")
            return
        if sys.platform == "win32":
            os.startfile(str(path))
        else:
            subprocess.Popen(["xdg-open", str(path)])

    def _open_selected_folder(self) -> None:
        tasks = self.table.selected_tasks()
        if not tasks:
            return
        task = tasks[0]
        file_path = Path(task.save_path) / task.filename
        if sys.platform == "win32":
            if file_path.exists():
                subprocess.Popen(["explorer", "/select,", str(file_path)])
            elif Path(task.save_path).exists():
                os.startfile(task.save_path)
        else:
            subprocess.Popen(["xdg-open", task.save_path])

    def _copy_link(self, url: str) -> None:
        cb = QApplication.clipboard()
        if cb is not None:
            cb.setText(url)

    def _redownload(self, task: DownloadTask) -> None:
        self.run_coro(
            self.engine.add_download(
                url=task.url,
                save_path=task.save_path,
                filename=task.filename,
                headers=task.headers,
                cookies=task.cookies,
                proxy=task.proxy,
                connections=task.max_connections,
                category=task.category,
                queue_name=task.queue_name,
                start_now=True,
            )
        )

    def _show_properties(self, task: DownloadTask) -> None:
        dl = self.engine.get_downloader(task.id)
        segs = dl.segment_states if dl else [s.to_dict() for s in self.db.get_segments(task.id)]
        limit_bps = int(self.engine.get_download_speed_limit(task.id))
        dlg = PropertiesDialog(
            task,
            segs,
            self,
            current_speed_limit=limit_bps,
            on_refresh_url=self._update_expired_url,
            on_speed_limit=self._apply_task_speed_limit,
        )
        dlg.exec()

    def _apply_task_speed_limit(self, task: DownloadTask, bytes_per_sec: int) -> None:
        self.engine.set_download_speed_limit(task.id, float(bytes_per_sec))
        txt = f"{bytes_per_sec // 1024} KB/s" if bytes_per_sec > 0 else "Unlimited"
        self.status_bar.showMessage(f"Speed limit for {task.filename or task.url}: {txt}", 4000)

    def _prompt_speed_limit(self, task: DownloadTask) -> None:
        cur_kbps = int(self.engine.get_download_speed_limit(task.id) // 1024)
        kbps, ok = QInputDialog.getInt(
            self,
            "Per-Download Speed Limit",
            f"Max speed in KB/s for {task.filename or task.url} (0 = Unlimited):",
            cur_kbps,
            0,
            1000000,
        )
        if ok:
            self._apply_task_speed_limit(task, kbps * 1024)

    def _show_settings(self) -> None:
        dlg = SettingsDialog(self.config_manager, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            cfg = self.config_manager.get()
            self.theme_manager.set_font_size(cfg.font_size)
            self.theme_manager.set_theme(cfg.theme)
            set_language(cfg.language)
            self.setWindowTitle(_("app.title"))
            self._build_menu_bar()
            self.toolbar.retranslate_ui()
            self.sidebar.retranslate_ui(self._last_sidebar_counts)
            if cfg.clipboard_monitoring and not self.clipboard_monitor.is_running:
                self.clipboard_monitor.start()
            elif not cfg.clipboard_monitoring and self.clipboard_monitor.is_running:
                self.clipboard_monitor.stop()
            if self.on_settings_applied:
                self.on_settings_applied()
            self._sync_speed_combo()

    def _show_scheduler(self) -> None:
        dlg = SchedulerDialog(self.scheduler, self.queue_manager, self)
        dlg.exec()

    def _show_ytdlp(self, url: str = "", cookies: Optional[dict[str, str]] = None) -> None:
        dlg = YtDlpPanel(
            self.config_manager,
            self.run_coro,
            on_queue_video=self._queue_video_download,
            initial_url=url,
            cookies=cookies,
            parent=self,
        )
        dlg.exec()

    def _show_site_grabber(self) -> None:
        dlg = SiteGrabberDialog(
            self.config_manager,
            self.run_coro,
            on_queue_urls=self._queue_grabbed_urls,
            parent=self,
        )
        dlg.exec()

    def _queue_grabbed_urls(self, urls: list[str], save_dir: str, connections: int) -> None:
        proxy = self._proxy_url()
        for url in urls:
            if is_video_page_url(url):
                self._show_ytdlp(url)
                continue
            self.run_coro(
                self.engine.add_download(
                    url=url,
                    save_path=save_dir,
                    connections=connections,
                    proxy=proxy,
                )
            )

    def _toggle_drop_basket(self, visible: bool) -> None:
        if visible:
            tasks = self.engine.get_all_downloads()
            active = [t for t in tasks if t.status == DownloadStatus.DOWNLOADING]
            self.drop_basket.set_status(len(active), sum(t.speed for t in active))
            self.drop_basket.show()
            self.drop_basket.raise_()
        else:
            self.drop_basket.hide()

    def _queue_video_download(self, opts: dict[str, Any]) -> None:
        cfg = self.config_manager.get()
        out_dir = str(opts.get("save_path") or "").strip() or cfg.save_locations.get("video", cfg.download_dir)
        proxy = self._proxy_url()
        self.run_coro(
            self.engine.add_video_download(
                url=opts["url"],
                save_path=out_dir,
                title=opts.get("title", ""),
                cookies=opts.get("cookies"),
                proxy=proxy,
                ytdlp_options=opts,
            )
        )

    def on_video_requested(self, url: str, cookies: Optional[dict[str, str]] = None) -> None:
        self.showNormal()
        self.activateWindow()
        self.raise_()
        self._show_ytdlp(url, cookies=cookies)

    def on_quick_video_requested(self, url: str, cookies: Optional[dict[str, str]] = None) -> None:
        cfg = self.config_manager.get()
        self._queue_video_download(
            {
                "url": url,
                "title": "",
                "cookies": cookies,
                "format_id": "",
                "resolution": "Best",
                "audio_only": False,
                "playlist": False,
                "save_path": cfg.save_locations.get("video", cfg.download_dir),
            }
        )

    def on_download_confirm_requested(self, payload: dict[str, Any]) -> None:
        self.showNormal()
        self.activateWindow()
        self.raise_()
        url = str(payload.get("url") or "")
        if not url:
            return
        queues = [q.name for q in self.queue_manager.get_all_queues()]
        dlg = AddUrlDialog(
            config_manager=self.config_manager,
            queues=queues,
            run_coro=self.run_coro,
            initial_url=url,
            parent=self,
        )
        if payload.get("filename"):
            dlg.edt_filename.setText(str(payload["filename"]))
        if payload.get("save_path"):
            dlg.edt_folder.setText(str(payload["save_path"]))
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        res = dlg.get_result()
        urls = res["urls"] or [url]
        cfg = self.config_manager.get()
        headers = dict(payload.get("headers") or {})
        if res.get("referer"):
            headers["Referer"] = str(res["referer"])
        cookies = dict(payload.get("cookies") or {})
        proxy = payload.get("proxy") or self._proxy_url()
        start_now = res["action"] == "start"

        async def add_confirmed() -> None:
            for u in urls:
                save_dir, cat = self._resolve_save_dir(
                    res["save_path"] or cfg.download_dir,
                    res["filename"] or u,
                    res["auto_categorize"],
                )
                await self.engine.add_download(
                    url=u,
                    save_path=save_dir,
                    filename=res["filename"],
                    headers=headers,
                    cookies=cookies,
                    proxy=proxy,
                    auth=res.get("auth"),
                    connections=res["connections"],
                    checksum=res["checksum"],
                    checksum_type=res["checksum_type"],
                    category=cat,
                    queue_name=res["queue_name"],
                    conflict_mode=cfg.conflict_resolution,
                    start_now=start_now,
                )

        self.run_coro(add_confirmed())

    def _show_history(self) -> None:
        dlg = _HistoryDialog(self.db, self)
        dlg.exec()

    def _create_queue(self) -> None:
        name, ok = QInputDialog.getText(self, "New Queue", "Queue name:")
        if ok and name.strip():
            self.queue_manager.create_queue(name.strip())
            self._reload_queues_sidebar()

    def _start_selected_queue(self) -> None:
        cat = self.table.download_model._category
        qname = cat[6:] if cat.startswith("queue:") else "default"
        self.run_coro(self.queue_manager.start_queue(qname))

    def _on_queue_reordered(self, queue_name: str, ordered_ids: list[str]) -> None:
        self.queue_manager.reorder_queue(queue_name, ordered_ids)
        self._refresh_downloads()

    def _export_downloads(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export Downloads", "downloads.json", "JSON (*.json)")
        if path:
            self.db.export_downloads(Path(path))

    def _export_urls_txt(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export URL List", "urls.txt", "Text Files (*.txt)")
        if path:
            urls = [t.url for t in self.engine.get_all_downloads() if t.url]
            Path(path).write_text("\n".join(urls) + ("\n" if urls else ""), encoding="utf-8")

    def _import_downloads(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import Downloads", "", "Supported (*.json *.txt);;JSON (*.json);;URL List (*.txt)")
        if not path:
            return
        p = Path(path)
        if p.suffix.lower() == ".txt":
            urls = [
                ln.strip()
                for ln in p.read_text(encoding="utf-8", errors="ignore").splitlines()
                if ln.strip().startswith(("http://", "https://", "ftp://"))
            ]
            if urls:
                self._show_add_url_dialog("\n".join(urls))
            return
        count = self.db.import_downloads(p)
        for rec in self.db.get_all_downloads():
            if self.engine.get_download(rec.id) is None:
                segs = [s.to_dict() for s in self.db.get_segments(rec.id)]
                self.engine.register_existing_task(rec.to_download_task(), segs)
        self._refresh_downloads()
        QMessageBox.information(self, "Import Complete", f"Imported {count} download(s).")

    def _toggle_theme(self) -> None:
        next_t = self.theme_manager.toggle_theme()
        self.config_manager.update(theme=next_t)

    def _check_updates(self) -> None:
        checker = UpdateChecker()

        async def run_check() -> None:
            has_upd, latest, url = await checker.check_for_updates()
            self._updateCheckReady.emit(has_upd, latest, url)

        self.run_coro(run_check())

    def _on_update_result(self, has_update: bool, latest: str, url: str) -> None:
        if has_update:
            QMessageBox.information(
                self,
                "Update Available",
                f"TurboFetch {latest} is available.\nDownload: {url}",
            )
        else:
            QMessageBox.information(
                self,
                "No Updates",
                f"You are running the latest version ({UpdateChecker.CURRENT_VERSION}).",
            )

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About TurboFetch",
            "TurboFetch Download Manager v1.0.0\n\n"
            "Free & open-source multi-connection download manager for Windows.",
        )

    def _on_clipboard_url(self, url: str) -> None:
        reply = QMessageBox.question(
            self,
            "Download Detected",
            f"Download this URL with TurboFetch?\n\n{url}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._show_add_url_dialog(url)

    def _focus_download_in_window(self, download_id: str) -> None:
        self.showNormal()
        self.activateWindow()
        self.raise_()
        model = self.table.download_model
        for row in range(model.rowCount()):
            task = model.get_task(row)
            if task is not None and task.id == download_id:
                self.table.selectRow(row)
                self.table.scrollTo(model.index(row, 0))
                break

    def _toggle_pause_by_id(self, download_id: str) -> None:
        task = self.engine.get_download(download_id)
        if task is None:
            return
        if task.status in (DownloadStatus.DOWNLOADING, DownloadStatus.PROBING):
            self.run_coro(self.engine.pause_download(download_id))
        else:
            self.run_coro(self.engine.resume_download(download_id))

    def on_download_added(self, download_id: str) -> None:
        self._refresh_downloads()
        task = self.engine.get_download(download_id)
        if task is None:
            return
        label = task.filename or task.url
        self.status_bar.showMessage(f"Download started: {label}", 5000)
        cfg = self.config_manager.get()
        if cfg.play_sounds:
            play_notification_sound()
        if cfg.show_start_popup:
            self.toast_popup.show_download(download_id, "TurboFetch - Download Started")
        elif self.tray is not None and not self.isActiveWindow():
            self.tray.showMessage("Download Started", label, self.tray.MessageIcon.Information, 3000)

    def on_download_completed(self, download_id: str) -> None:
        task = self.engine.get_download(download_id)
        if task is not None:
            cfg = self.config_manager.get()
            if cfg.play_sounds:
                play_notification_sound()
            if cfg.show_start_popup:
                self.toast_popup.show_download(download_id, "TurboFetch - Download Complete")
            if self.tray is not None:
                self.tray.notify_completed(task.filename or task.url)
            if cfg.auto_scan_defender and task.save_path and task.filename:
                target_file = Path(task.save_path) / task.filename

                async def run_scan() -> None:
                    ok, msg = await scan_file_with_defender(target_file)
                    self._defenderScanFinished.emit(task.filename, ok, msg)

                self.run_coro(run_scan())
        self._refresh_downloads()
        if self._completion_action != "nothing":
            still_active = any(
                t.status in (DownloadStatus.DOWNLOADING, DownloadStatus.PROBING, DownloadStatus.MERGING)
                for t in self.engine.get_all_downloads()
            )
            if not still_active:
                self.scheduler._execute_completion_action(self._completion_action)

    def _on_defender_scan_finished(self, filename: str, clean: bool, msg: str) -> None:
        if clean:
            self.status_bar.showMessage(f"Defender Scan ({filename}): {msg}", 5000)
        else:
            QMessageBox.warning(self, "Security Warning", f"Windows Defender alert for {filename}:\n{msg}")

    def on_download_failed(self, download_id: str, error: str) -> None:
        task = self.engine.get_download(download_id)
        if task and self.tray is not None:
            self.tray.notify_failed(task.filename or task.url, error)
        self._refresh_downloads()

    def on_status_changed(self, _download_id: str, _status: str) -> None:
        self._refresh_downloads()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        urls: list[str] = []
        if event.mimeData().hasUrls():
            for u in event.mimeData().urls():
                if u.isLocalFile() and u.toLocalFile().lower().endswith(".txt"):
                    p = Path(u.toLocalFile())
                    for ln in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                        ln = ln.strip()
                        if ln.startswith(("http://", "https://", "ftp://")):
                            urls.append(ln)
                else:
                    s = u.toString()
                    if s.startswith(("http://", "https://", "ftp://")):
                        urls.append(s)
        elif event.mimeData().hasText():
            for ln in event.mimeData().text().splitlines():
                ln = ln.strip()
                if ln.startswith(("http://", "https://", "ftp://")):
                    urls.append(ln)
        if urls:
            self._show_add_url_dialog("\n".join(urls))

    def _toggle_visibility(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.showNormal()
            self.activateWindow()

    def _quit_app(self) -> None:
        self._force_quit = True
        self.close()

    def closeEvent(self, event: Any) -> None:
        cfg = self.config_manager.get()
        if not self._force_quit and cfg.minimize_to_tray and self.tray is not None:
            event.ignore()
            self.hide()
            return
        self.clipboard_monitor.stop()
        self._refresh_timer.stop()
        self.toast_popup.close()
        self.drop_basket.close()
        if self.tray is not None:
            self.tray.hide()
        event.accept()
