import re
from html.parser import HTMLParser
from typing import Any, Callable, Optional
from urllib.parse import urljoin, urlparse

import httpx
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from turbofetch.app.engine.protocols import build_client_kwargs
from turbofetch.app.utils.config import ConfigManager
from turbofetch.app.utils.filename import categorize_file, filename_from_url

_IMAGE_EXTS = {"jpg", "jpeg", "png", "gif", "webp", "bmp", "svg"}


class _LinkExtractor(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        attr_map = dict(attrs)
        raw = None
        if tag == "a":
            raw = attr_map.get("href")
        elif tag in ("video", "audio", "source", "img"):
            raw = attr_map.get("src")
        if raw:
            full = urljoin(self.base_url, raw.strip())
            parsed = urlparse(full)
            if parsed.scheme in ("http", "https"):
                self.links.append(full)


class SiteGrabberDialog(QDialog):
    _scanFinished = Signal(object, str)

    def __init__(
        self,
        config_manager: ConfigManager,
        run_coro: Optional[Callable[[Any], Any]],
        on_queue_urls: Callable[[list[str], str, int], None],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.config_manager = config_manager
        self.run_coro = run_coro
        self.on_queue_urls = on_queue_urls
        self._all_links: list[str] = []
        self.setWindowTitle("Site Grabber - Extract & Download Page Links")
        self.resize(680, 500)
        self._build_ui()
        self._scanFinished.connect(self._on_scan_finished)

    def _build_ui(self) -> None:
        cfg = self.config_manager.get()
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.edt_page_url = QLineEdit()
        self.edt_page_url.setPlaceholderText("https://example.com/downloads/")
        self.btn_scan = QPushButton("Scan Page")
        self.btn_scan.setProperty("primary", "true")
        self.btn_scan.clicked.connect(self._on_scan)
        top.addWidget(self.edt_page_url)
        top.addWidget(self.btn_scan)
        layout.addLayout(top)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Filter:"))
        self.cmb_filter = QComboBox()
        self.cmb_filter.addItems(
            ["All Downloadable", "video", "music", "compressed", "documents", "programs", "images", "All Links"]
        )
        self.cmb_filter.currentTextChanged.connect(self._apply_filter)
        self.edt_search = QLineEdit()
        self.edt_search.setPlaceholderText("Filter by keyword or extension...")
        self.edt_search.textChanged.connect(self._apply_filter)
        btn_sel_all = QPushButton("Select All")
        btn_sel_all.clicked.connect(lambda: self._set_all_checked(True))
        btn_none = QPushButton("Select None")
        btn_none.clicked.connect(lambda: self._set_all_checked(False))
        filter_row.addWidget(self.cmb_filter)
        filter_row.addWidget(self.edt_search)
        filter_row.addWidget(btn_sel_all)
        filter_row.addWidget(btn_none)
        layout.addLayout(filter_row)

        self.list_links = QListWidget()
        layout.addWidget(self.list_links)

        save_row = QHBoxLayout()
        save_row.addWidget(QLabel("Save to:"))
        self.edt_save_dir = QLineEdit(cfg.download_dir)
        btn_browse = QPushButton("Browse...")
        btn_browse.clicked.connect(self._browse_dir)
        save_row.addWidget(self.edt_save_dir)
        save_row.addWidget(btn_browse)
        save_row.addWidget(QLabel("Connections:"))
        self.spn_conns = QSpinBox()
        self.spn_conns.setRange(1, 32)
        self.spn_conns.setValue(cfg.default_connections)
        save_row.addWidget(self.spn_conns)
        layout.addLayout(save_row)

        footer = QHBoxLayout()
        self.lbl_status = QLabel("Enter a webpage URL and click Scan Page.")
        footer.addWidget(self.lbl_status)
        footer.addStretch()
        btn_dl = QPushButton("Download Selected")
        btn_dl.setProperty("primary", "true")
        btn_dl.clicked.connect(self._on_download)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.reject)
        footer.addWidget(btn_dl)
        footer.addWidget(btn_close)
        layout.addLayout(footer)

    def _browse_dir(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Select Save Folder", self.edt_save_dir.text())
        if chosen:
            self.edt_save_dir.setText(chosen)

    def _on_scan(self) -> None:
        url = self.edt_page_url.text().strip()
        if not url.startswith(("http://", "https://")) or self.run_coro is None:
            return
        self.btn_scan.setEnabled(False)
        self.lbl_status.setText("Scanning page links...")
        self.run_coro(self._scan_page(url))

    async def _scan_page(self, url: str) -> None:
        try:
            kwargs = build_client_kwargs(
                headers={"User-Agent": self.config_manager.get().user_agent},
                timeout=20,
                url=url,
            )
            async with httpx.AsyncClient(**kwargs) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                parser = _LinkExtractor(str(resp.url))
                parser.feed(resp.text)
                seen: list[str] = []
                seen_set: set[str] = set()
                for ln in parser.links:
                    clean = ln.split("#")[0]
                    if clean not in seen_set:
                        seen_set.add(clean)
                        seen.append(clean)
                self._scanFinished.emit(seen, "")
        except Exception as exc:
            self._scanFinished.emit([], str(exc))

    def _on_scan_finished(self, links: list[str], error: str) -> None:
        self.btn_scan.setEnabled(True)
        if error:
            self.lbl_status.setText(f"Scan error: {error}")
            return
        self._all_links = links
        self._apply_filter()

    def _matches_filter(self, url: str, filt: str, query: str) -> bool:
        if query and query not in url.lower():
            return False
        if filt == "All Links":
            return True
        fname = filename_from_url(url)
        ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
        if filt == "images":
            return ext in _IMAGE_EXTS
        cat = categorize_file(fname, self.config_manager.get().file_types)
        if filt == "All Downloadable":
            return cat != "other" or ext in _IMAGE_EXTS
        return cat == filt

    def _apply_filter(self) -> None:
        filt = self.cmb_filter.currentText()
        query = self.edt_search.text().strip().lower()
        self.list_links.clear()
        matched = [u for u in self._all_links if self._matches_filter(u, filt, query)]
        for u in matched:
            item = QListWidgetItem(u)
            item.setCheckState(Qt.CheckState.Checked)
            self.list_links.addItem(item)
        self.lbl_status.setText(f"Showing {len(matched)} of {len(self._all_links)} link(s)")

    def _set_all_checked(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(self.list_links.count()):
            self.list_links.item(i).setCheckState(state)

    def _on_download(self) -> None:
        selected = [
            self.list_links.item(i).text()
            for i in range(self.list_links.count())
            if self.list_links.item(i).checkState() == Qt.CheckState.Checked
        ]
        if not selected:
            return
        self.on_queue_urls(selected, self.edt_save_dir.text().strip(), self.spn_conns.value())
        self.accept()
