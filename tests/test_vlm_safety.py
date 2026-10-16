"""Unit tests for VLM Safety, Verification, and Parsing."""

import unittest
from backend.server.vlm import VLMClient, VALID_CATEGORIES


class TestVLMSafety(unittest.TestCase):
    def test_valid_categories(self):
        for cat in ["person_down", "fighting", "tailgating", "crowd_incident", "suspicious_activity"]:
            self.assertIn(cat, VALID_CATEGORIES)

    def test_parse_json_verified_true(self):
        raw_text = '{"verified": true, "confidence": 0.92, "what_is_visible": "Two individuals physically wrestling and striking each other.", "reason": "Active physical combat observed", "tags": ["brawl"]}'
        parsed = VLMClient._parse_json_response(raw_text, expected_category="fighting")
        self.assertIsNotNone(parsed)
        self.assertTrue(parsed["verified"])
        self.assertEqual(parsed["category"], "fighting")
        self.assertEqual(parsed["summary"], "Two individuals physically wrestling and striking each other.")
        self.assertEqual(parsed["tags"], ["brawl"])

    def test_parse_json_verified_false(self):
        raw_text = '{"verified": false, "confidence": 0.20, "what_is_visible": "People standing peacefully talking in a cafe.", "reason": "No fighting observed"}'
        parsed = VLMClient._parse_json_response(raw_text, expected_category="fighting")
        self.assertIsNotNone(parsed)
        self.assertFalse(parsed["verified"])
        self.assertEqual(parsed["category"], "none")

    def test_thinking_text_rejection_when_unverified(self):
        # When model outputs raw thinking tokens describing that no person is down
        raw_thinking = "Let's see: It's a busy street with lots of people walking, no one lying down, no fighting."
        parsed = VLMClient._parse_json_response(raw_thinking, expected_category="person_down")
        # Should be None or verified=False
        self.assertTrue(parsed is None or parsed.get("verified") is False)

    def test_unverified_candidate_dropped_completely(self):
        client = VLMClient()
        # Candidate with no frames must immediately return rejection
        result = client.describe_event({"category_hint": "person_down", "frames": []})
        self.assertFalse(result["verified"])
        self.assertEqual(result["category"], "none")
        self.assertEqual(result["confidence"], 0.0)

    def test_vlm_fifo_queue_processing(self):
        import time
        from backend.vision.pipeline import _VLM_QUEUE, _ensure_vlm_worker
        processed = []

        def mock_callback(cand):
            processed.append(cand["id"])

        _ensure_vlm_worker()
        _VLM_QUEUE.put_nowait(({"id": 101}, mock_callback))
        _VLM_QUEUE.put_nowait(({"id": 102}, mock_callback))
        time.sleep(0.4)
        self.assertIn(101, processed)
        self.assertIn(102, processed)
        self.assertEqual(processed, [101, 102])


if __name__ == "__main__":
    unittest.main()
