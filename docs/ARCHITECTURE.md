# EventLens Architecture

## System Overview

EventLens is an open-source, edge-native video surveillance intelligence platform designed to run completely offline on a single consumer GPU (Lenovo Legion RTX 5070 Ti, 12 GB VRAM).

```
                      +---------------------------------------+
                      |       Video Stream / RTSP / File      |
                      +---------------------------------------+
                                          |
                                          v  [3-5 FPS Sampling]
                      +---------------------------------------+
                      |    Ingest Engine (backend/vision/)     |
                      +---------------------------------------+
                                          |
                                          v
                      +---------------------------------------+
                      |     YOLOv11 Detection + ByteTrack     |
                      |   (Filters Person Class IDs: 1, 2...) |
                      +---------------------------------------+
                                          |
                                          v  [Geometric & Temporal Check]
                      +---------------------------------------+
                      |   Rule-Based Trigger Engine (Zero VLM)|
                      |    - Tailgating (Door zone crossing)  |
                      |    - Person Down (Aspect ratio + stop)|
                      |    - Crowd Incident (Regional count)  |
                      |    - Suspicious (Loitering in zones)  |
                      |    - Fighting (IoU + High speed)      |
                      +---------------------------------------+
                                          |
                 +------------------------+-----------------------+
                 | (Only on Triggered Candidate Moments)          |
                 v                                                v
+-----------------------------------+           +-----------------------------------+
|      MJPEG Live Stream Hub        |           |  Ollama Local Vision Model (VLM)  |
|  (/stream/{cam_id} Annotated HUD) |           |  (Qwen2.5-VL / Gemma3 / Hermes)   |
+-----------------------------------+           +-----------------------------------+
                 |                                                |
                 v                                                v  [Classified & Confirmed]
+-----------------------------------+           +-----------------------------------+
|   Security Console Web Frontend   |           |    SQLite Database (events.db)    |
| (index.html / dashboard.js / CSS) | <-------- |   (Stores keyframe, JSON tracks)  |
+-----------------------------------+           +-----------------------------------+
                 ^                                                ^
                 |                                                |
                 +------------------------------------------------+
                                          |
                                          v
                      +---------------------------------------+
                      |    Conversational Query Engine (Chat) |
                      |    Natural Language -> Safe Read SQL  |
                      +---------------------------------------+
```

## Key Architectural Decisions

1. **Selective VLM Invocation**: High-parameter Vision-Language Models cannot process continuous 30 FPS video on consumer hardware. EventLens executes lightweight YOLO + ByteTrack at 3-5 FPS to maintain tracking IDs. The VLM is invoked **only** when rule triggers detect a candidate anomaly.
2. **Deterministic Trigger Pre-Filters**: Bounding-box aspect ratio shifts and door-zone cross intervals act as zero-cost gates, reducing VLM calls by >98% during normal activity.
3. **Safe Text-to-SQL Execution**: Conversational queries are validated against AST/token whitelists before execution on a read-only SQLite connection, guaranteeing database integrity and query transparency.
4. **Single-Process Lightweight Service**: FastAPI hosts the REST endpoints, MJPEG video streaming, and background camera worker threads with zero external message broker overhead.
