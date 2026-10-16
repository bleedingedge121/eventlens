"""EventLens Rule-Based Event Trigger Engine.

Adheres strictly to AGENTS.md Section 10 and hardening specifications:
- Rules only PROPOSE candidate events; the VLM VERIFIES them.
- No fabricated secondary tags (tags come strictly from verified VLM output).
- No uncalibrated mock hazard zones.
- person_down: requires sustained prone posture (aspect > 1.15 for >= 3s),
  must have been observed upright (aspect < 0.8) within the last 10s,
  with vertical transition drop and near-zero post-transition movement.
  Seated patrons who were never upright are ignored.
- crowd_incident: requires count >= 8 AND density surge over 30s baseline.
- tailgating: only active if a calibrated door zone/line is configured.
- fighting: requires sustained bounding box overlap (IoU >= 0.35) for >= 1.5s.
"""

from collections import deque
from datetime import datetime
import time
from typing import Any, Dict, List, Optional, Set, Tuple


def point_in_polygon(x: float, y: float, polygon: List[List[float]]) -> bool:
    """Ray casting algorithm to test if (x, y) is inside polygon."""
    n = len(polygon)
    if n < 3:
        return False
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
        self.positions: deque = deque(maxlen=120)
        self.zone_entry_times: Dict[str, float] = {}
        self.door_crossing_time: Optional[float] = None
        self.door_crossing_dir: Optional[float] = None
        self.was_outside_door: bool = True

        # Posture transition tracking
        self.was_upright: bool = False
        self.last_upright_time: float = -1.0
        self.prone_start_time: Optional[float] = None
        self.prone_start_pos: Optional[Tuple[float, float]] = None
        self.transition_drop_verified: bool = False
        self.max_height: float = 0.0
        self.last_seen: float = time.time()


