"""EventLens Vision Pipeline Orchestrator.

Provides the agreed internal interfaces between Backend A and Backend B:
- `start_camera(camera_id: str, source: str, on_candidate: Callable) -> bool`
- `stop_camera(camera_id: str) -> bool`
- `get_latest_jpeg(camera_id: str) -> bytes`
- `get_camera_status(camera_id: str) -> dict`
- `list_active_cameras() -> dict`
"""

from collections import deque
import json
import logging
from pathlib import Path
import threading
import time
from typing import Callable, Dict, List, Optional
import cv2
import numpy as np

from backend.vision.detect_track import DetectorTracker
from backend.vision.ingest import VideoIngest
from backend.vision.triggers import TriggerEngine

logger = logging.getLogger("eventlens.pipeline")

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = BASE_DIR / "config"

# Thread-safe global registries
_WORKERS: Dict[str, threading.Thread] = {}
_RUNNING_FLAGS: Dict[str, bool] = {}
_INGEST_ENGINES: Dict[str, VideoIngest] = {}
_LATEST_FRAMES: Dict[str, bytes] = {}
_CAMERA_METRICS: Dict[str, dict] = {}
_LOCK = threading.Lock()


def load_camera_config(camera_id: str) -> dict:
    cam_file = CONFIG_DIR / "cameras.json"
    if cam_file.exists():
        try:
            with open(cam_file, "r", encoding="utf-8") as f:
                all_cams = json.load(f)
                return all_cams.get(camera_id, {})
        except Exception as e:
            logger.warning(f"Failed to read camera config: {e}")
    return {}


