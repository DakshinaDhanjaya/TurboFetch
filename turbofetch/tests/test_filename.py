import tempfile
import unittest
from pathlib import Path

from turbofetch.app.utils.filename import (
    categorize_file,
    filename_from_url,
    parse_content_disposition,
    resolve_conflict,
    sanitize_filename,
)


class TestFilename(unittest.TestCase):
    def test_content_disposition_basic(self) -> None:
        self.assertEqual(
            parse_content_disposition('attachment; filename="test.zip"'),
            "test.zip",
        )

    def test_content_disposition_utf8(self) -> None:
        self.assertEqual(
            parse_content_disposition("attachment; filename*=UTF-8''%E4%B8%AD%E6%96%87.zip"),
            "中文.zip",
        )

    def test_content_disposition_no_quotes(self) -> None:
        self.assertEqual(
            parse_content_disposition("attachment; filename=test.zip"),
            "test.zip",
        )

    def test_content_disposition_empty(self) -> None:
        self.assertIsNone(parse_content_disposition(""))
        self.assertIsNone(parse_content_disposition(None))

    def test_filename_from_url(self) -> None:
        self.assertEqual(
            filename_from_url("https://example.com/path/file.zip?v=1"),
            "file.zip",
        )

    def test_filename_from_url_no_extension(self) -> None:
        self.assertEqual(
            filename_from_url("https://example.com/download"),
            "download",
        )

    def test_filename_from_url_encoded(self) -> None:
        self.assertEqual(
            filename_from_url("https://example.com/my%20file%20name.pdf"),
            "my file name.pdf",
        )

    def test_sanitize_removes_invalid_chars(self) -> None:
        cleaned = sanitize_filename('a<b>c:d"e/f\\g|h?i*j.zip')
        for ch in '<>:"/\\|?*':
            self.assertNotIn(ch, cleaned)

    def test_sanitize_reserved_names(self) -> None:
        self.assertEqual(sanitize_filename("CON"), "CON_")
        self.assertEqual(sanitize_filename("nul.txt"), "NUL_.txt")

    def test_sanitize_trailing_dots(self) -> None:
        self.assertEqual(sanitize_filename("file..."), "file")

    def test_resolve_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "sample.zip"
            base.write_bytes(b"1")
            first = resolve_conflict(base)
            self.assertEqual(first.name, "sample(1).zip")
            first.write_bytes(b"2")
            second = resolve_conflict(base)
            self.assertEqual(second.name, "sample(2).zip")

    def test_categorize_file(self) -> None:
        self.assertEqual(categorize_file("archive.zip"), "compressed")
        self.assertEqual(categorize_file("movie.mp4"), "video")
        self.assertEqual(categorize_file("song.mp3"), "music")
        self.assertEqual(categorize_file("setup.exe"), "programs")
        self.assertEqual(categorize_file("report.pdf"), "documents")
        self.assertEqual(categorize_file("unknown.xyz"), "other")


if __name__ == "__main__":
    unittest.main()
