# EventLens System Fixes & Improvements Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all discovered failure modes, eliminate thread contention and stderr warnings, harden SafeSQL and trigger engines, and upgrade NVR scrubbing and UI resilience.

**Architecture:** 
1. Introduce a dedicated FIFO worker queue for VLM inference to prevent thread stampedes and lock starvation.
2. Enhance trigger algorithms with video loop reset handling and normalized kinetic oscillation for fighting.
3. Replace deprecated FastAPI startup hooks with modern lifespan context and add disconnect detection to MJPEG streaming.
4. Silence DirectShow OpenCV C++ stderr warnings and harden SafeSQL with SQLite syntax normalizers.

**Tech Stack:** Python 3.11, FastAPI, OpenCV, Ultralytics YOLOv11, SQLite, Ollama, Vanilla ES6+ HTML5/CSS3.

## Global Constraints
- 100% offline edge processing only (no cloud APIs).
- Maintain frozen API contract (AGENTS.md Section 8) and database schema (Section 9).
- All 26 existing unit tests must remain passing.
- Backward compatibility with existing video datasets and config files.

---

## Subsystem 1: Backend Server & Ingestion Hardening

### Task 1: Silence DirectShow OpenCV Warnings & Add Lifespan Context Manager

**Files:**
- Modify: `backend/server/main.py:1-75, 190-210, 370-400`
- Test: `tests/test_camera_api.py`

**Interfaces:**
- Consumes: `cv2.utils.logging.setLogLevel`, FastAPI `lifespan`
- Produces: Clean server startup and probe endpoints with zero C++ stderr pollution

- [x] **Step 1: Write a test verifying `_probe_devices` executes cleanly without crashing on missing camera indices**
- [x] **Step 2: Add `cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)` to `main.py` and `ingest.py`**
- [x] **Step 3: Refactor `@app.on_event("startup")` to FastAPI `asynccontextmanager` `lifespan(app: FastAPI)`**
- [x] **Step 4: Run `.\.venv\Scripts\python -m unittest tests.test_camera_api` to verify**
- [x] **Step 5: Commit changes**

---

### Task 2: MJPEG Stream Client Disconnect Detection & Resource Cleanup

**Files:**
- Modify: `backend/server/main.py:430-450`
- Test: `tests/test_camera_api.py`

**Interfaces:**
- Consumes: `fastapi.Request.is_disconnected()`
- Produces: Clean generator termination when browser tab closes or camera changes

- [x] **Step 1: Inject `request: Request` into `GET /stream/{camera_id}`**
- [x] **Step 2: Check `if await request.is_disconnected(): break` in `frame_generator`**
- [x] **Step 3: Add test validating stream generator terminates on client disconnect**
- [x] **Step 4: Commit changes**

---

### Task 3: Background VLM Dispatcher Queue (Eliminate Thread Stampedes)

**Files:**
- Modify: `backend/vision/pipeline.py:30-50, 180-215`
- Modify: `backend/server/main.py:105-150`
- Test: `tests/test_vlm_safety.py`

**Interfaces:**
- Consumes: `queue.Queue`, background worker thread
- Produces: Orderly FIFO candidate event dispatching without unconstrained thread creation or `_call_lock` timeouts

- [x] **Step 1: Create a bounded `queue.Queue(maxsize=16)` in `pipeline.py` or `main.py` with a dedicated worker thread**
- [x] **Step 2: Replace raw `threading.Thread(...).start()` with `queue.put_nowait(cand)`**
- [x] **Step 3: Gracefully drop lowest-priority candidate if queue is full**
- [x] **Step 4: Run unit tests to confirm candidates are processed sequentially without locking**
- [x] **Step 5: Commit changes**

---

## Subsystem 2: Vision & Anomaly Trigger Engine Enhancements

### Task 4: Video Loop & Seek Timestamp Reset Detection in Triggers

**Files:**
- Modify: `backend/vision/triggers.py:70-120, 230-275`
- Test: `tests/test_triggers.py`

**Interfaces:**
- Consumes: `timestamp_sec` monotonic checks
- Produces: Auto-reset of track history and zone entry times when video loops or seeks backward

