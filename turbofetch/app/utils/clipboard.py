import re
import time
from typing import Callable, Optional

from PySide6.QtWidgets import QApplication

URL_PATTERN: re.Pattern = re.compile(
    r"https?://[^\s<>\"']+|ftp://[^\s<>\"']+", re.IGNORECASE
)

DOWNLOADABLE_EXTENSIONS: set[str] = {
    ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz",
    ".exe", ".msi", ".dmg", ".deb", ".rpm", ".appimage",
    ".iso", ".img",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".mp3", ".flac", ".wav", ".aac", ".ogg", ".wma", ".m4a",
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v",
    ".apk", ".ipa",
    ".torrent",
}

MIN_URL_LENGTH: int = 60
DEDUP_WINDOW: float = 30.0


class ClipboardMonitor:
    def __init__(self, on_url_detected: Callable[[str], None]) -> None:
        self._on_url_detected = on_url_detected
        self._clipboard = QApplication.clipboard()
        self._running: bool = False
        self._recent_urls: dict[str, float] = {}

    def _has_downloadable_extension(self, url: str) -> bool:
        path = url.split("?")[0].split("#")[0]
        dot_idx = path.rfind(".")
        if dot_idx == -1:
            return False
        ext = path[dot_idx:].lower()
        return ext in DOWNLOADABLE_EXTENSIONS

    def _is_candidate_url(self, url: str) -> bool:
        return self._has_downloadable_extension(url) or len(url) >= MIN_URL_LENGTH

    def _is_duplicate(self, url: str) -> bool:
        now = time.monotonic()
        self._recent_urls = {
            u: t for u, t in self._recent_urls.items() if now - t < DEDUP_WINDOW
        }
        if url in self._recent_urls:
            return True
        self._recent_urls[url] = now
        return False

    def _on_clipboard_changed(self) -> None:
        if not self._running:
            return
        text: Optional[str] = self._clipboard.text()
        if not text:
            return
        match = URL_PATTERN.search(text.strip())
        if not match:
            return
        url = match.group(0)
        if not self._is_candidate_url(url):
            return
        if self._is_duplicate(url):
            return
        self._on_url_detected(url)

    def start(self) -> None:
        if self._running or self._clipboard is None:
            return
        self._running = True
        self._clipboard.dataChanged.connect(self._on_clipboard_changed)

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._clipboard is not None:
            try:
                self._clipboard.dataChanged.disconnect(self._on_clipboard_changed)
            except (TypeError, RuntimeError):
                pass
        self._recent_urls.clear()

    @property
    def is_running(self) -> bool:
        return self._running
