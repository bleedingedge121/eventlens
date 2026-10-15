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

Modern CCTV surveillance records petabytes of passive footage, yet anomalous security breaches (tailgating through access control, slips/falls, altercations, unauthorized loitering, and crowd surges) are rarely identified until after damage occurs. Cloud vision APIs introduce latency, recurring bandwidth costs, and severe privacy violations.

**EventLens** solves this with an edge-native, 100% open-source architecture that runs on a single consumer laptop (Lenovo Legion with RTX 5070 Ti, 12 GB VRAM). It continuously tracks individuals using YOLOv11 + ByteTrack, selectively invokes a local Vision-Language Model (VLM) via Ollama upon geometric rule triggers, logs verified events into SQLite, and provides a natural-language conversational interface powered by safe text-to-read-only-SQL.

---

## 📐 System Architecture

```
Live Stream / RTSP / Video
           │
           ▼ (3-5 FPS Sampling)
   Ingest & Frame Buffer
           │
           ▼
 YOLOv11 + ByteTrack (Person Class IDs)
           │
           ▼ (Zero-VLM Geometry & Velocity Rules)
 Rule-Based Anomaly Trigger Engine
    ├── Tailgating (Consecutive door crossing < 2.0s)
    ├── Person Down (Aspect ratio width/height > 1.15)
    ├── Crowd Incident (Regional occupancy > threshold)
    ├── Suspicious Activity (Restricted zone loitering)
    └── Fighting (Bounding box IoU overlap + erratic velocity)
           │
           ├───► MJPEG Streaming Hub (HUD Annotated Stream)
           │
           ▼ (Only on Triggered Moments)
 Local Ollama VLM (Qwen2.5-VL / Gemma 3 / Hermes)
           │
           ▼ (Defensive JSON Validation)
 SQLite Storage (data/events.db + Keyframe Storage)
           │
    ┌──────┴──────────────────────────┐
    ▼                                 ▼
Operations Console           Conversational Chat
(index.html / dashboard.js)  (Natural Language -> Safe SQL)
```

---

## ⚡ Key Technical Innovations

1. **Selective VLM Invocation**: Rather than exhausting VRAM by streaming all 30 FPS into an LLM, EventLens runs lightweight YOLOv11 tracking continuously. The slow VLM runs **only** during triggered anomaly moments (~340ms median latency).
2. **Defensive Prompting & Safe SQL**: Conversational queries are translated into strictly audited `SELECT` statements on the `events` table with token blacklisting, single-statement enforcement, and read-only database connections.
3. **100% Offline Privacy Guarantee**: All inference runs locally on the machine. No audio, visual, or metadata ever leaves the device.

---

## 🚀 Quickstart Guide (PowerShell)

### 1. Clone & Set Up Virtual Environment
```powershell
git clone https://github.com/bleedingedge121/eventlens.git
cd eventlens

# Run automated PowerShell environment bootstrap:
.\scripts\setup.ps1
```

### 2. Pull Required Models (via local Ollama)
```powershell
ollama pull qwen2.5-vl:7b
ollama pull Hermes-4-14B:latest
```

### 3. Verify Environment
```powershell
python .\scripts\check_env.py
```

### 4. Seed Database with Initial Mock Events
```powershell
python .\scripts\seed_demo_db.py
```

### 5. Launch the Server
```powershell
uvicorn backend.server.main:app --host 0.0.0.0 --port 8000
```

Access the interfaces:
- **Operations Console**: [http://localhost:8000/index.html](http://localhost:8000/index.html)
- **Conversational Querying**: [http://localhost:8000/chat.html](http://localhost:8000/chat.html)

---

## 📡 API Contract (Frozen)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Returns system health (`{"ok": true}`) |
| `GET` | `/api/events` | Filters events by `category`, `camera_id`, `since`, `limit` |
| `GET` | `/api/events/{id}` | Returns a single event by ID |
| `GET` | `/api/stats` | Aggregated metrics (counts by category, average latency, today's total) |
| `GET` | `/stream/{camera_id}` | Live annotated MJPEG video stream |
| `POST` | `/api/source` | Starts ingestion for a camera (`{"camera_id": "cam1", "source": "path"}`) |
| `POST` | `/api/chat` | Conversational query (`{"question": "..."}` -> `{"answer", "sql", "events"}`) |

---

## 📊 Evaluation & Latency Benchmark

Run the automated evaluation benchmark on the 13 test scenarios:
```powershell
python .\eval\run_eval.py
```

Benchmark results on Lenovo Legion RTX 5070 Ti:
- **Median Latency (Trigger to DB saved)**: `338.7 ms`
- **95th Percentile (p95)**: `428.7 ms`
- **Mean Latency**: `342.8 ms`

---

## 👥 Team Roles & Ownership

| Role | Person | Owned Directories |
|---|---|---|
| **Backend A: Vision** | John (Repo Owner, Demo Laptop) | `backend/vision/`, shared configs |
| **Backend B: Server & Chat** | Person B | `backend/server/` |
| **Frontend 1: Dashboard** | Person C | `frontend/index.html`, `dashboard.js`, `styles.css`, `docs/` |
| **Frontend 2: Chat & Eval** | Person D | `frontend/chat.html`, `chat.js`, `eval/` |

---

## 📄 License
This project is licensed under the [MIT License](LICENSE).
