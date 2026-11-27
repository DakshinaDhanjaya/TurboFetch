import sys
import tempfile
from pathlib import Path
from typing import Optional

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


class SingleInstance:
    def __init__(self, app_name: str = "TurboFetch") -> None:
        self._app_name = app_name
        self._lock_file_path = Path(tempfile.gettempdir()) / f"{app_name}.lock"
        self._lock_file: Optional[object] = None

    def acquire(self) -> bool:
        try:
            self._lock_file = open(self._lock_file_path, "w")
            if sys.platform == "win32":
                msvcrt.locking(self._lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._lock_file.write(str(self._lock_file_path.name))
            self._lock_file.flush()
            return True
        except (OSError, IOError):
            if self._lock_file:
                self._lock_file.close()
                self._lock_file = None
            return False

    def release(self) -> None:
        if self._lock_file is None:
            return
        try:
            if sys.platform == "win32":
                msvcrt.locking(self._lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
            self._lock_file.close()
        except (OSError, IOError):
            pass
        finally:
            self._lock_file = None
        try:
            self._lock_file_path.unlink(missing_ok=True)
        except OSError:
            pass

    def __enter__(self) -> "SingleInstance":
        if not self.acquire():
            raise RuntimeError(f"{self._app_name} is already running.")
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        self.release()
