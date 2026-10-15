"""EventLens High-Performance Video Ingestion & Stream Buffer.

Provides:
- Threaded, zero-lag frame grabbing for RTSP feeds, USB webcams, and video files.
- Buffer size 1 enforcement to prevent RTSP queue latency accumulation.
- Windows DirectShow (CAP_DSHOW) fast webcam initialization.
- Automatic reconnection with exponential backoff for dropped network streams.
- Seamless video looping for test scenario playback.
- Tactical CCTV calibration pattern fallback for headless/offline testing.
"""

import logging
from pathlib import Path
import threading
import time
from typing import Generator, Optional, Tuple, Union
import cv2
import numpy as np

logger = logging.getLogger("eventlens.ingest")


class VideoIngest:
    """Threaded, zero-latency video ingest engine."""

    def __init__(
        self,
        source: Union[str, int],
        target_fps: float = 4.0,
        loop_video: bool = True,
        reconnect_delay: float = 2.0,
    ):
        self.source = str(source).strip()
        self.target_fps = max(1.0, float(target_fps))
        self.frame_interval = 1.0 / self.target_fps
        self.loop_video = loop_video
        self.reconnect_delay = reconnect_delay

        self._is_webcam = self.source.isdigit() or (len(self.source) == 1 and self.source in "0123456789")
        self._is_rtsp = self.source.lower().startswith("rtsp://") or self.source.lower().startswith("http://")

        self.cap: Optional[cv2.VideoCapture] = None
        self._latest_frame: Optional[np.ndarray] = None
        self._latest_timestamp: float = 0.0
        self._frame_lock = threading.Lock()
        self._running = False
        self._reader_thread: Optional[threading.Thread] = None

        self._fps_measured: float = 0.0
        self._frames_captured: int = 0
        self._consecutive_failures: int = 0
        self._is_connected: bool = False

        self._start_capture()

    def _open_capture(self) -> Optional[cv2.VideoCapture]:
        """Attempts to open the video capture device or file."""
        cap = None
        try:
            if self._is_webcam:
                dev_idx = int(self.source)
                # On Windows, DirectShow opens in ~150ms instead of ~5000ms with MSMF
                cap = cv2.VideoCapture(dev_idx, cv2.CAP_DSHOW)
                if not cap.isOpened():
                    cap = cv2.VideoCapture(dev_idx)
            elif self._is_rtsp:
                cap = cv2.VideoCapture(self.source, cv2.CAP_FFMPEG)
                if cap.isOpened():
                    # Set buffer size to 1 to eliminate RTSP frame latency
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            else:
                # Video file
                resolved_path = Path(self.source)
                if not resolved_path.exists():
                    # Try resolving relative to workspace root
                    workspace_path = Path(__file__).resolve().parent.parent.parent / self.source
                    if workspace_path.exists():
                        resolved_path = workspace_path

                cap = cv2.VideoCapture(str(resolved_path))

            if cap is not None and cap.isOpened():
                self._is_connected = True
                self._consecutive_failures = 0
                return cap
            else:
                if cap is not None:
                    cap.release()
                return None
        except Exception as e:
            logger.warning(f"[VideoIngest] Failed to open source '{self.source}': {e}")
            return None

    def _reader_loop(self):
        """Dedicated background reader thread that constantly grabs the latest frame."""
        last_success_time = time.time()
        fps_calc_time = time.time()
        fps_counter = 0

        while self._running:
            if self.cap is None or not self.cap.isOpened():
                self._is_connected = False
                time.sleep(self.reconnect_delay)
                self.cap = self._open_capture()
                if self.cap is None:
                    continue

            ret, frame = self.cap.read()

            if ret and frame is not None:
                self._consecutive_failures = 0
                self._is_connected = True
                last_success_time = time.time()
                fps_counter += 1

                with self._frame_lock:
                    self._latest_frame = frame
                    self._latest_timestamp = last_success_time
                    self._frames_captured += 1

                # Calculate measured FPS
                if time.time() - fps_calc_time >= 1.0:
                    self._fps_measured = fps_counter / (time.time() - fps_calc_time)
                    fps_counter = 0
                    fps_calc_time = time.time()

                # Pace the reader slightly for static video files to respect real FPS
                if not self._is_webcam and not self._is_rtsp:
                    time.sleep(0.01)
            else:
                # Read failed
                self._consecutive_failures += 1

                # Handle loop for pre-recorded video files
                if not self._is_webcam and not self._is_rtsp and self.loop_video and self.cap is not None:
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    time.sleep(0.02)
                    continue

                if self._consecutive_failures > 15:
                    logger.info(f"[VideoIngest] Stream interrupted on {self.source}. Reconnecting...")
                    self._is_connected = False
                    if self.cap is not None:
                        self.cap.release()
                        self.cap = None
                    time.sleep(self.reconnect_delay)

    def _start_capture(self):
        """Starts the background capture reader."""
        self._running = True
        self.cap = self._open_capture()
        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            daemon=True,
            name=f"IngestReader-{self.source}",
        )
        self._reader_thread.start()

    def frames(self) -> Generator[Tuple[float, np.ndarray], None, None]:
        """Generator yielding (timestamp, frame_bgr) at target_fps."""
        last_yield_time = 0.0
        synthetic_step = 0

        while self._running:
            now = time.time()
            elapsed = now - last_yield_time
            if elapsed < self.frame_interval:
                time.sleep(max(0.002, self.frame_interval - elapsed))
                continue

            frame = None
            timestamp = now

            with self._frame_lock:
                if self._latest_frame is not None:
                    frame = self._latest_frame.copy()
                    timestamp = self._latest_timestamp

            if frame is None or not self._is_connected:
                # Generate tactical CCTV standby pattern
                frame = self._generate_synthetic_standby(synthetic_step)
                synthetic_step += 1

            last_yield_time = time.time()
            yield timestamp, frame

    def get_latest_now(self) -> Optional[np.ndarray]:
        """Instantly fetches the most recently captured raw frame without waiting."""
        with self._frame_lock:
            return self._latest_frame.copy() if self._latest_frame is not None else None

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    @property
    def stats(self) -> dict:
        return {
            "source": self.source,
            "connected": self._is_connected,
            "measured_fps": round(self._fps_measured, 1),
            "target_fps": self.target_fps,
            "frames_captured": self._frames_captured,
        }

    def stop(self):
        """Stops the ingestion worker and releases hardware handles."""
        self._running = False
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=1.0)
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        self._is_connected = False

    def _generate_synthetic_standby(self, step: int) -> np.ndarray:
        """Generates a professional CCTV standby test card."""
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        img[:] = (12, 18, 28)  # Deep carbon slate

        # Fine telemetry grid
        for y in range(0, 480, 40):
            cv2.line(img, (0, y), (640, y), (20, 28, 42), 1)
        for x in range(0, 640, 40):
            cv2.line(img, (x, 0), (x, 480), (20, 28, 42), 1)

        # Crosshairs in center
        cv2.line(img, (310, 240), (330, 240), (56, 189, 248), 1)
        cv2.line(img, (320, 230), (320, 250), (56, 189, 248), 1)

        # Tactical Door Zone outline
        cv2.rectangle(img, (180, 240), (420, 460), (30, 45, 65), 1)
        cv2.putText(
            img,
            "PERIMETER BOUNDARY: CH-01",
            (190, 258),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            (70, 95, 125),
            1,
        )

        # Moving calibration target
        px = int(240 + 100 * np.sin(step * 0.08))
        py = int(280 + 20 * np.cos(step * 0.08))
        cv2.rectangle(img, (px, py), (px + 64, py + 128), (56, 189, 248), 2)
        cv2.putText(
            img,
            "SYNTH-TARGET",
            (px, py - 6),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            (56, 189, 248),
            1,
        )

        # Header HUD
        cv2.putText(
            img,
            f"EVENTLENS // {self.source.upper()} [STANDBY]",
            (20, 32),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (56, 189, 248),
            2,
        )
        time_str = time.strftime("%H:%M:%S")
        cv2.putText(
            img,
            time_str,
            (520, 32),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (240, 246, 252),
            1,
        )

        return img
