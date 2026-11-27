import os
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from turbofetch.app.utils.config import ConfigManager


class SettingsDialog(QDialog):
    def __init__(
        self,
        config_manager: ConfigManager,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.config_manager = config_manager
        self.setWindowTitle("TurboFetch Settings")
        self.resize(680, 520)
        self._save_edits: dict[str, QLineEdit] = {}
        self._type_edits: dict[str, QLineEdit] = {}
        self._build_ui()
        self._load_values()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs)

        self._build_general_tab()
        self._build_connection_tab()
        self._build_speed_tab()
        self._build_proxy_tab()
        self._build_save_locations_tab()
        self._build_file_types_tab()
        self._build_extension_tab()
        self._build_appearance_tab()

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_ok = QPushButton("OK")
        btn_ok.setProperty("primary", "true")
        btn_ok.clicked.connect(self._on_ok)
        btn_apply = QPushButton("Apply")
        btn_apply.clicked.connect(self._save_values)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_ok)
        btn_row.addWidget(btn_apply)
        btn_row.addWidget(btn_cancel)
        root.addLayout(btn_row)

    def _build_general_tab(self) -> None:
        tab = QWidget()
        form = QFormLayout(tab)

        dir_row = QHBoxLayout()
        self.edt_download_dir = QLineEdit()
        btn_dir = QPushButton("Browse...")
        btn_dir.clicked.connect(self._browse_default_dir)
        dir_row.addWidget(self.edt_download_dir)
        dir_row.addWidget(btn_dir)
        form.addRow("Default Download Folder:", dir_row)

        self.spn_max_concurrent = QSpinBox()
        self.spn_max_concurrent.setRange(1, 20)
        form.addRow("Max Simultaneous Downloads:", self.spn_max_concurrent)

        self.chk_auto_categorize = QCheckBox("Auto-categorize downloads into subfolders")
        form.addRow("", self.chk_auto_categorize)

        self.chk_clipboard = QCheckBox("Monitor clipboard for downloadable URLs")
        form.addRow("", self.chk_clipboard)

        self.chk_confirm_browser = QCheckBox("Show File Info confirmation dialog for browser downloads")
        form.addRow("", self.chk_confirm_browser)

        self.chk_auto_scan_defender = QCheckBox("Scan completed files with Windows Defender")
        form.addRow("", self.chk_auto_scan_defender)

        self.chk_tray = QCheckBox("Minimize to system tray on close")
        form.addRow("", self.chk_tray)

        self.chk_start_popup = QCheckBox("Show popup notification when a download starts")
        form.addRow("", self.chk_start_popup)

        self.chk_play_sounds = QCheckBox("Play sound on download start and completion")
        form.addRow("", self.chk_play_sounds)

        self.chk_startup = QCheckBox("Start TurboFetch with Windows")
        form.addRow("", self.chk_startup)

        self.cmb_conflict = QComboBox()
        self.cmb_conflict.addItems(["auto_rename", "overwrite", "ask"])
        form.addRow("Filename Conflict:", self.cmb_conflict)

        self.cmb_language = QComboBox()
        self.cmb_language.addItems(["en", "si"])
        form.addRow("Language:", self.cmb_language)

        self.tabs.addTab(tab, "General")

    def _build_connection_tab(self) -> None:
        tab = QWidget()
        form = QFormLayout(tab)

        self.spn_default_conns = QSpinBox()
        self.spn_default_conns.setRange(1, 32)
        form.addRow("Connections per Download:", self.spn_default_conns)

        self.spn_timeout = QSpinBox()
        self.spn_timeout.setRange(5, 300)
        self.spn_timeout.setSuffix(" s")
        form.addRow("Timeout:", self.spn_timeout)

        self.spn_retries = QSpinBox()
        self.spn_retries.setRange(0, 100)
        form.addRow("Max Retries:", self.spn_retries)

        self.edt_user_agent = QLineEdit()
        form.addRow("User-Agent:", self.edt_user_agent)

        self.tabs.addTab(tab, "Connection")

    def _build_speed_tab(self) -> None:
        tab = QWidget()
        form = QFormLayout(tab)

        self.spn_global_limit = QSpinBox()
        self.spn_global_limit.setRange(0, 1000000)
        self.spn_global_limit.setSuffix(" KB/s (0 = unlimited)")
        form.addRow("Global Speed Limit:", self.spn_global_limit)

        self.spn_per_dl_limit = QSpinBox()
        self.spn_per_dl_limit.setRange(0, 1000000)
        self.spn_per_dl_limit.setSuffix(" KB/s (0 = unlimited)")
        form.addRow("Per-Download Limit:", self.spn_per_dl_limit)

        self.tabs.addTab(tab, "Speed")

    def _build_proxy_tab(self) -> None:
        tab = QWidget()
        form = QFormLayout(tab)

        self.chk_proxy = QCheckBox("Enable Proxy")
        form.addRow("", self.chk_proxy)

        self.cmb_proxy_type = QComboBox()
        self.cmb_proxy_type.addItems(["http", "https", "socks5"])
        form.addRow("Proxy Type:", self.cmb_proxy_type)

        self.edt_proxy_host = QLineEdit()
        form.addRow("Host:", self.edt_proxy_host)

        self.spn_proxy_port = QSpinBox()
        self.spn_proxy_port.setRange(1, 65535)
        form.addRow("Port:", self.spn_proxy_port)

        self.edt_proxy_user = QLineEdit()
        form.addRow("Username:", self.edt_proxy_user)

        self.edt_proxy_pass = QLineEdit()
        self.edt_proxy_pass.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Password:", self.edt_proxy_pass)

        self.tabs.addTab(tab, "Proxy")

    def _build_save_locations_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.tbl_locations = QTableWidget(0, 3)
        self.tbl_locations.setHorizontalHeaderLabels(["Category", "Folder", ""])
        self.tbl_locations.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.tbl_locations)
        self.tabs.addTab(tab, "Save Locations")

    def _build_file_types_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.tbl_types = QTableWidget(0, 2)
        self.tbl_types.setHorizontalHeaderLabels(["Category", "Extensions (comma-separated)"])
        self.tbl_types.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.tbl_types)
        self.tabs.addTab(tab, "File Types")

    def _build_extension_tab(self) -> None:
        tab = QWidget()
        form = QFormLayout(tab)

        self.spn_port = QSpinBox()
        self.spn_port.setRange(1024, 65535)
        form.addRow("Local Server Port:", self.spn_port)

        token_row = QHBoxLayout()
        self.edt_token = QLineEdit()
        self.edt_token.setReadOnly(True)
        btn_copy = QPushButton("Copy")
        btn_copy.clicked.connect(self._copy_token)
        btn_regen = QPushButton("Regenerate")
        btn_regen.clicked.connect(self._regen_token)
        token_row.addWidget(self.edt_token)
        token_row.addWidget(btn_copy)
        token_row.addWidget(btn_regen)
        form.addRow("Pairing Token:", token_row)

        info = QLabel("Paste this token into the TurboFetch browser extension Options page to pair.")
        info.setWordWrap(True)
        form.addRow("", info)

        btn_open_ext = QPushButton("Open Extension Folder")
        btn_open_ext.clicked.connect(self._open_extension_folder)
        form.addRow("Extension Files:", btn_open_ext)

        self.tabs.addTab(tab, "Extension")

    def _build_appearance_tab(self) -> None:
        tab = QWidget()
        form = QFormLayout(tab)

        self.cmb_theme = QComboBox()
        self.cmb_theme.addItems(["dark", "light", "system"])
        form.addRow("Theme:", self.cmb_theme)

        self.spn_font_size = QSpinBox()
        self.spn_font_size.setRange(8, 16)
        form.addRow("Font Size:", self.spn_font_size)

        self.tabs.addTab(tab, "Appearance")

    def _browse_default_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Select Download Directory", self.edt_download_dir.text())
        if d:
            self.edt_download_dir.setText(d)

    def _copy_token(self) -> None:
        cb = QApplication.clipboard()
        if cb is not None:
            cb.setText(self.edt_token.text())
            QMessageBox.information(self, "Copied", "Pairing token copied to clipboard.")

    def _regen_token(self) -> None:
        self.edt_token.setText(self.config_manager.generate_pairing_token())

    def _open_extension_folder(self) -> None:
        candidates = [
            Path(__file__).resolve().parents[2] / "extension",
            Path(getattr(sys, "_MEIPASS", "")) / "extension",
        ]
        target = next((p for p in candidates if str(p) and p.exists()), None)
        if target is None:
            QMessageBox.information(self, "Extension Folder", "Extension folder not found.")
            return
        if sys.platform == "win32":
            os.startfile(str(target))

    def _load_values(self) -> None:
        cfg = self.config_manager.get()
        self.edt_download_dir.setText(cfg.download_dir)
        self.spn_max_concurrent.setValue(cfg.max_concurrent_downloads)
        self.chk_auto_categorize.setChecked(cfg.auto_categorize)
        self.chk_clipboard.setChecked(cfg.clipboard_monitoring)
        self.chk_confirm_browser.setChecked(cfg.confirm_browser_download)
        self.chk_auto_scan_defender.setChecked(cfg.auto_scan_defender)
        self.chk_tray.setChecked(cfg.minimize_to_tray)
        self.chk_start_popup.setChecked(cfg.show_start_popup)
        self.chk_play_sounds.setChecked(cfg.play_sounds)
        self.chk_startup.setChecked(cfg.start_with_windows)
        self.cmb_conflict.setCurrentText(cfg.conflict_resolution)
        self.cmb_language.setCurrentText(cfg.language)

        self.spn_default_conns.setValue(cfg.default_connections)
        self.spn_timeout.setValue(cfg.timeout)
        self.spn_retries.setValue(cfg.max_retries)
        self.edt_user_agent.setText(cfg.user_agent)

        self.spn_global_limit.setValue(cfg.global_speed_limit // 1024)
        self.spn_per_dl_limit.setValue(cfg.per_download_speed_limit // 1024)

        self.chk_proxy.setChecked(cfg.proxy_enabled)
        self.cmb_proxy_type.setCurrentText(cfg.proxy_type)
        self.edt_proxy_host.setText(cfg.proxy_host)
        self.spn_proxy_port.setValue(cfg.proxy_port)
        self.edt_proxy_user.setText(cfg.proxy_username)
        self.edt_proxy_pass.setText(cfg.proxy_password)

        self.tbl_locations.setRowCount(0)
        self._save_edits.clear()
        for row, (cat, path) in enumerate(cfg.save_locations.items()):
            self.tbl_locations.insertRow(row)
            cat_item = QTableWidgetItem(cat)
            cat_item.setFlags(cat_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.tbl_locations.setItem(row, 0, cat_item)
            edt = QLineEdit(path)
            self._save_edits[cat] = edt
            self.tbl_locations.setCellWidget(row, 1, edt)
            btn = QPushButton("Browse")
            btn.clicked.connect(lambda _=False, e=edt: self._browse_cat_dir(e))
            self.tbl_locations.setCellWidget(row, 2, btn)

        self.tbl_types.setRowCount(0)
        self._type_edits.clear()
        for row, (cat, exts) in enumerate(cfg.file_types.items()):
            self.tbl_types.insertRow(row)
            cat_item = QTableWidgetItem(cat)
            cat_item.setFlags(cat_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.tbl_types.setItem(row, 0, cat_item)
            edt = QLineEdit(", ".join(exts))
            self._type_edits[cat] = edt
            self.tbl_types.setCellWidget(row, 1, edt)

        self.spn_port.setValue(cfg.port)
        self.edt_token.setText(cfg.pairing_token)
        self.cmb_theme.setCurrentText(cfg.theme)
        self.spn_font_size.setValue(cfg.font_size)

    def _browse_cat_dir(self, target_edit: QLineEdit) -> None:
        d = QFileDialog.getExistingDirectory(self, "Select Category Folder", target_edit.text())
        if d:
            target_edit.setText(d)

    def _apply_windows_startup(self, enable: bool) -> None:
        if sys.platform != "win32":
            return
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE,
            )
            if enable:
                exe = sys.executable
                cmd = f'"{exe}"' if getattr(sys, "frozen", False) else f'"{exe}" -m turbofetch.app.main --minimized'
                winreg.SetValueEx(key, "TurboFetch", 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(key, "TurboFetch")
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
        except OSError:
            pass

    def _save_values(self) -> None:
        save_locations = {cat: edt.text().strip() for cat, edt in self._save_edits.items()}
        file_types = {
            cat: [e.strip().lower().lstrip(".") for e in edt.text().split(",") if e.strip()]
            for cat, edt in self._type_edits.items()
        }
        startup_enabled = self.chk_startup.isChecked()
        self.config_manager.update(
            download_dir=self.edt_download_dir.text().strip(),
            max_concurrent_downloads=self.spn_max_concurrent.value(),
            auto_categorize=self.chk_auto_categorize.isChecked(),
            clipboard_monitoring=self.chk_clipboard.isChecked(),
            confirm_browser_download=self.chk_confirm_browser.isChecked(),
            auto_scan_defender=self.chk_auto_scan_defender.isChecked(),
            minimize_to_tray=self.chk_tray.isChecked(),
            show_start_popup=self.chk_start_popup.isChecked(),
            play_sounds=self.chk_play_sounds.isChecked(),
            start_with_windows=startup_enabled,
            conflict_resolution=self.cmb_conflict.currentText(),
            language=self.cmb_language.currentText(),
            default_connections=self.spn_default_conns.value(),
            max_connections_per_download=self.spn_default_conns.value(),
            timeout=self.spn_timeout.value(),
            max_retries=self.spn_retries.value(),
            user_agent=self.edt_user_agent.text().strip(),
            global_speed_limit=self.spn_global_limit.value() * 1024,
            per_download_speed_limit=self.spn_per_dl_limit.value() * 1024,
            proxy_enabled=self.chk_proxy.isChecked(),
            proxy_type=self.cmb_proxy_type.currentText(),
            proxy_host=self.edt_proxy_host.text().strip(),
            proxy_port=self.spn_proxy_port.value(),
            proxy_username=self.edt_proxy_user.text(),
            proxy_password=self.edt_proxy_pass.text(),
            save_locations=save_locations,
            file_types=file_types,
            port=self.spn_port.value(),
            pairing_token=self.edt_token.text().strip(),
            theme=self.cmb_theme.currentText(),
            font_size=self.spn_font_size.value(),
        )
        self._apply_windows_startup(startup_enabled)

    def _on_ok(self) -> None:
        self._save_values()
        self.accept()
