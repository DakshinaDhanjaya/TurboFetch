import asyncio
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import httpx

from turbofetch.app.db.database import Database
from turbofetch.app.engine.downloader import DownloadEngine
from turbofetch.app.engine.speed_limiter import SpeedLimiter
from turbofetch.app.scheduler.queue_manager import QueueManager
from turbofetch.app.scheduler.scheduler import DownloadScheduler
from turbofetch.app.server.server import LocalServer
from turbofetch.app.utils.config import ConfigManager


class TestServerAndScheduler(unittest.TestCase):
    def test_local_server_auth_cors_and_endpoints(self) -> None:
        async def run_test() -> None:
            import os
            for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
                os.environ.pop(k, None)
            with tempfile.TemporaryDirectory() as tmp:
                cfg_mgr = ConfigManager(Path(tmp))
                cfg = cfg_mgr.load()
                token = cfg.pairing_token
                engine = DownloadEngine(SpeedLimiter())
                video_urls: list[tuple[str, dict[str, str]]] = []
                server = LocalServer(
                    host="127.0.0.1",
                    port=0,
                    pairing_token=token,
                    download_engine=engine,
                    config_manager=cfg_mgr,
                    on_video_request=lambda u, c: video_urls.append((u, c)),
                )
                await server.start()
                base = f"http://127.0.0.1:{server.actual_port}"
                try:
                    async with httpx.AsyncClient(trust_env=False) as client:
                        unauth = await client.get(f"{base}/api/status")
                        self.assertEqual(unauth.status_code, 401)

                        bad_cors = await client.get(
                            f"{base}/api/status",
                            headers={
                                "Authorization": f"Bearer {token}",
                                "Origin": "https://evil.example",
                            },
                        )
                        self.assertEqual(bad_cors.status_code, 403)

                        ok = await client.get(
                            f"{base}/api/status",
                            headers={
                                "Authorization": f"Bearer {token}",
                                "Origin": "chrome-extension://abcdef",
                            },
                        )
                        self.assertEqual(ok.status_code, 200)
                        self.assertEqual(ok.json()["status"], "running")

                        pair = await client.post(
                            f"{base}/api/pair",
                            json={"extension_id": "ext-123", "token": token},
                        )
                        self.assertEqual(pair.status_code, 200)
                        self.assertTrue(pair.json()["paired"])

                        bad_dl = await client.post(
                            f"{base}/api/download",
                            headers={"Authorization": f"Bearer {token}"},
                            json={"url": "file:///etc/passwd"},
                        )
                        self.assertEqual(bad_dl.status_code, 400)

                        added = await client.post(
                            f"{base}/api/download",
                            headers={"Authorization": f"Bearer {token}"},
                            json={
                                "url": "https://example.com/archive.zip",
                                "filename": "archive.zip",
                                "start_now": False,
                            },
                        )
                        self.assertEqual(added.status_code, 201)
                        dl_id = added.json()["download_id"]

                        listing = await client.get(
                            f"{base}/api/downloads",
                            headers={"Authorization": f"Bearer {token}"},
                        )
                        self.assertEqual(listing.status_code, 200)
                        self.assertEqual(len(listing.json()["downloads"]), 1)
                        self.assertEqual(listing.json()["downloads"][0]["id"], dl_id)

                        vid = await client.post(
                            f"{base}/api/video",
                            headers={"Authorization": f"Bearer {token}"},
                            json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "cookies": {"SID": "abc"}},
                        )
                        self.assertEqual(vid.status_code, 202)
                        self.assertEqual(video_urls, [("https://www.youtube.com/watch?v=dQw4w9WgXcQ", {"SID": "abc"})])

                        shown: list[bool] = []
                        server.on_show_window = lambda: shown.append(True)
                        show_resp = await client.post(
                            f"{base}/api/show",
                            headers={"Authorization": f"Bearer {token}"},
                        )
                        self.assertEqual(show_resp.status_code, 200)
                        self.assertTrue(show_resp.json()["shown"])
                        self.assertEqual(shown, [True])
                finally:
                    await server.stop()

        asyncio.run(run_test())

    def test_queue_and_scheduler(self) -> None:
        async def run_test() -> None:
            import os
            for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
                os.environ.pop(k, None)
            with tempfile.TemporaryDirectory() as tmp:
                db = Database(Path(tmp) / "sched.db")
                db.initialize()
                engine = DownloadEngine(SpeedLimiter())
                qm = QueueManager(db, engine)
                qm.create_queue("night", max_concurrent=2)
                sched = DownloadScheduler(db, engine, qm)
                now = datetime(2026, 11, 26, 23, 30)
                sid = sched.add_schedule("night", "start", "23:30", days="daily")
                self.assertEqual(len(sched.get_schedules()), 1)
                await sched._check_schedules(now=now)
                q = qm.get_queue("night")
                self.assertIsNotNone(q)
                self.assertTrue(q.is_active)
                sched.remove_schedule(sid)
                self.assertEqual(len(sched.get_schedules()), 0)
                db.close()

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
