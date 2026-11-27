from datetime import datetime
from typing import Any, Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from turbofetch.app.engine.downloader import DownloadTask
from turbofetch.app.ui.download_table import format_eta, format_size, format_speed
from turbofetch.app.ui.segment_bar import SegmentBar


class PropertiesDialog(QDialog):
    def __init__(
        self,
        task: DownloadTask,
        segments: list[dict[str, Any]],
        parent: Optional[QWidget] = None,
        current_speed_limit: int = 0,
        on_refresh_url: Optional[Callable[[DownloadTask], None]] = None,
        on_speed_limit: Optional[Callable[[DownloadTask, int], None]] = None,
    ) -> None:
        super().__init__(parent)
        self.task = task
        self._current_speed_limit = current_speed_limit
        self._on_refresh_url = on_refresh_url
        self._on_speed_limit = on_speed_limit
        self.setWindowTitle(f"Properties - {task.filename or task.url}")
        self.resize(540, 600)
        self._build_ui(segments)

    def _ro_line(self, value: str) -> QLineEdit:
        edt = QLineEdit(value)
        edt.setReadOnly(True)
        return edt

    def _build_ui(self, segments: list[dict[str, Any]]) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        form.addRow("URL:", self._ro_line(self.task.url))
        form.addRow("Final URL:", self._ro_line(self.task.final_url or self.task.url))
        form.addRow("Filename:", self._ro_line(self.task.filename))
        form.addRow("Save Path:", self._ro_line(self.task.save_path))
        form.addRow("Size:", QLabel(f"{format_size(self.task.size)} ({self.task.size:,} bytes)"))

        pct = (self.task.downloaded / self.task.size * 100.0) if self.task.size > 0 else 0.0
        form.addRow("Downloaded:", QLabel(f"{format_size(self.task.downloaded)} ({pct:.1f}%)"))
        form.addRow("Status:", QLabel(self.task.status.value.capitalize()))
        form.addRow("Speed:", QLabel(format_speed(self.task.speed)))
        form.addRow("ETA:", QLabel(format_eta(self.task.eta)))
        form.addRow("Connections:", QLabel(f"{self.task.connections} / {self.task.max_connections}"))
        form.addRow("Category:", QLabel(self.task.category))
        form.addRow("Queue:", QLabel(self.task.queue_name))
        form.addRow(
            "Date Added:",
            QLabel(datetime.fromtimestamp(self.task.date_added).strftime("%Y-%m-%d %H:%M:%S")),
        )
        completed_str = (
            datetime.fromtimestamp(self.task.date_completed).strftime("%Y-%m-%d %H:%M:%S")
            if self.task.date_completed
            else "-"
        )
        form.addRow("Date Completed:", QLabel(completed_str))
        form.addRow("ETag:", self._ro_line(self.task.etag or "-"))
        form.addRow("Last-Modified:", self._ro_line(self.task.last_modified or "-"))
        form.addRow(
            "Checksum:",
            self._ro_line(
                f"{self.task.checksum_type}: {self.task.checksum}"
                if self.task.checksum
                else "-"
            ),
        )
        if self.task.error:
            err_lbl = QLabel(self.task.error)
            err_lbl.setWordWrap(True)
            err_lbl.setStyleSheet("color: #ef4444;")
            form.addRow("Error:", err_lbl)

        if self._on_speed_limit is not None:
            limit_row = QHBoxLayout()
            self.spn_limit = QSpinBox()
            self.spn_limit.setRange(0, 1000000)
            self.spn_limit.setValue(max(0, self._current_speed_limit // 1024))
            self.spn_limit.setSuffix(" KB/s (0 = unlimited)")
            btn_apply_limit = QPushButton("Apply")
            btn_apply_limit.clicked.connect(self._apply_speed_limit)
            limit_row.addWidget(self.spn_limit)
            limit_row.addWidget(btn_apply_limit)
            form.addRow("Speed Limit:", limit_row)

        layout.addLayout(form)

        layout.addWidget(QLabel("Segment Progress:"))
        self.segment_bar = SegmentBar(self)
        self.segment_bar.set_segments(segments)
        layout.addWidget(self.segment_bar)

        btn_row = QHBoxLayout()
        if self._on_refresh_url is not None:
            btn_refresh = QPushButton("Refresh Expired URL...")
            btn_refresh.clicked.connect(self._refresh_url)
            btn_row.addWidget(btn_refresh)
        btn_row.addStretch()
        btn_copy = QPushButton("Copy URL")
        btn_copy.clicked.connect(self._copy_url)
        btn_close = QPushButton("Close")
        btn_close.setProperty("primary", "true")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_copy)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

    def _apply_speed_limit(self) -> None:
        if self._on_speed_limit is not None:
            self._on_speed_limit(self.task, self.spn_limit.value() * 1024)

    def _refresh_url(self) -> None:
        if self._on_refresh_url is not None:
            self._on_refresh_url(self.task)
            self.accept()

    def _copy_url(self) -> None:
        cb = QApplication.clipboard()
        if cb is not None:
            cb.setText(self.task.url)
