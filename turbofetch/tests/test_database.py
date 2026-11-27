import tempfile
import unittest
from pathlib import Path

from turbofetch.app.db.database import Database
from turbofetch.app.db.models import (
    DownloadRecord,
    HistoryRecord,
    QueueRecord,
    ScheduleRecord,
    SegmentRecord,
)


class TestDatabase(unittest.TestCase):
    def test_crud_and_export_import(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            db = Database(db_path)
            db.initialize()

            rec = DownloadRecord(
                id="dl-100",
                url="https://example.com/file.zip",
                final_url="https://example.com/file.zip",
                filename="file.zip",
                save_path=tmp,
                size=1024000,
                downloaded=512000,
                status="paused",
                category="compressed",
                queue_name="default",
                resumable=True,
            )
            db.insert_download(rec)
            fetched = db.get_download("dl-100")
            self.assertIsNotNone(fetched)
            self.assertEqual(fetched.filename, "file.zip")
            self.assertTrue(fetched.resumable)

            segs = [
                SegmentRecord(id=0, download_id="dl-100", start_byte=0, end_byte=511999, downloaded=512000, state="completed"),
                SegmentRecord(id=1, download_id="dl-100", start_byte=512000, end_byte=1023999, downloaded=0, state="pending"),
            ]
            db.save_segments("dl-100", segs)
            loaded_segs = db.get_segments("dl-100")
            self.assertEqual(len(loaded_segs), 2)
            self.assertEqual(loaded_segs[0].state, "completed")

            task = fetched.to_download_task()
            roundtrip = DownloadRecord.from_download_task(task)
            self.assertEqual(roundtrip.id, rec.id)

            db.create_queue(QueueRecord(name="night", max_concurrent=5, is_active=True))
            self.assertIsNotNone(db.get_queue("night"))

            sched = ScheduleRecord(id="s-1", queue_name="night", action="start", time="23:00", days="daily")
            db.save_schedule(sched)
            self.assertEqual(len(db.get_all_schedules()), 1)

            db.add_to_history(HistoryRecord(id="h-1", url=rec.url, filename=rec.filename, save_path=tmp, size=rec.size))
            self.assertEqual(len(db.get_history()), 1)

            export_file = Path(tmp) / "export.json"
            db.export_downloads(export_file)
            db.delete_download("dl-100")
            self.assertIsNone(db.get_download("dl-100"))
            imported = db.import_downloads(export_file)
            self.assertEqual(imported, 1)
            self.assertEqual(len(db.get_segments("dl-100")), 2)
            db.close()


if __name__ == "__main__":
    unittest.main()
