"""EventLens Rule-Based Event Trigger Engine.

Adheres strictly to AGENTS.md Section 10:
- Zones and thresholds come from config/cameras.json.
- Checks:
  1. tailgating: 2 distinct tracks cross the door zone within 1-2 seconds.
  2. person_down: bounding box width/height ratio > aspect threshold and motionless for N seconds.
  3. crowd_incident: person count in camera view/region > crowd_threshold.
  4. suspicious_activity: person stays inside restricted zone longer than max_loitering_seconds.
  5. fighting: two person tracks overlap (IoU) with high speed/acceleration.
"""

from collections import deque
from datetime import datetime, timezone
import time
from typing import Any, Dict, List, Optional, Tuple


def point_in_polygon(x: float, y: float, polygon: List[List[float]]) -> bool:
    """Ray casting algorithm to test if (x, y) is inside polygon."""
    n = len(polygon)
    inside = False
    p1x, p1y = polygon[0]
    for i in range(n + 1):
        p2x, p2y = polygon[i % n]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xints = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xints:
                        inside = not inside
        p1x, p1y = p2x, p2y
    return inside


def compute_iou(box1: List[float], box2: List[float]) -> float:
    """Computes Intersection over Union of two bounding boxes [x1, y1, x2, y2]."""
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])

    inter_w = max(0.0, x2 - x1)
    inter_h = max(0.0, y2 - y1)
    inter_area = inter_w * inter_h

    area1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
    area2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
    union_area = area1 + area2 - inter_area

    if union_area <= 0:
        return 0.0
    return inter_area / union_area


class TrackHistory:
    def __init__(self, track_id: int):
        self.track_id = track_id
        # stores (timestamp_sec, [x1, y1, x2, y2], center_x, center_y)
        self.positions: deque = deque(maxlen=60)
        self.zone_entry_times: Dict[str, float] = {}
        self.door_crossing_time: Optional[float] = None
        self.was_outside_door: bool = False
        self.down_start_time: Optional[float] = None
        self.down_start_pos: Optional[Tuple[float, float]] = None
        self.last_seen: float = time.time()


