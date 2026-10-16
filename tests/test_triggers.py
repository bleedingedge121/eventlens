"""Unit tests for Rule-Based Trigger Engine (Standard Library unittest)."""

import unittest
from backend.vision.triggers import TriggerEngine, compute_iou, point_in_polygon


class TestTriggers(unittest.TestCase):
    def test_point_in_polygon(self):
        # Square polygon from (0, 0) to (10, 10)
        poly = [[0, 0], [10, 0], [10, 10], [0, 10]]
        self.assertTrue(point_in_polygon(5, 5, poly))
        self.assertFalse(point_in_polygon(15, 15, poly))

    def test_compute_iou(self):
        box1 = [0, 0, 10, 10]
        box2 = [0, 0, 10, 10]
        self.assertEqual(compute_iou(box1, box2), 1.0)

        box3 = [20, 20, 30, 30]
        self.assertEqual(compute_iou(box1, box3), 0.0)

        box4 = [5, 0, 15, 10]  # Overlap 5x10 = 50, Union = 100 + 100 - 50 = 150 -> 1/3
        self.assertAlmostEqual(compute_iou(box1, box4), 1.0 / 3.0, places=4)

    def test_crowd_trigger_requires_minimum_eight_and_surge(self):
        config = {"crowd_threshold": 8}
        engine = TriggerEngine("cam1", config)

        # Baseline: 5 people in the scene (must NOT trigger)
        det_five = [{"track_id": i, "box": [i * 30, 10, i * 30 + 20, 70], "confidence": 0.9} for i in range(1, 6)]
        for t in range(20):
            cands = engine.update(det_five, current_time=float(t))
            self.assertEqual(len(cands), 0)

        # Surge to 10 people (>= 8 and >= 1.35x baseline of 5)
        det_ten = [{"track_id": i, "box": [i * 30, 10, i * 30 + 20, 70], "confidence": 0.9} for i in range(1, 11)]
        cands_surge = engine.update(det_ten, current_time=21.0)
        self.assertEqual(len(cands_surge), 1)
        self.assertEqual(cands_surge[0]["category_hint"], "crowd_incident")
        self.assertEqual(cands_surge[0]["tags"], [])  # No hardcoded tags

    def test_person_down_transition_and_seated_ignore(self):
        config = {
            "person_down_aspect_ratio_threshold": 1.15,
            "person_down_still_seconds": 3.0,
        }
        engine = TriggerEngine("cam1", config)

        # Seated person (w=70, h=60 -> aspect = 1.16), BUT never observed standing upright
        det_seated = [{"track_id": 99, "box": [100, 100, 170, 160], "confidence": 0.9}]
        for t in range(10):
            cands = engine.update(det_seated, current_time=float(t))
            self.assertEqual(len(cands), 0)  # Must be IGNORED because was never upright

        # Legitimate fall: Track 1 starts standing upright (w=40, h=120, aspect=0.33)
        det_standing = [{"track_id": 1, "box": [200, 100, 240, 220], "confidence": 0.95}]
        for t in range(10, 16):
            engine.update(det_standing, current_time=float(t))

        # Person collapses (w=120, h=50 -> aspect=2.4) at y=170 (downward drop)
        det_fallen = [{"track_id": 1, "box": [200, 170, 320, 220], "confidence": 0.95}]
        engine.update(det_fallen, current_time=17.0)

        # Dwells prone for 3.1 seconds (time 17.0 -> 20.2)
        cands_fall = engine.update(det_fallen, current_time=20.2)
        self.assertEqual(len(cands_fall), 1)
        self.assertEqual(cands_fall[0]["category_hint"], "person_down")
        self.assertEqual(cands_fall[0]["tags"], [])  # Zero fake tags

    def test_tailgating_door_line_requirement(self):
        # 1. Without door zone configured: tailgating is disabled
        engine_no_door = TriggerEngine("cam1", {"door_zone": None})
        det_pass = [
            {"track_id": 1, "box": [100, 100, 140, 180], "confidence": 0.9},
            {"track_id": 2, "box": [110, 110, 150, 190], "confidence": 0.9},
        ]
        self.assertEqual(len(engine_no_door.update(det_pass, current_time=1.0)), 0)

        # 2. With calibrated door zone configured
        door_zone = [[50, 50], [200, 50], [200, 200], [50, 200]]
        engine_door = TriggerEngine("cam1", {"door_zone": door_zone, "tailgating_time_window_seconds": 2.0})

        # Person 1 enters door zone at t=1.0
        det_p1 = [{"track_id": 1, "box": [80, 80, 120, 160], "confidence": 0.9}]
        engine_door.update(det_p1, current_time=1.0)

        # Person 2 enters door zone right behind Person 1 at t=1.8 (within 2.0s)
        det_p2 = [
            {"track_id": 1, "box": [80, 90, 120, 170], "confidence": 0.9},
            {"track_id": 2, "box": [85, 70, 125, 150], "confidence": 0.9},
        ]
        cands_tail = engine_door.update(det_p2, current_time=1.8)
        self.assertEqual(len(cands_tail), 1)
        self.assertEqual(cands_tail[0]["category_hint"], "tailgating")

    def test_fighting_sustained_overlap_and_speed(self):
        config = {
            "fighting_overlap_iou": 0.35,
            "fighting_speed_threshold_pixels_per_sec": 100.0,
        }
        engine = TriggerEngine("cam1", config)

        # Frame 1: Two people start overlapping with rapid motion
        t0 = 0.0
        det1 = [
            {"track_id": 10, "box": [100, 100, 150, 200], "confidence": 0.9},
            {"track_id": 11, "box": [110, 100, 160, 200], "confidence": 0.9},
        ]
        engine.update(det1, current_time=t0)

        # Frame 2-5: Sustained overlap for >= 1.5s with rapid displacement
        all_cands = []
        for step in range(1, 6):
            t = step * 0.4  # t reaches 2.0s
            det = [
                {"track_id": 10, "box": [100 + step * 45, 100, 150 + step * 45, 200], "confidence": 0.9},
                {"track_id": 11, "box": [110 + step * 45, 100, 160 + step * 45, 200], "confidence": 0.9},
            ]
            cands = engine.update(det, current_time=t)
            all_cands.extend(cands)

        self.assertEqual(len(all_cands), 1)
        self.assertEqual(all_cands[0]["category_hint"], "fighting")

    def test_video_loop_reset(self):
        engine = TriggerEngine("cam1", {})
        det = [{"track_id": 1, "box": [100, 100, 140, 200], "confidence": 0.9}]
        engine.update(det, current_time=10.0)
        self.assertEqual(engine.last_update_time, 10.0)

        # Seek backward / loop to 1.0
        engine.update(det, current_time=1.0)
        self.assertEqual(engine.last_update_time, 1.0)
        self.assertEqual(len(engine.crowd_history), 1)


if __name__ == "__main__":
    unittest.main()
