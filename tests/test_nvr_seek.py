"""Unit tests for NVR Seeking, Frame Indexing, and Playback Control."""

import unittest
from backend.vision.ingest import VideoIngest
from backend.vision.pipeline import seek_camera, set_camera_playback


class TestNVRSeek(unittest.TestCase):
    def test_video_ingest_seek_methods(self):
        # Test synthetic standby ingest instance
        ingest = VideoIngest(source="non_existent.mp4", target_fps=25.0)
        self.assertTrue(hasattr(ingest, "current_frame_idx"))
        self.assertTrue(hasattr(ingest, "total_frames"))
        self.assertTrue(hasattr(ingest, "is_paused"))

        # Test pause toggle
        ingest.set_paused(True)
        self.assertTrue(ingest.is_paused)
        ingest.set_paused(False)
        self.assertFalse(ingest.is_paused)

        # Test seek request
        ingest.seek(50)
        self.assertEqual(ingest._seek_requested, 50)

        ingest.stop()

    def test_pipeline_seek_and_playback_api(self):
        # Testing pipeline seek/playback when camera not yet active
        res_seek = seek_camera("cam_unknown", frame_idx=10)
        self.assertFalse(res_seek)

        res_playback = set_camera_playback("cam_unknown", paused=True)
        self.assertFalse(res_playback)


if __name__ == "__main__":
    unittest.main()
