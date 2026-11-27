from datetime import datetime
from typing import Any, Optional

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QRect,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QStyleOptionViewItem,
    QStyledItemDelegate,
    QTableView,
    QWidget,
)

from turbofetch.app.engine.downloader import DownloadStatus, DownloadTask


def format_size(num_bytes: int) -> str:
    if num_bytes < 0:
        return "Unknown"
    val = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if val < 1024.0:
            return f"{val:.1f} {unit}" if unit != "B" else f"{int(val)} B"
        val /= 1024.0
    return f"{val:.1f} PB"


def format_speed(bps: float) -> str:
    if bps <= 0:
        return "-"
    for unit in ("B/s", "KB/s", "MB/s", "GB/s"):
        if bps < 1024.0:
            return f"{bps:.1f} {unit}"
        bps /= 1024.0
    return f"{bps:.1f} TB/s"


def format_eta(seconds: float) -> str:
    if seconds <= 0:
        return "-"
    secs = int(seconds)
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


class DownloadTableModel(QAbstractTableModel):
    COLUMNS = [
        "Name",
        "Size",
        "Progress",
        "Speed",
        "ETA",
        "Status",
        "Date Added",
        "Connections",
    ]

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._all_downloads: list[DownloadTask] = []
        self._filtered: list[DownloadTask] = []
        self._category: str = "all"
        self._search: str = ""
        self._sort_col: int = 6
        self._sort_order: Qt.SortOrder = Qt.SortOrder.DescendingOrder

    def set_downloads(self, downloads: list[DownloadTask]) -> None:
        self.beginResetModel()
        self._all_downloads = list(downloads)
        self._apply_filters()
        self.endResetModel()

    def refresh_visible(self) -> None:
        if not self._filtered:
            return
        top_left = self.index(0, 0)
        bottom_right = self.index(len(self._filtered) - 1, len(self.COLUMNS) - 1)
        self.dataChanged.emit(top_left, bottom_right)

    def filter_by_category(self, category: str) -> None:
        self.beginResetModel()
        self._category = category
        self._apply_filters()
        self.endResetModel()

    def filter_by_search(self, query: str) -> None:
        self.beginResetModel()
        self._search = query.strip().lower()
        self._apply_filters()
        self.endResetModel()

    def _matches_category(self, task: DownloadTask) -> bool:
        cat = self._category
        if cat == "all":
            return True
        if cat == "unfinished":
            return task.status != DownloadStatus.COMPLETED
        if cat == "finished":
            return task.status == DownloadStatus.COMPLETED
        if cat in ("downloading", "paused", "failed", "queued"):
            return task.status.value == cat
        if cat.startswith("queue:"):
            return task.queue_name == cat[6:]
        return task.category.lower() == cat.lower()

    def _matches_search(self, task: DownloadTask) -> bool:
        if not self._search:
            return True
        return (
            self._search in (task.filename or "").lower()
            or self._search in (task.url or "").lower()
            or self._search in (task.category or "").lower()
        )

    def _apply_filters(self) -> None:
        items = [t for t in self._all_downloads if self._matches_category(t) and self._matches_search(t)]
        reverse = self._sort_order == Qt.SortOrder.DescendingOrder

        def sort_key(t: DownloadTask) -> Any:
            if self._sort_col == 0:
                return (t.filename or t.url).lower()
            if self._sort_col == 1:
                return t.size
            if self._sort_col == 2:
                return (t.downloaded / t.size) if t.size > 0 else 0.0
            if self._sort_col == 3:
                return t.speed
            if self._sort_col == 4:
                return t.eta
            if self._sort_col == 5:
                return t.status.value
            if self._sort_col == 6:
                return t.date_added
            if self._sort_col == 7:
                return t.connections
            return t.date_added

        if self._category.startswith("queue:"):
            items.sort(key=lambda t: (t.priority, t.date_added))
        else:
            items.sort(key=sort_key, reverse=reverse)
        self._filtered = items

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        self.beginResetModel()
        self._sort_col = column
        self._sort_order = order
        self._apply_filters()
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._filtered)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self.COLUMNS)

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            if 0 <= section < len(self.COLUMNS):
                return self.COLUMNS[section]
        return None

    def get_task(self, row: int) -> Optional[DownloadTask]:
        if 0 <= row < len(self._filtered):
            return self._filtered[row]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        task = self.get_task(index.row())
        if task is None:
            return None
        col = index.column()

        if role == Qt.ItemDataRole.UserRole:
            return task

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return task.filename or task.url
            if col == 1:
                return format_size(task.size)
            if col == 2:
                if task.status == DownloadStatus.COMPLETED:
                    return 100.0
                if task.size > 0:
                    return min(99.9, (task.downloaded / task.size) * 100.0)
                return 0.0
            if col == 3:
                return format_speed(task.speed) if task.status == DownloadStatus.DOWNLOADING else "-"
            if col == 4:
                return format_eta(task.eta) if task.status == DownloadStatus.DOWNLOADING else "-"
            if col == 5:
                return task.status.value.capitalize()
            if col == 6:
                return datetime.fromtimestamp(task.date_added).strftime("%Y-%m-%d %H:%M")
            if col == 7:
                return f"{task.connections}/{task.max_connections}" if task.status == DownloadStatus.DOWNLOADING else str(task.max_connections)

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (1, 3, 4, 5, 6, 7):
                return int(Qt.AlignmentFlag.AlignCenter)
            return int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

        if role == Qt.ItemDataRole.ToolTipRole and task.error:
            return task.error

        return None


