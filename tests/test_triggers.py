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
        self.assertEqual(candidates[0]["camera_id"], "cam1")


if __name__ == "__main__":
    unittest.main()
