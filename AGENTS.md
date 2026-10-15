# EventLens: project brief for AI agents

Read this whole file before doing anything in this repo. It is the shared context for every teammate's AI agent (Hermes or otherwise). If a request conflicts with this file, say so and ask the user before acting.

## 1. What this project is

HackHive 2026 (48-hour hackathon, MIT Bengaluru, with Honeywell), Problem Statement 3:
"Open-Source AI System for Live Video Event Summarization, Classification, and Conversational Querying."

The system ingests a live or simulated video stream, detects and tracks people, uses an open-source vision-language model (VLM) to describe what is happening, classifies each event into a fixed category, stores it in a database, and lets a user ask questions in plain English, for example: "Show all tailgating events from camera 2 today."

Deliverables: a working prototype that processes a live or simulated stream, records classified events with summaries, answers natural-language questions about them, plus a report on accuracy and latency.

## 2. Hard constraints (never violate)

- Open-source models only for inference. No paid cloud APIs in runtime code. (Using an AI assistant to write the code is fine; the running system must not call cloud APIs.)
- Must run on ONE consumer GPU or laptop: Lenovo Legion with RTX 5070 Ti laptop GPU (plan for about 12 GB VRAM; verify with nvidia-smi). Quantized models are fine.
- Everything works offline once models are downloaded.
- Privacy: all processing is local. Store only key frames and short frame sets for detected events, never continuous footage.
- Environment: Windows, PowerShell, Python 3.11 or 3.12, Ollama installed locally.
- The team is mostly beginners using AI to write code. Keep everything simple, readable and runnable.

## 3. Team and ownership

Four people: 2 backend, 2 frontend. Each person edits ONLY their own paths.

| Role | Person | Owns |
|---|---|---|
| Backend A: Vision | John (also repo owner, runs the demo laptop) | backend/vision/ |
| Backend B: Server, DB, VLM, chat | Person B | backend/server/ |
| Frontend 1: Dashboard, then slides | Person C | frontend/index.html, frontend/dashboard.js, frontend/styles.css, docs/ |
| Frontend 2: Chat, then evaluation | Person D | frontend/chat.html, frontend/chat.js, eval/ |

Agent rules about ownership:
1. At the start of a session, find out which role the user has. If unknown, ask.
2. Edit only files in that role's paths. If a change is needed elsewhere, describe it in a short note for the user to pass to the owner. Do not make the edit.
3. Never change the API contract (section 8) or database schema (section 9) alone. Tell the user the change must be agreed with the whole team first.
4. Shared files (README.md, requirements.txt, .gitignore, this file) are edited only by John's agent. Others propose changes by message.

## 4. Repo layout

```
hackhive-ps3/
  AGENTS.md              this file
  README.md              how to install and run (John)
  requirements.txt       Python dependencies (John)
  .gitignore             blocks videos, models, databases, venv
  config/
    cameras.json         per-camera zones and thresholds (John)
    settings.json        model names, Ollama address, paths (John)
  backend/
    vision/              Backend A (John)
      pipeline.py        ingest -> detect/track -> triggers -> candidate events
      ingest.py          webcam / video file / RTSP, frame sampling
      detect_track.py    YOLO + ByteTrack
      triggers.py        rule-based event triggers
    server/              Backend B (Person B)
      main.py            FastAPI app, endpoints, MJPEG stream, starts workers
      db.py              SQLite access
      vlm.py             Ollama vision calls
      chat.py            question -> safe SQL -> answer
      mock_events.json   fake events for frontend development
  frontend/              served as static files by FastAPI
    index.html, dashboard.js, styles.css      Person C
    chat.html, chat.js                        Person D
  eval/                  Person D
    ground_truth.csv     clip name, true category, event start time
    run_eval.py          precision/recall per category, latency stats
    results/
  docs/                  Person C: slides, report, demo_script.md
  data/                  NOT in git: videos, events.db, saved frames, model files
```

## 5. Architecture (single process, kept deliberately simple)

One FastAPI process runs everything. `POST /api/source` starts a background thread per camera that runs the vision pipeline. No message queues, no extra services.

```
video source
  -> ingest (sample ~3-5 fps)
  -> YOLO detect + ByteTrack IDs (person class)
  -> triggers (cheap rules; VLM NOT used here)
  -> candidate event {camera_id, category_hint, timestamp, track_ids, frames[3-4], keyframe}
  -> vlm.describe_event(candidate) -> {category, confidence, summary}   (Ollama vision model)
  -> db.insert_event(...)  (+ save key frame to data/frames/)
  -> dashboard polls /api/events; chat uses the same table
```

