import os
import shutil
import subprocess
import sys
import tempfile
import threading
import zipfile
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


APP_NAME = "TurboFetch"
APP_VERSION = "1.0.0"
APP_PUBLISHER = "TurboFetch Open Source"


def resource_path(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


def create_shortcut(lnk_path: Path, target_exe: Path, working_dir: Path, icon_path: Path, args: str = "") -> None:
    lnk_path.parent.mkdir(parents=True, exist_ok=True)
    esc = lambda s: str(s).replace('"', '""')
    vbs = (
        'Set sh = CreateObject("WScript.Shell")\n'
        f'Set sc = sh.CreateShortcut("{esc(lnk_path)}")\n'
        f'sc.TargetPath = "{esc(target_exe)}"\n'
        f'sc.WorkingDirectory = "{esc(working_dir)}"\n'
        f'sc.IconLocation = "{esc(icon_path)},0"\n'
        + (f'sc.Arguments = "{esc(args)}"\n' if args else "")
        + "sc.Save\n"
    )
    fd, vbs_file = tempfile.mkstemp(suffix=".vbs")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(vbs)
        flags = 0x08000000 if sys.platform == "win32" else 0
        subprocess.run(["cscript", "//nologo", vbs_file], check=True, creationflags=flags)
    finally:
        Path(vbs_file).unlink(missing_ok=True)


def write_uninstaller(install_dir: Path, desktop_lnk: Path, start_menu_dir: Path) -> Path:
    uninst = install_dir / "uninstall.cmd"
    lines = [
        "@echo off",
        "taskkill /F /IM TurboFetch.exe >nul 2>&1",
        f'if exist "{desktop_lnk}" del /F /Q "{desktop_lnk}"',
        f'if exist "{start_menu_dir}" rmdir /S /Q "{start_menu_dir}"',
        'reg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" /v "TurboFetch" /f >nul 2>&1',
        'reg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\TurboFetch" /f >nul 2>&1',
        f'start "" /min cmd /c "timeout /t 2 /nobreak >nul & rmdir /S /Q ""{install_dir}"""',
    ]
    uninst.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    return uninst


def register_windows_apps(install_dir: Path, exe_path: Path, uninst_path: Path, start_with_windows: bool) -> None:
    if sys.platform != "win32":
        return
    import winreg

    uninst_key = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\TurboFetch"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, uninst_key) as key:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, f"{APP_NAME} Download Manager")
        winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, APP_VERSION)
        winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, APP_PUBLISHER)
        winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, str(exe_path))
        winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, str(install_dir))
        winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, f'cmd.exe /c "{uninst_path}"')
        winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)

    run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, run_key) as key:
        if start_with_windows:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{exe_path}" --minimized')
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass


