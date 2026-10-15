# EventLens: project brief for AI agents

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
