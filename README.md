# EventLens 👁️⚡

> **Open-Source AI System for Live Video Event Summarization, Classification, and Conversational Querying**  
> *Developed for HackHive 2026 (MIT Bengaluru with Honeywell) — Problem Statement 3*

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg)](pyproject.toml)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](backend/server/main.py)
[![Ultralytics YOLO](https://img.shields.io/badge/YOLO-v11-00FFFF.svg)](backend/vision/detect_track.py)
[![Ollama](https://img.shields.io/badge/Ollama-Offline%20Inference-white.svg)](backend/server/vlm.py)
[![Target GPU](https://img.shields.io/badge/GPU-RTX%205070%20Ti%20(12GB)-76B900.svg)](scripts/check_env.py)

---

## 🎯 Executive Summary

Modern CCTV surveillance systems record petabytes of passive footage, yet critical physical security breaches (tailgating through turnstiles, slip-and-fall incidents, physical altercations, restricted area loitering, and crowd surges) are rarely identified until after damage or injury occurs. Cloud-based video intelligence APIs introduce unacceptable network latency, continuous per-minute cloud billing, and serious corporate privacy violations.

**EventLens** delivers an edge-native, 100% open-source intelligence pipeline running on a single laptop (Lenovo Legion with RTX 5070 Ti, 12 GB VRAM):
1. **Continuous Lightweight Ingestion**: Ingests video at 3–5 FPS with YOLOv11 + ByteTrack to detect and track human targets in real-time with negligible compute overhead.
2. **Deterministic Geometric Rule Triggers**: Real-time bounding box geometry, aspect-ratio inversion, velocity vectors, and zone polygons trigger anomaly candidates *without* continuous vision-language calls.
3. **Selective Local VLM Verification**: Only triggered anomaly candidate frames are dispatched to a local Ollama Vision-Language Model (Qwen2.5-VL / Gemma 3) for multi-sentence summarization and category confirmation.
4. **Conversational SafeSQL Auditing**: Security officers query recorded events in plain English ("*Show all tailgating events from camera 1 today*"). A local LLM compiles the query into single, read-only `SELECT` statements strictly audited against SQLite.
5. **Industrial SOC Console**: Zero-framework, dark command-center interface with HUD overlays, live zones, keyboard shortcuts, and full audit transparency.

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
           ▼ (Zero-VLM Geometry & Velocity Rules)
 Rule-Based Anomaly Trigger Engine (backend/vision/triggers.py)
    ├── Tailgating (Consecutive door crossing < 2.0s)
    ├── Person Down (Aspect ratio width/height > 1.15 + still for N s)
    ├── Crowd Incident (Regional occupancy > threshold)
    ├── Suspicious Activity (Restricted zone loitering > N s)
    └── Fighting (Bounding box IoU overlap + erratic velocity)
           │
           ├───► MJPEG Streaming Hub (HUD Annotated Stream: /stream/{camera_id})
           │
           ▼ (Triggered Anomaly Moments ONLY)
 Local Ollama VLM (backend/server/vlm.py)
           │
           ▼ (Defensive JSON Validation & False Alarm Filtering)
 SQLite Storage (data/events.db + Keyframe Storage data/frames/)
           │
    ┌──────┴───────────────────────────────────┐
    ▼                                          ▼
Security Operations Console            Conversational AI Query
(http://localhost:8000)                (http://localhost:8000/chat.html)
```

---

## ⚡ Key Technical Highlights

* **Zero Cloud Dependence**: 100% offline inference. No audio, video, or event telemetry ever leaves the local machine.
* **Selective VLM Invocation**: Rather than exhausting VRAM processing 30 FPS with a slow multimodal model, continuous tracking is handled by YOLOv11 (`~4ms`), reserving the VLM solely for triggered moments (`~340ms` median latency).
* **Safe Read-Only SQL Engine**: Natural language questions are converted into validated SQLite `SELECT` queries with statement single-statement enforcement, token blacklisting (`DROP`, `DELETE`, `UPDATE`), and read-only database connections.
* **Production-Grade Developer Experience**: One-command runner for both Windows PowerShell (`run.ps1`) and POSIX Bash (`run.sh`), with automated database seeding, health diagnostics, and Docker Compose fallbacks.

---

## 🚀 One-Command Quickstart

### On Windows (PowerShell)

```powershell
# Run the entire application natively:
.\run.ps1
```

*Want to run specific tasks?*
```powershell
.\run.ps1 -Mode seed    # Reset and seed database with 12 benchmark demo incidents
.\run.ps1 -Mode check   # Run GPU and environment pre-flight diagnostics
.\run.ps1 -Mode docker  # Launch full stack via Docker Compose with NVIDIA GPU passthrough
```

### On Linux / macOS / WSL (Bash)

```bash
# Make executable and run:
chmod +x run.sh
./run.sh
```

---

## 🌐 Web Interfaces

Once started, open your browser to:

| Interface | URL | Purpose |
|---|---|---|
| **Security Console** | [http://localhost:8000](http://localhost:8000) | Live video viewport, detection zones, telemetry HUD, incident feed |
| **Conversational Query** | [http://localhost:8000/chat.html](http://localhost:8000/chat.html) | Natural language dialogue, SafeSQL inspector, benchmark presets |
| **Interactive API Docs** | [http://localhost:8000/docs](http://localhost:8000/docs) | Swagger / OpenAPI documentation for all frozen endpoints |

---

## ⌨️ Console Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| <kbd>/</kbd> | Instantly focus incident search filter / chat input |
| <kbd>Z</kbd> | Toggle detection zone perimeter overlays on/off |
| <kbd>M</kbd> | Toggle synthesized Web Audio alert chimes (Mute / Unmute) |
| <kbd>1</kbd> / <kbd>2</kbd> | Switch between Camera 1 (Turnstiles) and Camera 2 (Corridor) |
| <kbd>F</kbd> | Toggle video viewport fullscreen mode |
| <kbd>Esc</kbd> | Dismiss incident inspection modal |

---

## 📡 Frozen API Specification

Adheres strictly to HackHive Section 8 frozen API contracts:

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Returns server health status (`{"ok": true}`) |
| `GET` | `/api/events` | Queries incident ledger with optional `category`, `camera_id`, `since`, `limit` |
| `GET` | `/api/events/{id}` | Fetches detailed record and keyframe for a single event |
| `GET` | `/api/stats` | Aggregated telemetry (counts by category, average latency, total today) |
| `GET` | `/stream/{camera_id}` | Live annotated MJPEG video stream with bounding boxes |
| `POST` | `/api/source` | Starts video ingestion (`{"camera_id": "cam1", "source": "path-or-rtsp"}`) |
| `POST` | `/api/chat` | Natural language text-to-SQL query (`{"question": "..."}` → `{"answer", "sql", "events"}`) |

---

## 📊 Evaluation & Latency Benchmark

Run the automated evaluation benchmark on the 13 test scenarios:
```powershell
python .\eval\run_eval.py
```

Benchmark results on Lenovo Legion RTX 5070 Ti (12 GB VRAM):
* **Median Latency (Trigger to DB saved)**: `338.7 ms`
* **95th Percentile (p95)**: `428.7 ms`
* **Mean Latency**: `342.8 ms`
* **Tailgating Recall**: `100.0%`
* **Person Down Recall**: `100.0%`
* **Fighting Precision (with VLM confirmation)**: `88.9%`

---

## 📄 License
This project is licensed under the [MIT License](LICENSE).
