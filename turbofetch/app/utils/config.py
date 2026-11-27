import json
import secrets
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def default_file_types() -> dict[str, list[str]]:
    return {
        "compressed": ["zip", "rar", "7z", "tar", "gz", "bz2", "xz", "iso"],
        "documents": ["pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "rtf", "odt", "ods"],
        "music": ["mp3", "flac", "wav", "aac", "ogg", "wma", "m4a"],
        "video": ["mp4", "mkv", "avi", "mov", "wmv", "flv", "webm", "m4v", "mpg", "mpeg"],
        "programs": ["exe", "msi", "deb", "rpm", "dmg", "appimage", "apk"],
        "other": [],
    }


def default_save_locations(base_dir: Optional[str] = None) -> dict[str, str]:
    root = Path(base_dir) if base_dir else Path.home() / "Downloads"
    return {
        "compressed": str(root / "Compressed"),
        "documents": str(root / "Documents"),
        "music": str(root / "Music"),
        "video": str(root / "Video"),
        "programs": str(root / "Programs"),
        "other": str(root / "Other"),
    }


@dataclass
class AppConfig:
    download_dir: str = field(default_factory=lambda: str(Path.home() / "Downloads"))
    max_concurrent_downloads: int = 3
    default_connections: int = 8
    auto_start: bool = True
    start_with_windows: bool = False
    minimize_to_tray: bool = True
    clipboard_monitoring: bool = True
    confirm_browser_download: bool = False
    auto_scan_defender: bool = False
    show_start_popup: bool = True
    play_sounds: bool = True
    single_instance: bool = True
    language: str = "en"
    max_connections_per_download: int = 8
    timeout: int = 30
    max_retries: int = 10
    retry_delay: float = 2.0
    user_agent: str = DEFAULT_USER_AGENT
    global_speed_limit: int = 0
    per_download_speed_limit: int = 0
    proxy_enabled: bool = False
    proxy_type: str = "http"
    proxy_host: str = ""
    proxy_port: int = 8080
    proxy_username: str = ""
    proxy_password: str = ""
    auto_categorize: bool = True
    conflict_resolution: str = "auto_rename"
    save_locations: dict[str, str] = field(default_factory=default_save_locations)
    file_types: dict[str, list[str]] = field(default_factory=default_file_types)
    port: int = 29512
    pairing_token: str = field(default_factory=lambda: secrets.token_hex(16))
    bind_address: str = "127.0.0.1"
    theme: str = "dark"
    font_size: int = 10
    scheduler_enabled: bool = False


class ConfigManager:
    def __init__(self, config_dir: Optional[Path] = None) -> None:
        self._config_dir = config_dir or (Path.home() / "AppData" / "Local" / "TurboFetch")
        self._config_file = self._config_dir / "config.json"
        self._lock = threading.RLock()
        self._config: Optional[AppConfig] = None

    @property
    def config_dir(self) -> Path:
        return self._config_dir

    @property
    def config_file(self) -> Path:
        return self._config_file

    def load(self) -> AppConfig:
        with self._lock:
            self._config_dir.mkdir(parents=True, exist_ok=True)
            if self._config_file.exists():
                try:
                    raw = json.loads(self._config_file.read_text(encoding="utf-8"))
                    defaults = asdict(AppConfig())
                    merged = {**defaults, **{k: v for k, v in raw.items() if k in defaults}}
                    if not merged.get("pairing_token"):
                        merged["pairing_token"] = self.generate_pairing_token()
                    self._config = AppConfig(**merged)
                except (json.JSONDecodeError, TypeError, ValueError):
                    self._config = AppConfig()
                    self.save(self._config)
            else:
                self._config = AppConfig()
                self.save(self._config)
            return self._config

    def save(self, config: Optional[AppConfig] = None) -> None:
        with self._lock:
            if config is not None:
                self._config = config
            if self._config is None:
                self._config = AppConfig()
            self._config_dir.mkdir(parents=True, exist_ok=True)
            self._config_file.write_text(
                json.dumps(asdict(self._config), indent=2),
                encoding="utf-8",
            )

    def get(self) -> AppConfig:
        with self._lock:
            if self._config is None:
                return self.load()
            return self._config

    def update(self, **kwargs: Any) -> AppConfig:
        with self._lock:
            cfg = self.get()
            for key, value in kwargs.items():
                if hasattr(cfg, key):
                    setattr(cfg, key, value)
            self.save(cfg)
            return cfg

    def reset(self) -> AppConfig:
        with self._lock:
            token = self._config.pairing_token if self._config else self.generate_pairing_token()
            self._config = AppConfig(pairing_token=token)
            self.save(self._config)
            return self._config

    def generate_pairing_token(self) -> str:
        return secrets.token_hex(16)

    def export_config(self, path: Path) -> None:
        with self._lock:
            cfg = self.get()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(asdict(cfg), indent=2), encoding="utf-8")

    def import_config(self, path: Path) -> AppConfig:
        with self._lock:
            raw = json.loads(path.read_text(encoding="utf-8"))
            defaults = asdict(AppConfig())
            merged = {**defaults, **{k: v for k, v in raw.items() if k in defaults}}
            self._config = AppConfig(**merged)
            self.save(self._config)
            return self._config
