import asyncio
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlparse

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from turbofetch.app.utils.config import ConfigManager


class YtDlpPanel(QDialog):
    _analysisReady = Signal(object)
    _progressUpdated = Signal(int, str)
    _downloadFinished = Signal(bool, str)

    def __init__(
        self,
        config_manager: ConfigManager,
        run_coro: Optional[Callable[[Any], Any]] = None,
        on_direct_url: Optional[Callable[[str, str], None]] = None,
        on_queue_video: Optional[Callable[[dict[str, Any]], None]] = None,
        initial_url: str = "",
        cookies: Optional[dict[str, str]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.config_manager = config_manager
        self.run_coro = run_coro
        self.on_direct_url = on_direct_url
        self.on_queue_video = on_queue_video
        self._formats: list[dict[str, Any]] = []
        self._video_title: str = ""
        self._playlist_entries: list[dict[str, Any]] = []
        self._has_ffmpeg = self._detect_ffmpeg() is not None
        self._cookies = dict(cookies) if cookies else {}
        self._cookie_file: Optional[Path] = None
        self.setWindowTitle("Video & Playlist Downloader (yt-dlp)")
        self.resize(580, 400)
        self._build_ui()
        self._analysisReady.connect(self._on_analysis_ready)
        self._progressUpdated.connect(self._on_progress)
        self._downloadFinished.connect(self._on_finished)
        if initial_url:
            self.edt_url.setText(initial_url)
            self._on_analyze()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        url_row = QHBoxLayout()
        self.edt_url = QLineEdit()
        self.edt_url.setPlaceholderText("Paste YouTube / video / playlist URL")
        self.btn_analyze = QPushButton("Analyze")
        self.btn_analyze.clicked.connect(self._on_analyze)
        url_row.addWidget(self.edt_url)
        url_row.addWidget(self.btn_analyze)
        layout.addLayout(url_row)

        self.lbl_title = QLabel("Paste a video URL and click Analyze.")
        self.lbl_title.setWordWrap(True)
        layout.addWidget(self.lbl_title)

        form = QFormLayout()
        self.cmb_format = QComboBox()
        default_fmt = "bestvideo*+bestaudio/best" if self._has_ffmpeg else "best[ext=mp4]/best/bv*+ba/b"
        self.cmb_format.addItem("Use Quality Preset Below", default_fmt)
        form.addRow("Specific Stream:", self.cmb_format)

        self.cmb_resolution = QComboBox()
        self.cmb_resolution.addItems(["1080p", "720p", "480p", "360p", "Best", "1440p", "2160p"])
        form.addRow("Quality / Resolution:", self.cmb_resolution)

        save_row = QHBoxLayout()
        cfg = self.config_manager.get()
        default_dir = cfg.save_locations.get("video", cfg.download_dir)
        self.edt_save_dir = QLineEdit(default_dir)
        btn_browse_dir = QPushButton("Browse...")
        btn_browse_dir.clicked.connect(self._browse_save_dir)
        save_row.addWidget(self.edt_save_dir)
        save_row.addWidget(btn_browse_dir)
        form.addRow("Save Folder:", save_row)

        opts_row = QHBoxLayout()
        audio_label = "Audio only (MP3)" if self._has_ffmpeg else "Audio only (Best Audio)"
        self.chk_audio_only = QCheckBox(audio_label)
        self.chk_subtitles = QCheckBox("Subtitles (.srt)")
        self.chk_thumbnail = QCheckBox("Embed Thumbnail")
        self.chk_thumbnail.setEnabled(self._has_ffmpeg)
        opts_row.addWidget(self.chk_audio_only)
        opts_row.addWidget(self.chk_subtitles)
        opts_row.addWidget(self.chk_thumbnail)
        form.addRow("Options:", opts_row)

        playlist_row = QHBoxLayout()
        self.chk_playlist = QCheckBox("Download playlist")
        self.chk_split_playlist = QCheckBox("Split items")
        self.chk_split_playlist.setChecked(True)
        self.edt_playlist_range = QLineEdit()
        self.edt_playlist_range.setPlaceholderText("Items e.g. 1-5")
        playlist_row.addWidget(self.chk_playlist)
        playlist_row.addWidget(self.chk_split_playlist)
        playlist_row.addWidget(self.edt_playlist_range)
        form.addRow("Playlist:", playlist_row)
        layout.addLayout(form)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        layout.addWidget(self.progress_bar)

        self.lbl_status = QLabel("Idle")
        self.lbl_status.setWordWrap(True)
        layout.addWidget(self.lbl_status)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_download = QPushButton("Download")
        self.btn_download.setProperty("primary", "true")
        self.btn_download.clicked.connect(self._on_download)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(self.btn_download)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

    def _detect_ffmpeg(self) -> Optional[str]:
        exe = shutil.which("ffmpeg")
        if exe:
            return exe
        try:
            import imageio_ffmpeg

            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            return None

    def _browse_save_dir(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Select Video Folder", self.edt_save_dir.text())
        if chosen:
            self.edt_save_dir.setText(chosen)

    def _ytdlp_cmd(self) -> Optional[list[str]]:
        exe = shutil.which("yt-dlp")
        if exe:
            return [exe]
        import importlib.util

        if importlib.util.find_spec("yt_dlp") is not None:
            if getattr(sys, "frozen", False):
                return [sys.executable, "--ytdlp-worker"]
            return [sys.executable, "-m", "yt_dlp"]
        return None

    def _on_analyze(self) -> None:
        url = self.edt_url.text().strip()
        if not url:
            return
        cmd_base = self._ytdlp_cmd()
        if cmd_base is None:
            QMessageBox.warning(
                self,
                "yt-dlp Not Found",
                "Install yt-dlp with: pip install yt-dlp",
            )
            return
        if self.run_coro is None:
            return
        self.btn_analyze.setEnabled(False)
        self.lbl_status.setText("Analyzing...")
        self.run_coro(self._analyze_url(cmd_base, url))

    def _common_ytdlp_args(self, url: str) -> list[str]:
        args: list[str] = []
        node_exe = shutil.which("node")
        if node_exe:
            args.extend(["--js-runtimes", f"node:{node_exe}", "--remote-components", "ejs:github"])
        args.extend(self._cookie_args(url))
        cfg = self.config_manager.get()
        if cfg.proxy_enabled and cfg.proxy_host:
            creds = f"{cfg.proxy_username}:{cfg.proxy_password}@" if cfg.proxy_username else ""
            args.extend(["--proxy", f"{cfg.proxy_type}://{creds}{cfg.proxy_host}:{cfg.proxy_port}"])
        return args

    def _cookie_args(self, url: str) -> list[str]:
        if not self._cookies:
            return []
        host = (urlparse(url).hostname or "").lower()
        parts = host.split(".")
        domain = f".{'.'.join(parts[-2:])}" if len(parts) >= 2 else host
        expires = int(time.time()) + 86400 * 30
        if self._cookie_file is None:
            fd, tmp_name = tempfile.mkstemp(prefix="tf_cookies_", suffix=".txt")
            with open(fd, "w", encoding="utf-8") as f:
                f.write("# Netscape HTTP Cookie File\n")
                for k, v in self._cookies.items():
                    ck = str(k).replace("\t", "").replace("\r", "").replace("\n", "")
                    cv = str(v).replace("\t", "").replace("\r", "").replace("\n", "")
                    if ck:
                        f.write(f"{domain}\tTRUE\t/\tTRUE\t{expires}\t{ck}\t{cv}\n")
            self._cookie_file = Path(tmp_name)
        return ["--cookies", str(self._cookie_file)]

    async def _analyze_url(self, cmd_base: list[str], url: str) -> None:
        try:
            args = [
                *cmd_base,
                "--dump-single-json",
                "--no-warnings",
                "--ignore-no-formats-error",
                "--flat-playlist",
                *self._common_ytdlp_args(url),
                url,
            ]
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                self._analysisReady.emit({"error": stderr.decode("utf-8", errors="replace")})
                return
            info = json.loads(stdout.decode("utf-8", errors="replace"))
            self._analysisReady.emit(info)
        except Exception as exc:
            self._analysisReady.emit({"error": str(exc)})

    def _on_analysis_ready(self, info: dict[str, Any]) -> None:
        self.btn_analyze.setEnabled(True)
        if "error" in info:
            err = str(info["error"]).strip()
            if "Sign in to confirm" in err and not self._cookies:
                err += "\nTip: Open the video in Chrome and click the 'Download Video (TurboFetch)' button so your YouTube cookies are forwarded automatically."
            self.lbl_status.setText(f"Error: {err}")
            return
        self._video_title = info.get("title", "Video")
        entries = [e for e in (info.get("entries") or []) if isinstance(e, dict)]
        self._playlist_entries = entries
        uploader = info.get("uploader") or info.get("channel") or ""
        dur = info.get("duration")
        dur_str = f" | {int(dur // 60)}:{int(dur % 60):02d}" if isinstance(dur, (int, float)) and dur > 0 else ""
        if entries:
            meta = f" (Playlist: {len(entries)} videos)"
            self.chk_playlist.setChecked(True)
        else:
            meta = f" ({uploader}{dur_str})" if uploader or dur_str else ""
        self.lbl_title.setText(f"Title: {self._video_title}{meta}")
        self.cmb_format.clear()
        default_fmt = "bestvideo*+bestaudio/best" if self._has_ffmpeg else "best[ext=mp4]/best/bv*+ba/b"
        self.cmb_format.addItem("Use Quality Preset Below (Recommended H.264 MP4)", default_fmt)
        self._formats = info.get("formats", [])
        seen_labels: set[str] = set()
        for fmt in reversed(self._formats):
            fid = fmt.get("format_id", "")
            ext = fmt.get("ext", "")
            vcodec = fmt.get("vcodec", "none")
            acodec = fmt.get("acodec", "none")
            has_video = vcodec not in (None, "none")
            has_audio = acodec not in (None, "none")
            if not has_video and not has_audio:
                continue
            if not self._has_ffmpeg and has_video and not has_audio:
                continue
            height = fmt.get("height")
            width = fmt.get("width")
            if isinstance(height, int) and isinstance(width, int) and height > 0 and width > 0:
                res = f"{min(width, height)}p"
            else:
                res = f"{height}p" if height else (fmt.get("resolution") or "audio")
            fsize = fmt.get("filesize") or fmt.get("filesize_approx")
            size_str = f", {fsize / (1024 * 1024):.1f} MB" if isinstance(fsize, (int, float)) and fsize > 0 else ""
            codec_str = "H.264" if str(vcodec).startswith("avc1") else (str(vcodec).split(".")[0] if has_video else "Audio")
            tag = "video+audio" if (has_video and has_audio) else ("audio" if has_audio else "auto-muxed")
            label = f"{res} - {ext} ({codec_str}, {tag}{size_str}) [{fid}]"
            if label not in seen_labels:
                seen_labels.add(label)
                self.cmb_format.addItem(label, fid)
        self.lbl_status.setText("Ready - select quality and click Download")

    def _parse_playlist_indices(self, spec: str, total: int) -> list[int]:
        if not spec.strip():
            return list(range(total))
        chosen: list[int] = []
        for token in spec.split(","):
            token = token.strip()
            if "-" in token:
                parts = token.split("-", 1)
                try:
                    start = max(1, int(parts[0]))
                    end = min(total, int(parts[1]))
                    for idx in range(start, end + 1):
                        if idx - 1 not in chosen:
                            chosen.append(idx - 1)
                except ValueError:
                    pass
            else:
                try:
                    idx = int(token)
                    if 1 <= idx <= total and idx - 1 not in chosen:
                        chosen.append(idx - 1)
                except ValueError:
                    pass
        return chosen or list(range(total))

    def _on_download(self) -> None:
        url = self.edt_url.text().strip()
        if not url:
            return
        cmd_base = self._ytdlp_cmd()
        if cmd_base is None:
            QMessageBox.warning(
                self,
                "yt-dlp Not Found",
                "Install yt-dlp with: pip install yt-dlp",
            )
            return
        if self.on_queue_video is not None:
            fmt_id = str(self.cmb_format.currentData() or "")
            res_tag = ""
            if fmt_id and not fmt_id.startswith("best"):
                res_prefix = self.cmb_format.currentText().split(" - ", 1)[0].strip()
                res_tag = f"{res_prefix}-{fmt_id}" if res_prefix else fmt_id
            save_dir = self.edt_save_dir.text().strip()
            base_opts = {
                "cookies": self._cookies,
                "format_id": fmt_id,
                "resolution_tag": res_tag,
                "resolution": self.cmb_resolution.currentText(),
                "audio_only": self.chk_audio_only.isChecked(),
                "subtitles": self.chk_subtitles.isChecked(),
                "embed_thumbnail": self.chk_thumbnail.isChecked(),
                "save_path": save_dir,
            }
            if (
                self.chk_playlist.isChecked()
                and self.chk_split_playlist.isChecked()
                and self._playlist_entries
            ):
                indices = self._parse_playlist_indices(
                    self.edt_playlist_range.text(), len(self._playlist_entries)
                )
                queued_any = False
                for idx in indices:
                    entry = self._playlist_entries[idx]
                    e_url = entry.get("webpage_url") or entry.get("url") or ""
                    if not e_url and entry.get("id"):
                        e_url = f"https://www.youtube.com/watch?v={entry['id']}"
                    elif e_url and not str(e_url).startswith("http"):
                        vid_id = entry.get("id") or e_url
                        e_url = f"https://www.youtube.com/watch?v={vid_id}"
                    if not e_url:
                        continue
                    queued_any = True
                    self.on_queue_video(
                        {
                            **base_opts,
                            "url": str(e_url),
                            "title": str(entry.get("title") or self._video_title or "Video"),
                            "playlist": False,
                            "playlist_range": "",
                        }
                    )
                if queued_any:
                    self.accept()
                    return
            self.on_queue_video(
                {
                    **base_opts,
                    "url": url,
                    "title": self._video_title,
                    "playlist": self.chk_playlist.isChecked(),
                    "playlist_range": self.edt_playlist_range.text().strip(),
                }
            )
            self.accept()
            return
        if self.run_coro is None:
            return
        self.btn_download.setEnabled(False)
        self.progress_bar.setValue(0)
        self.lbl_status.setText("Starting download...")
        self.run_coro(self._start_download(cmd_base, url))

    async def _start_download(self, cmd_base: list[str], url: str) -> None:
        cfg = self.config_manager.get()
        out_dir = cfg.save_locations.get("video", cfg.download_dir)
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        args = [*cmd_base, "--newline", "-P", out_dir, *self._common_ytdlp_args(url)]

        if self.chk_audio_only.isChecked():
            if self._has_ffmpeg:
                args.extend(["-x", "--audio-format", "mp3"])
            else:
                args.extend(["-f", "bestaudio/best"])
        else:
            fmt_id = self.cmb_format.currentData()
            res = self.cmb_resolution.currentText()
            if fmt_id and fmt_id not in ("bestvideo*+bestaudio/best", "best[ext=mp4]/best/bv*+ba/b"):
                args.extend(["-f", str(fmt_id)])
            elif res != "Best":
                height = res.rstrip("p")
                if self._has_ffmpeg:
                    args.extend(["-f", f"bestvideo[height<={height}]+bestaudio/best[height<={height}]"])
                else:
                    args.extend(["-f", f"best[height<={height}][ext=mp4]/best[height<={height}]/best"])
            elif not self._has_ffmpeg:
                args.extend(["-f", "best[ext=mp4]/best/bv*+ba/b"])

        if not self.chk_playlist.isChecked():
            args.append("--no-playlist")
        elif self.edt_playlist_range.text().strip():
            args.extend(["--playlist-items", self.edt_playlist_range.text().strip()])

        args.append(url)
        last_error = ""
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            assert proc.stdout is not None
            while True:
                line_bytes = await proc.stdout.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="replace").strip()
                if line.startswith("ERROR:"):
                    last_error = line
                if "[download]" in line and "%" in line:
                    for part in line.split():
                        if part.endswith("%"):
                            try:
                                pct = int(float(part[:-1]))
                                self._progressUpdated.emit(pct, line)
                            except ValueError:
                                pass
                            break
            code = await proc.wait()
            if code == 0:
                self._downloadFinished.emit(True, f"Saved to {out_dir}")
            else:
                self._downloadFinished.emit(False, last_error or f"yt-dlp exited with code {code}")
        except Exception as exc:
            self._downloadFinished.emit(False, str(exc))

    def _on_progress(self, pct: int, text: str) -> None:
        self.progress_bar.setValue(max(0, min(100, pct)))
        self.lbl_status.setText(text[:100])

    def _on_finished(self, success: bool, msg: str) -> None:
        self.btn_download.setEnabled(True)
        if success:
            self.progress_bar.setValue(100)
        self.lbl_status.setText(msg)

    def closeEvent(self, event: Any) -> None:
        if self._cookie_file is not None:
            self._cookie_file.unlink(missing_ok=True)
            self._cookie_file = None
        super().closeEvent(event)