Key design decision: the slow VLM runs ONLY on triggered moments, never on every frame. This is how we meet latency. Do not change this.

Internal interfaces (Backend A and Backend B agree on these):
- `backend/vision/pipeline.py`: `start_camera(camera_id, source, on_candidate)` and `get_latest_jpeg(camera_id) -> bytes` (annotated frame for the MJPEG stream).
- `backend/server/vlm.py`: `describe_event(candidate) -> dict` with keys `category`, `confidence`, `summary`.
- `backend/server/db.py`: `insert_event(event) -> id`, `query_events(filters) -> list`, `run_readonly_query(sql) -> rows`.

## 6. Tech stack

- Python 3.11 or 3.12; FastAPI + Uvicorn; SQLite; OpenCV.
- Vision: Ultralytics YOLO (small model such as yolo11n or yolo11s) with built-in ByteTrack (`tracker="bytetrack.yaml"`).
- VLM: a small open vision model served by Ollama (Qwen2.5-VL, Gemma 3 or SmolVLM class). The exact model name lives in `config/settings.json` and is chosen after a speed test. Check what the installed Ollama version actually offers.
- Chat model: a small open text model via Ollama, name in `config/settings.json`.
- Frontend: plain HTML, CSS and JavaScript only. No React, no npm, no build step. Poll the server every 2 seconds. Live video is an `<img>` pointing at the MJPEG endpoint.
- Windows GPU gotcha: install PyTorch with CUDA BEFORE other packages, using the CUDA 12.8-or-newer command from pytorch.org (RTX 50-series need a recent build). A plain `pip install ultralytics` can pull CPU-only PyTorch. `python -c "import torch; print(torch.cuda.is_available())"` must print True.

Do not add new frameworks or dependencies without telling the user and having John add them to requirements.txt.

## 7. Setup and run (PowerShell)

```
python -m venv .venv
.venv\Scripts\Activate.ps1
# install CUDA PyTorch first (command from pytorch.org, CUDA 12.8 or newer), then:
pip install -r requirements.txt
ollama pull <vlm model from config/settings.json>
ollama pull <chat model from config/settings.json>
uvicorn backend.server.main:app --port 8000
```

Then open http://localhost:8000 (dashboard) and http://localhost:8000/chat.html (chat). Start a video with:
`POST /api/source {"camera_id": "cam1", "source": "data/videos/test1.mp4"}`

These are the target commands. If a file does not exist yet, build it; do not pretend it exists.

## 8. API contract (frozen at Hour 2; the team agrees before any change)

Categories (exactly these strings): `person_down`, `fighting`, `tailgating`, `crowd_incident`, `suspicious_activity`

Event object:
```json
{
  "id": 42,
  "timestamp": "2026-10-16T14:03:22",
  "camera_id": "cam1",
  "category": "tailgating",
  "confidence": 0.82,
  "summary": "Two people entered through the door within one second; only the first used the access reader.",
  "keyframe_url": "/frames/42.jpg",
  "track_ids": [3, 5]
}
```

Endpoints:
- `GET /api/events?category=&camera_id=&since=&limit=` returns `{"events": [...]}`
- `GET /api/events/{id}` returns one event
- `GET /api/stats` returns counts per category, average latency, events today
- `GET /stream/{camera_id}` returns the annotated live video (MJPEG)
- `POST /api/chat` with `{"question": "..."}` returns `{"answer": "...", "sql": "...", "events": [...]}`
- `POST /api/source` with `{"camera_id": "...", "source": "path-or-rtsp"}` starts processing
- `GET /api/health` returns `{"ok": true}`

Until the real backend works, the frontend develops against `backend/server/mock_events.json` served by a mock server.

## 9. Database

SQLite file at `data/events.db`, one table:

```
events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp TEXT,        -- ISO 8601
  camera_id TEXT,
  category TEXT,         -- one of the five categories
  confidence REAL,       -- 0..1
  summary TEXT,
  keyframe_path TEXT,
  track_ids TEXT,        -- JSON list
  latency_ms INTEGER     -- trigger to saved
)
```

## 10. Trigger rules (Backend A)

