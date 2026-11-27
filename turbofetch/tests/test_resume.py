import unittest

from turbofetch.app.engine.protocols import FileInfo, is_resume_valid
from turbofetch.app.engine.segment import SegmentManager, SegmentState


class TestResume(unittest.TestCase):
    def _base_info(self) -> FileInfo:
        return FileInfo(
            url="https://example.com/archive.zip",
            final_url="https://example.com/archive.zip",
            filename="archive.zip",
            size=10_000_000,
            resumable=True,
            etag='"abc123"',
            last_modified="Wed, 21 Oct 2025 07:28:00 GMT",
        )

    def test_resume_validates_etag(self) -> None:
        orig = self._base_info()
        changed = self._base_info()
        changed.etag = '"xyz999"'
        self.assertFalse(is_resume_valid(orig, changed))

    def test_resume_validates_size(self) -> None:
        orig = self._base_info()
        changed = self._base_info()
        changed.size = 10_000_001
        self.assertFalse(is_resume_valid(orig, changed))

    def test_resume_validates_last_modified(self) -> None:
        orig = self._base_info()
        changed = self._base_info()
        changed.last_modified = "Thu, 22 Oct 2025 07:28:00 GMT"
        self.assertFalse(is_resume_valid(orig, changed))

    def test_resume_rejects_non_resumable(self) -> None:
        orig = self._base_info()
        changed = self._base_info()
        changed.resumable = False
        self.assertFalse(is_resume_valid(orig, changed))

    def test_resume_all_match(self) -> None:
        orig = self._base_info()
        same = self._base_info()
        self.assertTrue(is_resume_valid(orig, same))

    def test_segment_state_persistence(self) -> None:
        size = 4 * 1024 * 1024
        mgr = SegmentManager("resume-1", size, num_connections=4)
        segs = mgr.create_segments()
        mgr.update_segment_progress(segs[0].id, segs[0].length)
        mgr.mark_segment_state(segs[0].id, SegmentState.COMPLETED)
        mgr.update_segment_progress(segs[1].id, 50000)
        mgr.mark_segment_state(segs[1].id, SegmentState.PAUSED)

        serialized = mgr.to_dict()
        restored = SegmentManager.from_dict("resume-1", size, serialized, num_connections=4)
        self.assertEqual(restored.segments[0].state, SegmentState.COMPLETED)
        self.assertEqual(restored.segments[1].downloaded, 50000)
        self.assertEqual(restored.segments[1].state, SegmentState.PAUSED)

    def test_partial_completion_resume(self) -> None:
        size = 4 * 1024 * 1024
        mgr = SegmentManager("resume-2", size, num_connections=4)
        segs = mgr.create_segments()
        mgr.update_segment_progress(segs[0].id, segs[0].length)
        mgr.mark_segment_state(segs[0].id, SegmentState.COMPLETED)
        mgr.update_segment_progress(segs[1].id, 20000)
        mgr.mark_segment_state(segs[1].id, SegmentState.DOWNLOADING)

        resumable = mgr.get_resumable_segments()
        self.assertEqual(len(resumable), 3)
        self.assertEqual(resumable[0].id, 1)
        self.assertEqual(resumable[0].downloaded, 20000)
        self.assertEqual(resumable[0].current_offset, segs[1].start + 20000)
        self.assertEqual(resumable[0].state, SegmentState.PENDING)


if __name__ == "__main__":
    unittest.main()
