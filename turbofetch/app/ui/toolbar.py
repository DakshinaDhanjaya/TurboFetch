from typing import Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QSizePolicy, QStyle, QToolBar, QWidget

from turbofetch.app.utils.i18n import _


class DownloadToolbar(QToolBar):
    addUrlRequested = Signal()
    resumeRequested = Signal()
    pauseRequested = Signal()
    stopRequested = Signal()
    deleteRequested = Signal()
    openFileRequested = Signal()
    openFolderRequested = Signal()
    scheduleRequested = Signal()
    ytdlpRequested = Signal()
    settingsRequested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("Main Toolbar", parent)
        self.setMovable(False)
        self.setIconSize(QSize(16, 16))
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        style = self.style()

        self.act_add = QAction(style.standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder), "Add", self)
        self.act_add.setToolTip("Add URL (Ctrl+N)")
        self.act_add.triggered.connect(self.addUrlRequested.emit)
        self.addAction(self.act_add)

        self.addSeparator()

        self.act_resume = QAction(style.standardIcon(QStyle.StandardPixmap.SP_MediaPlay), "Resume", self)
        self.act_resume.triggered.connect(self.resumeRequested.emit)
        self.addAction(self.act_resume)

        self.act_pause = QAction(style.standardIcon(QStyle.StandardPixmap.SP_MediaPause), "Pause", self)
        self.act_pause.triggered.connect(self.pauseRequested.emit)
        self.addAction(self.act_pause)

        self.act_stop = QAction(style.standardIcon(QStyle.StandardPixmap.SP_MediaStop), "Stop", self)
        self.act_stop.triggered.connect(self.stopRequested.emit)
        self.addAction(self.act_stop)

        self.act_delete = QAction(style.standardIcon(QStyle.StandardPixmap.SP_TrashIcon), "Delete", self)
        self.act_delete.triggered.connect(self.deleteRequested.emit)
        self.addAction(self.act_delete)

        self.addSeparator()

        self.act_open_file = QAction(style.standardIcon(QStyle.StandardPixmap.SP_FileIcon), "Open", self)
        self.act_open_file.setToolTip("Open Downloaded File")
        self.act_open_file.triggered.connect(self.openFileRequested.emit)
        self.addAction(self.act_open_file)

        self.act_open_folder = QAction(style.standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon), "Folder", self)
        self.act_open_folder.setToolTip("Open Containing Folder")
        self.act_open_folder.triggered.connect(self.openFolderRequested.emit)
        self.addAction(self.act_open_folder)

        self.act_schedule = QAction(style.standardIcon(QStyle.StandardPixmap.SP_BrowserReload), "Schedule", self)
        self.act_schedule.triggered.connect(self.scheduleRequested.emit)
        self.addAction(self.act_schedule)

        self.act_ytdlp = QAction(style.standardIcon(QStyle.StandardPixmap.SP_ArrowDown), "Video", self)
        self.act_ytdlp.setToolTip("Video & Playlist Downloader (yt-dlp)")
        self.act_ytdlp.triggered.connect(self.ytdlpRequested.emit)
        self.addAction(self.act_ytdlp)

        spacer = QWidget(self)
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.addWidget(spacer)

        self.act_settings = QAction(style.standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView), _("action.settings").rstrip("."), self)
        self.act_settings.setToolTip("Settings (Ctrl+,)")
        self.act_settings.triggered.connect(self.settingsRequested.emit)
        self.addAction(self.act_settings)

        self.retranslate_ui()
        self.set_button_states(False, None)

    def retranslate_ui(self) -> None:
        self.act_add.setText(_("action.add"))
        self.act_resume.setText(_("action.resume"))
        self.act_pause.setText(_("action.pause"))
        self.act_stop.setText(_("action.stop"))
        self.act_delete.setText(_("action.delete"))
        self.act_open_file.setText(_("action.open_file"))
        self.act_open_folder.setText(_("action.open_folder"))
        self.act_schedule.setText(_("action.schedule"))
        self.act_ytdlp.setText(_("action.video"))
        self.act_settings.setText(_("app.settings"))

    def set_button_states(self, has_selection: bool, selected_status: Optional[str] = None) -> None:
        self.act_delete.setEnabled(has_selection)
        self.act_open_folder.setEnabled(has_selection)
        if not has_selection:
            self.act_resume.setEnabled(False)
            self.act_pause.setEnabled(False)
            self.act_stop.setEnabled(False)
            self.act_open_file.setEnabled(False)
            return

        status = (selected_status or "").lower()
        is_active = status in ("downloading", "probing", "merging")
        is_resumable = status in ("paused", "stopped", "failed", "queued")
        self.act_pause.setEnabled(is_active)
        self.act_stop.setEnabled(is_active or status == "paused")
        self.act_resume.setEnabled(is_resumable)
        self.act_open_file.setEnabled(status == "completed")
