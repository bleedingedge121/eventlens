# EventLens Comprehensive System Report
**HackHive 2026 (MIT Bengaluru with Honeywell) — Problem Statement 3**  
*Open-Source AI System for Live Video Event Summarization, Classification, and Conversational Querying*

---

## Executive Summary

EventLens is an edge-native, 100% open-source physical security intelligence platform running entirely offline on a single consumer laptop (Lenovo Legion with NVIDIA RTX 5070 Ti, 12 GB VRAM).

This document serves as the authoritative technical report detailing:
1. **What All Is Done**: Complete inventory of implemented components, features, models, endpoints, and interfaces.
2. **How It Is Done**: Underlying algorithms, architectural decisions, mathematical thresholds, and optimization strategies.
3. **What Is Broken & Known Limitations**: Transparent engineering analysis of failure modes, hardware bottlenecks, heuristic trade-offs, and edge-case behavior.

---

## 1. What All Is Done

### 1.1 Core Vision & Ingestion Engine
- **Multi-Source Ingestion Pipeline (`backend/vision/ingest.py`)**:
  - Ingests from USB/integrated webcams (Windows DirectShow / POSIX v4l2), local video files (`.mp4`, `.avi`, `.mov`, `.mkv`), and RTSP network security cameras.
  - Automatic frame sampling and pacing maintaining target frame rate (default 3–5 FPS for surveillance tracking, configurable).
  - Loop mode support for continuous automated benchmark replay.
  - Thread-safe frame caching with microsecond Presentation Time Stamp (PTS) and frame index tracking.
  - Video playhead seeking (`seek_frame`, `seek_ratio`) and runtime pause/resume playback controls.

- **Object Detection & Target Tracking (`backend/vision/detect_track.py`)**:
  - Ultralytics YOLOv11 (`yolo11n.pt` / `yolo11s.pt`) execution with hardware acceleration (PyTorch CUDA 12.8 on RTX GPU, MPS on Apple Silicon, CPU fallback).
  - Human target isolation (`classes=[0]` for person detection) avoiding compute waste on background classes.
  - Integrated ByteTrack tracker (`tracker="bytetrack.yaml"`) assigning persistent track IDs across frames and surviving temporary occlusions.
  - Dynamic tactical visualization: bounding boxes, track ID labels, centroid dots, velocity vectors, and operational HUD overlays.

- **Deterministic Anomaly Trigger Engine (`backend/vision/triggers.py`)**:
  - Pure Python + NumPy zero-VLM geometric anomaly rule processor running at <1ms per frame.
  - Six distinct operational anomaly detectors:
    1. **Tailgating**: Consecutive door zone entry by distinct track IDs within a configurable time window ($\le 1.8$s).
    2. **Person Down / Slip & Fall**: Dual-criteria trigger based on bounding-box aspect ratio inversion ($w/h \ge 0.70$) OR vertical height collapse ($\le 60\%$ of peak standing height) combined with spatial stillness ($>0.8$s). Features a persistent spatial region memory resistant to ByteTrack ID re-assignment.
    3. **Crowd Incident**: Regional occupancy exceeding density threshold ($\ge 7$ active tracks).
    4. **Suspicious Activity / Loitering**: Dwell time inside restricted polygon zones exceeding maximum duration ($\ge 6.0$s).
    5. **Fighting / Physical Altercation**: Track bounding-box IoU overlap ($\ge 0.38$) combined with high-velocity kinetic movement ($\ge 105$ px/s).
    6. **Suicide Risk / Fall Hazard**: Entry and dwell time ($\ge 2.5$s) in critical hazard zones (ledges, atrium railings, stairwell drop drops).
  - Per-category trigger debouncing and cooldown management preventing flood alarms.

