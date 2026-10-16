import unittest
from fastapi.testclient import TestClient
from backend.server.main import app

class TestCameraAPI(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_get_cameras_config(self):
        res = self.client.get("/api/cameras/config")
        self.assertEqual(res.status_code, 200)
        data = res.json().get("cameras", {})
        self.assertIn("cam1", data)
        self.assertIn("cam2", data)

    def test_add_and_delete_camera(self):
        # 1. Add camera
        payload = {
            "camera_id": "test_cam_unit",
            "name": "Unit Test Camera",
            "source": "data/videos/test_tailgating.mp4",
            "camera_type": "turnstile"
        }
        res = self.client.post("/api/cameras", json=payload)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json().get("ok"))

        # Verify it shows in config
        res_cfg = self.client.get("/api/cameras/config")
        self.assertIn("test_cam_unit", res_cfg.json().get("cameras", {}))

        # 2. Delete camera
        res_del = self.client.delete("/api/cameras/test_cam_unit")
        self.assertEqual(res_del.status_code, 200)
        self.assertTrue(res_del.json().get("ok"))

        # Verify it is removed
        res_cfg2 = self.client.get("/api/cameras/config")
        self.assertNotIn("test_cam_unit", res_cfg2.json().get("cameras", {}))

    def test_seek_and_playback_endpoints(self):
        # Even if camera is not running, endpoints return gracefully with status dict
        res_seek = self.client.post("/api/cameras/cam1/seek", json={"ratio": 0.5})
        self.assertEqual(res_seek.status_code, 200)
        self.assertIn("ok", res_seek.json())
        self.assertIn("success", res_seek.json())

        res_play = self.client.post("/api/cameras/cam1/playback", json={"paused": True})
        self.assertEqual(res_play.status_code, 200)
        self.assertIn("ok", res_play.json())
        self.assertIn("success", res_play.json())

    def test_get_devices(self):
        res = self.client.get("/api/devices")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("devices", data)
        self.assertIsInstance(data["devices"], list)

    def test_mjpeg_stream_endpoint(self):
        res = self.client.get("/stream/cam1?max_frames=1")
        self.assertEqual(res.status_code, 200)
        self.assertIn("multipart/x-mixed-replace", res.headers.get("content-type", ""))
        self.assertTrue(len(res.content) > 0)
        self.assertIn(b"--frame", res.content)

    def test_lifespan_startup_and_teardown(self):
        with TestClient(app) as client:
            res = client.get("/api/health")
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json(), {"ok": True})

    def test_camera_zones_get_and_update(self):
        # 1. GET zones for cam1
        res = self.client.get("/api/cameras/cam1/zones")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["camera_id"], "cam1")
        self.assertIn("door_zone", data)
        self.assertIn("restricted_zones", data)

        # 2. PUT updated zones
        new_door = [[100, 200], [300, 200], [300, 400], [100, 400]]
        res_put = self.client.put("/api/cameras/cam1/zones", json={"door_zone": new_door})
        self.assertEqual(res_put.status_code, 200)
        self.assertTrue(res_put.json().get("ok"))
        self.assertEqual(res_put.json().get("door_zone"), new_door)

        # Verify persistent read
        res_check = self.client.get("/api/cameras/cam1/zones")
        self.assertEqual(res_check.json().get("door_zone"), new_door)

    def test_delete_events_requires_confirmation(self):
        # Without confirmation -> 400
        res = self.client.delete("/api/events")
        self.assertEqual(res.status_code, 400)

        # With confirm=true query param -> 200
        res_ok = self.client.delete("/api/events?confirm=true")
        self.assertEqual(res_ok.status_code, 200)
        self.assertTrue(res_ok.json().get("success"))

        # With header -> 200
        res_hdr = self.client.delete("/api/events", headers={"X-Confirm-Delete": "true"})
        self.assertEqual(res_hdr.status_code, 200)
        self.assertTrue(res_hdr.json().get("success"))

    def test_clip_endpoints_path_traversal_protection(self):
        # Negative / invalid ID -> 400
        res = self.client.get("/api/clips/-5")
        self.assertEqual(res.status_code, 400)

        res_vid = self.client.get("/api/clips/-1/video")
        self.assertEqual(res_vid.status_code, 400)

        # Nonexistent event -> returns empty list gracefully
        res_empty = self.client.get("/api/clips/999999")
        self.assertEqual(res_empty.status_code, 200)
        self.assertEqual(res_empty.json()["frames"], [])

    def test_stats_includes_genuine_gpu_telemetry(self):
        res = self.client.get("/api/stats")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("gpu", data)
        self.assertIn(data["gpu"]["status"], ["available", "unavailable"])


if __name__ == "__main__":
    unittest.main()