class ProgressDelegate(QStyledItemDelegate):
    _STATUS_COLORS = {
        "downloading": QColor("#3b82f6"),
        "completed": QColor("#22c55e"),
        "failed": QColor("#ef4444"),
        "paused": QColor("#f59e0b"),
        "stopped": QColor("#64748b"),
        "queued": QColor("#6366f1"),
        "probing": QColor("#06b6d4"),
        "merging": QColor("#8b5cf6"),
    }

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> None:
        task: Optional[DownloadTask] = index.data(Qt.ItemDataRole.UserRole)
        progress = float(index.data(Qt.ItemDataRole.DisplayRole) or 0.0)
        status = task.status.value if task else "queued"
        color = self._STATUS_COLORS.get(status, QColor("#3b82f6"))

        painter.save()
        rect: QRect = option.rect.adjusted(6, 6, -6, -6)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor("#17233c"))
        painter.setPen(QPen(QColor("#243659"), 1))
        painter.drawRoundedRect(rect, 5, 5)

        fill_w = int((rect.width() - 2) * max(0.0, min(100.0, progress)) / 100.0)
        if fill_w > 0:
            fill_rect = QRect(rect.x() + 1, rect.y() + 1, fill_w, rect.height() - 2)
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(fill_rect, 4, 4)

        painter.setPen(QColor("#eef4ff"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"{progress:.1f}%")
        painter.restore()


class DownloadTableView(QTableView):
    contextMenuRequested = Signal(object, list)
    openFileRequested = Signal(str)
    queueReordered = Signal(str, list)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._model = DownloadTableModel(self)
        self.setModel(self._model)
        self.setItemDelegateForColumn(2, ProgressDelegate(self))
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSortingEnabled(True)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(34)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        self.doubleClicked.connect(self._on_double_click)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDropIndicatorShown(True)

        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        widths = {1: 90, 2: 140, 3: 95, 4: 80, 5: 95, 6: 130, 7: 105}
        for col, w in widths.items():
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
            self.setColumnWidth(col, w)

    @property
    def download_model(self) -> DownloadTableModel:
        return self._model

    def selected_tasks(self) -> list[DownloadTask]:
        rows = sorted({idx.row() for idx in self.selectionModel().selectedRows()})
        tasks: list[DownloadTask] = []
        for r in rows:
            t = self._model.get_task(r)
            if t is not None:
                tasks.append(t)
        return tasks

    def _on_context_menu(self, pos: Any) -> None:
        tasks = self.selected_tasks()
        if tasks:
            self.contextMenuRequested.emit(self.viewport().mapToGlobal(pos), tasks)

    def _on_double_click(self, index: QModelIndex) -> None:
        task = self._model.get_task(index.row())
        if task is not None and task.status == DownloadStatus.COMPLETED:
            self.openFileRequested.emit(task.id)

    def dropEvent(self, event: Any) -> None:
        if not self._model._category.startswith("queue:"):
            event.ignore()
            return
        source_tasks = self.selected_tasks()
        if not source_tasks:
            event.ignore()
            return
        drop_idx = self.indexAt(event.position().toPoint())
        target_row = drop_idx.row() if drop_idx.isValid() else self._model.rowCount() - 1
        ordered = [t.id for t in self._model._filtered]
        moved_ids = [t.id for t in source_tasks]
        remaining = [tid for tid in ordered if tid not in moved_ids]
        insert_at = max(0, min(len(remaining), target_row))
        new_order = remaining[:insert_at] + moved_ids + remaining[insert_at:]
        self.queueReordered.emit(self._model._category[6:], new_order)
        event.accept()
