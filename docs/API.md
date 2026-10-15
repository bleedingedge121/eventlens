# EventLens REST API Specification

Frozen API Contract (AGENTS.md Section 8) with production enhancements implemented in `backend/server/main.py`.

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
  * `category` *(optional, string)*: Filter by category (`tailgating`, `person_down`, `fighting`, `crowd_incident`, `suspicious_activity`)
  * `camera_id` *(optional, string)*: Filter by camera identifier (`cam1`, `cam2`)
  * `since` *(optional, ISO 8601 string)*: Only return events on or after this timestamp
  * `limit` *(optional, integer, default: 50, max: 100)*: Maximum events to return
* **Response**:
```json
{
  "events": [
    {
      "id": 1,
      "timestamp": "2026-10-15T09:14:22",
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
  "message": "All incident records and keyframes cleared"
}
```

---

### 5. System Statistics
* **Endpoint**: `GET /api/stats`
* **Response**:
```json
{
  "categories": {
    "tailgating": 2,
    "person_down": 1,
    "fighting": 0,
    "crowd_incident": 1,
    "suspicious_activity": 1
  },
  "events_today": 5,
  "total_events": 5,
  "avg_latency_ms": 340.5
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
      "fps": 18.2,
      "processed_frames": 412,
      "active_tracks": 1,
      "source": "data/videos/test_normal.mp4"
    }
  ]
}
```

---

### 7. Start Video Ingestion
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

### 8. Stop Camera Worker
* **Endpoint**: `DELETE /api/source/{camera_id}`
* **Response**:
```json
{
  "success": true,
  "camera_id": "cam1"
}
```

---

### 9. Live MJPEG Video Stream
* **Endpoint**: `GET /stream/{camera_id}`
* **Response**: `multipart/x-mixed-replace; boundary=frame`
* Stream of real-time annotated JPEG frames containing tactical bounding boxes, track IDs, and HUD telemetry.
* If a camera is offline or disconnected, streams an auto-generated standby CCTV test card.

---

### 10. Conversational SafeSQL Natural Language Query
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
  "answer": "Found 1 matching event (1 tailgating). Most recent: [ID #1 on cam1 at 2026-10-15T09:14:22] \"Two individuals entered through turnstile A...\"",
  "sql": "SELECT * FROM events WHERE category = 'tailgating' AND camera_id = 'cam1' AND timestamp LIKE '2026-10-15%' ORDER BY id DESC LIMIT 50",
  "events": [
    {
      "id": 1,
      "timestamp": "2026-10-15T09:14:22",
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

### 11. Probe Available Local Webcams / Devices
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

### 12. Multi-Frame Temporal Clip Frames
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

### 13. Discovered Dataset Test Videos
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
