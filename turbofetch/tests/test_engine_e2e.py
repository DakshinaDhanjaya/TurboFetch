import asyncio
import hashlib
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from turbofetch.app.engine.downloader import DownloadEngine, DownloadStatus
from turbofetch.app.engine.speed_limiter import SpeedLimiter


class _RangeHandler(BaseHTTPRequestHandler):
    payload: bytes = b""
    etag: str = '"test-etag-1"'

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_HEAD(self) -> None:
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.payload)))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("ETag", self.etag)
        self.send_header("Content-Disposition", 'attachment; filename="payload.bin"')
        self.end_headers()

    def do_GET(self) -> None:
        range_hdr = self.headers.get("Range")
        if range_hdr and range_hdr.startswith("bytes="):
            spec = range_hdr[6:].split(",")[0]
            start_str, end_str = spec.split("-", 1)
            start = int(start_str) if start_str else 0
            end = int(end_str) if end_str else len(self.payload) - 1
            end = min(end, len(self.payload) - 1)
            chunk = self.payload[start : end + 1]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(self.payload)}")
            self.send_header("Content-Length", str(len(chunk)))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("ETag", self.etag)
            self.end_headers()
            self.wfile.write(chunk)
        else:
            self.send_response(200)
            self.send_header("Content-Length", str(len(self.payload)))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("ETag", self.etag)
            self.end_headers()
            self.wfile.write(self.payload)


class TestEngineEndToEnd(unittest.TestCase):
    def test_segmented_download_with_checksum(self) -> None:
        data = os.urandom(3 * 1024 * 1024 + 777)
        expected_sha256 = hashlib.sha256(data).hexdigest()
        _RangeHandler.payload = data
        server = ThreadingHTTPServer(("127.0.0.1", 0), _RangeHandler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        async def run_download() -> Path:
            for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
                os.environ.pop(k, None)
            with tempfile.TemporaryDirectory() as tmp:
                limiter = SpeedLimiter(global_limit=0)
                engine = DownloadEngine(speed_limiter=limiter, max_concurrent=2)
                done_event = asyncio.Event()

                def on_complete(task):
                    done_event.set()

                engine.set_on_complete(on_complete)
                task = await engine.add_download(
                    url=f"http://127.0.0.1:{port}/download",
                    save_path=tmp,
                    connections=8,
                    checksum=expected_sha256,
                    checksum_type="sha256",
                    start_now=True,
                )
                await asyncio.wait_for(done_event.wait(), timeout=20.0)
                self.assertEqual(task.status, DownloadStatus.COMPLETED)
                out_file = Path(tmp) / task.filename
                self.assertTrue(out_file.exists())
                self.assertEqual(out_file.read_bytes(), data)
                return out_file

        try:
            asyncio.run(run_download())
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