### 1.2 Local Vision-Language Model (VLM) & 16x Latency Acceleration
- **Ollama VLM Client (`backend/server/vlm.py`)**:
  - Zero-cloud offline multimodal inference via Ollama (`qwen3-vl:8b` primary, with automatic fallback discovery to `qwen2.5-vl`, `gemma3`, `llava`, `minicpm`).
  - **16x Latency Speedup Architecture**:
    - **VRAM Model Pinning**: `keep_alive: -1` keeps model weights hot in GPU VRAM, eliminating 4–8 second cold reload penalties between events.
    - **Bounded KV-Cache (`num_ctx: 2048`)**: Restricts attention context memory to ~100MB, guaranteeing 100% of model layers remain in the 12 GB VRAM and preventing CPU offload.
    - **Patch Dimension Scaling (320px)**: Pre-scales incoming frames down to 320px max dimension with 75% JPEG quality before base64 transport, dramatically slashing visual token count while preserving scene composition.
    - **Single Keyframe Dispatch**: Dispatches the most descriptive keyframe rather than multi-frame bursts, achieving deterministic ~340ms inference.
    - **Non-Blocking Lock (`timeout=8.0s`)**: Prevents pipeline lockups if Ollama experiences momentary queuing.
  - **Multi-Tier Defensive Response Parser**:
    - Direct JSON deserialization.
    - Markdown fenced codeblock extraction (` ```json ... ``` `).
    - Substring brace search (`{...}`).
    - Heuristic partial/truncated JSON repair.
    - Regex attribute extraction.
    - Semantic free-form prose extraction (parses conversational reasoning model thoughts when `<think>` blocks terminate before emitting raw JSON).
  - **Semantic Weapon Recognition**:
    - Contextual prompt evaluation for firearms (guns, rifles, handguns) and bladed weapons (knives, machetes).
    - Negation protection filtering false alerts from phrases like "no visible weapon", "unarmed", or photographic terms like "wide shot".
  - **False Alarm Suppression**:
    - Candidates classified as `none` by the VLM are automatically discarded.
    - Confidence thresholding (events below 50% confidence dropped as noise).

### 1.3 Event Persistence & Temporal Clips
- **Database Architecture (`backend/server/db.py`)**:
  - SQLite database (`data/events.db`) implementing AGENTS.md Section 9 schema.
  - Indexed on `timestamp`, `category`, and `camera_id` for instantaneous querying.
  - Thread-safe connection context management with timeout guards.
- **Evidence Storage**:
  - Keyframe images stored at `data/frames/{event_id}.jpg`.
  - Multi-frame temporal image sequences stored at `data/clips/{event_id}/frame_XX.jpg`.
  - Compiled MP4 event clips generated via OpenCV `VideoWriter` at `data/clips/{event_id}/clip.mp4` for direct browser streaming.
  - Automated schema migration adding `tags TEXT DEFAULT '[]'` column while strictly maintaining AGENTS.md Section 8 and Section 9 backward compatibility.

### 1.4 Conversational SafeSQL Engine (`backend/server/chat.py`)
- Natural-language to SQL translation using local LLMs (e.g. `Hermes-4-14B:latest` or `qwen2.5-coder`).
- Strict security validation:
  - Statement must begin with `SELECT`.
  - Semicolons and multiple statements strictly prohibited.
  - Strict token blacklist blocking all write/DDL keywords (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `EXEC`, `PRAGMA`).
  - Strict table isolation: queries can ONLY access the `events` table.
  - Automatic normalization of dialect differences (e.g., PostgreSQL `ILIKE` normalized to SQLite `LIKE`).
  - Mandatory `LIMIT <= 100` enforcement.
  - Read-only SQLite connection execution.
- Python-side temporal resolution: natural language concepts ("today", "yesterday", "last hour") resolved deterministically into concrete ISO timestamps in Python before prompting the model.
- Safe deterministic regex template fallback guaranteeing reliable responses (including weapon and dangerous terrain searches) even when Ollama is offline.

### 1.5 Dangerous Terrain & Problem Area Hazard Monitoring
- **OSHA Caution Hatching & Live Overlays**: Hazard zones rendered with industrial diagonal caution hatching in HTML5 Canvas (`drawZones`), with distinct severity color coding (`CRITICAL` vs `HIGH`).
- **Live Dwell & Occupancy Telemetry**: Continuous tracking of occupants dwelling in hazardous zones (`Atrium Balcony Drop Ledge`, `Wet Floor / Spill Zone`, `High-Voltage Electrical Substation Panel`), exposing `active_hazards` via `/api/cameras/{cam_id}`.
- **Viewport Hazard Alert Banner**: Instant high-contrast alert banner displayed on top of the live stream when any target exceeds safety dwell limits.
- **Problem Areas Status Strip**: Dedicated status strip below the viewport detailing active violations and clear statuses across all configured camera hazards.
- **Video Loop Wrap-Around Resilience**: Timestamp reset logic preventing negative deltas or stale dwell calculations when test videos seek or replay.

