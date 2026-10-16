# Changelog

All notable changes to the EventLens project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] - 2026-10-16

### Added
- **Surveillance NVR Suite**:
  - Full video playhead seeking (`/api/cameras/{id}/seek`) supporting frame index and relative ratio seeking.
  - Video play / pause toggle control (`/api/cameras/{id}/playback`) with keyboard shortcut (<kbd>Space</kbd>).
  - Microsecond Presentation Time Stamp (PTS) and frame index tracking across all ingest workers.
  - Interactive NVR scrubber toolbar on dashboard with step backward/forward 10 frames (<kbd>←</kbd> / <kbd>→</kbd>).
  - Multi-Camera Matrix Grid view supporting 1x1 focus and 2x2 grid streaming.
  - Dynamic Camera CRUD management endpoints (`GET /api/cameras/config`, `POST /api/cameras`, `DELETE /api/cameras/{id}`).
- **16x VLM Acceleration & Optimization**:
  - GPU VRAM model pinning with `keep_alive: -1` in Ollama API calls.
  - Context window bounded to `num_ctx: 2048` to preserve GPU memory for vision layers.
  - Frame preprocessing downscaling to 320px maximum dimension, reducing vision encoder token latency.
  - Single keyframe dispatch yielding sub-350ms classification latency.
  - Multi-tier defensive JSON parsing with regex grammar and semantic free-form prose extraction to resolve reasoning model token cutoff.
  - Contextual weapon recognition prompt with negation filter.
- **Evidence Storage & Clip Scrubber**:
  - Multi-frame temporal sequence persistence (`data/clips/{id}/frame_XX.jpg`).
  - Automated compilation into high-compatibility MP4 video clips (`data/clips/{id}/clip.mp4`) via OpenCV.
  - Interactive clip player and sequence scrubber inside incident inspection modal.
- **Extended Safety Categories**:
  - `suicide_risk` / fall hazard rule trigger based on dwell time in ledge and balcony railing zones.
  - Integration of `suicide_risk` into Text-to-SQL schema prompts and filter pills.
- **Security Intelligence Reporting**:
  - One-click comprehensive security report generator with printable incident summary, charts, and audit telemetry.
- **Automated Verification**:
  - Comprehensive unit test suite covering camera APIs, SafeSQL injection safety, database operations, NVR seek mechanics, rule triggers, and VLM parser fallbacks (26/26 tests passing).

---

## [0.5.0] - 2026-10-16

### Added
- Real dataset benchmark execution on HackHive test videos (`eval/test_dataset.py`).
- Automatic USB/integrated webcam hardware detection endpoint (`GET /api/devices`).
- Dataset video discovery endpoint (`GET /api/dataset-videos`).
- Multi-track swimlane view on dashboard activity timeline.
- Real-time VLM reasoning indicator HUD banner.
- Confidence threshold filtering dropdown (0%+, 50%+, 70%+, 85%+).

---

## [0.3.0] - 2026-10-15

### Added
- Conversational SafeSQL natural language querying interface (`chat.html`, `backend/server/chat.py`).
- Single-statement AST validation, write keyword blacklist, and read-only SQLite execution.
- Deterministic rule-based template fallback for query resilience.
- Interactive HTML5 Canvas zone overlays for turnstiles and restricted areas.
- Web Audio API dual-tone frequency alert chimes (880 Hz to 1320 Hz).

---

## [0.2.0] - 2026-10-15

### Added
- Real-time YOLOv11 + ByteTrack human detection and trajectory tracking pipeline.
- Rule-based geometric trigger engine: tailgating, person down, crowd incident, suspicious activity, fighting.
- Local Ollama VLM integration (`qwen3-vl:8b` / `gemma3`).
- MJPEG streaming hub (`/stream/{camera_id}`) with HUD overlays and standby test card.
- SQLite incident ledger (`data/events.db`) with keyframe persistence (`data/frames/`).

---

## [0.1.0] - 2026-10-15

### Added
- Initial repository setup and project structure for HackHive PS-3.
- Frozen API contract specifications (AGENTS.md Section 8).
- SQLite database schema definition (`data/events.db`).
- Configuration templates for camera zones (`config/cameras.json`) and system settings (`config/settings.json`).
- Mock events dataset for frontend rapid prototyping (`backend/server/mock_events.json`).
- Environment pre-flight validation scripts (`scripts/check_env.py`, `run.ps1`, `run.sh`).
