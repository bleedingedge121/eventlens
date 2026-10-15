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
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.server.chat import ChatEngine
from backend.server.db import Database
from backend.server.vlm import VLMClient
from backend.vision.pipeline import get_latest_jpeg, start_camera

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


class SourceRequest(BaseModel):
    camera_id: str
    source: str


class ChatRequest(BaseModel):
    question: str


def on_candidate_event(candidate: dict):
    """Callback invoked by the vision pipeline when an event rule triggers.

    Runs the VLM and stores the resulting event into the database.
    """
    import time
    start_t = time.time()

    # Call VLM to describe and confirm
    vlm_result = vlm.describe_event(candidate)

    # Drop if VLM classified as "none" (filtering false alarms)
    if vlm_result.get("category") == "none":
        return

    latency_ms = int((time.time() - start_t) * 1000)

    # Save keyframe image to disk
    event_id_guess = int(time.time() * 1000) % 1000000
    keyframe_bytes = candidate.get("keyframe_bytes")
    keyframe_path = str(FRAMES_DIR / f"{event_id_guess}.jpg")
    if keyframe_bytes:
        Path(keyframe_path).write_bytes(keyframe_bytes)

    event_payload = {
        "timestamp": candidate.get("timestamp"),
        "camera_id": candidate.get("camera_id"),
        "category": vlm_result["category"],
        "confidence": vlm_result["confidence"],
        "summary": vlm_result["summary"],
        "keyframe_path": keyframe_path,
        "track_ids": candidate.get("track_ids", []),
        "latency_ms": latency_ms,
    }

    db.insert_event(event_payload)


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


@app.get("/stream/{camera_id}")
async def video_stream(camera_id: str):
    """Streams MJPEG frames for the given camera."""
    async def frame_generator():
        while True:
            frame_bytes = get_latest_jpeg(camera_id)
            if frame_bytes:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
                )
            await asyncio.sleep(0.08)  # ~12 FPS stream refresh

    return StreamingResponse(
        frame_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


# Mount static frames directory
app.mount("/frames", StaticFiles(directory=str(FRAMES_DIR)), name="frames")

# Mount frontend files
FRONTEND_DIR = BASE_DIR / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