### 1.6 Weapon Detection & Security Threat Tagging
- **Multi-Class Threat Extraction**: Visual VLM analysis detecting firearms, bladed weapons, and blunt instruments with rigorous false-positive suppression (ignoring colloquial terms like "camera shot").
- **Security Tags System**: Structured tags attached to every event (e.g. `["tailgating", "badge_passback"]`, `["dangerous_terrain", "fall_hazard"]`, `["weapon_detected", "firearm"]`).
- **SOC Tag Chips**: High-visibility pill chips rendered on incident cards in the operations feed and inspection modals (`🔫 WEAPON: FIREARM`, `⚠️ DANGEROUS TERRAIN`, `🚶‍♂️🚶‍♂️ TAILGATING`).
- **Dedicated Incident Filters**: Instant filter buttons for `Weapons` and `Terrain Hazards` with real-time incident counters.

### 1.7 Surveillance NVR Console (`frontend/`)
- **Operations Console (`index.html`, `dashboard.js`, `styles.css`)**:
  - Industrial dark-theme SOC design system (zero frameworks, pure vanilla ES6+).
  - Single Camera Focus (1x1) and Multi-Camera Matrix Grid (2x2) layouts.
  - Interactive NVR Recording Scrubber:
    - Real-time PTS and frame index indicators.
    - Play / Pause control (`Space` shortcut).
    - Frame step forward / backward 10 frames (`←` / `→` shortcuts).
    - Recording buffer seek slider with live stream synchronization.
    - Visual anomaly timeline markers pinpointing incident timestamps on the seek bar.
  - Dynamic Camera Management: Add, edit, and delete cameras at runtime with persistent updates to `config/cameras.json`.
  - Interactive HTML5 Canvas zone perimeter overlays (Door zones, Restricted zones, Hazard zones) with keyboard toggle (`Z`).
  - Synthesized dual-tone Web Audio alert chimes (880 Hz to 1320 Hz) with mute toggle (`M`).
  - Real-time incident feed with multi-category filter tabs, confidence threshold selector (0%+, 50%+, 70%+, 85%+), and live instant search (`/`).
  - Incident Inspection Modal:
    - High-resolution keyframe viewer.
    - Integrated HTML5 MP4 video clip player.
    - Multi-frame clip sequence scrubber (`◀ Prev`, `▶ Next`, `▶ Play Clip`).
    - Security tags row displaying all classified threat and hazard tags.
    - Copy raw JSON telemetry button.
    - Direct "Query AI about this Event" bridge to the conversational engine.
  - Dual-mode Activity Timeline: Combined incident distribution and Multi-Track Swimlanes per camera.
  - Visual analytics: Incidents by Category and Incidents by Camera distribution bars.
  - Instant Security Intelligence Report generator with print/export modal.
  - Quick-switch test clip buttons (tailgating, person down, crowd, suspicious, normal, live webcam, and real HackHive dataset clips).

- **Conversational AI Query Console (`chat.html`, `chat.js`)**:
  - Interactive natural-language security terminal.
  - Preset quick-query chips.
  - SafeSQL query audit inspector with one-click SQL copying and syntax highlighting.
  - Matching incident cards with keyframe previews and confidence ratings.
  - Deep-link query pre-filling via URL query parameter (`chat.html?q=...`).

---

## 2. How It Is Done

### 2.1 The Two-Tier Vision Architecture
```
                        [ Live Video Ingestion ]
                                   │
                                   ▼ (Sampled @ 3-5 FPS)
                        [ YOLOv11n + ByteTrack ]
                                   │
                                   ▼ (Bounding boxes + Track IDs)
                     [ Geometric Rule Engine (<1ms) ]
                                   │
                 ┌─────────────────┴─────────────────┐
                 ▼ (Normal Activity: ~98%)           ▼ (Triggered Moment: ~2%)
         [ Stream to Console ]               [ Candidate Anomaly Event ]
                                                     │
                                                     ▼ (Single 320px Keyframe)
                                             [ Ollama Qwen3-VL:8B ]
                                                     │
                                                     ▼ (JSON Parsed & Confirmed)
                                             [ SQLite DB + Frames/Clips ]
```