def load_settings() -> dict:
    settings_file = CONFIG_DIR / "settings.json"
    if settings_file.exists():
        try:
            with open(settings_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read settings: {e}")
    return {}


def _generate_standby_jpeg(camera_id: str) -> bytes:
    """Generates an immediate CCTV standby frame when a stream is initializing."""
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    img[:] = (8, 12, 20)  # Graphite carbon

    # Subtle grid
    for y in range(0, 480, 48):
        cv2.line(img, (0, y), (640, y), (18, 25, 38), 1)
    for x in range(0, 640, 64):
        cv2.line(img, (x, 0), (x, 480), (18, 25, 38), 1)

    # Frame boundary
    cv2.rectangle(img, (16, 16), (624, 464), (32, 45, 68), 1)

    # Status labels
    cv2.putText(img, f"EVENTLENS // {camera_id.upper()}", (36, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (56, 189, 248), 2)
    cv2.putText(img, "STREAM STANDBY - AWAITING SOURCE INGESTION", (36, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (148, 163, 184), 1)
    cv2.putText(img, time.strftime("%Y-%m-%d %H:%M:%S"), (36, 440), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (100, 116, 139), 1)
    cv2.putText(img, "OFFLINE BUFFER", (480, 440), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (244, 63, 94), 1)

    ret, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return buf.tobytes() if ret else b""


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

    with _LOCK:
        _INGEST_ENGINES[camera_id] = ingest
        _CAMERA_METRICS[camera_id] = {
            "source": source,
            "fps": 0.0,
            "processed_frames": 0,
            "active_tracks": 0,
            "last_active": time.time(),
        }

    # Circular context frame buffer (3-4 frames for VLM temporal analysis)
    frame_buffer = deque(maxlen=4)
    fps_start_time = time.time()
    frames_counted = 0

    try:
        for timestamp_sec, raw_frame in ingest.frames():
            if not _RUNNING_FLAGS.get(camera_id, False):
                break

            # 1. Run YOLOv11 + ByteTrack
            detections, annotated_frame = tracker.track(raw_frame)

            # 2. Add real-time tactical surveillance HUD overlay to the annotated frame
            h, w = annotated_frame.shape[:2]
            frames_counted += 1
            now = time.time()

            if now - fps_start_time >= 1.0:
                current_fps = round(frames_counted / (now - fps_start_time), 1)
                fps_start_time = now
                frames_counted = 0
                with _LOCK:
                    if camera_id in _CAMERA_METRICS:
                        _CAMERA_METRICS[camera_id]["fps"] = current_fps
                        _CAMERA_METRICS[camera_id]["processed_frames"] += frames_counted
                        _CAMERA_METRICS[camera_id]["active_tracks"] = len(detections)
                        _CAMERA_METRICS[camera_id]["last_active"] = now

            # Top Camera Header
            cv2.putText(
                annotated_frame,
                f"{camera_id.upper()} // {source[:24]}",
                (14, 26),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (240, 246, 252),
                2,
            )

            # Encode and cache the latest JPEG for MJPEG stream
            ret, jpeg_buf = cv2.imencode(".jpg", annotated_frame, [cv2.IMWRITE_JPEG_QUALITY, 82])
            if ret:
                with _LOCK:
                    _LATEST_FRAMES[camera_id] = jpeg_buf.tobytes()

            frame_buffer.append(raw_frame)

            # 3. Check Anomaly Triggers (Geometry & Velocity Rules)
            candidates = trigger.update(detections, current_time=timestamp_sec)
            for cand in candidates:
                # Package recent frames and keyframe
                recent_frames_bytes = []
                for f in list(frame_buffer):
                    s_ret, f_jpeg = cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 78])
                    if s_ret:
                        recent_frames_bytes.append(f_jpeg.tobytes())

                cand["frames"] = recent_frames_bytes
                cand["keyframe_bytes"] = jpeg_buf.tobytes() if ret else None

                # Dispatch candidate event to background worker (runs VLM + SQLite insertion)
                try:
                    threading.Thread(
                        target=on_candidate,
                        args=(cand,),
                        daemon=True,
                        name=f"VLM-Dispatcher-{cand.get('category_hint')}",
                    ).start()
                except Exception as e:
                    logger.error(f"[Pipeline] Error dispatching candidate event: {e}")

    except Exception as e:
        logger.error(f"[Pipeline] Camera worker loop encountered error on {camera_id}: {e}")
    finally:
        ingest.stop()
        with _LOCK:
            _INGEST_ENGINES.pop(camera_id, None)
            _RUNNING_FLAGS[camera_id] = False


def start_camera(camera_id: str, source: str, on_candidate: Callable[[dict], None]) -> bool:
    """Spawns or restarts the background vision processing thread for a camera."""
    with _LOCK:
        # Stop existing worker if active
        if camera_id in _RUNNING_FLAGS and _RUNNING_FLAGS[camera_id]:
            _RUNNING_FLAGS[camera_id] = False
            if camera_id in _INGEST_ENGINES:
                _INGEST_ENGINES[camera_id].stop()
            time.sleep(0.2)

        _RUNNING_FLAGS[camera_id] = True
        worker = threading.Thread(
            target=_camera_worker_loop,
            args=(camera_id, source, on_candidate),
            daemon=True,
            name=f"CameraWorker-{camera_id}",
        )
        _WORKERS[camera_id] = worker
        worker.start()
        logger.info(f"[Pipeline] Started camera worker for {camera_id} with source: {source}")
        return True


def stop_camera(camera_id: str) -> bool:
    """Stops the vision worker for a specific camera."""
    with _LOCK:
        if camera_id in _RUNNING_FLAGS:
            _RUNNING_FLAGS[camera_id] = False
            if camera_id in _INGEST_ENGINES:
                _INGEST_ENGINES[camera_id].stop()
            logger.info(f"[Pipeline] Stopped camera {camera_id}")
            return True
        return False


def get_latest_jpeg(camera_id: str) -> bytes:
    """Retrieves the latest annotated JPEG frame, or generates an immediate standby frame."""
    with _LOCK:
        cached = _LATEST_FRAMES.get(camera_id)
        if cached:
            return cached
    # Fallback standby frame
    return _generate_standby_jpeg(camera_id)


def get_camera_status(camera_id: str) -> dict:
    """Returns runtime telemetry for a camera."""
    with _LOCK:
        is_active = _RUNNING_FLAGS.get(camera_id, False)
        metrics = _CAMERA_METRICS.get(camera_id, {})
        return {
            "camera_id": camera_id,
            "is_active": is_active,
            "fps": metrics.get("fps", 0.0),
            "processed_frames": metrics.get("processed_frames", 0),
            "active_tracks": metrics.get("active_tracks", 0),
            "source": metrics.get("source", "unassigned"),
        }


def list_active_cameras() -> List[dict]:
    """Returns telemetry list for all tracked cameras."""
    with _LOCK:
        return [get_camera_status(cid) for cid in list(_WORKERS.keys())]
