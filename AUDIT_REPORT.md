# EventLens System Audit Report

**Date**: 2026-10-17  
**Auditor**: Senior Systems, Computer Vision & Security Engineering Lead  
**Repository**: EventLens (https://github.com/bleedingedge121/eventlens)  
**Status**: Confirmed Bugs Documented; Immediate Remediation in Progress

---

## 1. Executive Summary

A comprehensive source code and execution audit of the EventLens repository was conducted across computer vision, vision-language model (VLM) verification, benchmarking routines, backend APIs, data pipelines, and security boundaries.

The audit verified critical reliability defects, most notably:
1. **Fabricated Benchmarking Metrics (`eval/run_eval.py`)**: Precision, recall, and latency metrics are generated using pseudo-random seeds (`np.random.rand() > 0.12`, `np.random.normal(340, 45)`) instead of executing video frames through the inference pipeline.
2. **Mock Telemetry & Hardware Misrepresentation**: GPU VRAM and pipeline status fallbacks provide hardcoded static values (e.g., 1450 MB / 12288 MB) when drivers/NVML are unavailable, concealing hardware faults.
3. **Evidence Timeline Distortion**: Multi-frame MP4 incident evidence clips are encoded at a static hardcoded `10.0 FPS` regardless of camera native frame rate, distorting event playback speed and temporal forensics.
4. **API Security Gaps**: Unauthenticated destructive endpoints (`DELETE /api/events`, `DELETE /api/cameras/{id}`) and unvalidated path traversal risks in clip file endpoints.
5. **VLM Verification Edge Cases**: Permissive schema validation and unverified model availability allow edge cases where failed or malformed responses could compromise incident ledgers.

---

## 2. Confirmed Findings & Bug Ledger

### Defect 1: Fabricated Benchmarking in `eval/run_eval.py`
- **Location**: `eval/run_eval.py` (lines 50–72)
- **Severity**: **CRITICAL** (Academic & Operational Integrity Violation)
- **Reproduction**:
  Inspect `eval/run_eval.py`. Line 52 calls `np.random.seed(42)`, and lines 57–62 simulate predictions and latencies with `is_correct = np.random.rand() > 0.12` and `lat = float(np.random.normal(loc=340, scale=45))`. Executing `python eval/run_eval.py` generates manufactured precision/recall tables without touching any video data or inference models.
- **Planned Fix**:
  Rewrite `run_eval.py` to:
  - Ingest ground-truth annotations from `eval/ground_truth.csv`.
  - Execute actual clips using `DetectorTracker`, `TriggerEngine`, and `VLMClient`.
  - Calculate real true positives (TP), false positives (FP), false negatives (FN), precision, recall, F1, and actual monotonic latency (`time.perf_counter()`).
  - Gracefully report missing datasets without fabricating mock results.
  - Separate any simulation into an explicitly labeled `--simulate` mode for headless testing only.

---

### Defect 2: Hardcoded GPU Telemetry Fallbacks
- **Location**: `backend/server/main.py`, `scripts/check_env.py`
- **Severity**: **HIGH** (Misleading Telemetry / Silent Hardware Failure)
- **Reproduction**:
  When NVIDIA NVML or CUDA is uninitialized or unavailable, static mock values (e.g., 1450 MB used of 12288 MB total) mislead operators into believing local GPU acceleration is functional when running on CPU fallback.
- **Planned Fix**:
  Implement dynamic query via `torch.cuda` / `pynvml`. When GPU metrics cannot be queried, return explicit `"status": "unavailable"` with `null` metrics.

---

### Defect 3: Evidence Video Encoding Framerate Distortion
- **Location**: `backend/server/main.py` (lines 206–216)
- **Severity**: **MEDIUM** (Forensic Evidence Integrity)
- **Reproduction**:
  Candidate event clips save captured frame sequences to MP4 using `cv2.VideoWriter(..., 10.0, ...)`. Ingested video streams running at 25 or 30 FPS playback at 10 FPS, causing a 2.5x–3.0x slow-motion distortion.
- **Planned Fix**:
  Track and pass the source stream's native frame rate or inter-frame delta timestamp into clip rendering.

---

### Defect 4: Destructive API Endpoints & Path Traversal Vulnerabilities
- **Location**: `backend/server/main.py` (`DELETE /api/events`, `DELETE /api/cameras/{id}`, `GET /api/clips/{event_id}`)
- **Severity**: **HIGH** (Security & Data Protection)
- **Reproduction**:
  - `DELETE /api/events` unconditionally wipes the entire SQLite database and file storage without confirmation or origin protection.
  - `DELETE /api/cameras/{camera_id}` deletes cameras from `config/cameras.json` without confirmation.
  - Event ID parameters in clip paths could be manipulated for directory traversal if non-integer characters are passed.
- **Planned Fix**:
  - Enforce integer validation and positive bounds on `event_id`.
  - Ensure path resolution stays strictly inside `DATA_DIR / "clips"` using `.resolve()`.
  - Add confirmation safeguards or headers for mass-deletion endpoints.

---

### Defect 5: VLM Client Verification & Image Encoding Robustness
- **Location**: `backend/server/vlm.py`
- **Severity**: **HIGH** (Reliability & Model Stability)
- **Reproduction**:
  - `_prepare_images`: Corrupt or truncated byte streams could crash or emit empty arrays without structured handling.
  - `_resolve_model`: If Ollama is offline or uninstalled, falls back without explicit error flags.
  - Output contract: Must enforce strict type compliance (`verified: bool`, `confidence: float`, `category: str`).
- **Planned Fix**:
  - Validate image decoding with `cv2.imdecode` and drop corrupt frames defensively.
  - Return explicit `verified=False`, `verdict="error"`, zero confidence on any network error, timeout, or parse failure.
  - Validate active models directly against `/api/tags`.

---

### Defect 6: Configuration Drift Between Endpoints and Trigger Engine
- **Location**: `backend/server/main.py`, `backend/vision/triggers.py`, `config/cameras.json`
- **Severity**: **MEDIUM** (Config Inconsistency)
- **Reproduction**:
  `POST /api/cameras` manually assigns hardcoded defaults (`fighting_overlap_iou: 0.38`, `crowd_threshold: 7`) rather than inheriting from `config/taxonomy.yaml` or a centralized schema.
- **Planned Fix**:
  Centralize camera and zone configuration defaults in `backend/server/config.py`.

---

## 3. Remediation Execution Plan

1. **Phase 2**: Overhaul `eval/run_eval.py` to execute real pipeline inference and output authentic metrics. Add `tests/test_eval.py`.
2. **Phase 3**: Harden `backend/server/vlm.py` with image validation, structured schemas, and Ollama probe.
3. **Phase 4 & 5**: Refine Person Down and Fighting trigger parameters in `backend/vision/triggers.py`.
4. **Phase 6**: Unify camera and zone configuration in `backend/server/config.py` and `backend/server/main.py`.
5. **Phase 7**: Add security validations and path traversal defenses to `backend/server/main.py`.
6. **Phase 8 & 9**: Fix clip framerate and telemetry in `backend/server/main.py`.
7. **Phase 10–13**: Run end-to-end tests, verify full regression suite, and publish `FIX_REPORT.md`.
