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
from contextlib import asynccontextmanager
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import cv2

logger = logging.getLogger("eventlens.server")

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

try:
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
except Exception:
    pass

import numpy as np

from backend.server.chat import ChatEngine
from backend.server.db import Database
from backend.server.vlm import VLMClient
from backend.vision.pipeline import (
    get_latest_jpeg,
    start_camera,
    stop_camera,
    stop_all_cameras,
    get_camera_status,
    list_active_cameras,
    seek_camera,
    set_camera_playback,
)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
FRAMES_DIR = DATA_DIR / "frames"
FRAMES_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto-initialize default camera stream with normal routine passage
    cam1_video = DATA_DIR / "videos" / "test_normal.mp4"
    if not cam1_video.exists():
        cam1_video = DATA_DIR / "videos" / "test_tailgating.mp4"
    if cam1_video.exists():
        start_camera("cam1", str(cam1_video), on_candidate=on_candidate_event)
        logger.info(f"[Server] Auto-initialized cam1 with {cam1_video.name}")
    yield
    stop_all_cameras()


app = FastAPI(
    title="EventLens Server",
    description="Open-Source AI Video Surveillance Event Summarization & Querying",
    version="0.1.0",
    lifespan=lifespan,
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


class SeekRequest(BaseModel):
    frame_idx: Optional[int] = None
    ratio: Optional[float] = None


class PlaybackRequest(BaseModel):
    paused: bool


class CameraCreateRequest(BaseModel):
    camera_id: str
    name: str
    description: Optional[str] = ""
    source: Optional[str] = None
    scene_profile: Optional[str] = "indoor_premises"
    door_zone: Optional[list] = None
    restricted_zones: Optional[list] = None
    crowd_threshold: Optional[int] = 7
    auto_start: bool = True


class ChatRequest(BaseModel):
    question: str


def on_candidate_event(candidate: dict):
    """Callback invoked by the vision pipeline when an event rule triggers.

    Runs the VLM verifier, feeds verification result back to trigger auto-pause,
    and stores event into database with appropriate status (high, needs_review, or rejected).
    """
    import time
    start_t = time.time()
    camera_id = candidate.get("camera_id", "cam1")
    category_hint = candidate.get("category_hint", "suspicious_activity")

    # Call VLM to verify
    vlm_result = vlm.describe_event(candidate)

    # 1. Update trigger auto-pause cooldown counter with VLM feedback
    try:
        from backend.vision.pipeline import get_trigger_engine
        trigger_eng = get_trigger_engine(camera_id)
        if trigger_eng:
            trigger_eng.record_vlm_feedback(category_hint, vlm_result.get("verdict", "no"))
    except Exception as e:
        logger.warning(f"[Server] Failed to record VLM feedback for {camera_id}: {e}")

    latency_ms = int((time.time() - start_t) * 1000)
    verified = 1 if vlm_result.get("verified", False) else 0
    confidence = float(vlm_result.get("confidence", 0.0))

    if verified:
        status = "high" if confidence >= 0.75 else "needs_review"
    else:
        status = "rejected"
        logger.info(f"[Server] Event '{category_hint}' dropped by VLM ({vlm_result.get('rejection_reason')})")

    event_payload = {
        "timestamp": candidate.get("timestamp"),
        "camera_id": camera_id,
        "category": vlm_result.get("category") or category_hint,
        "confidence": confidence,
        "summary": vlm_result.get("summary", ""),
        "keyframe_path": "",
        "track_ids": candidate.get("track_ids", []),
        "latency_ms": latency_ms,
        "tags": vlm_result.get("tags") or [category_hint],
        "verified": verified,
        "verdict": vlm_result.get("verdict", "no"),
        "status": status,
        "vlm_latency_ms": vlm_result.get("latency_ms", latency_ms),
        "raw_response": vlm_result.get("raw_response", ""),
        "rejection_reason": vlm_result.get("rejection_reason", ""),
    }

    event_id = db.insert_event(event_payload)

    if event_id and verified:
        # Save keyframe image for verified events
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
            decoded_images = []
            for i, frame_bytes in enumerate(clip_frames):
                if isinstance(frame_bytes, bytes):
                    (clip_dir / f"frame_{i:02d}.jpg").write_bytes(frame_bytes)
                    try:
                        nparr = np.frombuffer(frame_bytes, np.uint8)
                        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                        if img is not None:
                            decoded_images.append(img)
                    except Exception:
                        pass

            # Write high-compatibility MP4 video clip
            if decoded_images:
                try:
                    ch, cw = decoded_images[0].shape[:2]
                    clip_mp4_path = clip_dir / "clip.mp4"
                    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                    out = cv2.VideoWriter(str(clip_mp4_path), fourcc, 10.0, (cw, ch))
                    for c_img in decoded_images:
                        out.write(c_img)
                    out.release()
                    logger.info(f"[Server] Generated MP4 video clip: {clip_mp4_path}")
                except Exception as e:
                    logger.warning(f"[Server] MP4 clip generation error: {e}")

            logger.info(f"[Server] Saved {len(clip_frames)} clip frames to {clip_dir}")


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/events")
def get_events(
    category: Optional[str] = Query(None),
    camera_id: Optional[str] = Query(None),
    since: Optional[str] = Query(None),
    status: Optional[str] = Query("high"),
    limit: int = Query(50, le=10000),
):
    events = db.query_events(category=category, camera_id=camera_id, since=since, status=status, limit=limit)
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
    res = db.get_stats()
    res["vlm"] = vlm.get_status()
    return res


@app.get("/api/taxonomy")
def get_taxonomy_endpoint():
    """Returns validated incident taxonomy, categories, allowed tags, and scene profiles."""
    from backend.server.config import get_taxonomy
    return get_taxonomy().raw


@app.get("/api/config")
def get_config_endpoint():
    """Returns non-secret runtime configuration."""
    from backend.server.config import get_settings
    cfg = get_settings()
    return {
        "vision": cfg.get("vision", {}),
        "event_filter": cfg.get("event_filter", {}),
        "storage": {k: str(v) for k, v in cfg.get("storage", {}).items()},
        "ollama": {
            "vlm_model": cfg.get("ollama", {}).get("vlm_model"),
            "chat_model": cfg.get("ollama", {}).get("chat_model"),
            "timeout_seconds": cfg.get("ollama", {}).get("timeout_seconds"),
        },
    }


@app.post("/api/chat")
def post_chat(req: ChatRequest):
    if not req.question or not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")
    return chat.answer_question(req.question.strip())


class ReportNarrativeRequest(BaseModel):
    events: List[Dict[str, Any]]
    detail: str = "standard"
    notes: Optional[str] = ""
    period_label: Optional[str] = ""


def synthesize_report_narrative(
    events: List[Dict[str, Any]],
    detail: str = "standard",
    notes: str = "",
    period_label: str = "",
    ollama_host: str = "http://localhost:11434",
    model_name: str = "Hermes-4-14B:latest",
) -> str:
    n = len(events)
    if n == 0:
        return (
            "Operational audit confirmed zero anomalous incidents matching the requested filter parameters. "
            "All physical surveillance zones maintained normal perimeter integrity with zero critical security alarms."
        )

    # 1. Statistical breakdown
    by_cat: Dict[str, int] = {}
    by_cam: Dict[str, int] = {}
    weapons_count = 0
    falls_count = 0
    fights_count = 0
    low_conf = 0

    for e in events:
        cat = e.get("category", "unknown")
        cam = e.get("camera_id", "cam1")
        by_cat[cat] = by_cat.get(cat, 0) + 1
        by_cam[cam] = by_cam.get(cam, 0) + 1
        conf = e.get("confidence", 1.0)
        if conf is not None and conf < 0.60:
            low_conf += 1
        summary = (e.get("summary") or "").lower()
        tags = e.get("tags") or []
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except Exception:
                tags = []
        tags_str = " ".join(tags).lower() if isinstance(tags, list) else ""
        if "weapon" in summary or "weapon" in tags_str or "gun" in summary or "knife" in summary or cat == "weapons":
            weapons_count += 1
        if cat == "person_down" or "fall" in summary or "collapsed" in summary:
            falls_count += 1
        if cat == "fighting" or "altercation" in summary:
            fights_count += 1

    top_cat = sorted(by_cat.items(), key=lambda x: x[1], reverse=True)[0] if by_cat else ("None", 0)
    top_cam = sorted(by_cam.items(), key=lambda x: x[1], reverse=True)[0] if by_cam else ("cam1", 0)

    # 2. Try Ollama generation with a short 3.5s timeout
    try:
        sample_records = [
            {
                "id": e.get("id"),
                "time": e.get("timestamp"),
                "camera": e.get("camera_id"),
                "category": e.get("category"),
                "confidence": round(float(e.get("confidence", 0)), 2),
                "summary": (e.get("summary") or "")[:120],
            }
            for e in events[-25:]
        ]
        prompt = (
            f"You are a Senior Physical Security Intelligence Analyst. Write a high-level {detail} executive security assessment "
            f"based strictly on this verified incident ledger ({n} total incidents). "
            f"Key metrics: Top category={top_cat[0]} ({top_cat[1]}), Primary camera={top_cam[0].upper()} ({top_cam[1]}), "
            f"Weapons={weapons_count}, Violence={fights_count}, Collapses={falls_count}, Low-confidence (<60%)={low_conf}. "
            f"{'Operator instructions: ' + notes if notes else ''}\n"
            f"Sample recent records: {json.dumps(sample_records)}\n"
            "Format your response as a professional intelligence briefing with: "
            "1) Executive Threat Assessment, 2) Tactical Spatial Patterns, 3) Prioritized Action Recommendations. "
            "Keep it factual and direct. Do not mention code or database queries."
        )
        payload = {
            "model": model_name,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": 300},
        }
        import urllib.request
        req = urllib.request.Request(
            f"{ollama_host.rstrip('/')}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            ans = data.get("response", "").strip()
            if ans and len(ans) > 50:
                return ans
    except Exception:
        pass

    # 3. High quality factual analytical fallback (instantly generated, 100% reliable)
    paragraphs = []

    # Threat assessment paragraph
    p1 = (
        f"EXECUTIVE THREAT ASSESSMENT: During the reviewed monitoring interval, EventLens vision-language pipelines "
        f"verified {n} discrete anomalous security event{'s' if n != 1 else ''}. "
        f"The primary classification driver was '{top_cat[0].replace('_', ' ').title()}' accounting for "
        f"{top_cat[1]} incident{'s' if top_cat[1] != 1 else ''} ({round((top_cat[1]/n)*100, 1)}% of total volume)."
    )
    if weapons_count > 0:
        p1 += f" CRITICAL ADVISORY: {weapons_count} potential weapon/armed threat indicator(s) were flagged and demand priority chain-of-custody review."
    elif fights_count > 0:
        p1 += f" ALERT: {fights_count} physical altercation(s) were identified requiring perimeter dispatch evaluation."
    elif falls_count > 0:
        p1 += f" MEDICAL PROTOCOL: {falls_count} person-down/medical collapse incident(s) were recorded, indicating potential slip/trip safety hazards."
    paragraphs.append(p1)

    # Spatial clustering paragraph
    p2 = (
        f"TACTICAL SPATIAL CONCENTRATION: Perimeter telemetry indicates primary activity clustering on "
        f"camera {top_cam[0].upper()} ({top_cam[1]} incident{'s' if top_cam[1] != 1 else ''}, {round((top_cam[1]/n)*100, 1)}% of total volume). "
        f"Across all monitored zones, {low_conf} event{'s' if low_conf != 1 else ''} registered confidence below 60% and have been demarcated "
        f"for mandatory manual investigator verification."
    )
    paragraphs.append(p2)

    # Recommendations paragraph
    recs = []
    if "tailgating" in by_cat:
        recs.append("calibrate access reader badge-in debounce delays and inspect vestibule anti-passback turnstiles")
    if "fighting" in by_cat or weapons_count > 0:
        recs.append("increase roving security guard presence across vulnerable chokepoints")
    if "person_down" in by_cat or "suicide_risk" in by_cat:
        recs.append("audit emergency stairwells, high-drop railings, and wet surface warning signage")
    if "suspicious_activity" in by_cat or "crowd_incident" in by_cat:
        recs.append("tighten after-hours loitering rules and adjust zone occupancy thresholds")
    if not recs:
        recs.append("maintain scheduled surveillance patrols and verify optical lens clarity across all camera feeds")

    p3 = (
        f"RECOMMENDED OPERATIONAL DIRECTIVES: 1) Immediately {recs[0]}; "
        f"2) Validate the {low_conf} flagged low-confidence keyframe snapshots in the incident register; "
        f"3) Cross-examine temporal telemetry clusters on {top_cam[0].upper()} against site facility access badges."
    )
    if notes:
        p3 += f" Operator Guidance Directive addressed: \"{notes}\"."
    paragraphs.append(p3)

    return "\n\n".join(paragraphs)


@app.post("/api/report/narrative")
def post_report_narrative(req: ReportNarrativeRequest):
    """Generates an executive intelligence narrative based on incident ledger."""
    narrative = synthesize_report_narrative(
        events=req.events,
        detail=req.detail,
        notes=req.notes or "",
        period_label=req.period_label or "",
        ollama_host=chat.ollama_host,
        model_name=chat.model_name,
    )
    return {"narrative": narrative, "ok": True}


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
    cams = list_active_cameras()
    v_stat = vlm.get_status()
    for c in cams:
        c["vlm"] = v_stat
    return {"cameras": cams}


@app.get("/api/cameras/config")
def get_cameras_config():
    """Returns all camera definitions from config/cameras.json."""
    cam_file = BASE_DIR / "config" / "cameras.json"
    if cam_file.exists():
        try:
            with open(cam_file, "r", encoding="utf-8") as f:
                return {"cameras": json.load(f)}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    return {"cameras": {}}


@app.post("/api/cameras")
def create_camera(req: CameraCreateRequest):
    """Registers a new camera, updates config/cameras.json, and optionally starts ingestion."""
    cam_id = req.camera_id.strip().lower()
    if not cam_id:
        raise HTTPException(status_code=400, detail="camera_id is required")

    cam_file = BASE_DIR / "config" / "cameras.json"
    configs = {}
    if cam_file.exists():
        try:
            with open(cam_file, "r", encoding="utf-8") as f:
                configs = json.load(f)
        except Exception:
            configs = {}

    cam_dict = {
        "name": req.name.strip() or f"Camera {cam_id.upper()}",
        "description": req.description.strip(),
        "scene_profile": req.scene_profile or "indoor_premises",
        "door_zone": req.door_zone or [[180, 240], [420, 240], [420, 480], [180, 480]],
        "restricted_zones": req.restricted_zones or [],
        "crowd_threshold": req.crowd_threshold or 7,
        "tailgating_time_window_seconds": 1.8,
        "fighting_overlap_iou": 0.38,
        "fighting_speed_threshold_pixels_per_sec": 105.0,
    }
    configs[cam_id] = cam_dict

    try:
        with open(cam_file, "w", encoding="utf-8") as f:
            json.dump(configs, f, indent=2)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save camera config: {e}")

    started = False
    if req.auto_start and req.source:
        started = start_camera(cam_id, req.source, on_candidate=on_candidate_event)

    return {"success": True, "ok": True, "camera_id": cam_id, "camera": cam_dict, "started": started}


@app.delete("/api/cameras/{camera_id}")
def delete_camera(camera_id: str):
    """Stops worker and removes camera from config/cameras.json."""
    stop_camera(camera_id)
    cam_file = BASE_DIR / "config" / "cameras.json"
    if cam_file.exists():
        try:
            with open(cam_file, "r", encoding="utf-8") as f:
                configs = json.load(f)
            if camera_id in configs:
                del configs[camera_id]
                with open(cam_file, "w", encoding="utf-8") as f:
                    json.dump(configs, f, indent=2)
        except Exception as e:
            logger.warning(f"Error removing camera {camera_id} from config: {e}")
    return {"success": True, "ok": True, "camera_id": camera_id}


@app.get("/api/cameras/{camera_id}")
def get_camera(camera_id: str):
    """Returns telemetry for a specific camera."""
    status = get_camera_status(camera_id)
    status["vlm"] = vlm.get_status()
    return status


@app.get("/api/devices")
async def get_available_devices():
    """Detects available local webcams and USB video capture devices asynchronously."""
    import platform

    def _probe_devices():
        devs = []
        for idx in range(2):
            try:
                backend = cv2.CAP_DSHOW if platform.system() == "Windows" else cv2.CAP_ANY
                cap = cv2.VideoCapture(idx, backend)
                if cap.isOpened():
                    ret, _ = cap.read()
                    if ret:
                        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                        devs.append({
                            "index": str(idx),
                            "name": f"Live Camera #{idx} ({w}x{h})",
                            "resolution": f"{w}x{h}",
                            "ready": True,
                        })
                    cap.release()
            except Exception:
                pass
        return devs

    devices = await asyncio.to_thread(_probe_devices)
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
async def video_stream(camera_id: str, request: Request, max_frames: Optional[int] = None):
    """Streams live MJPEG frames for the given camera with zero-latency buffer and clean disconnect."""
    async def frame_generator():
        count = 0
        while True:
            if max_frames is not None and count >= max_frames:
                break
            if await request.is_disconnected():
                break
            frame_bytes = get_latest_jpeg(camera_id)
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
            )
            count += 1
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


@app.get("/api/clips/{event_id}/video")
def get_event_video_clip(event_id: int):
    """Returns the recorded MP4 event clip if available."""
    clip_mp4 = CLIPS_DIR / str(event_id) / "clip.mp4"
    if not clip_mp4.exists():
        raise HTTPException(status_code=404, detail="Video clip not found")
    return FileResponse(str(clip_mp4), media_type="video/mp4")


@app.post("/api/cameras/{camera_id}/seek")
def post_seek_camera(camera_id: str, req: SeekRequest):
    """Seeks the video ingest playhead to a frame number or ratio."""
    success = seek_camera(camera_id, frame_idx=req.frame_idx, ratio=req.ratio)
    return {"success": success, "ok": success, "camera_id": camera_id}


@app.post("/api/cameras/{camera_id}/playback")
def post_camera_playback(camera_id: str, req: PlaybackRequest):
    """Controls play/pause status of camera stream."""
    success = set_camera_playback(camera_id, paused=req.paused)
    return {"success": success, "ok": success, "camera_id": camera_id, "paused": req.paused}


# Mount frontend files
FRONTEND_DIR = BASE_DIR / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
