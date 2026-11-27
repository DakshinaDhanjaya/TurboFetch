from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QStyle, QTreeWidget, QTreeWidgetItem, QWidget

from turbofetch.app.utils.i18n import _


class CategorySidebar(QTreeWidget):
    categoryChanged = Signal(str)

    _CATEGORIES = [
        ("all", "All Downloads", QStyle.StandardPixmap.SP_DirHomeIcon),
        ("compressed", "Compressed", QStyle.StandardPixmap.SP_FileDialogDetailedView),
        ("documents", "Documents", QStyle.StandardPixmap.SP_FileIcon),
        ("music", "Music", QStyle.StandardPixmap.SP_MediaVolume),
        ("video", "Video", QStyle.StandardPixmap.SP_MediaPlay),
        ("programs", "Programs", QStyle.StandardPixmap.SP_ComputerIcon),
        ("other", "Other", QStyle.StandardPixmap.SP_DirIcon),
    ]

    _STATUS_GROUPS = [
        ("unfinished", "Unfinished", QStyle.StandardPixmap.SP_BrowserReload),
        ("finished", "Finished", QStyle.StandardPixmap.SP_DialogApplyButton),
        ("downloading", "Downloading", QStyle.StandardPixmap.SP_ArrowDown),
        ("paused", "Paused", QStyle.StandardPixmap.SP_MediaPause),
        ("failed", "Failed", QStyle.StandardPixmap.SP_MessageBoxCritical),
        ("queued", "Queued", QStyle.StandardPixmap.SP_FileDialogListView),
    ]

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setIndentation(12)
        self.setMinimumWidth(200)
        self.setMaximumWidth(250)
        self.setAnimated(True)
        self._items_by_key: dict[str, QTreeWidgetItem] = {}
        self._base_labels: dict[str, str] = {}
        self._queues_root: Optional[QTreeWidgetItem] = None
        self._build_tree()
        self.currentItemChanged.connect(self._on_item_changed)

    def _build_tree(self) -> None:
        style = self.style()

        cat_root = QTreeWidgetItem(self, [_("cat.header")])
        cat_root.setFlags(cat_root.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        self._cat_root = cat_root
        for key, _default_label, icon_id in self._CATEGORIES:
            label = _(f"cat.{key}")
            item = QTreeWidgetItem(cat_root, [label])
            item.setData(0, Qt.ItemDataRole.UserRole, key)
            item.setIcon(0, style.standardIcon(icon_id))
            self._items_by_key[key] = item
            self._base_labels[key] = label
        cat_root.setExpanded(True)

        status_root = QTreeWidgetItem(self, [_("status.header")])
        status_root.setFlags(status_root.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        self._status_root = status_root
        for key, _default_label, icon_id in self._STATUS_GROUPS:
            label = _(f"status.{key}")
            item = QTreeWidgetItem(status_root, [label])
            item.setData(0, Qt.ItemDataRole.UserRole, key)
            item.setIcon(0, style.standardIcon(icon_id))
            self._items_by_key[key] = item
            self._base_labels[key] = label
        status_root.setExpanded(True)

        self._queues_root = QTreeWidgetItem(self, [_("queues.header")])
        self._queues_root.setFlags(self._queues_root.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        self._queues_root.setExpanded(True)

        self.setCurrentItem(self._items_by_key["all"])

    def retranslate_ui(self, counts: Optional[dict[str, int]] = None) -> None:
        self._cat_root.setText(0, _("cat.header"))
        self._status_root.setText(0, _("status.header"))
        if self._queues_root is not None:
            self._queues_root.setText(0, _("queues.header"))
        for key, _default_label, _icon_id in self._CATEGORIES:
            self._base_labels[key] = _(f"cat.{key}")
        for key, _default_label, _icon_id in self._STATUS_GROUPS:
            self._base_labels[key] = _(f"status.{key}")
        self.set_counts(counts or {})

    def set_queues(self, queue_names: list[str]) -> None:
        if self._queues_root is None:
            return
        for key in list(self._items_by_key.keys()):
            if key.startswith("queue:"):
                self._items_by_key.pop(key, None)
                self._base_labels.pop(key, None)
        while self._queues_root.childCount() > 0:
            self._queues_root.removeChild(self._queues_root.child(0))
        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogListView)
        for name in queue_names:
            key = f"queue:{name}"
            item = QTreeWidgetItem(self._queues_root, [name])
            item.setData(0, Qt.ItemDataRole.UserRole, key)
            item.setIcon(0, icon)
            self._items_by_key[key] = item
            self._base_labels[key] = name

    def set_counts(self, counts: dict[str, int]) -> None:
        for key, item in self._items_by_key.items():
            base = self._base_labels.get(key, key)
            cnt = counts.get(key, 0)
            item.setText(0, f"{base} ({cnt})" if cnt > 0 else base)

    def _on_item_changed(
        self, current: Optional[QTreeWidgetItem], _previous: Optional[QTreeWidgetItem]
    ) -> None:
        if current is None:
            return
        key = current.data(0, Qt.ItemDataRole.UserRole)
        if key:
            self.categoryChanged.emit(str(key))