Zones and thresholds come from `config/cameras.json`, never hard-coded.
- tailgating: two different tracked people cross the door zone within about 1 to 2 seconds of each other.
- person_down: a tracked person's box becomes wider than tall and stays still for N seconds.
- crowd_incident: person count in a region exceeds a threshold.
- suspicious_activity: a person stays in a restricted zone longer than N seconds (loitering).
- fighting: two tracks overlap with fast, erratic movement; always confirmed by the VLM before it is stored.

Each candidate carries 3 to 4 frames and a key frame. Log timestamps at trigger, VLM done and DB saved so latency can be measured.

## 11. VLM contract (Backend B)

Send the candidate frames with a prompt asking for ONLY a JSON object: `{"category": one of the five or "none", "confidence": 0..1, "summary": "1-2 sentences"}`. Parse defensively. On timeout or bad output, fall back to the rule's category hint and a template summary, and lower the confidence. If the VLM returns `none`, drop the candidate (this is how false alarms get filtered).

## 12. Chat to database rules (Backend B)

1. Give the chat model the table layout and about 5 example question-to-SQL pairs.
2. It must return exactly ONE read-only `SELECT` on the `events` table with a `LIMIT` of 100 or less.
3. Code validates before running: single statement, starts with SELECT, no semicolons inside, no other tables, no write keywords. Run it on a read-only SQLite connection.
4. Resolve words like "today" and "last hour" in Python and pass real timestamps into the prompt; do not trust the model with dates.
5. If validation fails, fall back to fixed templates (by category, camera, date range).
6. The response includes the SQL used so the UI can show "how I got this".

## 13. Code conventions

- Complete files, no placeholders like "rest of code here".
- Simple, commented code a beginner can read. Prefer clarity over cleverness.
- Python: standard library first, type hints where easy, no global state except per-camera workers.
- Settings and thresholds in `config/`, not hard-coded.
- Frontend: vanilla JS, `fetch`, no frameworks. Dark "security console" look.
- Never commit videos, model weights, `.venv`, or `data/`.
- Commit messages: short and plain, for example "add tailgating rule".
- After every change, tell the user the exact PowerShell command to run and the output to expect.

## 14. How an agent should work here

- Build thin and end to end first: a video goes in, YOLO draws boxes, one real event is saved, it shows on the dashboard (target: Hour 8). Then improve.
- Ask for or write one small piece at a time. Do not rewrite working code or "clean up" unprompted.
- If an error appears, ask for the FULL error text and the file, then fix that specific problem.
- If something would take more than about 20 minutes, propose a simpler approach.
- Do not invent facts about performance. Accuracy and latency numbers come from `eval/`, measured.

## 15. Milestones (check off as done)

- [ ] M0 (Hour 0-2): setup done, GPU confirmed, VLM speed test done, contract frozen, mock server up
- [ ] M1 (Hour 8): thin slice works end to end
- [ ] M2 (Hour 16): tailgating + person_down real; VLM summaries; live feed; events list; chat answers 3 canned questions
- [ ] M3 (Hour 24): real chat (question to SQL to answer); fighting, crowd, loitering; first evaluation run
- [ ] M4 (Hour 36): feature freeze; only bug fixes after this
- [ ] M5 (Hour 42): final evaluation, report, slides, recorded backup demo video
- [ ] M6 (Hour 46): README verified from a clean start, final push, submit

## 16. Evaluation (Person D owns, everyone helps)

- Test set: about 25 to 30 short clips (10 to 20 s): roughly 5 tailgating, 5 person down, 5 staged fight (safe acting only), 3 crowd, 2 loitering, 10 normal, plus a few public clips. Team members act, with consent; nobody gets hurt.
- `eval/ground_truth.csv`: clip name, true category, event start time.
- `eval/run_eval.py` computes precision and recall per category, and latency (median and slowest 5 percent) from trigger to saved event.
- Report states limitations honestly.

## 17. Demo (3 to 4 minutes)

Problem, live feed with boxes, staged tailgating event appears with a summary, person down, chat query ("Show all tailgating events from camera 2 today"), results slide, "all open-source, on one laptop, nothing leaves the machine." Backup: recorded demo video and a pre-filled database; demo from video files rather than a webcam.

## 18. Known risks and fallbacks

- PyTorch on CPU: reinstall the CUDA build.
- VLM too slow: smaller model, 2 to 3 frames, lower resolution, process events in a background queue so video never stalls.
- Chat produces bad SQL: validation, then fixed templates.
- Integration trouble: check against section 8 first; use the mock server.
- GitHub trouble: teammates zip their folder and send it to John.
