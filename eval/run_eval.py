"""EventLens Evaluation Suite.

Authentic pipeline benchmarking according to AGENTS.md Section 16:
- Computes True Positives (TP), False Positives (FP), False Negatives (FN).
- Computes Precision, Recall, and F1-score per category and overall.
- Measures real monotonic execution latencies (median, p95, min, max, mean).
- Rejects fabricated random generation; tests against actual dataset videos.
- If datasets are missing, gracefully outputs diagnostic reports without fabricating scores.
"""

import argparse
import csv
import json
import logging
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Tuple
import cv2
import numpy as np

# Ensure root workspace is on python path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from backend.vision.detect_track import DetectorTracker
from backend.vision.triggers import TriggerEngine
from backend.vision.pipeline import load_camera_config, load_settings
from backend.server.vlm import VLMClient

logger = logging.getLogger("eventlens.eval")

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


def load_ground_truth(csv_path: Path) -> List[Dict[str, Any]]:
    """Loads ground-truth CSV containing: clip_name, category, start_sec, description."""
    gt = []
    if not csv_path.exists():
        logger.warning(f"Ground truth file not found: {csv_path}")
        return gt

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                start_sec = float(row.get("start_sec", 0.0))
            except (ValueError, TypeError):
                start_sec = 0.0

            gt.append({
                "clip_name": row.get("clip_name", "").strip(),
                "category": row.get("category", "none").strip(),
                "start_sec": start_sec,
                "description": row.get("description", "").strip(),
            })
    return gt


def find_video_clip(clip_name: str, search_dirs: List[Path]) -> Optional[Path]:
    """Finds clip_name across prioritized search directories."""
    for d in search_dirs:
        candidate = d / clip_name
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def calculate_metrics_from_counts(
    tp: Dict[str, int],
    fp: Dict[str, int],
    fn: Dict[str, int],
    categories: List[str] = CATEGORIES,
) -> Dict[str, Dict[str, float]]:
    """Calculates precision, recall, and F1 given TP, FP, FN per category."""
    report = {}
    for c in categories:
        c_tp = tp.get(c, 0)
        c_fp = fp.get(c, 0)
        c_fn = fn.get(c, 0)

        p = c_tp / (c_tp + c_fp) if (c_tp + c_fp) > 0 else 0.0
        r = c_tp / (c_tp + c_fn) if (c_tp + c_fn) > 0 else 0.0
        f1 = (2 * p * r) / (p + r) if (p + r) > 0 else 0.0

        report[c] = {
            "tp": c_tp,
            "fp": c_fp,
            "fn": c_fn,
            "precision": round(p, 3),
            "recall": round(r, 3),
            "f1": round(f1, 3),
        }

    # Macro averages
    all_tp = sum(tp.values())
    all_fp = sum(fp.values())
    all_fn = sum(fn.values())
    macro_p = all_tp / (all_tp + all_fp) if (all_tp + all_fp) > 0 else 0.0
    macro_r = all_tp / (all_tp + all_fn) if (all_tp + all_fn) > 0 else 0.0
    macro_f1 = (2 * macro_p * macro_r) / (macro_p + macro_r) if (macro_p + macro_r) > 0 else 0.0

    report["overall"] = {
        "tp": all_tp,
        "fp": all_fp,
        "fn": all_fn,
        "precision": round(macro_p, 3),
        "recall": round(macro_r, 3),
        "f1": round(macro_f1, 3),
    }
    return report


def compute_latency_percentiles(latencies: List[float]) -> Dict[str, Any]:
    """Calculates true latency percentiles from measured times."""
    if not latencies:
        return {
            "samples": 0,
            "median_latency_ms": 0.0,
            "p95_latency_ms": 0.0,
            "mean_latency_ms": 0.0,
            "min_latency_ms": 0.0,
            "max_latency_ms": 0.0,
        }

    arr = np.array(latencies, dtype=float)
    return {
        "samples": len(latencies),
        "median_latency_ms": round(float(np.median(arr)), 1),
        "p95_latency_ms": round(float(np.percentile(arr, 95)), 1),
        "mean_latency_ms": round(float(np.mean(arr)), 1),
        "min_latency_ms": round(float(np.min(arr)), 1),
        "max_latency_ms": round(float(np.max(arr)), 1),
    }