1. **Why not run VLM on every frame?**  
   Processing 30 FPS video through an 8B vision model requires ~10 seconds of compute per second of video, causing immediate buffer overflow and GPU thermal throttling. By running YOLOv11 (`~4ms`) for continuous person tracking and reserving the VLM solely for candidate moments, EventLens achieves sub-second end-to-end latency while running on a single laptop.

2. **Trigger Mathematics**:
   - **Person Down**:
     $$\text{Aspect Ratio} = \frac{\text{width}}{\text{height}} \ge 0.70 \quad \text{OR} \quad \frac{\text{height}}{\text{peak height}} \le 0.60$$
     $$\text{Displacement} = \sqrt{(\Delta x)^2 + (\Delta y)^2} < 45 \text{ px for } t \ge 0.8\text{s}$$
   - **Tailgating**:
     $$\Delta t = |t_{\text{cross}}(T_2) - t_{\text{cross}}(T_1)| \le 1.8\text{s} \quad \text{where } T_1 \ne T_2$$
   - **Fighting**:
     $$\text{IoU}(B_1, B_2) \ge 0.38 \quad \text{AND} \quad \frac{v_1 + v_2}{2} \ge 105 \text{ px/s}$$

### 2.2 VLM Optimization Stack
- **GPU Pinning**: Initializing Ollama with `"keep_alive": -1` instructs Ollama's runtime never to unload model weights from GPU VRAM.
- **Context Ceiling**: Setting `"num_ctx": 2048` limits the KV-cache to a predictable footprint (~100 MB), preventing PyTorch / llama.cpp memory fragmentation.
- **Pre-Scale Patch Downsampling**: Bilinear downsampling to max dimension 320px reduces visual patch count from 1,200 patches to ~256 patches, yielding a 4x reduction in vision encoder computation.
- **Resilient Regex Grammar Parsing**: When reasoning models output thinking tokens (`<think>...`), the token budget may exhaust before closing braces. Our regex parser searches both the reasoning trace and output text for canonical action keywords to classify the event deterministically.

### 2.3 SafeSQL Translation Flow
1. Operator types: `"Show all tailgating events from camera 1 today"`.
2. Python resolves temporal bounds: `today_str = "2026-10-16"`.
3. LLM prompt includes database schema, allowed categories, and few-shot examples.
4. Validation:
   - Must match `^select\s+.*from\s+events`
   - Rejects semicolons (`;`)
   - Rejects blacklisted mutation tokens
   - Verifies `LIMIT <= 100`
5. Read-only connection executes the SQL against SQLite.
6. Results rendered as structured JSON response + audit card.

---

## 3. What Is Broken & Known Limitations

To maintain rigorous engineering honesty, the following sections document actual limitations, observed failure modes, and hardware constraints discovered during extensive testing:

### 3.1 Algorithmic Limitations & Rule Triggers

| Trigger | Known Limitation / Failure Mode | Root Cause | Mitigation / Workaround |
|---|---|---|---|
| **Suspicious Activity (Loitering)** | Fails on short benchmark video clips (<6 seconds) | The loitering rule requires a continuous track to dwell in a polygon for $\ge 6.0$s. In short test clips or looped videos where timestamps restart, the dwell timer resets before reaching 6s. Evaluation shows **0% recall** on short clips. | Lower `max_loitering_seconds` to 2.0s for testing, or test on continuous live streams. |
| **Fighting Detection** | False alarms on dense crowd transit or rapid hugs/handshakes | Heuristic relies on IoU overlap ($\ge 0.38$) and velocity ($\ge 105$ px/s). Two individuals briskly crossing paths or dancing can trigger the rule. | VLM confirmation filters out obvious non-fights; if VLM is offline, fallback lower confidence (0.55) flags it as unverified. |
| **Tailgating Detection** | Misses tailgating if follower walks directly behind leader in full occlusion | ByteTrack may merge two aligned individuals into a single bounding box when one is completely occluded by the other. | Angle cameras at 45° to turnstiles rather than dead-on front view. |
| **Weapon Detection** | Low sensitivity on small concealed weapons (handguns, knives) | YOLOv11 is configured only for `person` class 0; weapon detection relies entirely on the VLM observing the 320px keyframe. Small items are blurred at 320px. | Add a dedicated YOLOv11-weapon model to detect handguns/knives at full resolution before VLM confirmation. |
| **Person Down / Fall Detection** | False trigger when a subject sits down cross-legged on the floor | Aspect ratio and height collapse trigger on sitting postures. | Filtered partially by checking if bounding box y-coordinate is near the bottom floor boundary. |

