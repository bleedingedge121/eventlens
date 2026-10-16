"""Unit tests for VLM Safety, Weapon Suppression, and Parsing."""

import unittest
from backend.server.vlm import VLMClient, VALID_CATEGORIES


class TestVLMSafety(unittest.TestCase):
    def test_suicide_risk_in_valid_categories(self):
        self.assertIn("suicide_risk", VALID_CATEGORIES)

    def test_parse_json_no_weapon_false_positive(self):
        # Even if text contains "camera shot" or "no weapon", weapon_detected must remain False
        raw_text = '{"category": "suspicious_activity", "confidence": 0.82, "summary": "Person loitering near door in this camera shot. No weapon visible.", "weapon_detected": false}'
        parsed = VLMClient._parse_json_response(raw_text)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["category"], "suspicious_activity")
        self.assertNotIn("[WEAPON DETECTED]", parsed["summary"])
        self.assertFalse(parsed.get("weapon_detected", False))

    def test_parse_json_true_weapon_detected(self):
        raw_text = '{"category": "suspicious_activity", "confidence": 0.95, "summary": "Person holding a handgun.", "weapon_detected": true}'
        parsed = VLMClient._parse_json_response(raw_text)
        self.assertIsNotNone(parsed)
        self.assertTrue(parsed.get("weapon_detected", False))
        self.assertIn("[WEAPON DETECTED]", parsed["summary"])

    def test_fallback_summary_does_not_mention_weapon(self):
        client = VLMClient()
        fallback = client._make_fallback("suspicious_activity")
        self.assertNotIn("weapon", fallback["summary"].lower())

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
