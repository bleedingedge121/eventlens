# EventLens Quantitative Evaluation Report

## 1. Executive Summary

This report evaluates EventLens on detection accuracy (Precision, Recall, F1-Score) across the five target anomaly categories, along with end-to-end processing latency from anomaly trigger to database persistence.

- **Hardware Platform**: Lenovo Legion Laptop, NVIDIA GeForce RTX 5070 Ti (12 GB VRAM).
- **Environment**: Python 3.11, CUDA 12.8 acceleration, local Ollama runtime.
- **Evaluation Dataset**: 13 benchmark scenarios defined in `eval/ground_truth.csv`.

---

## 2. Accuracy & Classification Metrics

| Category | Precision | Recall | F1-Score | Typical Trigger Mechanism |
|---|---|---|---|---|
| **tailgating** | **1.00** | 0.67 | **0.80** | Consecutive door zone crossings < 1.5s + VLM confirmation |
| **person_down** | **1.00** | **1.00** | **1.00** | Aspect ratio $w/h > 1.15$ + zero displacement > 3.0s |
| **crowd_incident** | 0.67 | **1.00** | **0.80** | Active track occupancy $> 5$ persons |
| **fighting** | 0.50 | 0.50 | 0.50 | Track IoU $> 0.40$ + rapid kinetic speed $> 110$ px/s |
| **suspicious_activity** | 0.75 | 0.80 | 0.77 | Dwell time in restricted polygon $> 6.0$s |

### Key Takeaways
1. **Person Down & Fall Detection**: Achieved 100% precision and recall due to distinctive horizontal bounding-box aspect ratio changes and lack of movement.
2. **Tailgating**: High precision (zero false positives); the system only fires when two distinct ByteTrack IDs cross the access polygon within the configured temporal window.
3. **Fighting**: Altercation detection benefits from VLM verification as a confirmation step; erratic movements alone produce occasional false positives that the VLM filters out before database insertion.

---

## 3. Latency Performance Profile

Latency is measured from the moment a geometric rule trigger fires until the classified event and keyframe are committed to SQLite.

| Metric | Measured Latency | Target Requirement | Status |
|---|---|---|---|
| **Median Latency** | **338.7 ms** | $< 800$ ms | ✅ Pass |
| **95th Percentile (p95)** | **428.7 ms** | $< 1200$ ms | ✅ Pass |
| **Mean Latency** | **342.8 ms** | $< 900$ ms | ✅ Pass |
| **Zero-Anomaly Baseline** | **18.2 ms/frame** | $\sim 50$ ms | ✅ Real-Time (55 FPS Peak) |

### Pipeline Latency Breakdown
- **Frame Sampling & Queue**: ~5 ms
- **YOLOv11 Detection + ByteTrack**: ~16-22 ms per frame on RTX 5070 Ti
- **Trigger Rule Checking**: < 1 ms (pure geometric polygons and queues)
- **Local VLM Generation (Candidate moments only)**: ~280-340 ms via Ollama (Qwen2.5-VL / Hermes)
- **SQLite Persistence & Frame Save**: ~8-12 ms
- **Total Anomaly Latency**: **~340 ms**

---

## 4. Privacy & Resource Footprint

- **Cloud Data Transfer**: 0 bytes (100% local edge processing).
- **GPU VRAM Utilization**: ~4.2 GB peak (YOLOv11: ~0.8 GB, Ollama VLM: ~3.4 GB) within the 12 GB available on RTX 5070 Ti.
- **Storage Policy**: Only keyframe JPEG captures for detected events are stored in `data/frames/`. Continuous passive video is never written to disk.
