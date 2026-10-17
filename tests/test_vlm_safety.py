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


    def test_benign_restaurant_prose_is_filtered_as_none(self):
        # User reported case: restaurant scene where VLM responds conversationally with benign observations
        raw_text = (
            "The scene is a restaurant or similar indoor space with several people. "
            "The people seem to be in a group, maybe interacting, but not necessarily in a panic."
        )
        parsed = VLMClient._parse_json_response(raw_text)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["category"], "none")
        self.assertFalse(parsed.get("is_incident", True))

    def test_json_is_incident_false_forces_none(self):
        # Even if category says "person_down", is_incident=false must force category to "none"
        raw_text = (
            '{"is_incident": false, "category": "person_down", "confidence": 0.85, '
            '"summary": "A patron is seated at a restaurant table eating lunch.", "weapon_detected": false}'
        )
        parsed = VLMClient._parse_json_response(raw_text)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["category"], "none")

    def test_benign_dining_prose_is_filtered_as_none(self):
        raw_text = "The footage depicts people dining normally at a cafeteria. No incident or fall observed."
        parsed = VLMClient._parse_json_response(raw_text)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["category"], "none")
        self.assertFalse(parsed.get("is_incident", True))

    def test_valid_incident_parsed_properly(self):
        raw_text = (
            '{"is_incident": true, "category": "person_down", "confidence": 0.92, '
            '"summary": "An individual has collapsed on the ground and appears unresponsive.", "weapon_detected": false}'
        )
        parsed = VLMClient._parse_json_response(raw_text)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["category"], "person_down")

    def test_missing_model_fails_closed(self):
        """When requested vision model is missing, describe_event must fail closed without verified incident."""
        client = VLMClient(model_name="nonexistent_vlm_model_xyz", fallback_model="nonexistent_fallback_abc")
        client._available_model = None
        # Mock _resolve_model to return None
        client._resolve_model = lambda: None
        result = client.describe_event({"category_hint": "person_down", "frames": [b"fake_image_bytes"]})
        self.assertFalse(result.get("verified", True))
        self.assertFalse(result.get("is_incident", True))
        self.assertEqual(result.get("verification_status"), "unverified_missing_model")
        self.assertIn("UNVERIFIED", result.get("summary", ""))

    def test_timeout_fails_closed(self):
        """When VLM call times out, describe_event must fail closed without verified incident."""
        client = VLMClient()
        client._resolve_model = lambda: "qwen3-vl:8b"
        # Mock _call_ollama to raise TimeoutError
        def mock_timeout(*args, **kwargs):
            raise TimeoutError("Model inference timed out after 15 seconds")
        client._call_ollama = mock_timeout

        result = client.describe_event({"category_hint": "fighting", "frames": [b"fake_image_bytes"]})
        self.assertFalse(result.get("verified", True))
        self.assertFalse(result.get("is_incident", True))
        self.assertEqual(result.get("verification_status"), "unverified_timeout")
        self.assertIn("UNVERIFIED", result.get("summary", ""))

    def test_malformed_response_fails_closed(self):
        """When VLM returns empty or garbage text, describe_event must fail closed without verified incident."""
        client = VLMClient()
        client._resolve_model = lambda: "qwen3-vl:8b"
        client._call_ollama = lambda *args, **kwargs: "??? gibberish not json and not valid description ???"

        result = client.describe_event({"category_hint": "suspicious_activity", "frames": [b"fake_image_bytes"]})
        self.assertFalse(result.get("verified", True))
        self.assertFalse(result.get("is_incident", True))
        self.assertEqual(result.get("verification_status"), "unverified_malformed_response")

    def test_crop_preserves_small_object_detail(self):
        """Box crops are extracted at high resolution to preserve small object/weapon details."""
        import numpy as np
        import cv2
        client = VLMClient()
        # Create a 640x480 test image with a small distinct pattern (e.g. 30x30 weapon proxy)
        test_img = np.zeros((480, 640, 3), dtype=np.uint8)
        # Person box: [200, 150, 350, 420]
        person_box = [200.0, 150.0, 350.0, 420.0]
        # Draw small weapon detail in hand region: [310, 260, 340, 290]
        test_img[260:290, 310:340] = (255, 255, 255)

        # Prepare images with crops
        imgs = client._prepare_images([test_img], boxes=[person_box], max_dim=768, include_crops=True)
        # Should return at least 2 images: crop of person + full scene
        self.assertGreaterEqual(len(imgs), 2)


if __name__ == "__main__":
    unittest.main()
