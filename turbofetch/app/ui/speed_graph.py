from collections import deque
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import QWidget

from turbofetch.app.ui.download_table import format_speed


class SpeedGraphWidget(QWidget):
    def __init__(self, max_points: int = 60, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._samples: deque[float] = deque([0.0] * max_points, maxlen=max_points)
        self._max_points = max_points
        self._current_speed: float = 0.0
        self._peak_speed: float = 0.0
        self.setMinimumHeight(46)
        self.setMaximumHeight(56)
        self.setMinimumWidth(220)

    def push_speed(self, bytes_per_sec: float) -> None:
        val = max(0.0, float(bytes_per_sec))
        self._current_speed = val
        if val > self._peak_speed:
            self._peak_speed = val
        self._samples.append(val)
        self.update()

    def clear(self) -> None:
        self._samples = deque([0.0] * self._max_points, maxlen=self._max_points)
        self._current_speed = 0.0
        self._peak_speed = 0.0
        self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(1, 1, self.width() - 2, self.height() - 2)
        painter.setBrush(QColor("#111a2e"))
        painter.setPen(QPen(QColor("#243659"), 1))
        painter.drawRoundedRect(rect, 6, 6)

        samples = list(self._samples)
        max_val = max(max(samples, default=0.0), 1024.0)
        w = rect.width() - 8
        h = rect.height() - 10
        x0 = rect.x() + 4
        y0 = rect.y() + 5

        if len(samples) > 1 and w > 0 and h > 0:
            step = w / (len(samples) - 1)
            line_path = QPainterPath()
            area_path = QPainterPath()
            for i, val in enumerate(samples):
                x = x0 + i * step
                y = y0 + h - (val / max_val) * h
                pt = QPointF(x, y)
                if i == 0:
                    line_path.moveTo(pt)
                    area_path.moveTo(QPointF(x, y0 + h))
                    area_path.lineTo(pt)
                else:
                    line_path.lineTo(pt)
                    area_path.lineTo(pt)
            area_path.lineTo(QPointF(x0 + (len(samples) - 1) * step, y0 + h))
            area_path.closeSubpath()

            grad = QLinearGradient(0, y0, 0, y0 + h)
            grad.setColorAt(0.0, QColor(59, 130, 246, 110))
            grad.setColorAt(1.0, QColor(37, 99, 235, 10))
            painter.fillPath(area_path, grad)
            painter.setPen(QPen(QColor("#3b82f6"), 1.8))
            painter.drawPath(line_path)

        painter.setPen(QColor("#93a8cc"))
        painter.drawText(
            rect.adjusted(8, 2, -8, -2),
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
            f"Now: {format_speed(self._current_speed)}  |  Peak: {format_speed(self._peak_speed)}",
        )
