"""EventLens Dataset Benchmark & Verification Suite.

Tests real video files from D:\\ClaudeCode\\HackHive\\dataset (or data/videos):
- Measures exact YOLOv11 + ByteTrack throughput (FPS).
- Detects persons, tracks, and extracts motion trajectories.
- Evaluates rule-based trigger engine activations.
- Verifies playback speed and latency.
"""

import argparse
import glob
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List

# Ensure EventLens workspace root is in python path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import cv2

from backend.vision.detect_track import DetectorTracker
from backend.vision.triggers import TriggerEngine
from backend.vision.pipeline import load_camera_config, load_settings


def benchmark_video(
    video_path: Path,
    tracker: DetectorTracker,
    camera_id: str = "cam1",
    max_frames: int = 0,
) -> Dict[str, Any]:
    cam_config = load_camera_config(camera_id)
    trigger = TriggerEngine(camera_id=camera_id, config=cam_config)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return {"error": f"Failed to open video {video_path}"}

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    native_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration_sec = total_frames / native_fps if native_fps > 0 else 0.0

    frame_dt = 1.0 / native_fps
    sim_time = 0.0
    processed_count = 0
    person_counts = []
    unique_tracks = set()
    triggered_events = []

    t0 = time.time()

    while True:
        ret, frame = cap.read()
        if not ret or frame is None:
            break

        processed_count += 1
        sim_time += frame_dt

        # Run detection and tracking
        detections, _ = tracker.track(frame)
        p_count = len(detections)
        person_counts.append(p_count)

        for d in detections:
            unique_tracks.add(d["track_id"])

        # Check triggers
        candidates = trigger.update(detections, sim_time)
        if candidates:
            for c in candidates:
                triggered_events.append({
                    "frame": processed_count,
                    "video_time_sec": round(sim_time, 2),
                    "category": c.get("category_hint"),
                    "track_ids": c.get("track_ids", []),
                })

        if max_frames > 0 and processed_count >= max_frames:
            break

    cap.release()
    elapsed_wall = time.time() - t0
    real_fps = processed_count / elapsed_wall if elapsed_wall > 0 else 0.0

    avg_persons = sum(person_counts) / len(person_counts) if person_counts else 0.0
    max_persons = max(person_counts) if person_counts else 0

    return {
        "file_name": video_path.name,
        "file_path": str(video_path),
        "resolution": f"{width}x{height}",
        "total_frames": total_frames,
        "processed_frames": processed_count,
        "native_fps": round(native_fps, 1),
        "duration_sec": round(duration_sec, 2),
        "wall_time_sec": round(elapsed_wall, 2),
        "inference_fps": round(real_fps, 1),
        "speedup_vs_realtime": round(real_fps / native_fps, 2) if native_fps > 0 else 1.0,
        "avg_persons": round(avg_persons, 1),
        "max_persons": max_persons,
        "unique_track_ids_count": len(unique_tracks),
        "triggered_events_count": len(triggered_events),
        "triggered_events": triggered_events,
    }


def main():
    parser = argparse.ArgumentParser(description="EventLens Dataset Benchmark Suite")
    parser.add_argument(
        "--dir",
        type=str,
        default=r"D:\ClaudeCode\HackHive\dataset",
        help="Directory containing test dataset videos",
    )
    parser.add_argument(
        "--file",
        type=str,
        default=None,
        help="Optional single video file to test",
    )
    parser.add_argument(
        "--camera",
        type=str,
        default="cam1",
        help="Camera config profile to test against (default: cam1)",
    )
    args = parser.parse_args()

    settings = load_settings()
    yolo_model = settings.get("vision", {}).get("yolo_model", "yolo11s.pt")
    device = settings.get("vision", {}).get("device", "cuda:0")
    conf_thresh = float(settings.get("vision", {}).get("confidence_threshold", 0.25))

    print("=" * 80)
    print("EVENTLENS DATASET BENCHMARK & VERIFICATION")
    print(f"Hardware Device: {device} | YOLO Model: {yolo_model} | Conf Thresh: {conf_thresh}")
    print("=" * 80)

    # Initialize tracker once
    tracker = DetectorTracker(model_name=yolo_model, conf_thresh=conf_thresh, device=device)

    # Collect files
    if args.file:
        files = [Path(args.file)]
    else:
        dataset_dir = Path(args.dir)
        if not dataset_dir.exists():
            # Fallback to local data/videos
            dataset_dir = Path(__file__).resolve().parent.parent / "data" / "videos"
            print(f"Notice: {args.dir} not found, falling back to {dataset_dir}")

        files = sorted(dataset_dir.glob("*.mp4"))

    if not files:
        print(f"No video files found to benchmark in {args.dir}")
        return

    print(f"Discovered {len(files)} video clips to evaluate.\n")

    results = []
    for vf in files:
        print(f"--> Processing: {vf.name} ...")
        clip_tracker = DetectorTracker(model_name=yolo_model, conf_thresh=conf_thresh, device=device)
        res = benchmark_video(vf, tracker=clip_tracker, camera_id=args.camera)
        if "error" in res:
            print(f"    [ERROR] {res['error']}")
            continue
        results.append(res)
        print(
            f"    Done: {res['processed_frames']} frames in {res['wall_time_sec']}s "
            f"({res['inference_fps']} FPS, {res['speedup_vs_realtime']}x real-time) | "
            f"Persons: max={res['max_persons']}, avg={res['avg_persons']} | "
            f"Events Triggered: {res['triggered_events_count']}"
        )
        for ev in res["triggered_events"]:
            print(f"      * [{ev['video_time_sec']}s] Category: {ev['category']} (tracks: {ev['track_ids']})")
        print()

    # Print summary table
    print("=" * 80)
    print(f"{'CLIP NAME':<34} | {'RES':<9} | {'FPS':<6} | {'INF FPS':<8} | {'PERSONS':<8} | {'EVENTS'}")
    print("-" * 80)
    for r in results:
        p_str = f"max {r['max_persons']}"
        ev_str = f"{r['triggered_events_count']} triggered"
        print(
            f"{r['file_name'][:34]:<34} | {r['resolution']:<9} | {r['native_fps']:<6} | "
            f"{r['inference_fps']:<8} | {p_str:<8} | {ev_str}"
        )
    print("=" * 80)

    # Save results
    out_dir = Path(__file__).resolve().parent / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / "dataset_benchmark.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nDetailed benchmark report saved to: {out_json}")


if __name__ == "__main__":
    main()
