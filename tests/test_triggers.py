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

    def test_crowd_trigger(self):
        config = {"crowd_threshold": 3}
        engine = TriggerEngine("cam1", config)

        detections = [
            {"track_id": 1, "box": [10, 10, 30, 60], "confidence": 0.9},
            {"track_id": 2, "box": [40, 10, 60, 60], "confidence": 0.9},
            {"track_id": 3, "box": [70, 10, 90, 60], "confidence": 0.9},
        ]

        candidates = engine.update(detections, current_time=1.0)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["category_hint"], "crowd_incident")
    def test_person_down_height_collapse(self):
        config = {
            "person_down_aspect_ratio_threshold": 0.85,
            "person_down_still_seconds": 1.0,
            "person_down_min_upright_frames": 3,
            "person_down_transition_frames": 2,
        }
        engine = TriggerEngine("cam1", config)

        # Baseline: Person standing upright (h=140, w=40) for 3 frames to establish baseline
        det_standing = [{"track_id": 1, "box": [100, 100, 140, 240], "confidence": 0.9}]
        for t in [0.0, 0.1, 0.2]:
            engine.update(det_standing, current_time=t)

        # Transition: Person collapses on floor (h=45, w=90 -> height collapsed < 0.6 of 140)
        det_collapsed = [{"track_id": 1, "box": [100, 195, 190, 240], "confidence": 0.9}]
        # 2 frames to satisfy transition_frames
        engine.update(det_collapsed, current_time=0.3)
        cands1 = engine.update(det_collapsed, current_time=0.4)
        self.assertEqual(len(cands1), 0)  # In DOWN_CANDIDATE, still waiting for still_seconds (1.0s)

        # Frame after 1.1s (0.4 + 1.1 = 1.5s): Person stays motionless
        cands2 = engine.update(det_collapsed, current_time=1.5)
        self.assertEqual(len(cands2), 1)
        self.assertEqual(cands2[0]["category_hint"], "person_down")

    def test_suicide_hazard_trigger(self):
        config = {
            "hazard_zones": [
                {
                    "name": "High Ledge",
                    "polygon": [[0, 0], [200, 0], [200, 100], [0, 100]],
                    "max_dwell_seconds": 1.5,
                }
            ]
        }
        engine = TriggerEngine("cam1", config)

        # Person enters high ledge zone (center at x=50, y=50)
        det = [{"track_id": 5, "box": [30, 20, 70, 80], "confidence": 0.92}]
        cands1 = engine.update(det, current_time=0.0)
        self.assertEqual(len(cands1), 0)

        # Dwells for 1.8 seconds
        cands2 = engine.update(det, current_time=1.8)
        self.assertEqual(len(cands2), 1)
        self.assertEqual(cands2[0]["category_hint"], "suicide_risk")

    def test_dangerous_terrain_hazard_tracking_and_tags(self):
        config = {
            "hazard_zones": [
                {
                    "name": "Atrium Balcony Ledge",
                    "hazard_type": "fall_hazard",
                    "severity": "CRITICAL",
                    "icon": "🛑",
                    "polygon": [[50, 20], [200, 20], [200, 100], [50, 100]],
                    "max_dwell_seconds": 2.0,
                }
            ]
        }
        engine = TriggerEngine("cam1", config)

        # Frame 1: Person inside hazard zone (standing person: w=20, h=60, center=(90, 70))
        det = [{"track_id": 9, "box": [80, 40, 100, 100], "confidence": 0.95}]
        engine.update(det, current_time=1.0)
        active = engine.get_active_zone_status()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["zone_name"], "Atrium Balcony Ledge")
        self.assertEqual(active[0]["hazard_type"], "fall_hazard")
        self.assertEqual(active[0]["icon"], "🛑")
        self.assertEqual(active[0]["dwell_sec"], 0.0)

        # Frame 2: Person dwells past 2.0s
        cands = engine.update(det, current_time=3.2)
        self.assertEqual(len(cands), 1)
        self.assertIn("dangerous_terrain", cands[0].get("tags", []))
        self.assertIn("fall_hazard", cands[0].get("tags", []))

        # Frame 3: Video loop wrap-around (timestamp goes from 3.2 to 0.5)
        # Verify engine resets safely without raising error
        engine.update(det, current_time=0.5)
        self.assertEqual(engine.last_update_time, 0.5)


if __name__ == "__main__":
    unittest.main()

