from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QStyle, QSystemTrayIcon, QWidget


def format_speed(bps: float) -> str:
    if bps <= 0:
        return "0 B/s"
    for unit in ("B/s", "KB/s", "MB/s", "GB/s"):
        if bps < 1024.0:
            return f"{bps:.1f} {unit}"
        bps /= 1024.0
    return f"{bps:.1f} TB/s"


class SystemTray(QSystemTrayIcon):
    showHideRequested = Signal()
    addUrlRequested = Signal()
    pauseAllRequested = Signal()
    resumeAllRequested = Signal()
    settingsRequested = Signal()
    exitRequested = Signal()

    def __init__(self, parent: Optional[QWidget] = None, icon: Optional[QIcon] = None) -> None:
        resolved_icon = icon
        if resolved_icon is None or resolved_icon.isNull():
            if parent is not None:
                resolved_icon = parent.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown)
            else:
                resolved_icon = QIcon()
        super().__init__(resolved_icon, parent)
        self._menu = QMenu(parent)

        act_show = QAction("Show / Hide", self._menu)
        act_show.triggered.connect(self.showHideRequested.emit)
        self._menu.addAction(act_show)

        act_add = QAction("Add URL", self._menu)
        act_add.triggered.connect(self.addUrlRequested.emit)
        self._menu.addAction(act_add)

        self._menu.addSeparator()

        act_pause_all = QAction("Pause All", self._menu)
        act_pause_all.triggered.connect(self.pauseAllRequested.emit)
        self._menu.addAction(act_pause_all)

        act_resume_all = QAction("Resume All", self._menu)
        act_resume_all.triggered.connect(self.resumeAllRequested.emit)
        self._menu.addAction(act_resume_all)

        self._menu.addSeparator()

        act_settings = QAction("Settings", self._menu)
        act_settings.triggered.connect(self.settingsRequested.emit)
        self._menu.addAction(act_settings)

        act_exit = QAction("Exit", self._menu)
        act_exit.triggered.connect(self.exitRequested.emit)
        self._menu.addAction(act_exit)

        self.setContextMenu(self._menu)
        self.activated.connect(self._on_activated)
        self._last_tooltip = "TurboFetch Download Manager"
        self.setToolTip(self._last_tooltip)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.showHideRequested.emit()

    def set_status(self, active_count: int, total_speed: float) -> None:
        tip = f"TurboFetch - Active: {active_count} | Speed: {format_speed(total_speed)}"
        if tip != self._last_tooltip:
            self._last_tooltip = tip
            self.setToolTip(tip)

    def notify_completed(self, filename: str) -> None:
        self.showMessage(
            "Download Complete",
            f"{filename} finished downloading.",
            QSystemTrayIcon.MessageIcon.Information,
            4000,
        )

    def notify_failed(self, filename: str, error: str) -> None:
        self.showMessage(
            "Download Failed",
            f"{filename}: {error}",
            QSystemTrayIcon.MessageIcon.Critical,
            5000,
        )
