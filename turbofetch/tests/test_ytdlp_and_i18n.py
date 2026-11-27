import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

from turbofetch.app.engine.downloader import (
    DownloadEngine,
    DownloadTask,
    SegmentDownloader,
    YtDlpDownloader,
)
from turbofetch.app.engine.speed_limiter import SpeedLimiter
from turbofetch.app.utils.i18n import set_language, tr


class TestYtDlpAndI18n(unittest.TestCase):
    def tearDown(self) -> None:
        set_language("en")

    def test_multi_quality_naming_and_ytdlp_args(self) -> None:
        async def run_test() -> None:
            orig_start = YtDlpDownloader.start

            async def noop_start(self) -> None:
                return None

            YtDlpDownloader.start = noop_start
            try:
                with tempfile.TemporaryDirectory() as tmp:
                    eng = DownloadEngine(SpeedLimiter())
                    url = "https://www.youtube.com/shorts/a3z_djpZ1jQ"
                    t1 = await eng.add_video_download(url, tmp, title="Demo", ytdlp_options={"resolution": "1080p"})
                    t2 = await eng.add_video_download(url, tmp, title="Demo", ytdlp_options={"resolution": "720p"})
                    t3 = await eng.add_video_download(url, tmp, title="Demo", ytdlp_options={"resolution": "720p"})
                    await asyncio.sleep(0)
                    self.assertIn("[1080p]", t1.filename)
                    self.assertIn("[720p]", t2.filename)
                    self.assertIn("[720p] (2)", t3.filename)

                    dl = eng.get_downloader(t1.id)
                    args = dl._build_args(["python", "-u", "-m", "yt_dlp"])
                    joined = " ".join(args)
                    self.assertIn("--progress", args)
                    self.assertIn("--newline", args)
                    self.assertIn("res:1080", joined)
                    self.assertIn("--merge-output-format mp4", joined)
                    self.assertIn("-movflags +faststart", joined)
            finally:
                YtDlpDownloader.start = orig_start

        asyncio.run(run_test())

    def test_ytdlp_progress_and_metadata_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task = DownloadTask(
                id="yt1",
                url="https://www.youtube.com/watch?v=x",
                filename="video [1080p].mp4",
                save_path=tmp,
                ytdlp_options={"resolution": "1080p"},
            )
            dl = YtDlpDownloader(task)
            dl._handle_ytdlp_line("TFMETA|Birthday Video \U0001f382|2048000", task.ytdlp_options, "", 0.0)
            self.assertIn("Birthday Video", task.filename)
            self.assertEqual(task.size, 2048000)

            dl._handle_ytdlp_line("TFPROG|1024000|2048000|2048000|512000|2", task.ytdlp_options, "", 0.0)
            self.assertEqual(task.downloaded, 1024000)
            self.assertEqual(task.speed, 512000.0)
            self.assertEqual(task.eta, 2.0)

    def test_frozen_ytdlp_worker_cmd_and_rename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task = DownloadTask(
                id="seg1",
                url="https://example.com/file.mp4",
                filename="file.mp4",
                save_path=tmp,
            )
            sdl = SegmentDownloader(task, SpeedLimiter())
            sdl.part_path.write_bytes(b"payload")
            sdl._rename_on_complete()
            self.assertEqual((Path(tmp) / "file.mp4").read_bytes(), b"payload")

            ydl = YtDlpDownloader(task)
            had_frozen = hasattr(sys, "frozen")
            orig_frozen = getattr(sys, "frozen", False)
            sys.frozen = True
            try:
                cmd = ydl._ytdlp_cmd()
                self.assertIsNotNone(cmd)
                self.assertTrue("--ytdlp-worker" in cmd or "yt-dlp" in cmd[0].lower())
            finally:
                if had_frozen:
                    sys.frozen = orig_frozen
                else:
                    delattr(sys, "frozen")

    def test_sinhala_i18n_translations(self) -> None:
        set_language("si")
        self.assertNotEqual(tr("menu.file"), "File")
        self.assertEqual(tr("app.title"), "TurboFetch \u0db6\u0dcf\u0d9c\u0dad \u0d9a\u0dc5\u0db8\u0db1\u0dcf\u0d9a\u0dbb\u0dd4")


if __name__ == "__main__":
    unittest.main()
