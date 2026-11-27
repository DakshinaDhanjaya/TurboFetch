import sys
from typing import Callable, Optional

from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from turbofetch.app.engine.downloader import DownloadStatus, DownloadTask
from turbofetch.app.ui.download_table import format_size, format_speed


class DownloadToastPopup(QFrame):
    def __init__(
        self,
        get_task: Callable[[str], Optional[DownloadTask]],
        on_open_app: Callable[[str], None],
        on_toggle_pause: Callable[[str], None],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._get_task = get_task
        self._on_open_app = on_open_app
        self._on_toggle_pause = on_toggle_pause
        self._download_id: str = ""

        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedWidth(360)
        self.setStyleSheet(
            """
            DownloadToastPopup {
                background-color: #111a2e;
                border: 1px solid #3b82f6;
                border-radius: 10px;
            }
            QLabel {
                background-color: transparent;
                color: #eef4ff;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        self.lbl_badge = QLabel("TurboFetch - Download Started")
        self.lbl_badge.setStyleSheet("color: #60a5fa; font-weight: 700; font-size: 12px;")
        btn_close = QPushButton("x")
        btn_close.setFixedSize(22, 22)
        btn_close.setStyleSheet(
            "QPushButton { background: transparent; border: none; color: #93a8cc; font-weight: 700; }"
            "QPushButton:hover { color: #ffffff; }"
        )
        btn_close.clicked.connect(self.hide)
        header.addWidget(self.lbl_badge)
        header.addStretch()
        header.addWidget(btn_close)
        layout.addLayout(header)

        self.lbl_name = QLabel("")
        self.lbl_name.setStyleSheet("font-weight: 600; font-size: 13px;")
        self.lbl_name.setWordWrap(False)
        layout.addWidget(self.lbl_name)

        self.progress = QProgressBar()
        self.progress.setFixedHeight(8)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)

        footer = QHBoxLayout()
        self.lbl_meta = QLabel("Connecting...")
        self.lbl_meta.setStyleSheet("color: #93a8cc; font-size: 11px;")
        footer.addWidget(self.lbl_meta)
        footer.addStretch()

        self.btn_pause = QPushButton("Pause")
        self.btn_pause.setFixedHeight(26)
        self.btn_pause.clicked.connect(self._handle_pause)

        self.btn_open = QPushButton("Open")
        self.btn_open.setProperty("primary", "true")
        self.btn_open.setFixedHeight(26)
        self.btn_open.clicked.connect(self._handle_open)

        footer.addWidget(self.btn_pause)
        footer.addWidget(self.btn_open)
        layout.addLayout(footer)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(400)
        self._poll_timer.timeout.connect(self._refresh)

    def show_download(self, download_id: str, title: str = "TurboFetch - Download Started") -> None:
        self._download_id = download_id
        self.lbl_badge.setText(title)
        self._refresh()
        self.adjustSize()
        self._position_bottom_right()
        self.show()
        self.raise_()
        self._poll_timer.start()
        self._hide_timer.start(6000)

    def _position_bottom_right(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        x = geo.right() - self.width() - 18
        y = geo.bottom() - self.height() - 18
        self.move(x, y)

    def _refresh(self) -> None:
        if not self._download_id:
            return
        task = self._get_task(self._download_id)
        if task is None:
            return
        display = task.filename or task.url
        if len(display) > 46:
            display = display[:43] + "..."
        self.lbl_name.setText(display)

        if task.status == DownloadStatus.COMPLETED:
            self.lbl_badge.setText("TurboFetch - Download Complete")
            self.lbl_badge.setStyleSheet("color: #22c55e; font-weight: 700; font-size: 12px;")
            self.progress.setRange(0, 100)
            self.progress.setValue(100)
            self.lbl_meta.setText(f"{format_size(task.size)} - Completed")
            self.btn_pause.hide()
        elif task.status == DownloadStatus.FAILED:
            self.lbl_badge.setText("TurboFetch - Download Failed")
            self.lbl_badge.setStyleSheet("color: #ef4444; font-weight: 700; font-size: 12px;")
            self.progress.setRange(0, 100)
            self.lbl_meta.setText(task.error or "Failed")
            self.btn_pause.hide()
        else:
            self.lbl_badge.setStyleSheet("color: #60a5fa; font-weight: 700; font-size: 12px;")
            self.btn_pause.show()
            is_paused = task.status in (DownloadStatus.PAUSED, DownloadStatus.STOPPED)
            self.btn_pause.setText("Resume" if is_paused else "Pause")
            if task.size > 0:
                self.progress.setRange(0, 100)
                pct = int(min(100.0, (task.downloaded / task.size) * 100.0))
                self.progress.setValue(pct)
                self.lbl_meta.setText(
                    f"{pct}% of {format_size(task.size)} | {format_speed(task.speed)}"
                )
            else:
                self.progress.setRange(0, 0)
                self.lbl_meta.setText(f"{task.status.value.capitalize()}...")

    def _handle_open(self) -> None:
        self._on_open_app(self._download_id)
        self.hide()

    def _handle_pause(self) -> None:
        self._on_toggle_pause(self._download_id)
        self._hide_timer.start(6000)

    def enterEvent(self, event: QEvent) -> None:
        self._hide_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self._hide_timer.start(4000)
        super().leaveEvent(event)

    def hideEvent(self, event: QEvent) -> None:
        self._poll_timer.stop()
        self._hide_timer.stop()
        super().hideEvent(event)


def play_notification_sound() -> None:
    if sys.platform != "win32":
        return
    try:
        import winsound

        winsound.MessageBeep(winsound.MB_ICONASTERISK)
    except Exception:
        pass
