from typing import Optional

from PySide6.QtCore import QTime
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from turbofetch.app.scheduler.queue_manager import QueueManager
from turbofetch.app.scheduler.scheduler import DownloadScheduler


class _AddScheduleDialog(QDialog):
    def __init__(self, queues: list[str], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New Schedule")
        self.resize(360, 260)
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.cmb_queue = QComboBox()
        self.cmb_queue.addItems(queues or ["default"])
        form.addRow("Queue:", self.cmb_queue)

        self.cmb_action = QComboBox()
        self.cmb_action.addItems(["start", "stop"])
        form.addRow("Action:", self.cmb_action)

        self.time_edit = QTimeEdit(QTime.currentTime())
        self.time_edit.setDisplayFormat("HH:mm")
        form.addRow("Time:", self.time_edit)

        days_row = QHBoxLayout()
        self._day_checks: dict[str, QCheckBox] = {}
        for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun"):
            chk = QCheckBox(day.capitalize())
            chk.setChecked(True)
            self._day_checks[day] = chk
            days_row.addWidget(chk)
        form.addRow("Days:", days_row)

        self.cmb_completion = QComboBox()
        self.cmb_completion.addItems(["nothing", "sleep", "hibernate", "shutdown", "close"])
        form.addRow("On Completion:", self.cmb_completion)

        layout.addLayout(form)
        btns = QHBoxLayout()
        btns.addStretch()
        ok = QPushButton("Add")
        ok.setProperty("primary", "true")
        ok.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        layout.addLayout(btns)

    def values(self) -> tuple[str, str, str, str, str]:
        selected_days = [d for d, chk in self._day_checks.items() if chk.isChecked()]
        days_str = "daily" if len(selected_days) == 7 or not selected_days else ",".join(selected_days)
        return (
            self.cmb_queue.currentText(),
            self.cmb_action.currentText(),
            self.time_edit.time().toString("HH:mm"),
            days_str,
            self.cmb_completion.currentText(),
        )


class SchedulerDialog(QDialog):
    def __init__(
        self,
        scheduler: DownloadScheduler,
        queue_manager: QueueManager,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.scheduler = scheduler
        self.queue_manager = queue_manager
        self.setWindowTitle("Download Scheduler")
        self.resize(620, 380)
        self._build_ui()
        self._reload()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Queue", "Action", "Time", "Days", "On Completion", "Enabled"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table)

        btn_row = QHBoxLayout()
        btn_add = QPushButton("Add Schedule")
        btn_add.setProperty("primary", "true")
        btn_add.clicked.connect(self._on_add)
        btn_remove = QPushButton("Remove Selected")
        btn_remove.clicked.connect(self._on_remove)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_remove)
        btn_row.addStretch()
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

    def _reload(self) -> None:
        self._schedules = self.scheduler.get_schedules()
        self.table.setRowCount(0)
        for row, s in enumerate(self._schedules):
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(s.queue_name))
            self.table.setItem(row, 1, QTableWidgetItem(s.action))
            self.table.setItem(row, 2, QTableWidgetItem(s.time))
            self.table.setItem(row, 3, QTableWidgetItem(s.days))
            self.table.setItem(row, 4, QTableWidgetItem(s.on_completion))
            self.table.setItem(row, 5, QTableWidgetItem("Yes" if s.enabled else "No"))

    def _on_add(self) -> None:
        queues = [q.name for q in self.queue_manager.get_all_queues()]
        dlg = _AddScheduleDialog(queues, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            q, act, tm, days, comp = dlg.values()
            self.scheduler.add_schedule(q, act, tm, days, comp)
            self._reload()

    def _on_remove(self) -> None:
        row = self.table.currentRow()
        if 0 <= row < len(self._schedules):
            self.scheduler.remove_schedule(self._schedules[row].id)
            self._reload()