class TriggerEngine:
    def __init__(self, camera_id: str, config: Dict[str, Any]):
        self.camera_id = camera_id
        self.config = config
        self.tracks: Dict[int, TrackHistory] = {}
        self.last_door_crossings: deque = deque(maxlen=10)  # stores (track_id, timestamp)
        self.last_trigger_times: Dict[str, float] = {}  # debouncing triggers
        self.cooldown_seconds = 8.0
        # Persistent spatial memory for collapsed persons (resistant to ID switches)
        self.prone_regions: List[Dict[str, Any]] = []

    def update(
        self,
        detections: List[Dict[str, Any]],
        current_time: float,
    ) -> List[Dict[str, Any]]:
        """Processes current frame detections.

        detections: list of dicts: {"track_id": int, "box": [x1, y1, x2, y2], "confidence": float}
        Returns list of candidate event dicts.
        """
        candidates: List[Dict[str, Any]] = []

        # 1. Update tracks
        active_ids = set()
        for det in detections:
            tid = det["track_id"]
            box = det["box"]
            cx = (box[0] + box[2]) / 2.0
            cy = (box[1] + box[3]) / 2.0
            active_ids.add(tid)

            if tid not in self.tracks:
                self.tracks[tid] = TrackHistory(tid)

            th = self.tracks[tid]
            th.positions.append((current_time, box, cx, cy))
            th.last_seen = current_time

        # Remove stale tracks older than 8 seconds
        stale = [tid for tid, th in self.tracks.items() if current_time - th.last_seen > 8.0]
        for tid in stale:
            del self.tracks[tid]

        # 2. Check Crowd Incident (Exceeds crowd threshold)
        crowd_thresh = self.config.get("crowd_threshold", 7)
        if len(active_ids) >= crowd_thresh:
            if self._can_trigger("crowd_incident", current_time, cooldown=15.0):
                candidates.append({
                    "camera_id": self.camera_id,
                    "category_hint": "crowd_incident",
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "track_ids": list(active_ids),
                })

        # 3. Check Person Down & Suspicious Activity per person
        aspect_thresh = self.config.get("person_down_aspect_ratio_threshold", 0.70)
        still_sec = self.config.get("person_down_still_seconds", 1.8)
        door_zone = self.config.get("door_zone")
        restricted_zones = self.config.get("restricted_zones", [])

        # Prune stale prone regions older than 2.5 seconds
        self.prone_regions = [
            r for r in self.prone_regions if current_time - r["last_seen"] <= 2.5
        ]

        for tid in active_ids:
            th = self.tracks[tid]
            if len(th.positions) < 2:
                continue

            latest_time, box, cx, cy = th.positions[-1]
            w = box[2] - box[0]
            h = box[3] - box[1]

            # Aspect ratio check: in angled surveillance CCTV, horizontal or collapsed person has w/h >= 0.70
            is_seated_webcam = (box[1] < 80 and h > 180 and (w / h) < 0.85)
            is_prone = (h > 0 and (w / h) >= aspect_thresh and not is_seated_webcam)

            if is_prone:
                # Update or register spatial prone region
                matched_region = None
                for reg in self.prone_regions:
                    dist = ((cx - reg["cx"]) ** 2 + (cy - reg["cy"]) ** 2) ** 0.5
                    if dist < 65.0:
                        matched_region = reg
                        break

                if matched_region is None:
                    matched_region = {
                        "cx": cx,
                        "cy": cy,
                        "start_time": current_time,
                        "last_seen": current_time,
                        "track_ids": {tid},
                    }
                    self.prone_regions.append(matched_region)
                else:
                    matched_region["last_seen"] = current_time
                    matched_region["cx"] = 0.8 * matched_region["cx"] + 0.2 * cx
                    matched_region["cy"] = 0.8 * matched_region["cy"] + 0.2 * cy
                    matched_region["track_ids"].add(tid)

                region_dt = current_time - matched_region["start_time"]
                if region_dt >= still_sec:
                    if self._can_trigger("person_down", current_time, cooldown=8.0):
                        candidates.append({
                            "camera_id": self.camera_id,
                            "category_hint": "person_down",
                            "timestamp": datetime.now().isoformat(timespec="seconds"),
                            "track_ids": list(matched_region["track_ids"]),
                        })

                # Also track individual track persistence
                if th.down_start_time is None:
                    th.down_start_time = latest_time
                    th.down_start_pos = (cx, cy)
                else:
                    dt = latest_time - th.down_start_time
                    start_cx, start_cy = th.down_start_pos
                    dist = ((cx - start_cx) ** 2 + (cy - start_cy) ** 2) ** 0.5
                    if dt >= still_sec and dist < 45.0:
                        if self._can_trigger("person_down", current_time, cooldown=8.0):
                            candidates.append({
                                "camera_id": self.camera_id,
                                "category_hint": "person_down",
                                "timestamp": datetime.now().isoformat(timespec="seconds"),
                                "track_ids": [tid],
                            })
            else:
                th.down_start_time = None
                th.down_start_pos = None

            # Check Door Crossing for Tailgating:
            # Must transition from OUTSIDE the door zone into the door zone
            in_door = bool(door_zone and point_in_polygon(cx, cy, door_zone))
            if in_door:
                if th.was_outside_door:
                    th.door_crossing_time = current_time
                    th.was_outside_door = False
                    tailgate_win = self.config.get("tailgating_time_window_seconds", 1.8)
                    for prior_tid, prior_t in list(self.last_door_crossings):
                        if prior_tid != tid and (current_time - prior_t) <= tailgate_win:
                            if self._can_trigger("tailgating", current_time, cooldown=12.0):
                                candidates.append({
                                    "camera_id": self.camera_id,
                                    "category_hint": "tailgating",
                                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                                    "track_ids": [prior_tid, tid],
                                })
                            break
                    self.last_door_crossings.append((tid, current_time))
            else:
                th.was_outside_door = True
                th.door_crossing_time = None

            # Check Restricted Zones (Loitering)
            for rzone in restricted_zones:
                zname = rzone.get("name", "restricted")
                poly = rzone.get("polygon", [])
                max_loiter = rzone.get("max_loitering_seconds", 6.0)
                if poly and point_in_polygon(cx, cy, poly):
                    if zname not in th.zone_entry_times:
                        th.zone_entry_times[zname] = current_time
                    elif current_time - th.zone_entry_times[zname] >= max_loiter:
                        if self._can_trigger(f"suspicious_{zname}_{tid}", current_time, cooldown=20.0):
                            candidates.append({
                                "camera_id": self.camera_id,
                                "category_hint": "suspicious_activity",
                                "timestamp": datetime.now().isoformat(timespec="seconds"),
                                "track_ids": [tid],
                            })
                else:
                    th.zone_entry_times.pop(zname, None)

        # 4. Check Fighting (Inter-track overlap & kinetic movement)
        active_list = list(active_ids)
        fight_iou_thresh = self.config.get("fighting_overlap_iou", 0.38)
        speed_thresh = self.config.get("fighting_speed_threshold_pixels_per_sec", 105.0)

        for i in range(len(active_list)):
            for j in range(i + 1, len(active_list)):
                t1 = self.tracks[active_list[i]]
                t2 = self.tracks[active_list[j]]
                iou = compute_iou(t1.positions[-1][1], t2.positions[-1][1])
                if iou >= fight_iou_thresh:
                    # Check velocity
                    if len(t1.positions) >= 2 and len(t2.positions) >= 2:
                        p1_now, p1_prev = t1.positions[-1], t1.positions[-2]
                        p2_now, p2_prev = t2.positions[-1], t2.positions[-2]
                        dt1 = p1_now[0] - p1_prev[0]
                        dt2 = p2_now[0] - p2_prev[0]
                        if dt1 > 0 and dt2 > 0:
                            s1 = (((p1_now[2] - p1_prev[2]) ** 2 + (p1_now[3] - p1_prev[3]) ** 2) ** 0.5) / dt1
                            s2 = (((p2_now[2] - p2_prev[2]) ** 2 + (p2_now[3] - p2_prev[3]) ** 2) ** 0.5) / dt2
                            if (s1 + s2) / 2.0 >= speed_thresh:
                                if self._can_trigger("fighting", current_time, cooldown=12.0):
                                    candidates.append({
                                        "camera_id": self.camera_id,
                                        "category_hint": "fighting",
                                        "timestamp": datetime.now().isoformat(timespec="seconds"),
                                        "track_ids": [active_list[i], active_list[j]],
                                    })

        # Deduplicate candidates within the same frame by category hint
        seen_cats = set()
        unique_candidates = []
        for c in candidates:
            cat = c["category_hint"]
            if cat not in seen_cats:
                seen_cats.add(cat)
                unique_candidates.append(c)

        return unique_candidates

    def _can_trigger(self, key: str, current_time: float, cooldown: Optional[float] = None) -> bool:
        cd = cooldown if cooldown is not None else self.cooldown_seconds
        last_t = self.last_trigger_times.get(key, -1e9)
        if current_time - last_t >= cd:
            self.last_trigger_times[key] = current_time
            return True
        return False
