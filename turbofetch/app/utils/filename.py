import re
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse

INVALID_CHARS: re.Pattern = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

WINDOWS_RESERVED: set[str] = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

DEFAULT_FILENAME: str = "download"

DEFAULT_CATEGORIES: dict[str, list[str]] = {
    "compressed": ["zip", "rar", "7z", "tar", "gz", "bz2", "xz", "iso"],
    "documents": ["pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "rtf", "odt", "ods"],
    "music": ["mp3", "flac", "wav", "aac", "ogg", "wma", "m4a"],
    "video": ["mp4", "mkv", "avi", "mov", "wmv", "flv", "webm", "m4v", "mpg", "mpeg"],
    "programs": ["exe", "msi", "deb", "rpm", "dmg", "appimage", "apk"],
    "other": [],
}


def parse_content_disposition(header: Optional[str]) -> Optional[str]:
    if not header:
        return None
    match = re.search(r"filename\*=(?:UTF-8''|utf-8''|[A-Za-z0-9-]+'' )?([^;]+)", header, re.IGNORECASE)
    if match:
        raw = match.group(1).strip().strip('"').strip("'")
        if "''" in raw:
            raw = raw.split("''", 1)[1]
        decoded = unquote(raw)
        if decoded:
            return decoded
    match = re.search(r'filename\s*=\s*"([^"]+)"', header, re.IGNORECASE)
    if match:
        return unquote(match.group(1).strip())
    match = re.search(r"filename\s*=\s*([^\s;]+)", header, re.IGNORECASE)
    if match:
        return unquote(match.group(1).strip().strip('"'))
    return None


def filename_from_url(url: str) -> str:
    parsed = urlparse(url)
    path = unquote(parsed.path)
    name = Path(path).name
    if not name or name == "/":
        return DEFAULT_FILENAME
    return name


def sanitize_filename(name: str) -> str:
    name = name.strip()
    name = INVALID_CHARS.sub("_", name)
    name = name.strip(". ")
    if not name:
        return DEFAULT_FILENAME
    stem = Path(name).stem.upper()
    suffix = Path(name).suffix
    if stem in WINDOWS_RESERVED:
        name = f"{stem}_{suffix}" if suffix else f"{stem}_"
    if len(name) > 200:
        ext = Path(name).suffix
        name = name[: 200 - len(ext)] + ext
    return name


def resolve_conflict(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 1
    while True:
        candidate = parent / f"{stem}({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def categorize_file(
    filename: str, categories: Optional[dict[str, list[str]]] = None
) -> str:
    if categories is None:
        categories = DEFAULT_CATEGORIES
    ext = Path(filename).suffix.lower().lstrip(".")
    if not ext:
        return "other"
    for category, extensions in categories.items():
        normalized = {e.lower().lstrip(".") for e in extensions}
        if ext in normalized:
            return category
    return "other"


_VIDEO_PAGE_RE: re.Pattern = re.compile(
    r"^https?://(?:www\.|m\.)?(?:youtube\.com/(?:watch|shorts/|live/)|youtu\.be/|vimeo\.com/|dailymotion\.com/video/|twitch\.tv/videos/|tiktok\.com/)",
    re.IGNORECASE,
)


def is_video_page_url(url: str) -> bool:
    return bool(url and _VIDEO_PAGE_RE.match(url.strip()))
