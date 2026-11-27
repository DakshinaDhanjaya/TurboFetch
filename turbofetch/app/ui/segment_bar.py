from typing import Any

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QToolTip, QWidget


class SegmentBar(QWidget):
    _STATE_COLORS = {
        "pending": QColor("#334155"),
        "downloading": QColor("#3b82f6"),
        "completed": QColor("#22c55e"),
        "failed": QColor("#ef4444"),
        "paused": QColor("#f59e0b"),
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._segments: list[dict[str, Any]] = []
        self.setMinimumHeight(22)
        self.setMaximumHeight(26)
        self.setMouseTracking(True)

    def set_segments(self, segments: list[dict[str, Any]]) -> None:
        self._segments = list(segments)
        self.update()

    def _total_span(self) -> int:
        if not self._segments:
            return 0
        max_end = max((int(s.get("end", -1)) for s in self._segments), default=-1)
        if max_end >= 0:
            return max_end + 1
        return sum(max(1, int(s.get("downloaded", 0))) for s in self._segments)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(1, 1, self.width() - 2, self.height() - 2)
        painter.setBrush(QColor("#111a2e"))
        painter.setPen(QPen(QColor("#243659"), 1))
        painter.drawRoundedRect(rect, 6, 6)

        if not self._segments:
            return

        total = self._total_span()
        if total <= 0:
            return

        w = rect.width()
        h = rect.height()
        x0 = rect.x()
        y0 = rect.y()

        for seg in self._segments:
            start = int(seg.get("start", 0))
            end = int(seg.get("end", -1))
            downloaded = int(seg.get("downloaded", 0))
            state = str(seg.get("state", "pending")).lower()

            if end >= start >= 0:
                seg_len = end - start + 1
                seg_x = x0 + (start / total) * w
                seg_w = max(1.0, (seg_len / total) * w)
                ratio = min(1.0, max(0.0, downloaded / seg_len)) if seg_len > 0 else 0.0
            else:
                seg_x = x0
                seg_w = w
                ratio = 0.5 if state == "downloading" else (1.0 if state == "completed" else 0.0)

            bg_rect = QRectF(seg_x, y0 + 1, seg_w, h - 2)
            painter.fillRect(bg_rect, QColor("#17233c"))

            color = self._STATE_COLORS.get(state, QColor("#334155"))
            fill_w = seg_w if state == "completed" else seg_w * ratio
            if fill_w > 0:
                painter.fillRect(QRectF(seg_x, y0 + 1, fill_w, h - 2), color)

            painter.setPen(QPen(QColor("#0b1220"), 1))
            painter.drawLine(int(seg_x + seg_w), int(y0), int(seg_x + seg_w), int(y0 + h))

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self._segments or self.width() <= 2:
            return
        total = self._total_span()
        if total <= 0:
            return
        rel_x = max(0.0, min(1.0, (event.position().x() - 1) / (self.width() - 2)))
        byte_pos = int(rel_x * total)
        for seg in self._segments:
            start = int(seg.get("start", 0))
            end = int(seg.get("end", -1))
            if end < 0 or (start <= byte_pos <= end):
                seg_len = (end - start + 1) if end >= start else 0
                dl = int(seg.get("downloaded", 0))
                pct = (dl / seg_len * 100.0) if seg_len > 0 else 0.0
                tip = (
                    f"Segment #{seg.get('id', 0)}\n"
                    f"State: {seg.get('state', 'pending')}\n"
                    f"Range: {start:,} - {end:,}\n"
                    f"Downloaded: {dl:,} B ({pct:.1f}%)"
                )
                QToolTip.showText(event.globalPosition().toPoint(), tip, self)
                break
