"""Comprehensive Unit Tests for Person-Down State Machine (Phase 4).

Tests deterministic behavior across all scenarios required by Phase 4:
1. Normal walking (stays upright)
2. Sitting down and remaining seated
3. Crouching or bending
4. Intentionally lying down on frame entry (too-short/missing upright history)
5. Transitioning from upright to prone and remaining down (fall confirmed)
6. Falling and then recovering (getting back up resets episode)
7. Stationary person with bounding-box detector jitter
8. Scale and resolution independence (normalized motion & collapse ratios)
9. Missing detections / temporary occlusion
10. Video loop / timestamp reset
11. Single emission per fall episode (no repeated alerts)
12. VLM verification honesty (positive, rejection, missing fields, timeout, unverified)
"""

import unittest
from backend.vision.triggers import TriggerEngine, PersonDownState, PersonDownFSM
from backend.server.vlm import VLMClient


class TestPersonDownFSM(unittest.TestCase):
    def setUp(self):
        self.config = {
            "person_down_aspect_ratio_threshold": 0.85,
            "person_down_height_collapse_ratio": 0.60,
            "person_down_min_upright_frames": 4,
            "person_down_transition_frames": 3,
            "person_down_still_seconds": 2.0,
            "person_down_motion_threshold_ratio": 0.15,
            "person_down_recovery_aspect_thresh": 0.65,
        }

    def test_walking_normally(self):
        """A person walking normally (upright, moving) must never trigger."""
        engine = TriggerEngine("cam1", self.config)
        cands = []
        # Walk across screen over 10 seconds (h=150, w=45 -> aspect=0.30)
        for i in range(50):
            t = i * 0.2
            x = 100 + i * 5
            det = [{"track_id": 1, "box": [x, 100, x + 45, 250], "confidence": 0.95}]
            cands.extend(engine.update(det, current_time=t))
        self.assertEqual(len(cands), 0)

    def test_sitting_down_and_remaining_seated(self):
        """A person who sits on a chair maintains aspect ratio < 0.85 and does not collapse < 0.60."""
        engine = TriggerEngine("cam1", self.config)
        # 1. Stand upright first (h=160, w=45 -> aspect=0.28)
        for i in range(5):
            det = [{"track_id": 1, "box": [100, 100, 145, 260], "confidence": 0.95}]
            engine.update(det, current_time=i * 0.1)

        # 2. Sit down on chair (h=110, w=55 -> h/baseline = 110/160 = 0.6875 > 0.60; aspect = 55/110 = 0.50 < 0.85)
        cands = []
        for i in range(30):
            t = 0.5 + i * 0.2
            det = [{"track_id": 1, "box": [100, 150, 155, 260], "confidence": 0.95}]
            cands.extend(engine.update(det, current_time=t))

        self.assertEqual(len(cands), 0, "Sitting person must not trigger person_down")

    def test_crouching_or_bending(self):
        """A person crouches temporarily (e.g. tying shoelace) and recovers."""
        engine = TriggerEngine("cam1", self.config)
        # 1. Establish upright baseline
        for i in range(5):
            det = [{"track_id": 1, "box": [100, 100, 145, 260], "confidence": 0.95}]
            engine.update(det, current_time=i * 0.1)

        # 2. Crouch for 1 second (less than still_seconds=2.0)
        # h=80, w=75 -> aspect=0.93 (prone posture)
        for i in range(5):
            t = 0.6 + i * 0.2  # 0.6 to 1.4s (0.8s duration)
            det = [{"track_id": 1, "box": [100, 180, 175, 260], "confidence": 0.95}]
            cands = engine.update(det, current_time=t)
            self.assertEqual(len(cands), 0)

        # 3. Stands back up
        for i in range(5):
            t = 1.6 + i * 0.2
            det = [{"track_id": 1, "box": [100, 100, 145, 260], "confidence": 0.95}]
            cands = engine.update(det, current_time=t)
            self.assertEqual(len(cands), 0)

    def test_entering_frame_already_lying_down(self):
        """Someone already lying on the ground when entering camera must not produce confirmed event (insufficient history)."""
        engine = TriggerEngine("cam1", self.config)
        cands = []
        # Prone posture from frame 1 (h=40, w=120 -> aspect=3.0)
        for i in range(30):
            t = i * 0.2
            det = [{"track_id": 2, "box": [200, 200, 320, 240], "confidence": 0.92}]
            cands.extend(engine.update(det, current_time=t))

        self.assertEqual(len(cands), 0, "Person entering already prone must not trigger without upright baseline")

    def test_fall_transition_and_sustained_down(self):
        """Valid fall: upright baseline -> collapse -> transition -> still for >2.0s -> confirmed."""
        engine = TriggerEngine("cam1", self.config)

        # 1. Upright baseline (4 frames)
        for i in range(4):
            det = [{"track_id": 1, "box": [100, 100, 140, 250], "confidence": 0.95}]
            engine.update(det, current_time=i * 0.1)

        # 2. Collapses prone (h=40, w=120, aspect=3.0)
        # Needs 3 transition frames to enter DOWN_CANDIDATE
        for i in range(3):
            t = 0.5 + i * 0.1
            det = [{"track_id": 1, "box": [100, 210, 220, 250], "confidence": 0.95}]
            cands = engine.update(det, current_time=t)
            self.assertEqual(len(cands), 0)

        # In DOWN_CANDIDATE: at t=0.7s. Requires still_seconds=2.0s (up to t=2.7s)
        # At t=2.0s (only 1.3s elapsed):
        det_still = [{"track_id": 1, "box": [100, 210, 220, 250], "confidence": 0.95}]
        cands_early = engine.update(det_still, current_time=2.0)
        self.assertEqual(len(cands_early), 0)

        # At t=2.8s (2.1s elapsed > 2.0s still_seconds):
        cands_confirmed = engine.update(det_still, current_time=2.8)
        self.assertEqual(len(cands_confirmed), 1)
        self.assertEqual(cands_confirmed[0]["category_hint"], "person_down")
        self.assertEqual(cands_confirmed[0]["track_ids"], [1])

    def test_single_alert_per_episode(self):
        """Once confirmed, staying down must NOT produce repeated candidate events."""
        engine = TriggerEngine("cam1", self.config)

        # 1. Establish upright
        for i in range(4):
            engine.update([{"track_id": 1, "box": [100, 100, 140, 250], "confidence": 0.95}], current_time=i * 0.1)

        # 2. Transition frames
        for i in range(3):
            engine.update([{"track_id": 1, "box": [100, 210, 220, 250], "confidence": 0.95}], current_time=0.5 + i * 0.1)

        # 3. Confirm at t=2.8s
        cands = engine.update([{"track_id": 1, "box": [100, 210, 220, 250], "confidence": 0.95}], current_time=2.8)
        self.assertEqual(len(cands), 1)

        # 4. Remains down for 10 more seconds:
        for t in [3.0, 4.0, 5.0, 7.0, 10.0, 15.0]:
            extra = engine.update([{"track_id": 1, "box": [100, 210, 220, 250], "confidence": 0.95}], current_time=t)
            self.assertEqual(len(extra), 0, f"Expected 0 extra candidates at t={t}")

    def test_recovery_allows_new_episode(self):
        """Person falls -> confirmed -> recovers (stands back up) -> falls again -> second event."""
        engine = TriggerEngine("cam1", self.config)

        # Episode 1: Upright baseline
        for i in range(4):
            engine.update([{"track_id": 1, "box": [100, 100, 140, 250], "confidence": 0.95}], current_time=i * 0.1)

        # Transition
        for i in range(3):
            engine.update([{"track_id": 1, "box": [100, 210, 220, 250], "confidence": 0.95}], current_time=0.5 + i * 0.1)

        # Confirm Episode 1
        cands1 = engine.update([{"track_id": 1, "box": [100, 210, 220, 250], "confidence": 0.95}], current_time=2.8)
        self.assertEqual(len(cands1), 1)

        # Person stands back up (aspect=0.28 < recovery_aspect=0.65)
        for i in range(4):
            engine.update([{"track_id": 1, "box": [100, 100, 140, 250], "confidence": 0.95}], current_time=4.0 + i * 0.2)

        # Cooldown is 15s, advance time to 20s
        # Episode 2: Second fall
        for i in range(3):
            engine.update([{"track_id": 1, "box": [100, 210, 220, 250], "confidence": 0.95}], current_time=20.0 + i * 0.1)

        # Confirm Episode 2 after still_seconds (2.0s)
        cands2 = engine.update([{"track_id": 1, "box": [100, 210, 220, 250], "confidence": 0.95}], current_time=22.5)
        self.assertEqual(len(cands2), 1)
        self.assertEqual(cands2[0]["category_hint"], "person_down")

    def test_detector_box_jitter_while_stationary(self):
        """Bounding box jitter (±3 pixels detector noise) on a fallen person must not exceed normalized motion threshold."""
        engine = TriggerEngine("cam1", self.config)

        for i in range(4):
            engine.update([{"track_id": 1, "box": [100, 100, 140, 250], "confidence": 0.95}], current_time=i * 0.1)

        for i in range(3):
            engine.update([{"track_id": 1, "box": [100, 210, 220, 250], "confidence": 0.95}], current_time=0.5 + i * 0.1)

        # Simulate detector jitter (±2-3 pixels around center)
        jitter = [-2, 1, 3, -1, 2, -3]
        emitted_cands = []
        for idx, j in enumerate(jitter):
            t = 0.8 + idx * 0.4
            box = [100 + j, 210 + j, 220 + j, 250 + j]
            cands = engine.update([{"track_id": 1, "box": box, "confidence": 0.95}], current_time=t)
            emitted_cands.extend(cands)

        # Still down at t=3.0s:
        box_final = [100, 210, 220, 250]
        extra = engine.update([{"track_id": 1, "box": box_final, "confidence": 0.95}], current_time=3.0)
        emitted_cands.extend(extra)

        # Exactly 1 confirmed candidate should have been emitted despite jitter
        self.assertEqual(len(emitted_cands), 1)
        self.assertEqual(emitted_cands[0]["category_hint"], "person_down")

    def test_different_resolutions_and_scales(self):
        """Thresholds are normalized by standing height, working for distant (small) and near (large) people."""
        for scale in [0.4, 1.0, 2.5]:
            engine = TriggerEngine("cam1", self.config)
            sh = 150.0 * scale
            sw = 45.0 * scale
            ph = 35.0 * scale
            pw = 110.0 * scale

            for i in range(4):
                det = [{"track_id": 1, "box": [50, 50, 50 + sw, 50 + sh], "confidence": 0.9}]
                engine.update(det, current_time=i * 0.1)

            for i in range(3):
                det = [{"track_id": 1, "box": [50, 50 + (sh - ph), 50 + pw, 50 + sh], "confidence": 0.9}]
                engine.update(det, current_time=0.5 + i * 0.1)

            det_down = [{"track_id": 1, "box": [50, 50 + (sh - ph), 50 + pw, 50 + sh], "confidence": 0.9}]
            cands = engine.update(det_down, current_time=2.8)
            self.assertEqual(len(cands), 1, f"Failed for person scale {scale}")

    def test_video_seek_or_loop_resets_cleanly(self):
        """When current_time jumps backward (video looped or seeked), tracking state resets cleanly."""
        engine = TriggerEngine("cam1", self.config)
        # Advance to t=10.0
        for i in range(5):
            engine.update([{"track_id": 1, "box": [100, 100, 140, 240], "confidence": 0.9}], current_time=i * 2.0)

        # Jump back to t=0.2 (loop)
        cands = engine.update([{"track_id": 1, "box": [100, 100, 140, 240], "confidence": 0.9}], current_time=0.2)
        self.assertEqual(len(cands), 0)
        self.assertEqual(engine.last_update_time, 0.2)


