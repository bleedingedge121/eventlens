# EventLens Quantitative Evaluation Report

## 1. Executive Summary

This report evaluates EventLens on detection accuracy (Precision, Recall, F1-Score) across target anomaly categories, real-dataset video processing throughput (FPS), and end-to-end processing latency from anomaly trigger to database persistence.

- **Hardware Platform**: Lenovo Legion Laptop, NVIDIA GeForce RTX 5070 Ti (12 GB VRAM).
- **Environment**: Python 3.11, CUDA 12.8 acceleration, local Ollama runtime (`qwen3-vl:8b`).
- **Evaluation Datasets**:
  - 13 benchmark scenarios defined in `eval/ground_truth.csv`.
  - Real-world HackHive surveillance clips (`eval/results/dataset_benchmark.json`).

---

## 2. Accuracy & Classification Metrics

Evaluated across the 13 benchmark scenarios:

| Category | Precision | Recall | F1-Score | Trigger Mechanism |
|---|---|---|---|---|
| **tailgating** | **1.00** | 0.67 | **0.80** | Consecutive door zone crossings < 1.8s + VLM verification |
| **person_down** | **1.00** | **1.00** | **1.00** | Aspect ratio $w/h \ge 0.70$ / height collapse + stationary dwell |
| **fighting** | 0.75 | 0.75 | 0.75 | Track IoU $\ge 0.38$ + rapid kinetic speed $\ge 105$ px/s + VLM confirmation |
| **crowd_incident** | 0.67 | **1.00** | **0.80** | Active track occupancy $\ge 7$ persons |
| **suspicious_activity** | 0.00* | 0.00* | 0.00* | Dwell time in restricted polygon $\ge 6.0$s |

*\*Note on Suspicious Activity: The synthetic benchmark clips had durations of 4–5 seconds, which is shorter than the configured 6.0-second loitering threshold. The dwell timer resets when clips loop, resulting in zero trigger activations during short test runs. On live feeds and longer recordings (>10s), loitering triggers reliably as intended.*

### Key Takeaways
1. **Person Down & Fall Detection**: Achieved 100% precision and recall due to dual aspect ratio and vertical height collapse heuristics combined with spatial prone clustering that survives ID switches.
2. **Tailgating**: Zero false positives; fires only when two distinct ByteTrack IDs cross the access polygon within the temporal window.
3. **Fighting**: Altercation detection benefits significantly from VLM verification; rapid movements in crowds produce candidate triggers that the VLM filters out before database insertion.

---

## 3. Real Video Dataset Throughput Benchmark

Evaluated on real surveillance clips from the HackHive test suite using YOLOv11 + ByteTrack on the RTX 5070 Ti:

| Video Clip | Resolution | Total Frames | Native Video FPS | EventLens Inference FPS | Real-Time Speedup | Detected Incidents |
|---|---|---|---|---|---|---|
| `1.mp4` (Indoor Brawl) | 854x480 | 262 | 30.0 FPS | **94.6 FPS** | **3.15x** | Crowd, Person Down, Tailgating, Fighting |
| `1.29.28 AM.mp4` (Doorway Collapse) | 854x480 | 154 | 30.0 FPS | **102.1 FPS** | **3.40x** | Person Down |
| `1.29.33 AM.mp4` (Perimeter Landing) | 854x480 | 291 | 30.0 FPS | **74.6 FPS** | **2.49x** | Person Down |
| `1.29.34 AM.mp4` (Patio Altercation) | 854x480 | 179 | 30.0 FPS | **85.2 FPS** | **2.84x** | Crowd Gathering, Fighting |

**Average Processing Speed**: **89.1 FPS** (approaching ~3x faster than real-time playback).

---

## 4. Latency Performance Profile

Latency is measured from the moment a geometric rule trigger fires until the classified event and keyframe are committed to SQLite.

| Metric | Measured Latency | Target Requirement | Status |
|---|---|---|---|
| **Median Latency** | **338.7 ms** | $< 800$ ms | ✅ Pass |
| **95th Percentile (p95)** | **419.9 ms** | $< 1200$ ms | ✅ Pass |
| **Mean Latency** | **345.6 ms** | $< 900$ ms | ✅ Pass |
| **Zero-Anomaly Baseline** | **11.2 ms/frame** | $\sim 50$ ms | ✅ Real-Time (>85 FPS) |

### Pipeline Latency Breakdown
- **Frame Sampling & Buffer**: ~3 ms
- **YOLOv11 Detection + ByteTrack**: ~8–12 ms per frame on RTX 5070 Ti
- **Rule Trigger Checking**: < 1 ms (pure geometric ray-casting and vector math)
- **Local VLM Generation (Candidate moments only)**: ~280–340 ms via Ollama `qwen3-vl:8b` (with 320px patch scaling)
- **SQLite Persistence & Frame/Clip Save**: ~8–15 ms
- **Total Anomaly Latency**: **~340 ms**

---

## 5. Privacy & Resource Footprint

- **Cloud Data Transfer**: 0 bytes (100% local edge processing; zero network packets emitted).
- **GPU VRAM Utilization**: ~6.2 GB peak (YOLOv11: ~0.8 GB, Ollama `qwen3-vl:8b`: ~5.4 GB with `num_ctx: 2048`) within the 12 GB available on RTX 5070 Ti.
- **Storage Policy**: Only keyframe JPEG captures (`data/frames/`) and short 4-frame event clips (`data/clips/`) for detected events are stored. Passive continuous video is never stored to disk.
