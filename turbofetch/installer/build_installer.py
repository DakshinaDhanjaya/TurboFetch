import subprocess
import sys
import zipfile
from pathlib import Path


def build_setup() -> int:
    root = Path(__file__).resolve().parents[2]
    src_dir = root / "build" / "portable" / "TurboFetch"
    if not (src_dir / "TurboFetch.exe").exists():
        src_dir = root / "dist" / "TurboFetch"
    if not (src_dir / "TurboFetch.exe").exists():
        print("ERROR: TurboFetch.exe stage not found. Run PyInstaller first.")
        return 1

    stage_dir = root / "build" / "installer_stage"
    work_dir = root / "build" / "installer_work"
    stage_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    payload_zip = stage_dir / "payload.zip"
    print(f"Packing {src_dir} -> {payload_zip}...")
    with zipfile.ZipFile(payload_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(src_dir.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(src_dir))

    icon_path = root / "turbofetch" / "app" / "ui" / "icon.ico"
    wizard_script = root / "turbofetch" / "installer" / "setup_wizard.py"

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--windowed",
        "--name",
        "TurboFetch-Setup",
        "--icon",
        str(icon_path),
        "--distpath",
        str(root / "dist"),
        "--workpath",
        str(work_dir),
        "--specpath",
        str(work_dir),
        "--add-data",
        f"{payload_zip};.",
        "--add-data",
        f"{icon_path};.",
        "--exclude-module",
        "PySide6",
        "--exclude-module",
        "shiboken6",
        "--exclude-module",
        "yt_dlp",
        "--exclude-module",
        "imageio_ffmpeg",
        "--exclude-module",
        "mutagen",
        "--exclude-module",
        "httpx",
        "--exclude-module",
        "pytest",
        str(wizard_script),
    ]
    print("Building dist/TurboFetch-Setup.exe...")
    res = subprocess.run(cmd)
    if res.returncode == 0:
        out = root / "dist" / "TurboFetch-Setup.exe"
        size_mb = out.stat().st_size / (1024 * 1024)
        print(f"SUCCESS: {out} ({size_mb:.1f} MB)")
    return res.returncode


if __name__ == "__main__":
    raise SystemExit(build_setup())