def evaluate_single_video(
    video_path: Path,
    tracker: DetectorTracker,
    trigger_engine: TriggerEngine,
    vlm_client: Optional[VLMClient] = None,
    max_frames: int = 0,
) -> Tuple[List[Dict[str, Any]], List[float], Dict[str, Any]]:
    """Executes actual video through YOLO + ByteTrack + Triggers (+ optional VLM).

    Returns:
        (detected_events, measured_latencies, clip_stats)
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return [], [], {"error": f"Could not open {video_path}"}

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    native_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    dt = 1.0 / native_fps if native_fps > 0 else 0.04

    sim_time = 0.0
    processed = 0
    detected_events: List[Dict[str, Any]] = []
    latencies: List[float] = []

    t_start = time.perf_counter()

    while True:
        ret, frame = cap.read()
        if not ret or frame is None:
            break

        processed += 1
        sim_time += dt

        step_t0 = time.perf_counter()
        detections, _ = tracker.track(frame)
        candidates = trigger_engine.update(detections, sim_time)

        if candidates:
            for cand in candidates:
                # Add context frames
                cand["frames"] = [frame]
                cand["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S")

                vlm_t0 = time.perf_counter()
                if vlm_client is not None:
                    vlm_res = vlm_client.describe_event(cand)
                    vlm_lat = (time.perf_counter() - vlm_t0) * 1000.0
                    total_event_lat = (time.perf_counter() - step_t0) * 1000.0
                    latencies.append(total_event_lat)

                    if vlm_res.get("verified", False):
                        detected_events.append({
                            "category": vlm_res.get("category") or cand.get("category_hint"),
                            "time_sec": sim_time,
                            "confidence": vlm_res.get("confidence", 0.0),
                            "latency_ms": total_event_lat,
                            "vlm_latency_ms": vlm_lat,
                            "verified": True,
                        })
                else:
                    # Trigger-only latency
                    trig_lat = (time.perf_counter() - step_t0) * 1000.0
                    latencies.append(trig_lat)
                    detected_events.append({
                        "category": cand.get("category_hint"),
                        "time_sec": sim_time,
                        "confidence": 0.85,
                        "latency_ms": trig_lat,
                        "verified": True,
                    })

        if max_frames > 0 and processed >= max_frames:
            break

    cap.release()
    total_elapsed = time.perf_counter() - t_start
    real_fps = processed / total_elapsed if total_elapsed > 0 else 0.0

    return detected_events, latencies, {
        "processed_frames": processed,
        "total_frames": total_frames,
        "native_fps": native_fps,
        "inference_fps": round(real_fps, 1),
        "wall_time_sec": round(total_elapsed, 2),
    }


def evaluate_dataset(
    gt_entries: List[Dict[str, Any]],
    search_dirs: List[Path],
    camera_id: str = "cam1",
    with_vlm: bool = False,
    max_frames: int = 0,
    time_tolerance_sec: float = 3.5,
) -> Dict[str, Any]:
    """Runs actual evaluation over all discovered video files against ground-truth."""
    settings = load_settings()
    yolo_model = settings.get("vision", {}).get("yolo_model", "yolo11s.pt")
    device = settings.get("vision", {}).get("device", "cuda:0")
    conf_thresh = float(settings.get("vision", {}).get("confidence_threshold", 0.35))

    tracker = DetectorTracker(model_name=yolo_model, conf_thresh=conf_thresh, device=device)
    vlm_client = VLMClient() if with_vlm else None

    tp = {c: 0 for c in CATEGORIES}
    fp = {c: 0 for c in CATEGORIES}
    fn = {c: 0 for c in CATEGORIES}
    all_latencies: List[float] = []

    evaluated_clips: List[Dict[str, Any]] = []
    missing_clips: List[str] = []

    for gt in gt_entries:
        clip_name = gt["clip_name"]
        true_cat = gt["category"]
        gt_time = gt["start_sec"]

        clip_path = find_video_clip(clip_name, search_dirs)
        if not clip_path:
            missing_clips.append(clip_name)
            continue

        cam_config = load_camera_config(camera_id)
        trigger_engine = TriggerEngine(camera_id=camera_id, config=cam_config)

        detections, latencies, clip_stats = evaluate_single_video(
            video_path=clip_path,
            tracker=tracker,
            trigger_engine=trigger_engine,
            vlm_client=vlm_client,
            max_frames=max_frames,
        )
        all_latencies.extend(latencies)

        # Match detections to ground truth
        matched = False
        for det in detections:
            pred_cat = det["category"]
            pred_time = det["time_sec"]

            if true_cat == "none":
                # Any detection on a negative clip is a false positive
                if pred_cat in CATEGORIES:
                    fp[pred_cat] += 1
            else:
                if pred_cat == true_cat:
                    # Check temporal tolerance
                    if abs(pred_time - gt_time) <= time_tolerance_sec:
                        if not matched:
                            tp[true_cat] += 1
                            matched = True
                    else:
                        # Event fired outside event window -> false positive
                        fp[pred_cat] += 1
                elif pred_cat in CATEGORIES:
                    fp[pred_cat] += 1

        if true_cat in CATEGORIES and not matched:
            fn[true_cat] += 1

        evaluated_clips.append({
            "clip_name": clip_name,
            "true_category": true_cat,
            "detections_count": len(detections),
            "matched": matched,
            "stats": clip_stats,
        })

    metrics = calculate_metrics_from_counts(tp, fp, fn)
    latency_summary = compute_latency_percentiles(all_latencies)

    return {
        "evaluated_clips_count": len(evaluated_clips),
        "missing_clips_count": len(missing_clips),
        "missing_clips": missing_clips,
        "classification": metrics,
        "latency": latency_summary,
        "evaluated_clips": evaluated_clips,
        "is_simulated": False,
    }


def run_simulation_mode(gt_entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Offline deterministic simulation mode for headless CI environments only.

    Explicitly labeled as simulation; never fakes real camera performance.
    """
    logger.info("Running offline simulation mode (CI/Mock testing)...")
    tp = {c: 0 for c in CATEGORIES}
    fp = {c: 0 for c in CATEGORIES}
    fn = {c: 0 for c in CATEGORIES}

    # Deterministic calculation based on ground-truth structure
    for item in gt_entries:
        cat = item["category"]
        if cat in CATEGORIES:
            tp[cat] += 1
        elif cat == "none":
            pass

    metrics = calculate_metrics_from_counts(tp, fp, fn)

    return {
        "is_simulated": True,
        "warning": "OFFLINE SIMULATION ONLY - NO VIDEO INGESTION OR REAL INFERENCE EXECUTED",
        "evaluated_clips_count": len(gt_entries),
        "missing_clips_count": 0,
        "classification": metrics,
        "latency": {
            "samples": 0,
            "median_latency_ms": 0.0,
            "p95_latency_ms": 0.0,
            "mean_latency_ms": 0.0,
        },
    }


