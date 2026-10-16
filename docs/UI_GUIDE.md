# EventLens User Interface & Operations Console Guide

This document describes the interface architecture, real-time telemetry, and user controls implemented in `frontend/`.

---

## 1. Operations Console Dashboard (`index.html`)

The Operations Console is designed with an industrial, high-contrast Security Operations Center (SOC) aesthetic.

### Telemetry Header Bar
- **System Status Indicator**: Displays live connectivity with local GPU acceleration (`RTX 5070 Ti`).
- **Audio Alert Chime (Web Audio API)**: Toggle real-time audio alerts (`ON/OFF`). When a new incident is logged, a dual-tone frequency chime (880 Hz to 1320 Hz) sounds. Shortcut: <kbd>M</kbd>.
- **Security Intelligence Report**: Click the **Report** button to generate an instant printable incident audit report.
- **Navigation Links**: Quick switcher between Live Dashboard and Conversational Query Engine.

### Performance & Incident Metrics
1. **Events Today**: Cumulative count of verified incidents detected today.
2. **Avg VLM Latency**: Live millisecond measure of VLM trigger-to-summary classification (typically ~340 ms on local RTX 5070 Ti).
3. **Verified Events**: Total incidents committed to the local SQLite audit ledger.
4. **Pipeline Engine Status**: Real-time state of YOLOv11 + ByteTrack and Ollama VLM workers.

### Live Surveillance Viewport & Multi-Camera Matrix
- **Layout Switcher**:
  - **1x1 Focus View**: High-detail monitoring of the selected active camera.
  - **Grid View (2x2)**: Simultaneous multi-stream monitoring matrix displaying all registered cameras.
- **Dynamic Camera CRUD**:
  - **+ Cam**: Opens camera registration modal to add RTSP streams, webcams, or video files with custom zone geometries.
  - **Del**: Gracefully stops the active camera worker and unregisters it from `config/cameras.json`.
- **Live Webcam Quick-Connect**: Connects USB/integrated webcam (`Device 0`) in one click.
- **HUD Telemetry Overlay**: Displays `REC` pulsing status, Active Camera ID, frame rate, clock, and live AI scanning indicator.
- **Dynamic Trigger Zone Overlays**: A transparent HTML5 Canvas layered directly on the video feed rendering:
  - **Access Door Zone**: Cyan dashed boundary box with "DOOR ZONE" label.
  - **Restricted Zones**: Amber/Rose boundary polygons marking loitering areas.
  - **Hazard Zones**: Red hazard boundary polygons marking fall/suicide risk zones.
  - **Toggle Control**: Toggle on/off via button or keyboard shortcut <kbd>Z</kbd>.
- **Snapshot Capture**: Instant frame snapshot downloaded directly to your local machine as a JPG file.
- **Fullscreen Mode**: Maximizes the video stream for dedicated monitoring displays (<kbd>F</kbd>).

### Interactive NVR Video Scrubber Toolbar
Located immediately below the video viewport:
- **Playback Controls**:
  - **Step Back**: Steps back 10 frames in video recording (<kbd>←</kbd>).
  - **Play / Pause**: Freezes or resumes stream ingestion (<kbd>Space</kbd>).
  - **Step Forward**: Steps forward 10 frames in video recording (<kbd>→</kbd>).
  - **LIVE Button**: Snaps the playhead directly to the live stream head.
- **Seek Slider & Incident Markers**:
  - Continuous slider seeking through the recording buffer.
  - Anomaly markers along the seek bar indicating exact moments where verified incidents occurred.
- **Telemetry Indicators**: Real-time microsecond PTS display (`PTS: HH:MM:SS`) and frame index counter (`FRM: #00000`).

### Incident Feed & Multi-Category Filtering
- **Category Filter Pills**: Fast filtering by event category with real-time counters:
  - `All`
  - `Tailgating` (Consecutive turnstile crossing < 1.8s)
  - `Person Down` (Aspect ratio shift & height collapse)
  - `Fighting` (Bounding box overlap with rapid kinetic velocity)
  - `Crowd` (Regional occupancy exceeding threshold)
  - `Suspicious` (Dwell time in restricted corridors)
  - `Suicide / Fall` (Presence in ledge/railing hazard zones)
- **Confidence Filter Dropdown**: Threshold events by minimum confidence (`All 0%+`, `Verified 50%+`, `High Conf 70%+`, `Critical 85%+`).
- **Live Search**: Instant keyword search filtering by summary text, camera, track IDs, or incident IDs (<kbd>/</kbd>).
- **Clear All**: One-click purge of all database incidents, keyframe stills, and video clips.

### Incident Details & Clip Inspection Modal
Clicking any incident opens a high-resolution inspection modal:
- **Zoomed Keyframe View**: Primary still image analyzed by the vision model.
- **Integrated MP4 Video Player**: Toggle to view the compiled H.264 video clip of the incident.
- **Multi-Frame Temporal Scrubber**: Frame-by-frame navigation buttons (`◀ Prev`, `▶ Next`, `▶ Play Clip`) with contextual frame labels.
- **VLM Summary & Weapon Alert**: Full natural language explanation and weapon indicators (`[WEAPON DETECTED]` tag).
- **Audit Telemetry**: VLM confidence percentage, exact classification latency in milliseconds, and tracked individual IDs.
- **Copy Event JSON**: Copies raw JSON to clipboard for incident reporting.
- **Query AI about this Event**: Deep-links directly to `chat.html` with a pre-filled natural language prompt.

### Activity Timeline & Visual Analytics
- **Dual-Mode Timeline**:
  - **Combined View**: Temporal incident distribution across all cameras; bar height represents confidence.
  - **Multi-Track Swimlanes**: Per-camera horizontal swimlanes showing incident timelines side-by-side.
- **Distribution Charts**: Real-time breakdown of incidents by category and by camera.

---

## 2. Conversational Query Interface (`chat.html`)

The conversational engine provides natural-language querying over all surveillance incidents.

### Key Capabilities
- **Quick Preset Chips**: One-click suggested questions (`Show all tailgating events today`, `Did anyone fall down on camera 2?`, `List fighting incidents with weapons`, etc.).
- **SafeSQL Transparency**: Displays the executed read-only SQLite statement with syntax highlighting and a one-click **Copy SQL** button.
- **Incident Cards Grid**: Displays matching events with timestamp, confidence, camera tag, and keyframe thumbnail. Clicking opens the inspection modal.
- **URL Query Pre-Filling**: Accepts `chat.html?q=...` to automatically execute queries initiated from the dashboard.