- [x] **Step 1: Write test in `test_triggers.py` simulating video looping where timestamp jumps from 8.0s to 0.1s**
- [x] **Step 2: In `TriggerEngine.update()`, check if `current_time < self.last_update_time - 0.5s` (video seek/loop)**
- [x] **Step 3: On wrap-around, clear or adjust `th.zone_entry_times`, `th.hazard_entry_times`, and `last_door_crossings`**
- [x] **Step 4: Verify test passes and loitering timers don't get stuck with negative deltas**
- [x] **Step 5: Commit changes**

---

### Task 5: Loitering & Fighting Heuristic Refinement

**Files:**
- Modify: `backend/vision/triggers.py:130-155, 270-305`
- Modify: `config/cameras.json`
- Test: `tests/test_triggers.py`

**Interfaces:**
- Consumes: Bounding-box normalized centroid velocity and direction reversal counting
- Produces: High-precision fighting trigger that distinguishes rapid directional altercations from steady crowd egress

- [x] **Step 1: Write tests for fighting vs crowd walking in `test_triggers.py`**
- [x] **Step 2: Add direction change / velocity vector variance check for fighting tracks (erratic oscillation)**
- [x] **Step 3: Adjust default `max_loitering_seconds` to 4.0s (from 6.0s/8.0s) in `config/cameras.json` for better responsiveness**
- [x] **Step 4: Run all trigger tests to verify improved precision**
- [x] **Step 5: Commit changes**

---

## Subsystem 3: Conversational SafeSQL Hardening

### Task 6: SafeSQL Dialect Normalization & Function Whitelist

**Files:**
- Modify: `backend/server/chat.py:75-125, 140-195`
- Test: `tests/test_chat_safety.py`

**Interfaces:**
- Consumes: Generated SQL string from Ollama
- Produces: Dialect-normalized SQL (e.g. `ILIKE` -> `LIKE`, `NOW()` -> concrete timestamp)

- [x] **Step 1: Add test cases in `test_chat_safety.py` for `ILIKE` normalization and SQLite date functions**
- [x] **Step 2: Implement regex pre-sanitization: replace `\bILIKE\b` with `LIKE`**
- [x] **Step 3: Allow safe scalar functions `strftime`, `date`, `datetime`, `count`, `lower`, `upper`**
- [x] **Step 4: Run test suite to verify 100% test pass rate**
- [x] **Step 5: Commit changes**

---

## Subsystem 4: Frontend Scrubber & Modal Polish

### Task 7: Scrubber Seek Debouncing & Keyboard Navigation

**Files:**
- Modify: `frontend/dashboard.js:75-105, 300-360`
- Test: Manual browser check & endpoint regression test

**Interfaces:**
- Consumes: Scrubber range input event with 60ms debounce
- Produces: Smooth seeking without HTTP request queue saturation

- [x] **Step 1: Implement 60ms debounce on `nvrSlider.addEventListener('input', ...)`**
- [x] **Step 2: Ensure immediate seek on `change` event (when user releases the mouse)**
- [x] **Step 3: Add keyboard listener for <kbd>Space</kbd> (play/pause) and <kbd>←</kbd> / <kbd>→</kbd> (step 10 frames) inside modal**
- [x] **Step 4: Verify with local test runner**
- [x] **Step 5: Commit changes**

---

## Subsystem 5: Evaluation & Dataset Benchmark Alignment

### Task 8: Align Evaluation Suite with Real Dataset Execution

**Files:**
- Modify: `eval/run_eval.py:40-100`
- Test: `eval/run_eval.py`

**Interfaces:**
- Consumes: `eval/results/dataset_benchmark.json` and real video test runs
- Produces: Grounded, empirical precision/recall and latency stats directly from executed clips rather than simulated random variables

- [x] **Step 1: Update `eval/run_eval.py` to evaluate actual local video clips (`data/videos/*.mp4` and `dataset/*.mp4`)**
- [x] **Step 2: Aggregate true positive / false positive matches against `eval/ground_truth.csv`**
- [x] **Step 3: Run `python .\eval\run_eval.py` and verify `eval_report.json` reflects verified measurements**
- [x] **Step 4: Commit changes**
