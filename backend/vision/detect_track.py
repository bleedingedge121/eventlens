"""EventLens YOLO Detection + ByteTrack Person Tracker.

Uses Ultralytics YOLO with ByteTrack configuration to detect and maintain consistent
person track IDs across incoming video frames.
"""

from typing import Any, Dict, List, Tuple
import cv2
import numpy as np


class DetectorTracker:
    def __init__(
        self,
        model_name: str = "yolo11n.pt",
        tracker_config: str = "bytetrack.yaml",
        conf_thresh: float = 0.35,
        device: str = "cuda:0",
    ):
        self.model_name = model_name
        self.tracker_config = tracker_config
        self.conf_thresh = conf_thresh
        self.device = device
        self.model = None
        self._init_model()

    def _init_model(self):
        try:
            from ultralytics import YOLO
            import torch

            # Check device fallback if CUDA isn't available
            dev = self.device if torch.cuda.is_available() else "cpu"
            self.model = YOLO(self.model_name)
            self.device = dev
        except Exception as e:
            print(f"[DetectorTracker] Warning: YOLO could not load directly ({e}). Simulation mode enabled.")
            self.model = None

    def track(self, frame: np.ndarray) -> Tuple[List[Dict[str, Any]], np.ndarray]:
        """Runs tracking on a frame.

        Returns:
            (detections, annotated_frame)
            where detections = [{"track_id": int, "box": [x1, y1, x2, y2], "confidence": float}]
        """
        if self.model is None or frame is None:
            # Fallback simulated frame annotation
            annotated = frame.copy() if frame is not None else np.zeros((360, 640, 3), dtype=np.uint8)
            cv2.putText(
                annotated,
                "EventLens Live Vision (Simulation / Standby)",
                (20, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (56, 189, 248),
                2,
            )
            return [], annotated

        # Run track filtering only person class (class 0)
        results = self.model.track(
            source=frame,
            persist=True,
            classes=[0],  # Person class only
            conf=self.conf_thresh,
            tracker=self.tracker_config,
            device=self.device,
            verbose=False,
        )

        detections: List[Dict[str, Any]] = []
        annotated_frame = frame.copy()

        if results and len(results) > 0:
            boxes = results[0].boxes
            if boxes is not None and boxes.id is not None:
                track_ids = boxes.id.int().cpu().tolist()
                xyxy = boxes.xyxy.cpu().tolist()
                confs = boxes.conf.cpu().tolist()

                for tid, box, conf in zip(track_ids, xyxy, confs):
                    detections.append({
                        "track_id": int(tid),
                        "box": [float(b) for b in box],
                        "confidence": float(conf),
                    })

                    # Draw annotated bounding boxes
                    x1, y1, x2, y2 = [int(v) for v in box]
                    cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), (56, 189, 248), 2)
                    label = f"ID:{tid} ({conf:.2f})"
                    cv2.putText(
                        annotated_frame,
                        label,
                        (x1, max(15, y1 - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        (56, 189, 248),
                        2,
                    )

        # Draw status HUD
        h, w = annotated_frame.shape[:2]
        hud_text = f"Persons Tracked: {len(detections)} | Model: {self.model_name}"
        cv2.putText(
            annotated_frame,
            hud_text,
            (15, h - 15),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (240, 246, 252),
            1,
        )

        return detections, annotated_frame
