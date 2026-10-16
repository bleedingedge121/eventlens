"""Comprehensive tests for Taxonomy, Strict VLM Verification, Status Tiers, and Scene Profiles."""

import unittest
from fastapi.testclient import TestClient
from backend.server.main import app, db
from backend.server.config import get_taxonomy, get_settings
from backend.server.vlm import VLMClient
from backend.vision.triggers import TriggerEngine


class TestVLMVerificationAndTaxonomy(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        db.clear_events()

    def test_get_taxonomy_endpoint(self):
        res = self.client.get("/api/taxonomy")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("categories", data)
        self.assertIn("scene_profiles", data)
        self.assertIn("indoor_premises", data["scene_profiles"])
        self.assertIn("outdoor_street", data["scene_profiles"])

        # Check category questions
        cat_map = {c["id"]: c for c in data["categories"]}
        self.assertIn("person_down", cat_map)
        self.assertIn("vlm_question", cat_map["person_down"])
        self.assertIn("allowed_tags", cat_map["person_down"])

    def test_get_config_endpoint_safe(self):
        res = self.client.get("/api/config")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("vision", data)
        self.assertIn("confidence_threshold", data["vision"])
        self.assertIn("ollama", data)

    def test_event_status_tiers_and_filtering(self):
        # Insert high confidence verified event (>= 0.75)
        id1 = db.insert_event({
            "timestamp": "2026-10-17T00:00:01",
            "camera_id": "cam1",
            "category": "tailgating",
            "confidence": 0.88,
            "summary": "Two individuals entered in immediate succession.",
            "verified": 1,
            "status": "high",
        })

        # Insert lower confidence verified event (< 0.75)
        id2 = db.insert_event({
            "timestamp": "2026-10-17T00:00:02",
            "camera_id": "cam1",
            "category": "suspicious_activity",
            "confidence": 0.68,
            "summary": "Individual standing near door.",
            "verified": 1,
            "status": "needs_review",
        })

        # Insert rejected event (VLM verdict was 'no')
        id3 = db.insert_event({
            "timestamp": "2026-10-17T00:00:03",
            "camera_id": "cam1",
            "category": "person_down",
            "confidence": 0.0,
            "summary": "Person is walking normally.",
            "verified": 0,
            "status": "rejected",
            "rejection_reason": "VLM verdict was 'no'",
        })

        # Default query / status=high -> returns only id1
        r_default = self.client.get("/api/events")
        ids_default = [e["id"] for e in r_default.json()["events"]]
        self.assertEqual(ids_default, [id1])

        # status=all_verified -> returns id1 and id2
        r_all_ver = self.client.get("/api/events?status=all_verified")
        ids_all_ver = [e["id"] for e in r_all_ver.json()["events"]]
        self.assertEqual(set(ids_all_ver), {id1, id2})

        # status=needs_review -> returns only id2
        r_review = self.client.get("/api/events?status=needs_review")
        ids_review = [e["id"] for e in r_review.json()["events"]]
        self.assertEqual(ids_review, [id2])

        # status=rejected -> returns only id3 (developer only view)
        r_rej = self.client.get("/api/events?status=rejected")
        ids_rej = [e["id"] for e in r_rej.json()["events"]]
        self.assertEqual(ids_rej, [id3])

    def test_stats_counts_verified_only(self):
        # Insert 1 verified, 1 rejected
        db.insert_event({
            "timestamp": "2026-10-17T00:00:01",
            "camera_id": "cam1",
            "category": "fighting",
            "confidence": 0.90,
            "verified": 1,
            "vlm_latency_ms": 350,
        })
        db.insert_event({
            "timestamp": "2026-10-17T00:00:02",
            "camera_id": "cam1",
            "category": "person_down",
            "confidence": 0.0,
            "verified": 0,
            "vlm_latency_ms": 1200,
        })

        stats = db.get_stats()
        self.assertEqual(stats["total_verified"], 1)
        self.assertEqual(stats["total_rejected"], 1)
        self.assertEqual(stats["categories"]["fighting"], 1)
        self.assertEqual(stats["categories"]["person_down"], 0)
        self.assertEqual(stats["p50_latency_ms"], 350)

    def test_normal_walking_pedestrians_do_not_trigger_person_down(self):
        """Normal walking people have upright aspect ratio (h > w) and do not collapse."""
        engine = TriggerEngine("cam1", {
            "person_down_still_seconds": 1.0,
            "person_down_min_track_age": 1.0,
        })

        # Walking pedestrian moving across screen: box maintains upright ratio (h=140, w=45)
        for t, x in enumerate([50, 75, 100, 125, 150, 175, 200]):
            det = [{"track_id": 10, "box": [x, 100, x + 45, 240], "confidence": 0.92}]
            cands = engine.update(det, current_time=t * 0.5)
            self.assertEqual(len(cands), 0)


if __name__ == "__main__":
    unittest.main()
