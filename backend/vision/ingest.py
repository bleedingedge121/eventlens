"""EventLens Video Stream Ingestion & Frame Sampler.

Handles live webcam inputs, RTSP network cameras, pre-recorded video files,
and synthetic test stream generation when no physical camera is plugged in.
Samples frames at a controlled ~3-5 FPS to prevent GPU saturation.
"""

import time
from typing import Generator, Optional, Tuple, Union
import cv2
import numpy as np


class VideoIngest:
    def __init__(self, source: Union[str, int], target_fps: float = 4.0):
        self.source = source
        self.target_fps = target_fps
        self.frame_interval = 1.0 / max(1.0, target_fps)
        self.cap: Optional[cv2.VideoCapture] = None
        self._is_running = True
        self._init_capture()

    def _init_capture(self):
        src = int(self.source) if str(self.source).isdigit() else str(self.source)
        try:
            self.cap = cv2.VideoCapture(src)
            if not self.cap.isOpened():
                self.cap = None
        except Exception:
            self.cap = None

    def frames(self) -> Generator[Tuple[float, np.ndarray], None, None]:
        """Yields (timestamp_sec, frame_bgr) at target_fps."""
        last_yield_time = 0.0
        synthetic_step = 0

        while self._is_running:
            now = time.time()
            elapsed = now - last_yield_time
            if elapsed < self.frame_interval:
                time.sleep(max(0.005, self.frame_interval - elapsed))
                continue

            frame = None
            if self.cap is not None and self.cap.isOpened():
                ret, captured = self.cap.read()
                if ret and captured is not None:
                    frame = captured
                else:
                    # Loop video file if reached EOF
                    if isinstance(self.source, str) and not self.source.startswith("rtsp"):
                        self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        ret, captured = self.cap.read()
                        if ret:
                            frame = captured

            if frame is None:
                # Generate synthetic frame for offline/headless testing
                frame = self._generate_synthetic_frame(synthetic_step)
                synthetic_step += 1

            last_yield_time = time.time()
            yield last_yield_time, frame

    def stop(self):
        self._is_running = False
        if self.cap is not None:
            self.cap.release()
            self.cap = None

    def _generate_synthetic_frame(self, step: int) -> np.ndarray:
        """Generates a clean synthetic security camera test feed."""
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        img[:] = (22, 27, 34)  # Security dark background

        # Grid lines
        for y in range(0, 480, 60):
            cv2.line(img, (0, y), (640, y), (35, 42, 54), 1)
        for x in range(0, 640, 80):
            cv2.line(img, (x, 0), (x, 480), (35, 42, 54), 1)

        # Draw door / restricted zone markers
        cv2.rectangle(img, (180, 240), (420, 460), (45, 60, 80), 2)
        cv2.putText(img, "ACCESS DOOR ZONE", (190, 260), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (100, 140, 180), 1)

        # Draw synthetic moving person box
        px = int(220 + 120 * np.sin(step * 0.1))
        py = int(280 + 30 * np.cos(step * 0.1))
        cv2.rectangle(img, (px, py), (px + 60, py + 130), (56, 189, 248), 2)
        cv2.putText(img, "PERSON (Simulated)", (px, py - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (56, 189, 248), 1)

        # Camera Header
        cam_label = f"EVENTLENS FEED [{self.source}] - LIVE"
        cv2.putText(img, cam_label, (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 230, 150), 2)
        cv2.circle(img, (590, 30), 8, (0, 0, 255), -1)  # Red REC dot
        cv2.putText(img, "REC", (605, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)

        return img