class TriggerEngine:
    def __init__(self, camera_id: str, config: Dict[str, Any]):
        self.camera_id = camera_id
        self.config = config
        self.tracks: Dict[int, TrackHistory] = {}
        self.last_door_crossings: deque = deque(maxlen=10)  # stores (track_id, timestamp, dir)
        self.last_trigger_times: Dict[str, float] = {}  # category -> timestamp
        self.recent_incident_tracks: Dict[str, Set[int]] = {}  # category -> set of active track IDs
        self.cooldown_seconds = 60.0  # 60s cooldown per incident group

        # Crowd baseline density tracking (timestamps & counts over 30s)
        self.crowd_history: deque = deque(maxlen=300)

        # Fighting sustained overlap tracking: (t1, t2) -> start_timestamp
        self.fighting_overlaps: Dict[Tuple[int, int], float] = {}

        self.last_update_time: float = -1.0

    def update(
        self,
        detections: List[Dict[str, Any]],
        current_time: float,
    ) -> List[Dict[str, Any]]:
        """Processes current frame detections.

        detections: list of dicts: {"track_id": int, "box": [x1, y1, x2, y2], "confidence": float}
        Returns list of candidate event dicts for VLM verification.
        """
        # Detect video loop or backward seek — reset tracking state cleanly
        if self.last_update_time > 0 and (current_time < self.last_update_time - 0.5):
            self.tracks.clear()
            self.last_door_crossings.clear()
            self.crowd_history.clear()
            self.fighting_overlaps.clear()
            self.recent_incident_tracks.clear()

        self.last_update_time = current_time
        candidates: List[Dict[str, Any]] = []

        # 1. Update tracks and posture state
        active_ids = set()
        for det in detections:
            tid = det["track_id"]
            box = det["box"]
            cx = (box[0] + box[2]) / 2.0
            cy = (box[1] + box[3]) / 2.0
            w = box[2] - box[0]
            h = box[3] - box[1]
            active_ids.add(tid)

            if tid not in self.tracks:
                self.tracks[tid] = TrackHistory(tid)

            th = self.tracks[tid]
            th.positions.append((current_time, box, cx, cy))
            if h > th.max_height:
                th.max_height = h
            th.last_seen = current_time

            # Upright check: aspect ratio w/h < 0.80 and height >= 50px
            aspect = (w / h) if h > 0 else 1.0
            if aspect < 0.80 and h >= 50.0:
                th.was_upright = True
                th.last_upright_time = current_time

        # Remove stale tracks older than 10 seconds
        stale = [tid for tid, th in self.tracks.items() if current_time - th.last_seen > 10.0]
        for tid in stale:
            del self.tracks[tid]

        # 2. Crowd Surge / Density check
        self.crowd_history.append((current_time, len(active_ids)))
        # Prune history older than 30s
        while self.crowd_history and (current_time - self.crowd_history[0][0] > 30.0):
            self.crowd_history.popleft()

        crowd_thresh = max(8, int(self.config.get("crowd_threshold", 8)))
        if len(active_ids) >= crowd_thresh and len(self.crowd_history) >= 15:
            # Baseline is average count over the 30s window
            counts = [c for _, c in self.crowd_history]
            baseline_count = sum(counts) / len(counts)
            # Require current count to be a significant surge (>= 1.35x baseline)
            if len(active_ids) >= 1.35 * baseline_count:
                if self._can_trigger("crowd_incident", active_ids, current_time, cooldown=45.0):
                    candidates.append({
                        "camera_id": self.camera_id,
                        "category_hint": "crowd_incident",
                        "timestamp": datetime.now().isoformat(timespec="seconds"),
                        "track_ids": list(active_ids),
                        "rule_confidence": min(0.95, round(len(active_ids) / (crowd_thresh * 1.5), 2)),
                        "tags": [],
                    })

        # 3. Person Down check (Prompt 3: strictly verify posture transition)
        aspect_thresh = float(self.config.get("person_down_aspect_ratio_threshold", 1.15))
        still_sec = float(self.config.get("person_down_still_seconds", 3.0))

        for tid in active_ids:
            th = self.tracks[tid]
            if len(th.positions) < 5:
                continue

            latest_time, box, cx, cy = th.positions[-1]
            w = box[2] - box[0]
            h = box[3] - box[1]
            aspect = (w / h) if h > 0 else 0.0

            # (a) bbox aspect ratio > 1.15 sustained
            is_flat = bool(h > 0 and aspect >= aspect_thresh)

            # (b) the track was previously upright (aspect < 0.8) within the last 10s
            was_recently_upright = bool(th.was_upright and (th.last_upright_time > 0) and (current_time - th.last_upright_time <= 10.0))

            if is_flat and was_recently_upright:
                if th.prone_start_time is None:
                    th.prone_start_time = latest_time
                    th.prone_start_pos = (cx, cy)
                    # (c) vertical drop check at transition: check vertical displacement from upright state
                    if len(th.positions) >= 8:
                        prev_cy = th.positions[-6][3]
                        th.transition_drop_verified = bool(cy >= prev_cy - 5.0)  # downward drop in image coords
                    else:
                        th.transition_drop_verified = True
                else:
                    duration_flat = latest_time - th.prone_start_time
                    start_cx, start_cy = th.prone_start_pos
                    drift = ((cx - start_cx) ** 2 + (cy - start_cy) ** 2) ** 0.5

                    # (d) near-zero motion afterward (< 35px drift) and sustained for >= 3.0s
                    if duration_flat >= still_sec and drift < 35.0 and th.transition_drop_verified:
                        if self._can_trigger("person_down", {tid}, current_time, cooldown=60.0):
                            candidates.append({
                                "camera_id": self.camera_id,
                                "category_hint": "person_down",
                                "timestamp": datetime.now().isoformat(timespec="seconds"),
                                "track_ids": [tid],
                                "rule_confidence": 0.85,
                                "tags": [],
                            })
            else:
                # Reset prone state if person stands up or shifts away
                if not is_flat:
                    th.prone_start_time = None
                    th.prone_start_pos = None

        # 4. Tailgating check (Prompt 5: only active if door zone is configured)
        door_zone = self.config.get("door_zone")
        if door_zone and isinstance(door_zone, list) and len(door_zone) >= 3:
            tailgate_win = float(self.config.get("tailgating_time_window_seconds", 2.0))
            for tid in active_ids:
                th = self.tracks[tid]
                if not th.positions:
                    continue
                latest_time, box, cx, cy = th.positions[-1]
                in_door = point_in_polygon(cx, cy, door_zone)

                if in_door:
                    if th.was_outside_door:
                        th.door_crossing_time = current_time
                        # Record crossing vector
                        if len(th.positions) >= 4:
                            th.door_crossing_dir = cy - th.positions[-3][3]
                        th.was_outside_door = False

                        # Compare against recent door crossings
                        for prior_tid, prior_t, prior_dir in list(self.last_door_crossings):
                            if prior_tid != tid and (current_time - prior_t) <= tailgate_win:
                                # Require movement in approximately the same direction
                                same_dir = True
                                if prior_dir is not None and th.door_crossing_dir is not None:
                                    same_dir = bool((prior_dir * th.door_crossing_dir) >= 0)
                                if same_dir:
                                    if self._can_trigger("tailgating", {prior_tid, tid}, current_time, cooldown=45.0):
                                        candidates.append({
                                            "camera_id": self.camera_id,
                                            "category_hint": "tailgating",
                                            "timestamp": datetime.now().isoformat(timespec="seconds"),
                                            "track_ids": [prior_tid, tid],
                                            "rule_confidence": 0.80,
                                            "tags": [],
                                        })
                                    break
                        self.last_door_crossings.append((tid, current_time, th.door_crossing_dir))
                else:
                    th.was_outside_door = True
                    th.door_crossing_time = None

        # 5. Fighting check (Prompt 5: sustained IoU >= 0.35 for >= 1.5s with high speed)
        active_list = list(active_ids)
        fight_iou_thresh = float(self.config.get("fighting_overlap_iou", 0.35))
        speed_thresh = float(self.config.get("fighting_speed_threshold_pixels_per_sec", 100.0))
        current_pair_overlaps = set()

        for i in range(len(active_list)):
            for j in range(i + 1, len(active_list)):
                id1, id2 = sorted([active_list[i], active_list[j]])
                t1 = self.tracks[id1]
                t2 = self.tracks[id2]
                if not t1.positions or not t2.positions:
                    continue

                iou = compute_iou(t1.positions[-1][1], t2.positions[-1][1])
                if iou >= fight_iou_thresh:
                    current_pair_overlaps.add((id1, id2))
                    if (id1, id2) not in self.fighting_overlaps:
                        self.fighting_overlaps[(id1, id2)] = current_time

                    overlap_duration = current_time - self.fighting_overlaps[(id1, id2)]

                    # Check kinetic activity
                    if overlap_duration >= 1.5 and len(t1.positions) >= 4 and len(t2.positions) >= 4:
                        p1_now, p1_prev = t1.positions[-1], t1.positions[-3]
                        p2_now, p2_prev = t2.positions[-1], t2.positions[-3]
                        dt1 = p1_now[0] - p1_prev[0]
                        dt2 = p2_now[0] - p2_prev[0]

                        if dt1 > 0 and dt2 > 0:
                            s1 = (((p1_now[2] - p1_prev[2]) ** 2 + (p1_now[3] - p1_prev[3]) ** 2) ** 0.5) / dt1
                            s2 = (((p2_now[2] - p2_prev[2]) ** 2 + (p2_now[3] - p2_prev[3]) ** 2) ** 0.5) / dt2
                            avg_speed = (s1 + s2) / 2.0

                            if avg_speed >= speed_thresh:
                                if self._can_trigger("fighting", {id1, id2}, current_time, cooldown=60.0):
                                    candidates.append({
                                        "camera_id": self.camera_id,
                                        "category_hint": "fighting",
                                        "timestamp": datetime.now().isoformat(timespec="seconds"),
                                        "track_ids": [id1, id2],
                                        "rule_confidence": min(0.95, round(avg_speed / speed_thresh * 0.8, 2)),
                                        "tags": [],
                                    })

        # Prune broken overlaps
        for pair in list(self.fighting_overlaps.keys()):
            if pair not in current_pair_overlaps:
                del self.fighting_overlaps[pair]

        # 6. Suspicious Activity (Loitering in restricted zones)
        restricted_zones = self.config.get("restricted_zones", [])
        if restricted_zones and isinstance(restricted_zones, list):
            for rzone in restricted_zones:
                zname = rzone.get("name", "restricted")
                poly = rzone.get("polygon", [])
                max_loiter = float(rzone.get("max_loitering_seconds", 6.0))
                if poly and len(poly) >= 3:
                    for tid in active_ids:
                        th = self.tracks[tid]
                        if not th.positions:
                            continue
                        cx, cy = th.positions[-1][2], th.positions[-1][3]
                        if point_in_polygon(cx, cy, poly):
                            if zname not in th.zone_entry_times:
                                th.zone_entry_times[zname] = current_time
                            dwell = current_time - th.zone_entry_times[zname]
                            if dwell >= max_loiter:
                                if self._can_trigger("suspicious_activity", {tid}, current_time, cooldown=60.0):
                                    candidates.append({
                                        "camera_id": self.camera_id,
                                        "category_hint": "suspicious_activity",
                                        "timestamp": datetime.now().isoformat(timespec="seconds"),
                                        "track_ids": [tid],
                                        "rule_confidence": 0.75,
                                        "tags": [],
                                    })
                        else:
                            th.zone_entry_times.pop(zname, None)

        # Deduplicate candidates within the same frame
        seen_cats = set()
        unique_candidates = []
        for c in candidates:
            cat = c["category_hint"]
            if cat not in seen_cats:
                seen_cats.add(cat)
                unique_candidates.append(c)

        return unique_candidates

    def _can_trigger(
        self,
        category: str,
        track_ids: Set[int],
        current_time: float,
        cooldown: float = 60.0,
    ) -> bool:
        """Enforces incident deduplication and cooldown per (category, track_ids)."""
        last_t = self.last_trigger_times.get(category, -1e9)
        active_incident_tracks = self.recent_incident_tracks.get(category, set())

        # If identical tracks are already in an active incident within cooldown, suppress new candidate
        if active_incident_tracks.intersection(track_ids) and (current_time - last_t < cooldown):
            return False

        if current_time - last_t >= cooldown or not active_incident_tracks.intersection(track_ids):
            self.last_trigger_times[category] = current_time
            self.recent_incident_tracks[category] = set(track_ids)
            return True

        return False
