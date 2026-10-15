"""Unit tests for EventLens Database Module (Standard Library unittest)."""

import tempfile
import unittest
from pathlib import Path
from backend.server.db import Database


class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test_events.db"
        self.db = Database(str(self.db_path))

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_insert_and_get_event(self):
        event_data = {
            "timestamp": "2026-10-15T12:00:00",
            "camera_id": "cam1",
            "category": "tailgating",
            "confidence": 0.89,
            "summary": "Tailgating incident detected.",
            "track_ids": [10, 11],
            "latency_ms": 350,
        }

        event_id = self.db.insert_event(event_data)
        self.assertEqual(event_id, 1)

        fetched = self.db.get_event(event_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["id"], 1)
        self.assertEqual(fetched["category"], "tailgating")
        self.assertEqual(fetched["track_ids"], [10, 11])
        self.assertEqual(fetched["confidence"], 0.89)

    def test_query_events_filter(self):
        self.db.insert_event({
            "timestamp": "2026-10-15T10:00:00",
            "camera_id": "cam1",
            "category": "tailgating",
            "confidence": 0.9,
            "summary": "Tailgating",
        })
        self.db.insert_event({
            "timestamp": "2026-10-15T11:00:00",
            "camera_id": "cam2",
            "category": "person_down",
            "confidence": 0.95,
            "summary": "Fall",
        })

        cam1_events = self.db.query_events(camera_id="cam1")
        self.assertEqual(len(cam1_events), 1)
        self.assertEqual(cam1_events[0]["category"], "tailgating")

        fall_events = self.db.query_events(category="person_down")
        self.assertEqual(len(fall_events), 1)
        self.assertEqual(fall_events[0]["camera_id"], "cam2")

    def test_get_stats(self):
        self.db.insert_event({
            "timestamp": "2026-10-15T10:00:00",
            "camera_id": "cam1",
            "category": "crowd_incident",
            "confidence": 0.8,
            "summary": "Crowd",
            "latency_ms": 300,
        })

        stats = self.db.get_stats()
        self.assertEqual(stats["total_events"], 1)
        self.assertEqual(stats["categories"]["crowd_incident"], 1)
        self.assertEqual(stats["avg_latency_ms"], 300.0)

    def test_readonly_query(self):
        self.db.insert_event({
            "timestamp": "2026-10-15T10:00:00",
            "camera_id": "cam1",
            "category": "fighting",
            "confidence": 0.85,
            "summary": "Altercation",
        })

        rows = self.db.run_readonly_query("SELECT * FROM events WHERE category = 'fighting' LIMIT 10")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["category"], "fighting")


if __name__ == "__main__":
    unittest.main()
