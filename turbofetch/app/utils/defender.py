import asyncio
import os
import shutil
import sys
from pathlib import Path


def find_defender_exe() -> str | None:
    if sys.platform != "win32":
        return None
    for base in (
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramW6432", r"C:\Program Files"),
    ):
        cand = Path(base) / "Windows Defender" / "MpCmdRun.exe"
        if cand.exists():
            return str(cand)
    return shutil.which("MpCmdRun")


async def scan_file_with_defender(file_path: Path) -> tuple[bool, str]:
    exe = find_defender_exe()
    if not exe:
        return True, "Windows Defender CLI not available"
    if not file_path.exists():
        return True, "File not found for scan"
    flags = getattr(asyncio.subprocess, "CREATE_NO_WINDOW", 0)
    kwargs = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
    try:
        proc = await asyncio.create_subprocess_exec(
            exe,
            "-Scan",
            "-ScanType",
            "3",
            "-File",
            str(file_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **kwargs,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60.0)
        if proc.returncode == 0:
            return True, "Clean (no threats found)"
        if proc.returncode == 2:
            return False, f"Threat detected in {file_path.name}!"
        msg = (stderr or stdout or b"").decode("utf-8", errors="ignore").strip()
        return True, msg or f"Defender exited with code {proc.returncode}"
    except asyncio.TimeoutError:
        return True, "Defender scan timed out"
    except Exception as exc:
        return True, f"Defender scan skipped: {exc}"
