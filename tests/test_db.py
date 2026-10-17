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

    def test_insert_and_get_tags(self):
        event_data = {
            "timestamp": "2026-10-15T15:00:00",
            "camera_id": "cam1",
            "category": "fighting",
            "confidence": 0.92,
            "summary": "[WEAPON DETECTED] Person with handgun.",
            "tags": ["fighting", "weapon_detected", "firearm"],
        }
        event_id = self.db.insert_event(event_data)
        fetched = self.db.get_event(event_id)
        self.assertIsNotNone(fetched)
        self.assertIn("tags", fetched)
        self.assertEqual(fetched["tags"], ["fighting", "weapon_detected", "firearm"])

    def test_verification_status_and_filtering(self):
        # 1. Verified event
        id1 = self.db.insert_event({
            "timestamp": "2026-10-15T15:00:00",
            "camera_id": "cam1",
            "category": "tailgating",
            "confidence": 0.88,
            "summary": "Verified tailgating.",
            "verified": True,
            "verification_status": "vlm_confirmed",
        })

        # 2. Unverified candidate (VLM failure)
        id2 = self.db.insert_event({
            "timestamp": "2026-10-15T15:05:00",
            "camera_id": "cam1",
            "category": "person_down",
            "confidence": 0.55,
            "summary": "[RULE TRIGGER — UNVERIFIED] Suspected fall.",
            "verified": False,
            "verification_status": "unverified_timeout",
        })

        ev1 = self.db.get_event(id1)
        self.assertTrue(ev1["verified"])
        self.assertEqual(ev1["verification_status"], "vlm_confirmed")

        ev2 = self.db.get_event(id2)
        self.assertFalse(ev2["verified"])
        self.assertEqual(ev2["verification_status"], "unverified_timeout")

        # Query only verified
        verified_events = self.db.query_events(verified=True)
        self.assertEqual(len(verified_events), 1)
        self.assertEqual(verified_events[0]["id"], id1)

        # Query only unverified
        unverified_events = self.db.query_events(verified=False)
        self.assertEqual(len(unverified_events), 1)
        self.assertEqual(unverified_events[0]["id"], id2)

        # Check stats counts only verified in category counts
        stats = self.db.get_stats()
        self.assertEqual(stats["total_events"], 1)
        self.assertEqual(stats["unverified_candidates"], 1)
        self.assertEqual(stats["categories"]["tailgating"], 1)
        self.assertEqual(stats["categories"]["person_down"], 0)


if __name__ == "__main__":
    unittest.main()