class SetupWizard(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME} Setup v{APP_VERSION}")
        self.geometry("540x415")
        self.resizable(False, False)
        self.configure(bg="#0b1220")
        ico = resource_path("icon.ico")
        if ico.exists():
            try:
                self.iconbitmap(str(ico))
            except Exception:
                pass

        default_dir = Path(os.environ.get("LocalAppData", str(Path.home() / "AppData" / "Local"))) / "Programs" / APP_NAME
        self.var_dir = tk.StringVar(value=str(default_dir))
        self.var_desktop = tk.BooleanVar(value=True)
        self.var_startmenu = tk.BooleanVar(value=True)
        self.var_autostart = tk.BooleanVar(value=False)
        self.var_browser_ext = tk.BooleanVar(value=True)
        self.var_launch = tk.BooleanVar(value=True)
        self.var_status = tk.StringVar(value="Ready to install TurboFetch on your PC.")
        self._installing = False
        self._build_ui()

    def _build_ui(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TProgressbar", troughcolor="#17233a", background="#2563eb", thickness=14)

        header = tk.Frame(self, bg="#111a2e", height=74)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(
            header,
            text=f"{APP_NAME} Download Manager Setup",
            font=("Segoe UI", 14, "bold"),
            fg="#f8fafc",
            bg="#111a2e",
        ).pack(anchor="w", padx=20, pady=(14, 2))
        tk.Label(
            header,
            text=f"Version {APP_VERSION} - Fast Multi-Connection & Video Downloader",
            font=("Segoe UI", 9),
            fg="#93c5fd",
            bg="#111a2e",
        ).pack(anchor="w", padx=20)

        body = tk.Frame(self, bg="#0b1220")
        body.pack(fill="both", expand=True, padx=20, pady=16)

        tk.Label(
            body,
            text="Destination Folder:",
            font=("Segoe UI", 9, "bold"),
            fg="#cbd5e1",
            bg="#0b1220",
        ).pack(anchor="w")

        dir_row = tk.Frame(body, bg="#0b1220")
        dir_row.pack(fill="x", pady=(4, 12))
        self.ent_dir = tk.Entry(
            dir_row,
            textvariable=self.var_dir,
            font=("Segoe UI", 9),
            bg="#111a2e",
            fg="#f8fafc",
            insertbackground="#f8fafc",
            relief="flat",
            highlightthickness=1,
            highlightbackground="#253654",
        )
        self.ent_dir.pack(side="left", fill="x", expand=True, ipady=5, padx=(0, 8))
        self.btn_browse = tk.Button(
            dir_row,
            text="Browse...",
            command=self._browse,
            bg="#1a2744",
            fg="#e2e8f0",
            relief="flat",
            padx=12,
            pady=4,
            cursor="hand2",
        )
        self.btn_browse.pack(side="right")

        for text, var in (
            ("Create a Desktop shortcut", self.var_desktop),
            ("Add TurboFetch to Start Menu", self.var_startmenu),
            ("Start TurboFetch automatically with Windows", self.var_autostart),
            ("Set up Browser Extension (Chrome / Edge / Firefox)", self.var_browser_ext),
            ("Launch TurboFetch after installation", self.var_launch),
        ):
            tk.Checkbutton(
                body,
                text=text,
                variable=var,
                font=("Segoe UI", 9),
                fg="#e2e8f0",
                bg="#0b1220",
                selectcolor="#111a2e",
                activebackground="#0b1220",
                activeforeground="#f8fafc",
            ).pack(anchor="w", pady=2)

        self.progress = ttk.Progressbar(body, mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=(14, 6))

        tk.Label(
            body,
            textvariable=self.var_status,
            font=("Segoe UI", 9),
            fg="#93c5fd",
            bg="#0b1220",
        ).pack(anchor="w")

        footer = tk.Frame(self, bg="#0b1220")
        footer.pack(fill="x", padx=20, pady=(0, 16))
        self.btn_cancel = tk.Button(
            footer,
            text="Cancel",
            command=self._on_cancel,
            bg="#1a2744",
            fg="#e2e8f0",
            relief="flat",
            width=10,
            pady=6,
            cursor="hand2",
        )
        self.btn_cancel.pack(side="right")
        self.btn_install = tk.Button(
            footer,
            text="Install",
            command=self._start_install,
            bg="#2563eb",
            fg="#ffffff",
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            width=12,
            pady=6,
            cursor="hand2",
        )
        self.btn_install.pack(side="right", padx=(0, 8))

    def _browse(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.var_dir.get(), title="Select Install Folder")
        if chosen:
            p = Path(chosen)
            if p.name.lower() != APP_NAME.lower():
                p = p / APP_NAME
            self.var_dir.set(str(p))

    def _on_cancel(self) -> None:
        if not self._installing:
            self.destroy()

    def _start_install(self) -> None:
        if self._installing:
            return
        payload = resource_path("payload.zip")
        if not payload.exists():
            messagebox.showerror("Error", "Installer payload not found.")
            return
        target = self.var_dir.get().strip()
        if not target:
            messagebox.showwarning("Invalid Folder", "Please select a valid install folder.")
            return
        self._installing = True
        self.btn_install.config(state="disabled")
        self.btn_browse.config(state="disabled")
        self.ent_dir.config(state="disabled")
        self.btn_cancel.config(state="disabled")
        threading.Thread(target=self._run_install, args=(payload, Path(target)), daemon=True).start()

    def _run_install(self, payload: Path, install_dir: Path) -> None:
        try:
            self._set_ui("Stopping any running TurboFetch instance...", 5)
            flags = 0x08000000 if sys.platform == "win32" else 0
            subprocess.run(["taskkill", "/F", "/IM", "TurboFetch.exe"], capture_output=True, creationflags=flags)

            install_dir.mkdir(parents=True, exist_ok=True)
            resolved_root = install_dir.resolve()
            with zipfile.ZipFile(payload, "r") as zf:
                members = zf.infolist()
                total = max(1, len(members))
                for idx, member in enumerate(members, 1):
                    dest = (install_dir / member.filename).resolve()
                    if not str(dest).startswith(str(resolved_root)):
                        continue
                    if member.is_dir():
                        dest.mkdir(parents=True, exist_ok=True)
                    else:
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(member) as src, open(dest, "wb") as dst:
                            dst.write(src.read())
                    if idx % 15 == 0 or idx == total:
                        pct = int(5 + (idx / total) * 85)
                        self._set_ui(f"Installing files... ({idx}/{total})", pct)

            exe_path = install_dir / "TurboFetch.exe"
            bundled_ext = install_dir / "_internal" / "turbofetch" / "extension"
            public_ext = install_dir / "Browser Extension"
            if bundled_ext.exists():
                if public_ext.exists():
                    shutil.rmtree(public_ext, ignore_errors=True)
                shutil.copytree(bundled_ext, public_ext)
            ico_path = install_dir / "_internal" / "turbofetch" / "app" / "ui" / "icon.ico"
            if not ico_path.exists():
                ico_path = exe_path

            desktop_lnk = Path.home() / "Desktop" / f"{APP_NAME}.lnk"
            start_menu_dir = (
                Path(os.environ.get("AppData", str(Path.home() / "AppData" / "Roaming")))
                / "Microsoft"
                / "Windows"
                / "Start Menu"
                / "Programs"
                / APP_NAME
            )

            self._set_ui("Creating shortcuts and Windows integration...", 93)
            uninst_path = write_uninstaller(install_dir, desktop_lnk, start_menu_dir)
            if self.var_desktop.get():
                create_shortcut(desktop_lnk, exe_path, install_dir, ico_path)
            if self.var_startmenu.get():
                create_shortcut(start_menu_dir / f"{APP_NAME}.lnk", exe_path, install_dir, ico_path)
                create_shortcut(
                    start_menu_dir / f"Uninstall {APP_NAME}.lnk",
                    Path(os.environ.get("ComSpec", "cmd.exe")),
                    install_dir,
                    ico_path,
                    args=f'/c "{uninst_path}"',
                )
            register_windows_apps(install_dir, exe_path, uninst_path, self.var_autostart.get())
            self._set_ui("Installation complete!", 100)

            def finish() -> None:
                self._installing = False
                if self.var_launch.get() and exe_path.exists():
                    launch_cmd = [str(exe_path)]
                    if self.var_browser_ext.get():
                        launch_cmd.append("--setup-extension")
                    subprocess.Popen(launch_cmd, cwd=str(install_dir))
                messagebox.showinfo(
                    "Setup Complete",
                    f"{APP_NAME} has been installed to:\n{install_dir}",
                )
                self.destroy()

            self.after(0, finish)
        except Exception as exc:
            def fail() -> None:
                self._installing = False
                self.btn_install.config(state="normal")
                self.btn_browse.config(state="normal")
                self.ent_dir.config(state="normal")
                self.btn_cancel.config(state="normal")
                self.var_status.set(f"Error: {exc}")
                messagebox.showerror("Installation Failed", str(exc))

            self.after(0, fail)

    def _set_ui(self, status: str, pct: int) -> None:
        def apply() -> None:
            self.var_status.set(status)
            self.progress["value"] = pct

        self.after(0, apply)


if __name__ == "__main__":
    app = SetupWizard()
    app.mainloop()
