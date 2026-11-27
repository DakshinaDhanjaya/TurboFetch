from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from turbofetch.app.ui.download_table import format_speed


class DropBasketWidget(QWidget):
    def __init__(
        self,
        on_urls_dropped: Callable[[list[str]], None],
        on_toggle_main: Callable[[], None],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._on_urls_dropped = on_urls_dropped
        self._on_toggle_main = on_toggle_main
        self._drag_offset: Optional[QPoint] = None

        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setAcceptDrops(True)
        self.setFixedSize(78, 78)
        self.setStyleSheet(
            """
            DropBasketWidget {
                background-color: #111a2e;
                border: 2px solid #3b82f6;
                border-radius: 39px;
            }
            QLabel {
                background: transparent;
                color: #eef4ff;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 8, 6, 8)
        layout.setSpacing(2)

        self.lbl_title = QLabel("TF")
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_title.setStyleSheet("color: #60a5fa; font-weight: 800; font-size: 16px;")

        self.lbl_sub = QLabel("Drop URL")
        self.lbl_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_sub.setStyleSheet("color: #93a8cc; font-size: 10px;")

        layout.addWidget(self.lbl_title)
        layout.addWidget(self.lbl_sub)
        self._position_default()

    def _position_default(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        self.move(geo.right() - self.width() - 28, geo.top() + 90)

    def set_status(self, active_count: int, total_speed: float) -> None:
        if active_count > 0:
            self.lbl_title.setText(str(active_count))
            self.lbl_sub.setText(format_speed(total_speed))
        else:
            self.lbl_title.setText("TF")
            self.lbl_sub.setText("Drop URL")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        self._on_toggle_main()
        super().mouseDoubleClickEvent(event)

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
            self._on_urls_dropped(urls)
