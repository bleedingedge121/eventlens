"""Unit tests for Rule-Based Trigger Engine (Standard Library unittest)."""

import unittest
from backend.vision.triggers import TriggerEngine, compute_iou, point_in_polygon


class TestTriggers(unittest.TestCase):
    def test_point_in_polygon(self):
        poly = [[0, 0], [10, 0], [10, 10], [0, 10]]
        self.assertTrue(point_in_polygon(5, 5, poly))
        self.assertFalse(point_in_polygon(15, 15, poly))

    def test_compute_iou(self):
        box1 = [0, 0, 10, 10]
        box2 = [0, 0, 10, 10]
        self.assertEqual(compute_iou(box1, box2), 1.0)

        box3 = [20, 20, 30, 30]
        self.assertEqual(compute_iou(box1, box3), 0.0)

        box4 = [5, 0, 15, 10]
        self.assertAlmostEqual(compute_iou(box1, box4), 1.0 / 3.0, places=4)

    def test_crowd_trigger(self):
        config = {
            "crowd_threshold": 3,
            "crowd_surge_seconds": 0.5,
        }
        engine = TriggerEngine("cam1", config)

        detections = [
            {"track_id": 1, "box": [10, 10, 30, 60], "confidence": 0.9},
            {"track_id": 2, "box": [40, 10, 60, 60], "confidence": 0.9},
            {"track_id": 3, "box": [70, 10, 90, 60], "confidence": 0.9},
        ]

        # Initial surge start
        engine.update(detections, current_time=1.0)
        # Sustained surge past 0.5s
        candidates = engine.update(detections, current_time=1.6)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["category_hint"], "crowd_incident")

    def test_person_down_upright_then_collapse(self):
        config = {
            "person_down_aspect_ratio_threshold": 1.15,
            "person_down_still_seconds": 1.0,
            "person_down_min_track_age": 1.5,
            "person_down_min_positions": 2,
        }
        engine = TriggerEngine("cam1", config)

        # Frame 1: Person standing upright (h=140, w=40, h/w = 3.5 >= 1.4)
        det_standing = [{"track_id": 1, "box": [100, 100, 140, 240], "confidence": 0.9}]
        engine.update(det_standing, current_time=0.0)
        engine.update(det_standing, current_time=1.0)

        # Frame 2: Person collapses on floor horizontally (w=90, h=45, w/h = 2.0 >= 1.15, h <= 0.7*140)
        det_collapsed = [{"track_id": 1, "box": [100, 195, 190, 240], "confidence": 0.9}]
        cands1 = engine.update(det_collapsed, current_time=1.6)
        self.assertEqual(len(cands1), 0)  # Still waiting for still_seconds

        # Frame 3: Motionless after still_seconds (1.6 to 2.8s)
        cands2 = engine.update(det_collapsed, current_time=2.8)
        self.assertEqual(len(cands2), 1)
        self.assertEqual(cands2[0]["category_hint"], "person_down")

    def test_person_down_never_upright_rejected(self):
        """Never trigger on tracks that were never upright (e.g. luggage, bench, crawling, ground object)."""
        config = {
            "person_down_still_seconds": 1.0,
            "person_down_min_track_age": 1.0,
            "person_down_min_positions": 2,
        }
        engine = TriggerEngine("cam1", config)

        # Person or object starts already horizontal (w=90, h=45, h/w = 0.5 < 1.4)
        det_horizontal = [{"track_id": 2, "box": [50, 100, 140, 145], "confidence": 0.9}]
        engine.update(det_horizontal, current_time=0.0)
        engine.update(det_horizontal, current_time=1.5)
        cands = engine.update(det_horizontal, current_time=3.0)

        # Must NOT trigger because it was never upright!
        self.assertEqual(len(cands), 0)

    def test_outdoor_street_profile_disables_person_down(self):
        """Scene profile 'outdoor_street' must disable person_down."""
        config = {
            "scene_profile": "outdoor_street",
            "person_down_still_seconds": 0.5,
            "person_down_min_track_age": 1.0,
            "person_down_min_positions": 2,
        }
        engine = TriggerEngine("cam1", config)
        self.assertEqual(engine.get_scene_profile(), "outdoor_street")

        # Person stands upright then collapses
        det_standing = [{"track_id": 3, "box": [100, 100, 140, 240], "confidence": 0.9}]
        engine.update(det_standing, current_time=0.0)
        engine.update(det_standing, current_time=1.0)

        det_collapsed = [{"track_id": 3, "box": [100, 195, 190, 240], "confidence": 0.9}]
        engine.update(det_collapsed, current_time=1.5)
        cands = engine.update(det_collapsed, current_time=2.5)

        # Must be empty because outdoor_street disables person_down
        self.assertEqual(len(cands), 0)

    def test_vlm_feedback_auto_pause(self):
        """3 consecutive VLM 'no' verdicts trigger auto-pause cooldown."""
        engine = TriggerEngine("cam1", {})
        engine.record_vlm_feedback("fighting", "no")
        self.assertFalse(engine._is_rule_paused("fighting", 0.0))

        engine.record_vlm_feedback("fighting", "no")
        self.assertFalse(engine._is_rule_paused("fighting", 0.0))

        engine.record_vlm_feedback("fighting", "no")
        # 3rd rejection -> paused!
        self.assertTrue(engine._is_rule_paused("fighting", 0.0))
        self.assertIn("fighting", engine.paused_reasons)


if __name__ == "__main__":
    unittest.main()
