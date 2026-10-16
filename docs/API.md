# EventLens REST API Specification

Frozen API Contract (AGENTS.md Section 8) and extended production endpoints implemented in `backend/server/main.py`.

## Base URL
`http://localhost:8000`

---

### 1. Health Check
* **Endpoint**: `GET /api/health`
* **Response**:
```json
{
  "ok": true
}
```

---

### 2. List Events
* **Endpoint**: `GET /api/events`
* **Query Parameters**:
  * `category` *(optional, string)*: Filter by category (`tailgating`, `person_down`, `fighting`, `crowd_incident`, `suspicious_activity`, `suicide_risk`)
  * `camera_id` *(optional, string)*: Filter by camera identifier (`cam1`, `cam2`)
  * `since` *(optional, ISO 8601 string)*: Only return events on or after this timestamp
  * `limit` *(optional, integer, default: 50, max: 100)*: Maximum events to return
* **Response**:
```json
{
  "events": [
    {
      "id": 1,
      "timestamp": "2026-10-16T09:14:22",
      "camera_id": "cam1",
      "category": "tailgating",
      "confidence": 0.88,
      "summary": "Two individuals entered through turnstile A in rapid succession (0.8s apart) on a single badge swipe.",
      "keyframe_url": "/frames/1.jpg",
      "track_ids": [101, 102],
      "latency_ms": 380
    }
  ]
}
```

---

### 3. Get Single Event
* **Endpoint**: `GET /api/events/{id}`
* **Response**: Single event object matching the item schema above. Returns `404` if not found.

---

### 4. Delete / Clear All Events
* **Endpoint**: `DELETE /api/events`
* **Response**:
```json
{
  "success": true,
  "message": "All incident records, keyframes, and event clips cleared"
}
```

---

### 5. System Statistics & VLM Telemetry
* **Endpoint**: `GET /api/stats`
* **Response**:
```json
{
  "categories": {
    "tailgating": 2,
    "person_down": 1,
    "fighting": 1,
    "crowd_incident": 1,
    "suspicious_activity": 1,
    "suicide_risk": 0
  },
  "events_today": 6,
  "total_events": 6,
  "avg_latency_ms": 340.5,
  "vlm": {
    "is_busy": false,
    "current_hint": "",
    "camera_id": "",
    "elapsed_sec": 0.0,
    "model": "qwen3-vl:8b"
  }
}
```

---

### 6. Active Cameras Telemetry
* **Endpoint**: `GET /api/cameras`
* **Response**:
```json
{
  "cameras": [
    {
      "camera_id": "cam1",
      "is_active": true,
      "fps": 28.5,
      "processed_frames": 1412,
      "active_tracks": 2,
      "source": "data/videos/test_tailgating.mp4",
      "frame_idx": 450,
      "total_frames": 800,
      "is_paused": false,
      "pts_sec": 15.0,
      "progress_ratio": 0.562
    }
  ]
}
```

---

### 7. Get All Cameras Configuration Schema
* **Endpoint**: `GET /api/cameras/config`
* **Response**: Full JSON dictionary loaded from `config/cameras.json`.

---

### 8. Create / Register Surveillance Camera
* **Endpoint**: `POST /api/cameras`
* **Request Body**:
```json
{
  "camera_id": "cam3",
  "name": "Warehouse Loading Dock",
  "description": "Monitors freight doors and staging bay",
  "source": "rtsp://192.168.1.100:554/stream1",
  "door_zone": [[100, 200], [300, 200], [300, 400], [100, 400]],
  "restricted_zones": [],
  "hazard_zones": [],
  "crowd_threshold": 8,
  "auto_start": true
}
```
* **Response**:
```json
{
  "success": true,
  "ok": true,
  "camera_id": "cam3",
  "started": true
}
```

---

### 9. Delete Surveillance Camera
* **Endpoint**: `DELETE /api/cameras/{camera_id}`
* **Response**:
```json
{
  "success": true,
  "ok": true,
  "camera_id": "cam3"
}
```

---

