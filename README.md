# EventLens 👁️⚡

> **Open-Source AI System for Live Video Event Summarization, Classification, and Conversational Querying**  
> *Developed for HackHive 2026 (MIT Bengaluru with Honeywell) — Problem Statement 3*

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg)](pyproject.toml)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](backend/server/main.py)
[![Ultralytics YOLO](https://img.shields.io/badge/YOLO-v11-00FFFF.svg)](backend/vision/detect_track.py)
[![Ollama](https://img.shields.io/badge/Ollama-Offline%20Inference-white.svg)](backend/server/vlm.py)
[![Target GPU](https://img.shields.io/badge/GPU-RTX%205070%20Ti%20(12GB)-76B900.svg)](scripts/check_env.py)
[![Tests Passing](https://img.shields.io/badge/Tests-26%2F26%20Passing-success.svg)](tests/)

---

## 🎯 Executive Summary

Modern CCTV surveillance systems record petabytes of passive footage, yet critical physical security breaches (tailgating through turnstiles, slip-and-fall incidents, physical altercations, restricted area loitering, and crowd surges) are rarely identified until after damage or injury occurs. Cloud-based video intelligence APIs introduce unacceptable network latency, continuous per-minute cloud billing, and serious corporate privacy violations.

**EventLens** delivers an edge-native, 100% open-source intelligence pipeline running on a single laptop (Lenovo Legion with RTX 5070 Ti, 12 GB VRAM):
1. **Continuous Lightweight Ingestion**: Ingests video at 3–5 FPS with YOLOv11 + ByteTrack to detect and track human targets in real-time with negligible compute overhead.
2. **Deterministic Geometric Rule Triggers**: Real-time bounding box geometry, aspect-ratio inversion, velocity vectors, and zone polygons trigger anomaly candidates *without* continuous vision-language calls.
3. **Selective Local VLM Verification**: Only triggered anomaly candidate frames are dispatched to a local Ollama Vision-Language Model (`qwen3-vl:8b` / `qwen2.5-vl` / `gemma3`) for multi-sentence summarization, weapon recognition, and category confirmation.
4. **16x VLM Acceleration**: GPU VRAM model pinning (`keep_alive: -1`), bounded KV cache (`num_ctx: 2048`), 320px patch dimension downscaling, and non-blocking inference lock deliver sub-350ms median event classification.
5. **Surveillance NVR Suite & Video Scrubber**: Full NVR playhead scrubber with exact frame index and microsecond PTS tracking, play/pause controls, step forward/backward buttons, and interactive anomaly seek markers.
6. **Multi-Camera Matrix Grid**: Real-time 1x1 single-camera focus and 2x2 multi-camera live grid with dynamic camera CRUD management.
7. **Clip Sequence Storage & Video Player**: Anomaly moments save both keyframe stills and multi-frame temporal sequences (`/clips/{id}`) compiled into playable MP4 video clips.
8. **Conversational SafeSQL Auditing**: Security officers query recorded events in plain English ("*Show all tailgating events from camera 1 today*"). A local LLM compiles the query into single, read-only `SELECT` statements strictly audited against SQLite.
9. **Industrial SOC Console**: Zero-framework, dark command-center interface with HUD overlays, live zones, confidence selectors, keyboard shortcuts, automated report generation, and full audit transparency.

---

## 📐 System Architecture

```
Live Stream / RTSP / Video Source
           │
           ▼ (3–5 FPS Sampling)
   Ingest & Frame Buffer (backend/vision/ingest.py)
           │
           ▼
 YOLOv11 + ByteTrack (Person Class IDs & Trajectories)
           │
           ▼ (Zero-VLM Geometry & Velocity Rules: <1ms)
 Rule-Based Anomaly Trigger Engine (backend/vision/triggers.py)
    ├── Tailgating (Consecutive door crossing < 1.8s)
    ├── Person Down (Aspect ratio w/h > 0.70 OR height collapse + stillness)
    ├── Crowd Incident (Regional occupancy >= threshold)
    ├── Suspicious Activity (Restricted zone loitering > N s)
    ├── Fighting (Bounding box IoU overlap + erratic velocity)
    └── Suicide / Fall Risk (Hazard ledge / railing dwell > 2.5s)
           │
           ├───► MJPEG Streaming Hub (HUD Annotated Stream: /stream/{camera_id})
           │
           ▼ (Triggered Anomaly Moments ONLY)
 Local Ollama VLM (backend/server/vlm.py)
    ├── VRAM Pinned (keep_alive: -1)
    ├── 320px Patch Downscaling (4x compute reduction)
    ├── KV Cache Constrained (num_ctx: 2048)
    └── Defensive Semantic Fallback Parser
           │
           ▼ (Defensive JSON Validation & False Alarm Filtering)
 SQLite Storage (data/events.db) + Evidence (data/frames/ & data/clips/)
           │
    ┌──────┴───────────────────────────────────┐
    ▼                                          ▼
Security Operations Console            Conversational AI Query
(http://localhost:8000)                (http://localhost:8000/chat.html)
```

---

## ⚡ Technical Breakdown: How It Is Done

| Subsystem | Underlying Technology | Engineering Implementation |
|---|---|---|
| **Video Ingestion** | OpenCV + Custom Worker Thread | Paced frame capture supporting webcam (DirectShow), RTSP, and local MP4/MKV files; maintains Presentation Time Stamp (PTS) and frame index buffers. |
| **Detection & Tracking** | YOLOv11n + ByteTrack | PyTorch CUDA 12.8 acceleration; filters exclusively for class 0 (`person`) to conserve VRAM; assigns persistent IDs across frames with spatial interpolation. |
| **Rule Trigger Engine** | Pure Python + NumPy | Ray-casting polygon intersection algorithm (`point_in_polygon`), bounding-box IoU matrix, and velocity vector calculation running in <1ms per frame. |
| **VLM Optimization** | Ollama REST API (`qwen3-vl:8b`) | Pinned to GPU memory (`keep_alive: -1`); 320px patch scaling; context limited to 2048; bounded threading lock (`timeout=8s`); multi-tier regex parser handling reasoning traces. |
| **SafeSQL Conversational** | Local LLM (`Hermes-4-14B` / regex) | Python-side ISO timestamp resolution; AST and token-level mutation blacklist; read-only SQLite pragma; deterministic regex template fallback. |
| **Evidence Persistence** | SQLite + OpenCV VideoWriter | `events` table indexed by timestamp/category; keyframes stored as JPEG; multi-frame burst compiled into H.264/MP4 clips at 10 FPS. |
| **Frontend Console** | Vanilla ES6+ HTML5/CSS3 | Zero build step, dark security theme, HTML5 Canvas zone overlays, Web Audio API frequency alert chimes, SVG icons, and 2-second auto-polling. |

---

## ⚠️ Known Limitations & Failure Modes (What Is Broken)

To ensure full engineering transparency and academic integrity, the following limitations are documented:

1. **Loitering Detection on Short Benchmark Videos**:
   - The suspicious activity rule requires a continuous track to dwell inside a restricted polygon for $\ge 6.0$s.
   - On short video clips (<6 seconds) or looped test clips where the video restarts, timestamps reset before reaching the dwell threshold, resulting in **0% recall on short clips**. Loitering functions correctly on continuous live streams.
2. **Fighting Rule False Alarms in Dense Crowds**:
   - The fighting heuristic triggers on bounding-box IoU ($\ge 0.38$) + centroid velocity ($\ge 105$ px/s).
   - Rapid crowd egress, high-fives, or playful shoving can trigger false positive candidate alerts. The VLM acts as an automated confirmation filter, but if the VLM is offline, the fallback confidence (0.55) may record the event.
3. **Weapon Detection is Semantic Prompting, Not Object Detection**:
   - YOLOv11 is configured only for `person` class; there is no dedicated weapon bounding-box detector.
   - Weapon detection relies on the VLM inspecting 320px downscaled keyframes. Concealed handguns or folding knives are often imperceptible at this resolution.
4. **OpenCV Video Seeking Jitter on Compressed Streams**:
   - `cv2.VideoCapture.set(cv2.CAP_PROP_POS_FRAMES)` on inter-frame compressed files (H.264/H.265) snaps to the nearest I-frame (keyframe). Fine frame seeking on variable framerate clips may jitter by 0.5–1.0s.
5. **DirectShow Multi-Device Terminal Warning on Windows**:
   - Probing unattached webcam indices (e.g. index 1) prints a harmless OpenCV stderr warning: `cv::VideoCapture::open VIDEOIO(DSHOW)...`. While caught by exception handlers, it appears in terminal logs.
6. **Multi-Camera Concurrent Compute Overhead**:
   - Running 3+ concurrent camera pipelines while simultaneously triggering an 8B VLM causes GPU memory contention and drops stream frame rate from 30 FPS to 12–15 FPS during VLM forward passes on a 12 GB VRAM card.

For full technical analysis, see the [Comprehensive System Report](docs/SYSTEM_REPORT.md).

---

## 🚀 One-Command Quickstart

### On Windows (PowerShell)

```powershell
# Run the entire application natively:
.\run.ps1
```

*Task-specific commands:*
```powershell
.\run.ps1 -Mode seed    # Reset and seed database with 12 benchmark demo incidents
.\run.ps1 -Mode check   # Run GPU and environment pre-flight diagnostics
.\run.ps1 -Mode clean   # Wipe recorded events, keyframes, and clips cleanly
.\run.ps1 -Mode docker  # Launch full stack via Docker Compose with NVIDIA GPU passthrough
```

### On Linux / macOS / WSL (Bash)

```bash
chmod +x run.sh
./run.sh
```

---

## 🌐 Web Interfaces

Once started, open your browser to:

| Interface | URL | Purpose |
|---|---|---|
| **Security Console** | [http://localhost:8000](http://localhost:8000) | Live video viewport, detection zones, telemetry HUD, NVR scrubber, incident feed |
| **Conversational Query** | [http://localhost:8000/chat.html](http://localhost:8000/chat.html) | Natural language dialogue, SafeSQL inspector, benchmark presets |
| **Interactive API Docs** | [http://localhost:8000/docs](http://localhost:8000/docs) | Swagger / OpenAPI documentation for all frozen and extended endpoints |

---

## ⌨️ Console Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| <kbd>/</kbd> | Instantly focus incident search filter / chat input |
| <kbd>Z</kbd> | Toggle detection zone perimeter overlays on/off |
| <kbd>M</kbd> | Toggle synthesized Web Audio alert chimes (Mute / Unmute) |
| <kbd>Space</kbd> | Pause / Resume live camera feed in NVR scrubber |
| <kbd>←</kbd> / <kbd>→</kbd> | Step back / forward 10 frames in video recording |
| <kbd>1</kbd> / <kbd>2</kbd> | Switch between Camera 1 (Turnstiles) and Camera 2 (Corridor) |
| <kbd>F</kbd> | Toggle video viewport fullscreen mode |
| <kbd>Esc</kbd> | Dismiss incident inspection modal |

---

## 📡 REST API Specification

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Returns server health status (`{"ok": true}`) |
| `GET` | `/api/events` | Queries incident ledger with optional `category`, `camera_id`, `since`, `limit` |
| `GET` | `/api/events/{id}` | Fetches detailed record and keyframe path for a single event |
| `DELETE` | `/api/events` | Wipes all event records, keyframes, and clips |
| `GET` | `/api/clips/{id}` | Fetches ordered multi-frame temporal image sequence filenames |
| `GET` | `/api/clips/{id}/video` | Streams/downloads recorded MP4 video event clip |
| `GET` | `/api/stats` | Aggregated telemetry (counts by category, average latency, total today, VLM status) |
| `GET` | `/api/cameras` | Lists active camera workers with real-time FPS and PTS telemetry |
| `GET` | `/api/cameras/config` | Reads entire camera zone configuration schema from `config/cameras.json` |
| `POST` | `/api/cameras` | Dynamic camera creation / registration (CRUD) |
| `DELETE` | `/api/cameras/{id}` | Stops camera worker and removes definition from `cameras.json` |
| `GET` | `/api/cameras/{id}` | Returns telemetry and VLM activity for specific camera |
| `POST` | `/api/cameras/{id}/seek` | Seeks camera playhead by frame index or relative ratio |
| `POST` | `/api/cameras/{id}/playback` | Toggles play / pause state on camera ingest stream |
| `GET` | `/api/devices` | Discovers plugged USB/integrated webcams with real hardware test verification |
| `GET` | `/api/dataset-videos` | Lists available offline evaluation & benchmark video datasets |
| `GET` | `/stream/{camera_id}` | Live annotated MJPEG video stream with bounding boxes and HUD |
| `POST` | `/api/source` | Starts video ingestion (`{"camera_id": "cam1", "source": "path-or-rtsp"}`) |
| `DELETE` | `/api/source/{camera_id}` | Stops camera worker thread |
| `POST` | `/api/chat` | Natural language text-to-SQL query (`{"question": "..."}` → `{"answer", "sql", "events"}`) |

---

## 📊 Evaluation & Latency Benchmark

Run the automated evaluation benchmark on the 13 test scenarios:
```powershell
python .\eval\run_eval.py
```

Benchmark results on Lenovo Legion RTX 5070 Ti (12 GB VRAM):
* **Median Latency (Trigger to DB saved)**: `338.7 ms`
* **95th Percentile (p95)**: `419.9 ms`
* **Mean Latency**: `345.6 ms`
* **Tailgating Recall**: `66.7%` (Precision: `100.0%`)
* **Person Down Recall**: `100.0%` (Precision: `100.0%`)
* **Fighting Precision (with VLM confirmation)**: `75.0%` (Recall: `75.0%`)
* **Crowd Incident Recall**: `100.0%` (Precision: `66.7%`)
* **Unit Test Suite**: 26 / 26 passing (`python -m unittest discover tests`)

---

## 📄 License
This project is licensed under the [MIT License](LICENSE).
