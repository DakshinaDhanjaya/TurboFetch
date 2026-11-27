import asyncio
import shutil
from pathlib import Path
from typing import Any, Callable, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from turbofetch.app.engine.protocols import FileInfo, probe_url
from turbofetch.app.utils.config import ConfigManager
from turbofetch.app.utils.filename import is_video_page_url


def _fmt_size(size: int) -> str:
    if size <= 0:
        return "Unknown"
    val = float(size)
    for u in ("B", "KB", "MB", "GB"):
        if val < 1024.0:
            return f"{val:.1f} {u}"
        val /= 1024.0
    return f"{val:.1f} TB"


class AddUrlDialog(QDialog):
    _probeFinished = Signal(object)

    def __init__(
        self,
        config_manager: ConfigManager,
        queues: list[str],
        run_coro: Optional[Callable[[Any], Any]] = None,
        initial_url: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.config_manager = config_manager
        self.queues = queues or ["default"]
        self.run_coro = run_coro
        self.action_choice: str = "start"
        self._detected_size: int = -1
        self.setWindowTitle("Add Download")
        self.resize(580, 540)
        self.setAcceptDrops(True)
        self._build_ui(initial_url)
        self._probeFinished.connect(self._apply_probe_result)
        if initial_url:
            self._on_detect()

    def _build_ui(self, initial_url: str) -> None:
        cfg = self.config_manager.get()
        layout = QVBoxLayout(self)

        url_header = QHBoxLayout()
        url_header.addWidget(QLabel("URL(s) (one per line for batch):"))
        self.btn_detect = QPushButton("Detect")
        self.btn_detect.clicked.connect(self._on_detect)
        url_header.addWidget(self.btn_detect)
        layout.addLayout(url_header)

        self.txt_urls = QTextEdit()
        self.txt_urls.setMaximumHeight(90)
        self.txt_urls.setPlaceholderText("https://example.com/file.zip")
        if initial_url:
            self.txt_urls.setPlainText(initial_url)
        self.txt_urls.textChanged.connect(self._on_urls_changed)
        layout.addWidget(self.txt_urls)

        self.batch_list = QListWidget()
        self.batch_list.setMaximumHeight(90)
        self.batch_list.hide()
        layout.addWidget(self.batch_list)

        form = QFormLayout()

        self.edt_filename = QLineEdit()
        self.edt_filename.setPlaceholderText("Auto-detect from server")
        form.addRow("Filename:", self.edt_filename)

        self.lbl_size = QLabel("Unknown")
        form.addRow("Detected Size:", self.lbl_size)

        folder_row = QHBoxLayout()
        self.edt_folder = QLineEdit(cfg.download_dir)
        self.edt_folder.textChanged.connect(self._update_free_space)
        btn_browse = QPushButton("Browse...")
        btn_browse.clicked.connect(self._browse_folder)
        folder_row.addWidget(self.edt_folder)
        folder_row.addWidget(btn_browse)
        form.addRow("Save Folder:", folder_row)

        self.lbl_free_space = QLabel("")
        form.addRow("Disk Space:", self.lbl_free_space)

        self.spn_connections = QSpinBox()
        self.spn_connections.setRange(1, 32)
        self.spn_connections.setValue(cfg.default_connections)
        form.addRow("Connections:", self.spn_connections)

        self.cmb_queue = QComboBox()
        self.cmb_queue.addItems(self.queues)
        form.addRow("Queue:", self.cmb_queue)

        checksum_row = QHBoxLayout()
        self.cmb_checksum = QComboBox()
        self.cmb_checksum.addItems(["sha256", "sha1", "md5"])
        self.edt_checksum = QLineEdit()
        self.edt_checksum.setPlaceholderText("Optional expected checksum")
        checksum_row.addWidget(self.cmb_checksum)
        checksum_row.addWidget(self.edt_checksum)
        form.addRow("Checksum:", checksum_row)

        self.chk_custom_name = QCheckBox("Auto-categorize folder by file type")
        self.chk_custom_name.setChecked(cfg.auto_categorize)
        form.addRow("", self.chk_custom_name)

        auth_row = QHBoxLayout()
        self.edt_auth_user = QLineEdit()
        self.edt_auth_user.setPlaceholderText("Username (optional)")
        self.edt_auth_pass = QLineEdit()
        self.edt_auth_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.edt_auth_pass.setPlaceholderText("Password")
        auth_row.addWidget(self.edt_auth_user)
        auth_row.addWidget(self.edt_auth_pass)
        form.addRow("HTTP Auth:", auth_row)

        self.edt_referer = QLineEdit()
        self.edt_referer.setPlaceholderText("Referer URL or extra Cookie/Header (optional)")
        form.addRow("Referer:", self.edt_referer)

        self._update_free_space()
        layout.addLayout(form)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_start = QPushButton("Download Now")
        self.btn_start.setProperty("primary", "true")
        self.btn_start.clicked.connect(lambda: self._accept_with("start"))

        self.btn_queue = QPushButton("Add to Queue")
        self.btn_queue.clicked.connect(lambda: self._accept_with("queue"))

        self.btn_schedule = QPushButton("Schedule")
        self.btn_schedule.clicked.connect(lambda: self._accept_with("schedule"))

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)

        btn_row.addWidget(self.btn_start)
        btn_row.addWidget(self.btn_queue)
        btn_row.addWidget(self.btn_schedule)
        btn_row.addWidget(self.btn_cancel)
        layout.addLayout(btn_row)

    def _accept_with(self, choice: str) -> None:
        self.action_choice = choice
        self.accept()

    def _browse_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Select Save Folder", self.edt_folder.text())
        if chosen:
            self.edt_folder.setText(chosen)

    def _parsed_urls(self) -> list[str]:
        lines = [ln.strip() for ln in self.txt_urls.toPlainText().splitlines()]
        return [ln for ln in lines if ln.startswith(("http://", "https://", "ftp://"))]

    def _on_urls_changed(self) -> None:
        urls = self._parsed_urls()
        if len(urls) > 1:
            self.batch_list.show()
            self.batch_list.clear()
            for u in urls:
                item = QListWidgetItem(u)
                item.setCheckState(Qt.CheckState.Checked)
                self.batch_list.addItem(item)
            self.edt_filename.setEnabled(False)
        else:
            self.batch_list.hide()
            self.edt_filename.setEnabled(True)
            if len(urls) == 1 and is_video_page_url(urls[0]):
                self.lbl_size.setText("Video page detected (will open Video Downloader)")

    def _on_detect(self) -> None:
        urls = self._parsed_urls()
        if not urls:
            return
        url = urls[0]
        if is_video_page_url(url):
            self.lbl_size.setText("Video page detected (will open Video Downloader)")
            return
        if self.run_coro is None:
            return
        self.lbl_size.setText("Probing...")

        async def do_probe() -> None:
            try:
                info = await probe_url(url, timeout=15)
                self._probeFinished.emit(info)
            except Exception:
                self._probeFinished.emit(None)

        self.run_coro(do_probe())

    def _update_free_space(self) -> None:
        raw = self.edt_folder.text().strip()
        target = Path(raw) if raw else Path.home()
        probe = target
        while not probe.exists() and probe.parent != probe:
            probe = probe.parent
        try:
            free_b = shutil.disk_usage(probe).free
            free_str = _fmt_size(free_b)
            if self._detected_size > 0 and self._detected_size > free_b:
                self.lbl_free_space.setText(f"Free: {free_str} (Warning: Not enough space!)")
                self.lbl_free_space.setStyleSheet("color: #f87171;")
            else:
                self.lbl_free_space.setText(f"Free: {free_str}")
                self.lbl_free_space.setStyleSheet("")
        except OSError:
            self.lbl_free_space.setText("Free: Unknown")

    def _apply_probe_result(self, info: Optional[FileInfo]) -> None:
        if info is None:
            self.lbl_size.setText("Detection failed")
            return
        self._detected_size = info.size
        if not self.edt_filename.text().strip():
            self.edt_filename.setText(info.filename)
        resumable = "Yes" if info.resumable else "No"
        self.lbl_size.setText(f"{_fmt_size(info.size)} (Resumable: {resumable})")
        self._update_free_space()

    def dragEnterEvent(self, event: Any) -> None:
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event: Any) -> None:
        if event.mimeData().hasUrls():
            lines = []
            for u in event.mimeData().urls():
                if u.isLocalFile() and u.toLocalFile().lower().endswith(".txt"):
                    p = Path(u.toLocalFile())
                    lines.extend(p.read_text(encoding="utf-8", errors="ignore").splitlines())
                else:
                    lines.append(u.toString())
            self.txt_urls.setPlainText("\n".join(ln for ln in lines if ln.strip()))
        elif event.mimeData().hasText():
            self.txt_urls.setPlainText(event.mimeData().text())

    def get_result(self) -> dict[str, Any]:
        urls = self._parsed_urls()
        if self.batch_list.isVisible():
            selected_urls = []
            for i in range(self.batch_list.count()):
                item = self.batch_list.item(i)
                if item.checkState() == Qt.CheckState.Checked:
                    selected_urls.append(item.text())
            urls = selected_urls
        auth_user = self.edt_auth_user.text().strip()
        auth_pass = self.edt_auth_pass.text()
        referer = self.edt_referer.text().strip()
        return {
            "urls": urls,
            "filename": self.edt_filename.text().strip() or None,
            "save_path": self.edt_folder.text().strip(),
            "connections": self.spn_connections.value(),
            "queue_name": self.cmb_queue.currentText(),
            "checksum": self.edt_checksum.text().strip() or None,
            "checksum_type": self.cmb_checksum.currentText(),
            "auto_categorize": self.chk_custom_name.isChecked(),
            "auth": (auth_user, auth_pass) if auth_user else None,
            "referer": referer,
            "action": self.action_choice,
        }