def main():
    parser = argparse.ArgumentParser(description="EventLens Authentic Evaluation Suite")
    parser.add_argument(
        "--gt",
        type=str,
        default=str(EVAL_DIR / "ground_truth.csv"),
        help="Path to ground truth CSV",
    )
    parser.add_argument(
        "--video-dir",
        type=str,
        default=None,
        help="Optional directory to search for video files",
    )
    parser.add_argument(
        "--camera",
        type=str,
        default="cam1",
        help="Camera configuration profile (default: cam1)",
    )
    parser.add_argument(
        "--with-vlm",
        action="store_true",
        help="Run real VLM verification via Ollama (requires Ollama running)",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=0,
        help="Limit frames per clip for rapid testing (0 = full clip)",
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Explicitly run offline simulation mode without video dependencies",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(RESULTS_DIR / "eval_report.json"),
        help="Output JSON report path",
    )
    args = parser.parse_args()

    gt_file = Path(args.gt)
    ground_truth = load_ground_truth(gt_file)
    print(f"Loaded {len(ground_truth)} ground truth entries from {gt_file}")

    if args.simulate:
        report = run_simulation_mode(ground_truth)
    else:
        # Assemble search directories
        search_dirs = []
        if args.video_dir:
            search_dirs.append(Path(args.video_dir))
        search_dirs.extend([
            BASE_DIR / "data" / "videos",
            EVAL_DIR / "dataset",
            Path("D:/ClaudeCode/HackHive/dataset"),
            BASE_DIR.parent / "dataset",
        ])

        print(f"Searching for video clips across {len(search_dirs)} paths...")
        report = evaluate_dataset(
            gt_entries=ground_truth,
            search_dirs=search_dirs,
            camera_id=args.camera,
            with_vlm=args.with_vlm,
            max_frames=args.max_frames,
        )

        if report["evaluated_clips_count"] == 0:
            print("\n" + "!" * 70)
            print("[WARNING] Zero matching video clips could be found on disk.")
            print(f"Missing clips ({report['missing_clips_count']}): {', '.join(report['missing_clips'][:5])}...")
            print("To generate synthetic test clips, run: python scripts/generate_test_clips.py")
            print("To run offline simulation for CI, pass the --simulate flag.")
            print("!" * 70 + "\n")

    # Display results table
    print("\n" + "=" * 70)
    print(f"{'CATEGORY':<22} | {'TP':<4} | {'FP':<4} | {'FN':<4} | {'PRECISION':<9} | {'RECALL':<8} | {'F1'}")
    print("-" * 70)
    for c in CATEGORIES:
        cls_data = report["classification"].get(c, {})
        tp_v = cls_data.get("tp", 0)
        fp_v = cls_data.get("fp", 0)
        fn_v = cls_data.get("fn", 0)
        p = cls_data.get("precision", 0.0)
        r = cls_data.get("recall", 0.0)
        f1 = cls_data.get("f1", 0.0)
        print(f"{c:<22} | {tp_v:<4} | {fp_v:<4} | {fn_v:<4} | {p:<9.2f} | {r:<8.2f} | {f1:.2f}")

    print("-" * 70)
    overall = report["classification"].get("overall", {})
    print(
        f"{'OVERALL':<22} | {overall.get('tp',0):<4} | {overall.get('fp',0):<4} | {overall.get('fn',0):<4} | "
        f"{overall.get('precision',0.0):<9.2f} | {overall.get('recall',0.0):<8.2f} | {overall.get('f1',0.0):.2f}"
    )
    print("=" * 70)

    # Latency Stats
    lat = report["latency"]
    print(f"\n--- Latency Performance (Samples: {lat.get('samples', 0)}) ---")
    print(f"Median Latency:       {lat.get('median_latency_ms', 0.0)} ms")
    print(f"95th Percentile (p95):{lat.get('p95_latency_ms', 0.0)} ms")
    print(f"Mean Latency:         {lat.get('mean_latency_ms', 0.0)} ms")
    if "min_latency_ms" in lat:
        print(f"Min / Max Latency:    {lat.get('min_latency_ms', 0.0)} ms / {lat.get('max_latency_ms', 0.0)} ms")

    # Save output
    out_file = Path(args.output)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"\nDetailed evaluation report saved to: {out_file}")


if __name__ == "__main__":
    main()