### 10. Start Video Ingestion
* **Endpoint**: `POST /api/source`
* **Request Body**:
```json
{
  "camera_id": "cam1",
  "source": "data/videos/test_tailgating.mp4"
}
```
*(Accepts local video file path, RTSP stream URL, or `"0"` for live webcam).*
* **Response**:
```json
{
  "success": true,
  "camera_id": "cam1",
  "source": "data/videos/test_tailgating.mp4"
}
```

---

### 11. Stop Camera Worker
* **Endpoint**: `DELETE /api/source/{camera_id}`
* **Response**:
```json
{
  "success": true,
  "camera_id": "cam1"
}
```

---

### 12. NVR Video Playhead Seek
* **Endpoint**: `POST /api/cameras/{camera_id}/seek`
* **Request Body**:
```json
{
  "frame_idx": 350,
  "ratio": null
}
```
*(Specify either `frame_idx` as an absolute frame number or `ratio` between 0.0 and 1.0).*
* **Response**:
```json
{
  "success": true,
  "ok": true,
  "camera_id": "cam1"
}
```

---

### 13. NVR Video Playback Control (Play / Pause)
* **Endpoint**: `POST /api/cameras/{camera_id}/playback`
* **Request Body**:
```json
{
  "paused": true
}
```
* **Response**:
```json
{
  "success": true,
  "ok": true,
  "camera_id": "cam1",
  "paused": true
}
```

---

### 14. Live MJPEG Video Stream
* **Endpoint**: `GET /stream/{camera_id}`
* **Response**: `multipart/x-mixed-replace; boundary=frame`
* Continuous stream of real-time annotated JPEG frames containing tactical bounding boxes, track IDs, velocity vectors, and HUD overlays.
* If camera is offline or disconnected, streams an auto-generated CCTV standby test card.

---

### 15. Conversational SafeSQL Natural Language Query
* **Endpoint**: `POST /api/chat`
* **Request Body**:
```json
{
  "question": "Show all tailgating events from camera 1 today"
}
```
* **Response**:
```json
{
  "answer": "Found 1 matching event (1 tailgating). Most recent: [ID #1 on cam1 at 2026-10-16T09:14:22] \"Two individuals entered through turnstile A...\"",
  "sql": "SELECT * FROM events WHERE category = 'tailgating' AND camera_id = 'cam1' AND timestamp LIKE '2026-10-16%' ORDER BY id DESC LIMIT 50",
  "events": [
    {
      "id": 1,
      "timestamp": "2026-10-16T09:14:22",
      "camera_id": "cam1",
      "category": "tailgating",
      "confidence": 0.88,
      "summary": "Two individuals entered through turnstile A in rapid succession...",
      "keyframe_url": "/frames/1.jpg",
      "track_ids": [101, 102],
      "latency_ms": 380
    }
  ]
}
```

---

### 16. Multi-Frame Temporal Clip Frames
* **Endpoint**: `GET /api/clips/{event_id}`
* **Response**:
```json
{
  "event_id": 42,
  "frames": [
    "/clips/42/frame_00.jpg",
    "/clips/42/frame_01.jpg",
    "/clips/42/frame_02.jpg",
    "/clips/42/frame_03.jpg"
  ],
  "count": 4
}
```

---

### 17. Stream / Download Recorded MP4 Video Clip
* **Endpoint**: `GET /api/clips/{event_id}/video`
* **Response**: `video/mp4` file response streaming the compiled incident video.

---

### 18. Probe Available Local Webcams / Devices
* **Endpoint**: `GET /api/devices`
* **Response**:
```json
{
  "devices": [
    {
      "index": "0",
      "name": "Live Camera #0 (640x480)",
      "resolution": "640x480",
      "ready": true
    }
  ]
}
```

---

### 19. Discovered Dataset Test Videos
* **Endpoint**: `GET /api/dataset-videos`
* **Response**:
```json
{
  "videos": [
    {
      "name": "1.mp4",
      "path": "D:/ClaudeCode/HackHive/dataset/1.mp4",
      "size_mb": 4.12,
      "directory": "dataset"
    }
  ]
}
```