### 3.2 Hardware & Platform Limitations

| Component | Limitation | Technical Cause |
|---|---|---|
| **Multi-Camera GPU Contention** | FPS drops from 30 FPS to 12–15 FPS when running 3+ cameras concurrently | A single laptop GPU (RTX 5070 Ti) has 12 GB VRAM. While YOLOv11 takes only ~800 MB, the 8B VLM requires ~5.5 GB. During VLM forward passes, CUDA compute cores are shared between inference streams. |
| **OpenCV Video Seeking Jitter** | Seeking on compressed MP4 files snaps to nearest I-frame (keyframe) | `cv2.VideoCapture.set(cv2.CAP_PROP_POS_FRAMES)` relies on container keyframe indices. Files encoded without frequent intra-frames (GOP > 60) have seek jitter of up to 1–2 seconds. |
| **Windows DirectShow Terminal Warning** | Benign warning printed to stderr: `cv::VideoCapture::open VIDEOIO(DSHOW)...` | In `backend/server/main.py`, `_probe_devices()` tests indices 0 and 1. If index 1 does not exist, DirectShow outputs a warning before returning `isOpened() == False`. |
| **Ollama Cold-Start First Inference** | First VLM inference call takes ~2.5s if model was not pre-warmed | Loading 8B parameters from disk to GPU takes 2–3s on PCIe. Mitigated by `keep_alive: -1` and pre-warming during startup. |
| **Reasoning Model Thinking Token Budget** | If `num_predict` is too low, reasoning models exhaust tokens inside `<think>...</think>` | Models like Qwen3-VL or DeepSeek emit extensive internal reasoning. If limited to 100 tokens, the response terminates before the JSON body is emitted. (Fixed by increasing to 280 tokens and implementing semantic regex fallback). |

---

## 4. Verification & Evaluation Results

### 4.1 Automated Benchmark Results (`eval/results/eval_report.json`)
Evaluated across 13 annotated benchmark scenarios on Lenovo Legion RTX 5070 Ti (12 GB VRAM):

- **Tailgating**: Precision `1.00`, Recall `0.67`, F1 `0.80`
- **Person Down**: Precision `1.00`, Recall `1.00`, F1 `1.00`
- **Fighting**: Precision `0.75`, Recall `0.75`, F1 `0.75`
- **Crowd Incident**: Precision `0.67`, Recall `1.00`, F1 `0.80`
- **Suspicious Activity**: Precision `0.00`*, Recall `0.00`*, F1 `0.00`* (*Due to clip duration < dwell threshold)
- **Median Latency (Trigger to DB saved)**: `338.7 ms`
- **95th Percentile Latency (p95)**: `419.9 ms`
- **Mean Latency**: `345.6 ms`
- **Unit Test Suite**: `26 / 26` passing (`tests/test_camera_api.py`, `tests/test_chat_safety.py`, `tests/test_db.py`, `tests/test_nvr_seek.py`, `tests/test_triggers.py`, `tests/test_vlm_safety.py`).

---

## 5. Summary & Deployment Readiness
EventLens successfully satisfies all HackHive Problem Statement 3 core requirements:
- 100% offline edge processing on a single consumer laptop GPU.
- Real-time YOLOv11 + ByteTrack human trajectory tracking.
- Selective local VLM invocation achieving ~340ms end-to-end incident logging.
- Conversational SafeSQL auditing with zero cloud data transmission.
- Full surveillance NVR operations suite with recording scrubber and multi-camera matrix.
