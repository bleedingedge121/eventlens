# EventLens User Interface & Operations Console Guide

This document describes the interface architecture, real-time telemetry, and user controls implemented in `frontend/`.

---

## 1. Operations Console Dashboard (`index.html`)

The Operations Console is designed with a dark, high-contrast Security Operations Center (SOC) aesthetic.

### Telemetry Header Bar
- **System Status Indicator**: Displays live connectivity with local GPU acceleration (`RTX 5070 Ti`).
- **Audio Alert Chime (Web Audio API)**: Toggle real-time audio alerts (`ON/OFF`). When a new incident is logged, a dual-tone frequency chime (880 Hz to 1320 Hz) sounds.
- **Navigation Links**: Quick switcher between Live Dashboard and Conversational Query Engine.

### Performance & Incident Metrics
1. **Events Today**: Cumulative count of verified incidents detected today.
2. **Avg VLM Latency**: Live millisecond measure of VLM trigger-to-summary classification (typically ~340 ms on local RTX 5070 Ti).
3. **Total Verified Events**: Total incidents across all cameras.
4. **Local Edge Stack**: GPU model and active pipelines.

### Live Camera Viewport
- **Dual Camera Switcher**: Seamlessly switch between Camera 1 (Lobby) and Camera 2 (Corridor).
- **HUD Telemetry Overlay**: Displays `REC` pulsing status, Active Camera ID, frame rate (~4 FPS target), and local timestamp.
- **Dynamic Trigger Zone Overlays**: A transparent HTML5 Canvas is layered directly on top of the video feed. It visually renders:
  - **Access Door Zone**: Cyan dashed boundary box with "DOOR ZONE" label.
  - **Restricted Zones**: Rose/Red boundary polygons marking unauthorized dwell areas (e.g. "SERVER CORRIDOR", "EMERGENCY STAIRWELL").
  - **Toggle Control**: "Zones: VISIBLE/HIDDEN" toggle button.
- **Snapshot Capture**: Instant frame snapshot downloaded directly to your local machine as a JPG file.
- **Fullscreen Mode**: Maximizes the video stream for dedicated monitoring displays.
- **Stream Ingestion Bar**: Allows pointing to webcam (`0`), video files (`data/videos/test.mp4`), or RTSP URLs.

### Incident Feed & Multi-Category Filtering
- **Category Filter Pills**: Fast filtering by event category with real-time incident counters:
  - `All`
  - `Tailgating` (Consecutive turnstile crossing < 1.5s)
  - `Person Down` (Aspect ratio shift & prolonged stillness)
  - `Fighting` (Bounding box overlap with violent kinetic velocity)
  - `Crowd` (Regional occupancy exceeding threshold)
  - `Suspicious` (Dwell time in restricted corridors)
- **Live Search**: Instant keyword search filtering by summary text, camera, track IDs, or incident IDs.
- **Color-Coded Severity Bars**:
  - 🔴 **Critical Severity** (Rose border): `person_down`, `fighting`
  - 🟡 **Warning Severity** (Amber border): `tailgating`, `crowd_incident`
  - 🔵 **Notice Severity** (Cyan border): `suspicious_activity`

### Incident Keyframe Inspector Modal
Clicking any incident opens a high-resolution inspector:
- Zoomed keyframe capture.
- Full natural language VLM summary.
- VLM confidence percentage and exact latency in milliseconds.
- Bounding-box tracked individual IDs (e.g. `Track ID #101`).
- **Copy Event JSON**: Copies raw JSON to clipboard for reporting.
- **Query AI about this Event**: Deep-links directly to `chat.html` with pre-filled natural language prompt.

---

## 2. Conversational Query Interface (`chat.html`)

The conversational engine provides natural-language querying over all surveillance incidents.

### Key Capabilities
- **Quick Preset Chips**: One-click suggested questions (`Show all tailgating events today`, `Did anyone fall down on camera 2?`, etc.).
- **Audit Transparency**: Displays the executed read-only SQLite statement with a one-click **Copy SQL** button.
- **Incident Cards Grid**: Displays matching events with timestamp, confidence, camera tag, and keyframe thumbnail.
- **URL Query Pre-Filling**: Accepts `chat.html?q=...` to automatically execute queries initiated from the dashboard.
