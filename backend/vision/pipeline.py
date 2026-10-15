"""EventLens Vision Pipeline Orchestrator.

Provides the agreed internal interfaces between Backend A and Backend B:
- `start_camera(camera_id: str, source: str, on_candidate: Callable) -> bool`
- `get_latest_jpeg(camera_id: str) -> Optional[bytes]`
"""

from collections import deque
import json
from pathlib import Path
import threading
import time
from typing import Callable, Dict, Optional

import cv2
import numpy as np

from backend.vision.detect_track import DetectorTracker
from backend.vision.ingest import VideoIngest
from backend.vision.triggers import TriggerEngine

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = BASE_DIR / "config"

# Global state for camera worker threads and latest annotated frames
_WORKERS: Dict[str, threading.Thread] = {}
_RUNNING_FLAGS: Dict[str, bool] = {}
_LATEST_FRAMES: Dict[str, bytes] = {}
_LOCK = threading.Lock()


def load_camera_config(camera_id: str) -> dict:
    cam_file = CONFIG_DIR / "cameras.json"
    if cam_file.exists():
        try:
            with open(cam_file, "r", encoding="utf-8") as f:
                all_cams = json.load(f)
                return all_cams.get(camera_id, {})
        except Exception:
            pass
    return {}


def load_settings() -> dict:
    settings_file = CONFIG_DIR / "settings.json"
    if settings_file.exists():
        try:
            with open(settings_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _camera_worker_loop(
    camera_id: str,
    source: str,
    on_candidate: Callable[[dict], None],
):
    settings = load_settings()
    cam_config = load_camera_config(camera_id)

    target_fps = settings.get("vision", {}).get("target_fps", 4.0)
    yolo_model = settings.get("vision", {}).get("yolo_model", "yolo11n.pt")
    device = settings.get("vision", {}).get("device", "cuda:0")

    ingest = VideoIngest(source=source, target_fps=target_fps)
    tracker = DetectorTracker(model_name=yolo_model, device=device)
    trigger = TriggerEngine(camera_id=camera_id, config=cam_config)

    # Frame buffer to supply candidate events with 3-4 context frames
    frame_buffer = deque(maxlen=4)

    for timestamp_sec, raw_frame in ingest.frames():
        if not _RUNNING_FLAGS.get(camera_id, False):
            break

        # 1. Run detection and tracking
        detections, annotated_frame = tracker.track(raw_frame)

        # 2. Store latest annotated JPEG frame for MJPEG stream
        ret, jpeg_buf = cv2.imencode(".jpg", annotated_frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ret:
            with _LOCK:
                _LATEST_FRAMES[camera_id] = jpeg_buf.tobytes()

        # Add raw frame to circular buffer
        frame_buffer.append(raw_frame)

        # 3. Check rule triggers
        candidates = trigger.update(detections, current_time=timestamp_sec)
        for cand in candidates:
            # Package frames and keyframe
            recent_frames_b64 = []
            for f in list(frame_buffer):
                s_ret, f_jpeg = cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 75])
                if s_ret:
                    recent_frames_b64.append(f_jpeg.tobytes())

            keyframe_bytes = jpeg_buf.tobytes() if ret else None
            cand["frames"] = recent_frames_b64
            cand["keyframe_bytes"] = keyframe_bytes

            # Notify candidate event callback (invokes VLM in background worker)
            try:
                threading.Thread(target=on_candidate, args=(cand,), daemon=True).start()
            except Exception as e:
                print(f"[Pipeline] Error dispatching candidate event: {e}")

    ingest.stop()


def start_camera(camera_id: str, source: str, on_candidate: Callable[[dict], None]) -> bool:
    """Spawns or restarts the background vision processing thread for a camera."""
    with _LOCK:
        if camera_id in _RUNNING_FLAGS and _RUNNING_FLAGS[camera_id]:
            _RUNNING_FLAGS[camera_id] = False
            time.sleep(0.3)

        _RUNNING_FLAGS[camera_id] = True
        worker = threading.Thread(
            target=_camera_worker_loop,
            args=(camera_id, source, on_candidate),
            daemon=True,
            name=f"CameraWorker-{camera_id}",
        )
        _WORKERS[camera_id] = worker
        worker.start()
        return True


def get_latest_jpeg(camera_id: str) -> Optional[bytes]:
    """Retrieves the latest annotated JPEG bytes for the requested camera."""
    with _LOCK:
        return _LATEST_FRAMES.get(camera_id)
