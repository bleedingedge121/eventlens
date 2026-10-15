"""EventLens Main FastAPI Server.

Implements all frozen endpoints from AGENTS.md Section 8:
- GET /api/events?category=&camera_id=&since=&limit=
- GET /api/events/{id}
- GET /api/stats
- GET /stream/{camera_id} (MJPEG live stream)
- POST /api/chat
- POST /api/source
- GET /api/health
- Static mounting for frontend and data/frames
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional
import cv2

logger = logging.getLogger("eventlens.server")

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.server.chat import ChatEngine
from backend.server.db import Database
from backend.server.vlm import VLMClient
from backend.vision.pipeline import (
    get_latest_jpeg,
    start_camera,
    stop_camera,
    get_camera_status,
    list_active_cameras,
)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
FRAMES_DIR = DATA_DIR / "frames"
FRAMES_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="EventLens Server",
    description="Open-Source AI Video Surveillance Event Summarization & Querying",
    version="0.1.0",
)

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

db = Database(str(DATA_DIR / "events.db"))
vlm = VLMClient()
chat = ChatEngine(db=db)

# Directories for keyframes and event clips
CLIPS_DIR = DATA_DIR / "clips"
CLIPS_DIR.mkdir(parents=True, exist_ok=True)

# Minimum confidence to store an event (below this = dropped as noise)
MIN_EVENT_CONFIDENCE = 0.50


class SourceRequest(BaseModel):
    camera_id: str
    source: str


class ChatRequest(BaseModel):
    question: str


def on_candidate_event(candidate: dict):
    """Callback invoked by the vision pipeline when an event rule triggers.

    Runs the VLM, filters by confidence threshold, and stores the resulting event into the database.
    Saves both keyframe image and multi-frame event clip.
    """
    import time
    start_t = time.time()

    # Call VLM to describe and confirm
    vlm_result = vlm.describe_event(candidate)

    # Drop if VLM classified as "none" (filtering false alarms)
    if vlm_result.get("category") == "none":
        logger.info(f"[Server] VLM filtered event as 'none' (false alarm) from {candidate.get('camera_id')}")
        return

    # Drop low-confidence events (noise reduction based on settings.json)
    min_conf = 0.50
    try:
        with open(BASE_DIR / "config" / "settings.json", "r") as f:
            min_conf = float(json.load(f).get("event_filter", {}).get("min_confidence", 0.50))
    except Exception:
        pass

    confidence = vlm_result.get("confidence", 0.0)
    if confidence < min_conf:
        logger.info(f"[Server] Dropped low-confidence event: {vlm_result.get('category')} at {confidence:.0%} < {min_conf:.0%}")
        return

    latency_ms = int((time.time() - start_t) * 1000)

    event_payload = {
        "timestamp": candidate.get("timestamp"),
        "camera_id": candidate.get("camera_id"),
        "category": vlm_result["category"],
        "confidence": vlm_result["confidence"],
        "summary": vlm_result["summary"],
        "keyframe_path": "",
        "track_ids": candidate.get("track_ids", []),
        "latency_ms": latency_ms,
    }

    event_id = db.insert_event(event_payload)

    if event_id:
        # Save keyframe image
        keyframe_bytes = candidate.get("keyframe_bytes")
        if keyframe_bytes:
            keyframe_path = str(FRAMES_DIR / f"{event_id}.jpg")
            Path(keyframe_path).write_bytes(keyframe_bytes)
            db.update_keyframe_path(event_id, keyframe_path)

        # Save multi-frame event clip (all context frames that triggered the event)
        clip_frames = candidate.get("frames", [])
        if clip_frames:
            clip_dir = CLIPS_DIR / str(event_id)
            clip_dir.mkdir(parents=True, exist_ok=True)
            for i, frame_bytes in enumerate(clip_frames):
                if isinstance(frame_bytes, bytes):
                    (clip_dir / f"frame_{i:02d}.jpg").write_bytes(frame_bytes)
            logger.info(f"[Server] Saved {len(clip_frames)} clip frames to {clip_dir}")


@app.on_event("startup")
def startup_event():
    """Auto-initializes default camera stream with normal routine passage."""
    cam1_video = DATA_DIR / "videos" / "test_normal.mp4"
    if not cam1_video.exists():
        cam1_video = DATA_DIR / "videos" / "test_tailgating.mp4"
    if cam1_video.exists():
        start_camera("cam1", str(cam1_video), on_candidate=on_candidate_event)
        logger.info(f"[Server] Auto-initialized cam1 with {cam1_video.name}")
    # cam2 remains on standby until activated by user


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/events")
def get_events(
    category: Optional[str] = Query(None),
    camera_id: Optional[str] = Query(None),
    since: Optional[str] = Query(None),
    limit: int = Query(50, le=100),
):
    events = db.query_events(category=category, camera_id=camera_id, since=since, limit=limit)
    return {"events": events}


@app.get("/api/events/{event_id}")
def get_event(event_id: int):
    event = db.get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@app.delete("/api/events")
def delete_all_events():
    """Wipes all event records from the database and frames folder."""
    db.clear_events()
    for f in FRAMES_DIR.glob("*.jpg"):
        try:
            f.unlink()
        except Exception:
            pass
    import shutil
    for cd in CLIPS_DIR.iterdir():
        if cd.is_dir():
            try:
                shutil.rmtree(cd, ignore_errors=True)
            except Exception:
                pass
    return {"success": True, "message": "All incident records, keyframes, and event clips cleared"}


@app.get("/api/stats")
def get_stats():
    return db.get_stats()


@app.post("/api/chat")
def post_chat(req: ChatRequest):
    if not req.question or not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")
    return chat.answer_question(req.question.strip())


@app.post("/api/source")
def set_source(req: SourceRequest):
    success = start_camera(
        camera_id=req.camera_id,
        source=req.source,
        on_candidate=on_candidate_event,
    )
    return {"success": success, "camera_id": req.camera_id, "source": req.source}


@app.delete("/api/source/{camera_id}")
def delete_source(camera_id: str):
    success = stop_camera(camera_id)
    return {"success": success, "camera_id": camera_id}


@app.get("/api/cameras")
def get_cameras():
    """Returns active cameras and their real-time telemetry."""
    return {"cameras": list_active_cameras()}


@app.get("/api/cameras/{camera_id}")
def get_camera(camera_id: str):
    """Returns telemetry for a specific camera."""
    return get_camera_status(camera_id)


@app.get("/api/devices")
def get_available_devices():
    """Detects available local webcams and USB video capture devices."""
    import platform
    devices = []
    # Test index 0 and 1
    for idx in range(2):
        try:
            backend = cv2.CAP_DSHOW if platform.system() == "Windows" else cv2.CAP_ANY
            cap = cv2.VideoCapture(idx, backend)
            if cap.isOpened():
                ret, _ = cap.read()
                if ret:
                    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    devices.append({
                        "index": str(idx),
                        "name": f"Live Camera #{idx} ({w}x{h})",
                        "resolution": f"{w}x{h}",
                        "ready": True,
                    })
                cap.release()
        except Exception:
            pass
    return {"devices": devices}


@app.get("/api/dataset-videos")
def get_dataset_videos():
    """Scans and returns available test video clips from dataset and data/videos directories."""
    search_dirs = [
        Path("D:/ClaudeCode/HackHive/dataset"),
        BASE_DIR.parent / "dataset",
        DATA_DIR / "videos",
    ]
    videos = []
    seen_paths = set()

    for s_dir in search_dirs:
        if s_dir.exists() and s_dir.is_dir():
            for ext in ("*.mp4", "*.avi", "*.mov", "*.mkv"):
                for vf in sorted(s_dir.glob(ext)):
                    abs_str = str(vf.resolve())
                    if abs_str not in seen_paths:
                        seen_paths.add(abs_str)
                        size_mb = round(vf.stat().st_size / (1024 * 1024), 2)
                        videos.append({
                            "name": vf.name,
                            "path": abs_str,
                            "relative_path": str(vf),
                            "size_mb": size_mb,
                            "directory": s_dir.name,
                        })

    return {"videos": videos}


@app.get("/stream/{camera_id}")
async def video_stream(camera_id: str):
    """Streams live MJPEG frames for the given camera with zero-latency buffer."""
    async def frame_generator():
        while True:
            frame_bytes = get_latest_jpeg(camera_id)
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
            )
            await asyncio.sleep(0.033)  # ~30 FPS smooth real-time playback

    return StreamingResponse(
        frame_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


# Mount static frames and clips directories
app.mount("/frames", StaticFiles(directory=str(FRAMES_DIR)), name="frames")
app.mount("/clips", StaticFiles(directory=str(CLIPS_DIR)), name="clips")


@app.get("/api/clips/{event_id}")
def get_event_clips(event_id: int):
    """Returns list of clip frame filenames for a given event."""
    clip_dir = CLIPS_DIR / str(event_id)
    if not clip_dir.exists():
        return {"event_id": event_id, "frames": []}
    frames = sorted([f.name for f in clip_dir.glob("*.jpg")])
    return {
        "event_id": event_id,
        "frames": [f"/clips/{event_id}/{f}" for f in frames],
        "count": len(frames),
    }


# Mount frontend files
FRONTEND_DIR = BASE_DIR / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
