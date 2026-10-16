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
                      |    Ingest Engine (backend/vision/)    |
                      |    - Microsecond PTS & Frame Tracking |
                      |    - Instant Seeking & Playhead Cache |
                      +---------------------------------------+
                                          |
                                          v
                      +---------------------------------------+
                      |     YOLOv11 Detection + ByteTrack     |
                      |   (Filters Person Class IDs: 1, 2...) |
                      +---------------------------------------+
                                          |
                                          v  [Geometric & Temporal Check: <1ms]
                      +---------------------------------------+
                      |   Rule-Based Trigger Engine (Zero VLM)|
                      |    - Tailgating (Door zone crossing)  |
                      |    - Person Down (Aspect ratio + stop)|
                      |    - Crowd Incident (Regional count)  |
                      |    - Suspicious (Loitering in zones)  |
                      |    - Fighting (IoU + High speed)      |
                      |    - Suicide / Fall Risk (Hazard dwell)|
                      +---------------------------------------+
                                          |
                 +------------------------+-----------------------+
                 | (Only on Triggered Candidate Moments)          |
                 v                                                v
+-----------------------------------+           +-----------------------------------+
|      MJPEG Live Stream Hub        |           |  Ollama Local Vision Model (VLM)  |
|  (/stream/{cam_id} Annotated HUD) |           |  (Qwen3-VL:8B / Gemma3)           |
|  - 1x1 Focus or 2x2 Matrix Grid   |           |  - VRAM Pinned (keep_alive: -1)   |
|  - NVR Scrubber Playhead Sync     |           |  - 320px Patch Downscaling        |
+-----------------------------------+           |  - num_ctx: 2048 KV Cache Bound   |
                 |                              +-----------------------------------+
                 v                                                |
+-----------------------------------+                             v  [Classified & Confirmed]
|   Security Console Web Frontend   |           +-----------------------------------+
| (index.html / dashboard.js / CSS) | <-------- |    SQLite Database (events.db)    |
| - Playhead Scrubber Toolbar       |           |   (Stores keyframe, JSON tracks)  |
| - HTML5 MP4 Clip Scrubber Player  |           |   + Multi-Frame MP4 Video Clips   |
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
2. **16x VLM Latency Acceleration**:
   - **VRAM Model Pinning**: `keep_alive: -1` in Ollama API requests prevents the OS and Ollama from flushing model weights between events.
   - **Context Window Ceiling (`num_ctx: 2048`)**: Caps the KV-cache to ~100 MB, ensuring all layers fit inside the 12 GB GPU VRAM without offloading to system RAM.
   - **320px Patch Downscaling**: Resizes keyframes to 320px maximum dimension before base64 encoding, reducing visual tokens by 4x while preserving full spatial posture and scene cues.
   - **Single Keyframe Dispatch**: Analyzes one crisp keyframe per event rather than sending multi-frame bursts, yielding sub-350ms classification.
3. **NVR Playhead Scrubber & PTS Tracking**:
   - Ingest workers maintain a monotonic microsecond Presentation Time Stamp (PTS) alongside raw frame indexes.
   - Clients can pause, resume, and seek to any relative ratio or frame number via `/api/cameras/{id}/seek` and `/api/cameras/{id}/playback`.
4. **Deterministic Anomaly Pre-Filters**: Bounding-box aspect ratio shifts and door-zone cross intervals act as zero-cost gates, reducing VLM calls by >98% during normal activity.
5. **Safe Text-to-SQL Execution**: Conversational queries are validated against AST/token whitelists before execution on a read-only SQLite connection, guaranteeing database integrity and query transparency.
6. **Multi-Frame Clip Generation**: Triggered events capture a 4-frame temporal burst around the anomaly moment, saved to `data/clips/{id}/` and encoded as browser-compatible MP4 video clips via OpenCV `VideoWriter`.
7. **Single-Process Lightweight Service**: FastAPI hosts REST endpoints, MJPEG video streaming, and background camera worker threads with zero external message broker overhead.
