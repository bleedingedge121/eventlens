# EventLens REST API Specification

Frozen API Contract (AGENTS.md Section 8) implemented in `backend/server/main.py`.

## Base URL
`http://localhost:8000`

---

### 1. Health Check
- **Endpoint**: `GET /api/health`
- **Response**:
```json
{
  "ok": true
}
```

---

### 2. List Events
- **Endpoint**: `GET /api/events`
- **Query Parameters**:
  - `category` (optional, string): Filter by category (`tailgating`, `person_down`, `fighting`, `crowd_incident`, `suspicious_activity`)
  - `camera_id` (optional, string): Filter by camera identifier (`cam1`, `cam2`)
  - `since` (optional, ISO 8601 string): Only return events on or after this timestamp
  - `limit` (optional, integer, default: 50, max: 100): Maximum events to return
- **Response**:
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
- **Endpoint**: `GET /api/events/{id}`
- **Response**: Single event object matching the item schema above. Returns `404` if not found.

---

### 4. System Statistics
- **Endpoint**: `GET /api/stats`
- **Response**:
```json
{
  "categories": {
    "tailgating": 2,
    "person_down": 1,
    "fighting": 1,
    "crowd_incident": 1,
    "suspicious_activity": 1
  },
  "events_today": 6,
  "total_events": 6,
  "avg_latency_ms": 411.7
}
```

---

### 5. Start Video Source
- **Endpoint**: `POST /api/source`
- **Request Body**:
```json
{
  "camera_id": "cam1",
  "source": "data/videos/test.mp4"
}
```
- **Response**:
```json
{
  "success": true,
  "camera_id": "cam1",
  "source": "data/videos/test.mp4"
}
```

---

### 6. Conversational Natural Language Query
- **Endpoint**: `POST /api/chat`
- **Request Body**:
```json
{
  "question": "Show all tailgating events from camera 1 today"
}
```
- **Response**:
```json
{
  "answer": "Found 2 matching events (2 tailgating). Most recent: [ID #6 on cam1 at 2026-10-15T15:10:02] ...",
  "sql": "SELECT * FROM events WHERE category = 'tailgating' AND camera_id = 'cam1' AND timestamp LIKE '2026-10-15%' ORDER BY id DESC LIMIT 50",
  "events": [...]
}
```

---

### 7. Live MJPEG Video Stream
- **Endpoint**: `GET /stream/{camera_id}`
- **Response**: Continuous `multipart/x-mixed-replace; boundary=frame` stream of annotated JPEG frames.
