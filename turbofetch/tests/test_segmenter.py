import unittest

from turbofetch.app.engine.segment import Segment, SegmentManager, SegmentState


class TestSegmenter(unittest.TestCase):
    def test_create_segments_basic(self) -> None:
        size = 100 * 1024 * 1024
        mgr = SegmentManager("dl1", size, num_connections=8)
        segs = mgr.create_segments()
        self.assertEqual(len(segs), 8)
        self.assertEqual(segs[0].start, 0)
        self.assertEqual(segs[-1].end, size - 1)
        total = sum(s.length for s in segs)
        self.assertEqual(total, size)

    def test_create_segments_small_file(self) -> None:
        size = 400 * 1024
        mgr = SegmentManager("dl2", size, num_connections=8, minimum_segment_size=256 * 1024)
        segs = mgr.create_segments()
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0].start, 0)
        self.assertEqual(segs[0].end, size - 1)

    def test_create_segments_single(self) -> None:
        size = 10 * 1024 * 1024
        mgr = SegmentManager("dl3", size, num_connections=1)
        segs = mgr.create_segments()
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0].length, size)

    def test_split_largest_segment(self) -> None:
        size = 8 * 1024 * 1024
        mgr = SegmentManager("dl4", size, num_connections=8, minimum_segment_size=256 * 1024)
        mgr.create_segments()
        new_seg = mgr.split_largest_segment()
        self.assertIsNotNone(new_seg)
        self.assertEqual(len(mgr.segments), 9)
        self.assertEqual(sum(s.length for s in mgr.segments), size)

    def test_split_multiple_times(self) -> None:
        size = 32 * 1024 * 1024
        mgr = SegmentManager("dl5", size, num_connections=8, minimum_segment_size=256 * 1024)
        mgr.create_segments()
        for _ in range(3):
            self.assertIsNotNone(mgr.split_largest_segment())
        segs = mgr.segments
        self.assertEqual(len(segs), 11)
        self.assertEqual(sum(s.length for s in segs), size)

    def test_all_completed(self) -> None:
        size = 4 * 1024 * 1024
        mgr = SegmentManager("dl6", size, num_connections=4)
        segs = mgr.create_segments()
        self.assertFalse(mgr.all_completed())
        for s in segs:
            mgr.mark_segment_state(s.id, SegmentState.COMPLETED)
        self.assertTrue(mgr.all_completed())

    def test_progress_tracking(self) -> None:
        size = 4 * 1024 * 1024
        mgr = SegmentManager("dl7", size, num_connections=4)
        segs = mgr.create_segments()
        mgr.update_segment_progress(segs[0].id, segs[0].length)
        mgr.update_segment_progress(segs[1].id, segs[1].length)
        downloaded, total, pct = mgr.get_progress()
        self.assertEqual(total, size)
        self.assertEqual(downloaded, segs[0].length + segs[1].length)
        self.assertAlmostEqual(pct, 50.0, places=2)

    def test_unknown_size(self) -> None:
        mgr = SegmentManager("dl8", -1, num_connections=8)
        segs = mgr.create_segments()
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0].start, 0)
        self.assertEqual(segs[0].end, -1)

    def test_segment_serialization(self) -> None:
        size = 8 * 1024 * 1024
        mgr = SegmentManager("dl9", size, num_connections=4)
        segs = mgr.create_segments()
        mgr.update_segment_progress(segs[0].id, 1024)
        mgr.mark_segment_state(segs[0].id, SegmentState.DOWNLOADING)
        data = mgr.to_dict()
        restored = SegmentManager.from_dict("dl9", size, data, num_connections=4)
        self.assertEqual(len(restored.segments), 4)
        self.assertEqual(restored.segments[0].downloaded, 1024)
        self.assertEqual(restored.segments[0].state, SegmentState.DOWNLOADING)

    def test_get_pending_segments(self) -> None:
        mgr = SegmentManager("dl10", 4 * 1024 * 1024, num_connections=4)
        segs = mgr.create_segments()
        mgr.mark_segment_state(segs[0].id, SegmentState.DOWNLOADING)
        pending = mgr.get_pending_segments()
        self.assertEqual(len(pending), 3)
        self.assertTrue(all(s.state == SegmentState.PENDING for s in pending))

    def test_get_resumable_segments(self) -> None:
        mgr = SegmentManager("dl11", 4 * 1024 * 1024, num_connections=4)
        segs = mgr.create_segments()
        mgr.mark_segment_state(segs[0].id, SegmentState.COMPLETED)
        mgr.mark_segment_state(segs[1].id, SegmentState.DOWNLOADING)
        mgr.mark_segment_state(segs[2].id, SegmentState.FAILED, "timeout")
        resumable = mgr.get_resumable_segments()
        self.assertEqual(len(resumable), 3)
        self.assertTrue(all(s.state == SegmentState.PENDING for s in resumable))

    def test_no_gaps_no_overlaps(self) -> None:
        size = 10_000_003
        mgr = SegmentManager("dl12", size, num_connections=8, minimum_segment_size=256 * 1024)
        mgr.create_segments()
        mgr.update_segment_progress(0, 12345)
        mgr.split_largest_segment()
        mgr.split_largest_segment()
        segs = sorted(mgr.segments, key=lambda s: s.start)
        self.assertEqual(segs[0].start, 0)
        for i in range(len(segs) - 1):
            self.assertEqual(segs[i].end + 1, segs[i + 1].start)
        self.assertEqual(segs[-1].end, size - 1)


if __name__ == "__main__":
    unittest.main()
