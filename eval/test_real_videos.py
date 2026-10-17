"""Evaluates person-down detection against real video clips."""
import sys
import time
from pathlib import Path
import cv2

from backend.vision.detect_track import DetectorTracker
from backend.vision.triggers import TriggerEngine

def evaluate_video(video_path: str):
    p = Path(video_path)
    if not p.exists():
        print(f"Error: {video_path} does not exist.")
        return

    cap = cv2.VideoCapture(str(p))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"\nEvaluating: {p.name} ({total_frames} frames, {fps:.1f} FPS)")

    tracker = DetectorTracker(model_name="yolo11s.pt", conf_thresh=0.25, device="cuda:0")
    engine = TriggerEngine("cam1", {
        "person_down_aspect_ratio_threshold": 0.85,
        "person_down_height_collapse_ratio": 0.60,
        "person_down_min_upright_frames": 4,
        "person_down_transition_frames": 3,
        "person_down_still_seconds": 1.5,
        "person_down_motion_threshold_ratio": 0.15,
        "person_down_recovery_aspect_thresh": 0.65,
    })

    frame_idx = 0
    emitted = []
    t0 = time.time()

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
        video_time = frame_idx / fps
        dets, _ = tracker.track(frame)
        cands = engine.update(dets, current_time=video_time)
        if cands:
            for c in cands:
                cat = c.get("category_hint")
                trks = c.get("track_ids")
                print(f"  -> Event triggered at frame {frame_idx} (t={video_time:.2f}s): {cat} | Tracks: {trks}")
                emitted.append((frame_idx, video_time, cat, trks))
        frame_idx += 1

    cap.release()
    elapsed = time.time() - t0
    speed = frame_idx / elapsed if elapsed > 0 else 0
    print(f"Done: {frame_idx} frames processed in {elapsed:.2f}s ({speed:.1f} FPS). Total triggers: {len(emitted)}")
    return emitted

if __name__ == "__main__":
    videos = [
        "data/videos/test_normal.mp4",
        "data/videos/test_person_down.mp4",
    ]
    if Path("D:/ClaudeCode/HackHive/dataset/WhatsApp Video 2026-10-16 at 1.29.28 AM.mp4").exists():
        videos.append("D:/ClaudeCode/HackHive/dataset/WhatsApp Video 2026-10-16 at 1.29.28 AM.mp4")
    if Path("D:/ClaudeCode/HackHive/dataset/WhatsApp Video 2026-10-16 at 1.29.33 AM.mp4").exists():
        videos.append("D:/ClaudeCode/HackHive/dataset/WhatsApp Video 2026-10-16 at 1.29.33 AM.mp4")

    for v in videos:
        evaluate_video(v)
