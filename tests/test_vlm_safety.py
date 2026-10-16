"""Unit tests for VLM Verification, Prompt Safety, and JSON Parsing."""

import unittest
from backend.server.vlm import VLMClient, VALID_CATEGORIES


class TestVLMSafety(unittest.TestCase):
    def test_core_valid_categories(self):
        expected = {"person_down", "fighting", "tailgating", "crowd_incident", "suspicious_activity"}
        self.assertEqual(VALID_CATEGORIES, expected)

    def test_parse_json_response_with_think_tags(self):
        client = VLMClient()
        raw_text = "<think>Let me see if person is down. Yes.</think>\n" \
                   '{"verdict": "yes", "observation": "A person lying flat on the floor", "tags": ["medical_emergency"]}'
        # Strip thinking tag
        import re
        clean_text = re.sub(r"<think>[\s\S]*?</think>", "", raw_text, flags=re.IGNORECASE).strip()
        parsed = client._parse_json_response(clean_text)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.get("verdict"), "yes")
        self.assertIn("lying flat", parsed.get("observation", ""))
        self.assertEqual(parsed.get("tags"), ["medical_emergency"])

    def test_vlm_rejection_on_no_verdict(self):
        client = VLMClient()
        # Candidate with no frames -> drops immediately
        cand = {
            "category_hint": "person_down",
            "camera_id": "cam1",
            "frames": [],
        }
        res = client.describe_event(cand)
        self.assertFalse(res["verified"])
        self.assertEqual(res["confidence"], 0.0)

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
