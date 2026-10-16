# EventLens Hackathon Demo Script (3-4 Minutes)

Designed for the HackHive 2026 judging presentation (Problem Statement 3).

---

### Step 1: The Problem & Our Approach (45 Seconds)
- **Speaker**: "Traditional CCTV systems record petabytes of passive video footage that nobody watches until after a security breach has already occurred. Cloud-based video LLM solutions are expensive, leak confidential visual data offsite, and have high latency."
- **Visual**: Show the EventLens Operations Console dashboard running on the laptop.
- **Key Point**: "EventLens is an open-source, edge-native surveillance intelligence platform. It runs 100% offline on this single Lenovo Legion RTX 5070 Ti laptop. Nothing ever leaves this machine."

---

### Step 2: Live Detection & Selective VLM Architecture (60 Seconds)
- **Action**: Switch to Camera 1 view.
- **Speaker**: "How do we run high-accuracy video understanding on a consumer laptop? Running an 8B VLM at 30 FPS would instantly crash VRAM. Instead, our zero-latency YOLO + ByteTrack pipeline tracks individuals with deterministic geometric rules at ~90 FPS."
- **Action**: Trigger or play a tailgating / person down simulation.
- **Speaker**: "The moment a rule trigger fires, candidate keyframes are dispatched to our local Ollama vision model (Qwen3-VL:8B). With 16x VRAM pinning and 320px patch scaling, the VLM verifies the event, confirms classification, and generates an audit summary in just ~340 milliseconds."

---

### Step 3: Surveillance NVR Scrubber & Multi-Camera Matrix (45 Seconds)
- **Action**: Click the **Grid** button to show the 2x2 multi-camera matrix.
- **Speaker**: "Notice our multi-camera matrix for simultaneous monitoring. Now let's switch back and use our NVR scrubber toolbar below the video."
- **Action**: Pause the stream (<kbd>Space</kbd>) and drag the scrubber slider back to view previous frames; point to the incident markers on the timeline.
- **Speaker**: "Security officers can pause, step frame-by-frame, and seek directly to exact incident markers with microsecond PTS tracking."

---

### Step 4: Conversational Natural Language Querying (60 Seconds)
- **Action**: Click over to `chat.html`.
- **Query 1**: Click *"Show all tailgating events from camera 1 today"*.
- **Speaker**: "Security operators shouldn't have to write database queries. They can ask questions in plain English. Notice how EventLens translates the request into a strictly validated, read-only SQL query, executes it against local SQLite, and displays matching incident keyframes."
- **Query 2**: Type *"Did anyone fall down on camera 2?"* and inspect the returned event card.

---

### Step 5: Quantitative Accuracy, Latency & Limitations (30 Seconds)
- **Visual**: Show the evaluation report from `docs/SYSTEM_REPORT.md` and `docs/EVALUATION.md`.
- **Speaker**: "Our benchmark across 13 annotated security scenarios demonstrates an average median latency of 338 ms and 100% recall on slip-and-fall incidents. We have documented all edge cases and known limitations openly in our system report."

---

### Step 6: Conclusion & Offline Privacy Guarantee (15 Seconds)
- **Speaker**: "Complete data privacy, immediate incident awareness, open-source stack, and edge deployment on one consumer laptop. Thank you!"