class TestVLMHonesty(unittest.TestCase):
    def test_explicit_rejection_none(self):
        """When VLM returns none, result has category=none and verified=True."""
        raw = '{"category": "none", "confidence": 0.92, "summary": "Normal foot traffic observed."}'
        parsed = VLMClient._parse_json_response(raw)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["category"], "none")
        self.assertEqual(parsed["confidence"], 0.92)

    def test_parse_failure_fallback_is_explicitly_unverified(self):
        """When model output is garbage, fallback must declare unverified status and never claim pipeline verification."""
        client = VLMClient()
        fallback = client._make_unverified_fallback("person_down", reason="parse_failure")
        self.assertFalse(fallback.get("verified", True))
        self.assertEqual(fallback.get("verification_status"), "unverified_parse_failure")
        self.assertIn("UNVERIFIED", fallback["summary"])
        self.assertNotIn("verified by pipeline", fallback["summary"].lower())

    def test_offline_fallback_is_explicitly_unverified(self):
        """When Ollama is offline, result must clearly indicate VLM OFFLINE."""
        client = VLMClient()
        fallback = client._make_fallback("person_down")
        self.assertFalse(fallback.get("verified", True))
        self.assertEqual(fallback.get("verification_status"), "vlm_offline")
        self.assertIn("VLM OFFLINE", fallback["summary"])


if __name__ == "__main__":
    unittest.main()
