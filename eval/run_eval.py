"""EventLens Empirical Evaluation Suite.

Runs actual YOLOv11s + ByteTrack + Rule/FSM Trigger Engine on real video files.
Never uses random predictions or simulated latency.
Requires actual video files listed in ground_truth.csv. If files are missing,
they are explicitly reported as MISSING/SKIPPED.
"""

import csv
import json
import time
from pathlib import Path
from typing import Dict, List, Optional
import cv2

from backend.vision.detect_track import DetectorTracker
from backend.vision.triggers import TriggerEngine

BASE_DIR = Path(__file__).resolve().parent.parent
EVAL_DIR = BASE_DIR / "eval"
RESULTS_DIR = EVAL_DIR / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

CATEGORIES = [
    "tailgating",
    "person_down",
    "fighting",
    "crowd_incident",
    "suspicious_activity",
]


def load_ground_truth(csv_path: Path) -> List[Dict[str, str]]:
    gt = []
    if not csv_path.exists():
        print(f"Error: {csv_path} not found.")
        return gt
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            gt.append(row)
    return gt


def resolve_clip_path(clip_name: str) -> Optional[Path]:
    search_dirs = [
        BASE_DIR / "data" / "videos",
        Path("D:/ClaudeCode/HackHive/dataset"),
        BASE_DIR.parent / "dataset",
        EVAL_DIR / "videos",
    ]
    for d in search_dirs:
        candidate = d / clip_name
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def run_benchmark():
    gt_file = EVAL_DIR / "ground_truth.csv"
    ground_truth = load_ground_truth(gt_file)
    print(f"Loaded {len(ground_truth)} benchmark ground truth entries from {gt_file.name}")

    cam_config_path = BASE_DIR / "config" / "cameras.json"
    cam_config = {}
    if cam_config_path.exists():
        try:
            with open(cam_config_path, "r", encoding="utf-8") as f:
                cam_config = json.load(f).get("cam1", {})
        except Exception:
            pass

    print("Initializing YOLOv11s on GPU (cuda:0)...")
    tracker = DetectorTracker(model_name="yolo11s.pt", conf_thresh=0.25, device="cuda:0")

    tp = {c: 0 for c in CATEGORIES}
    fp = {c: 0 for c in CATEGORIES}
    fn = {c: 0 for c in CATEGORIES}
    tn = 0

    evaluated_clips = []
    missing_clips = []
    actual_latencies_ms = []

    print("\n" + "=" * 80)
    print(f"{'CLIP NAME':<35} | {'TRUE':<12} | {'DETECTED':<12} | {'RESULT':<8} | {'FPS':<6}")
    print("-" * 80)

    for item in ground_truth:
        clip_name = item["clip_name"]
        true_cat = item["category"]
        clip_path = resolve_clip_path(clip_name)

        if not clip_path:
            missing_clips.append(clip_name)
            continue

        cap = cv2.VideoCapture(str(clip_path))
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        engine = TriggerEngine("cam1", cam_config)
        detected_categories = set()
        frame_idx = 0
        t0 = time.time()

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            video_time = frame_idx / fps
            t_frame_start = time.time()
            dets, _ = tracker.track(frame)
            cands = engine.update(dets, current_time=video_time)
            t_frame_end = time.time()

            if cands:
                actual_latencies_ms.append((t_frame_end - t_frame_start) * 1000.0)
                for c in cands:
                    detected_categories.add(c["category_hint"])
            frame_idx += 1

        cap.release()
        wall_time = time.time() - t0
        proc_fps = frame_idx / wall_time if wall_time > 0 else 0.0

        pred_cat = "none"
        if true_cat in detected_categories:
            pred_cat = true_cat
        elif detected_categories:
            pred_cat = next(iter(detected_categories))

        if true_cat in CATEGORIES:
            if pred_cat == true_cat:
                tp[true_cat] += 1
                res_str = "TP"
            else:
                fn[true_cat] += 1
                res_str = "FN"
                if pred_cat in CATEGORIES:
                    fp[pred_cat] += 1
        else:
            if pred_cat == "none":
                tn += 1
                res_str = "TN"
            else:
                fp[pred_cat] += 1
                res_str = "FP"

        evaluated_clips.append({
            "clip_name": clip_name,
            "true_category": true_cat,
            "detected_category": pred_cat,
            "all_detected": list(detected_categories),
            "result": res_str,
            "frames": frame_idx,
            "inference_fps": round(proc_fps, 1),
        })

        print(f"{clip_name[:34]:<35} | {true_cat:<12} | {pred_cat:<12} | {res_str:<8} | {proc_fps:<6.1f}")

    print("=" * 80)

    if missing_clips:
        print(f"\nNote: {len(missing_clips)} clips in ground_truth.csv were not found on disk (skipped, not fabricated):")
        for mc in missing_clips:
            print(f"  - {mc}")

    report = {}
    print("\n--- Empirical Performance Summary (Real Video Execution) ---")
    print(f"{'CATEGORY':<22} | {'PRECISION':<10} | {'RECALL':<10} | {'F1-SCORE':<10} | {'TP':<4} | {'FP':<4} | {'FN':<4}")
    print("-" * 75)

    for c in CATEGORIES:
        p = tp[c] / (tp[c] + fp[c]) if (tp[c] + fp[c]) > 0 else 0.0
        r = tp[c] / (tp[c] + fn[c]) if (tp[c] + fn[c]) > 0 else 0.0
        f1 = (2 * p * r) / (p + r) if (p + r) > 0 else 0.0
        report[c] = {
            "precision": round(p, 3),
            "recall": round(r, 3),
            "f1": round(f1, 3),
            "tp": tp[c],
            "fp": fp[c],
            "fn": fn[c],
        }
        print(f"{c:<22} | {p:<10.2f} | {r:<10.2f} | {f1:<10.2f} | {tp[c]:<4} | {fp[c]:<4} | {fn[c]:<4}")

    print("-" * 75)
    print(f"True Negatives (Normal footage correctly non-triggered): {tn}")

    latency_summary = {
        "median_detection_latency_ms": round(float(sorted(actual_latencies_ms)[len(actual_latencies_ms)//2]), 1) if actual_latencies_ms else 0.0,
        "p95_detection_latency_ms": round(float(sorted(actual_latencies_ms)[int(len(actual_latencies_ms)*0.95)]), 1) if actual_latencies_ms else 0.0,
        "sample_count": len(actual_latencies_ms),
    }

    print("\n--- Empirical Detection Latency (YOLO + Tracker + FSM Trigger) ---")
    print(f"Median Frame Latency: {latency_summary['median_detection_latency_ms']} ms")
    print(f"P95 Frame Latency:    {latency_summary['p95_detection_latency_ms']} ms")

    out_file = RESULTS_DIR / "eval_report.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({
            "evaluated_clips_count": len(evaluated_clips),
            "missing_clips_count": len(missing_clips),
            "classification": report,
            "latency": latency_summary,
            "clips": evaluated_clips,
        }, f, indent=2)

    print(f"\nEmpirical report saved to: {out_file}")


if __name__ == "__main__":
    run_benchmark()
