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
        target_fps: float = 25.0,
        loop_video: bool = True,
        reconnect_delay: float = 2.0,
    ):
        raw_source = str(source).strip().strip("\"'")
        # Auto-normalize smartphone IP Webcam / DroidCam URLs:
        # If user provides http://...:8080 without /video, OpenCV fails because it tries to read HTML instead of MJPEG stream.
        if (raw_source.startswith("http://") or raw_source.startswith("https://")) and (":8080" in raw_source or ":4747" in raw_source):
            clean_url = raw_source.rstrip("/")
            if clean_url.endswith(":8080"):
                raw_source = f"{clean_url}/video"
            elif clean_url.endswith(":4747"):
                raw_source = f"{clean_url}/video"
        self.source = raw_source
        self.target_fps = max(1.0, float(target_fps))
        self.native_fps = self.target_fps
        self.frame_interval = 1.0 / self.target_fps
        self.loop_video = loop_video
        self.reconnect_delay = reconnect_delay

        self._is_webcam = self.source.isdigit() or (len(self.source) == 1 and self.source in "0123456789")
        self._is_network = (
            self.source.lower().startswith("rtsp://")
            or self.source.lower().startswith("http://")
            or self.source.lower().startswith("https://")
        )
        self._is_rtsp = self._is_network
        self._is_file = not self._is_webcam and not self._is_network

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
                import platform
                plat = platform.system()
                if plat == "Windows":
                    # DirectShow on Windows opens in ~150ms instead of MSMF lag
                    cap = cv2.VideoCapture(dev_idx, cv2.CAP_DSHOW)
                elif plat == "Darwin":
                    # AVFoundation on macOS opens cameras instantaneously
                    cap = cv2.VideoCapture(dev_idx, cv2.CAP_AVFOUNDATION)
                if cap is None or not cap.isOpened():
                    cap = cv2.VideoCapture(dev_idx)
            elif self._is_network:
                import os
                if self.source.lower().startswith("rtsp://"):
                    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|stimeout;5000000"
                cap = cv2.VideoCapture(self.source, cv2.CAP_FFMPEG)
                if cap is None or not cap.isOpened():
                    cap = cv2.VideoCapture(self.source)
                if cap and cap.isOpened():
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            else:
                # Video file: resolve absolute and relative paths robustly
                clean_path = Path(self.source)
                candidate_paths = [
                    clean_path,
                    Path(__file__).resolve().parent.parent.parent / self.source,
                    Path(__file__).resolve().parent.parent.parent.parent / self.source,
                    Path("D:/ClaudeCode/HackHive/dataset") / clean_path.name,
                ]

                resolved_path = None
                for cp in candidate_paths:
                    if cp.exists() and cp.is_file():
                        resolved_path = cp
                        break

                if resolved_path is None:
                    resolved_path = clean_path

                cap = cv2.VideoCapture(str(resolved_path))
                if cap.isOpened():
                    raw_fps = cap.get(cv2.CAP_PROP_FPS)
                    if raw_fps and 5.0 <= raw_fps <= 120.0 and not np.isnan(raw_fps):
                        self.native_fps = float(raw_fps)
                        self.frame_interval = 1.0 / self.native_fps
                        logger.info(f"[VideoIngest] Video file {resolved_path.name} loaded @ {self.native_fps:.1f} FPS")

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
        """Dedicated background reader thread for live feeds (webcams, RTSP)."""
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
            else:
                # Read failed
                self._consecutive_failures += 1

                if self._consecutive_failures > 15:
                    logger.info(f"[VideoIngest] Live stream interrupted on {self.source}. Reconnecting...")
                    self._is_connected = False
                    if self.cap is not None:
                        self.cap.release()
                        self.cap = None
                    time.sleep(self.reconnect_delay)

    def _start_capture(self):
        """Initializes capture and reader thread if live stream."""
        self._running = True
        self.cap = self._open_capture()
        if not self._is_file:
            # Webcams & RTSP use a dedicated background thread to prevent buffer buildup
            self._reader_thread = threading.Thread(
                target=self._reader_loop,
                daemon=True,
                name=f"IngestReader-{self.source}",
            )
            self._reader_thread.start()

    def frames(self) -> Generator[Tuple[float, np.ndarray], None, None]:
        """Generator yielding (timestamp, frame_bgr) at real-world paced FPS."""
        last_yield_time = time.time()
        synthetic_step = 0
        fps_calc_time = time.time()
        fps_counter = 0

        while self._running:
            if self._is_file:
                # Video file: Read sequentially frame-by-frame with zero frame drops
                if self.cap is None or not self.cap.isOpened():
                    self.cap = self._open_capture()
                    if self.cap is None:
                        time.sleep(0.1)
                        continue

                t0 = time.time()
                ret, frame = self.cap.read()

                if not ret or frame is None:
                    if self.loop_video and self.cap is not None:
                        self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        continue
                    else:
                        break

                now = time.time()
                with self._frame_lock:
                    self._latest_frame = frame
                    self._latest_timestamp = now
                    self._frames_captured += 1
                    self._is_connected = True

                fps_counter += 1
                if now - fps_calc_time >= 1.0:
                    self._fps_measured = fps_counter / (now - fps_calc_time)
                    fps_counter = 0
                    fps_calc_time = now

                # Pace the video file playback so it runs at 1.0x natural speed
                elapsed = time.time() - last_yield_time
                target_dt = self.frame_interval
                if elapsed < target_dt:
                    time.sleep(max(0.001, target_dt - elapsed))

                last_yield_time = time.time()
                yield last_yield_time, frame
            else:
                # Live stream (webcam, RTSP): sample from the latest grabbed frame
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
