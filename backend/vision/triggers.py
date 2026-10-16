"""
EventLens Rule-Based Event Trigger Engine.

Adheres strictly to core requirements:
1. Scene profiles: indoor_premises | outdoor_street | custom.
   - outdoor_street disables person_down unless explicitly enabled, and raises crowd thresholds.
2. person_down must require:
   - track age >= min_track_age (2.0s)
   - upright -> horizontal transition within the last X seconds
   - sustained horizontal state >= Y seconds with near-zero centroid motion
   - bbox not heavily occluded (IoU with other boxes < 0.35)
   - NEVER trigger on tracks that were never upright!
3. Crowd: rolling baseline person count over 60s, triggers only on significant surge over baseline.
4. Auto-pause: if VLM says 'no' for 3 consecutive candidates of the same rule on a camera,
   that rule enters cooldown ('auto-paused: low verification rate').
"""

from collections import deque
from datetime import datetime
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("eventlens.vision.triggers")


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


class TrackHistory:
    def __init__(self, track_id: int, start_time: float):
        self.track_id = track_id
        self.first_seen = start_time
        self.last_seen = start_time
        # positions stores: (timestamp, [x1, y1, x2, y2], center_x, center_y)
        self.positions: deque = deque(maxlen=90)
        self.max_height: float = 0.0

        # Person down state machine
        self.was_upright: bool = False
        self.upright_last_time: float = 0.0
        self.prone_start_time: Optional[float] = None
        self.prone_start_pos: Optional[Tuple[float, float]] = None

        # Zone & door crossing
        self.door_crossing_time: Optional[float] = None
        self.zone_entry_times: Dict[str, float] = {}


class TriggerEngine:
    def __init__(self, camera_id: str, config: Dict[str, Any]):
        self.camera_id = camera_id
        self.config = config
        self.tracks: Dict[int, TrackHistory] = {}
        self.last_trigger_times: Dict[str, float] = {}
        self.last_door_crossings: deque = deque(maxlen=10)
        self.last_update_time: float = -1.0

        # Rolling crowd baseline (last 60s)
        self.count_history: deque = deque(maxlen=120)  # (time, count)
        self.crowd_surge_start: Optional[float] = None

        # Auto-pause tracking: 3 consecutive rejections pauses rule for 60s
        self.consecutive_rejections: Dict[str, int] = {}
        self.paused_rules: Dict[str, float] = {}
        self.paused_reasons: Dict[str, str] = {}

    def get_scene_profile(self) -> str:
        return self.config.get("scene_profile", "indoor_premises")

    def record_vlm_feedback(self, rule_category: str, verdict: str):
        """Records VLM confirmation or rejection. 3 consecutive rejections pauses rule."""
        if verdict != "yes":
            count = self.consecutive_rejections.get(rule_category, 0) + 1
            self.consecutive_rejections[rule_category] = count
            if count >= 3:
                pause_until = time.time() + 60.0
                self.paused_rules[rule_category] = pause_until
                self.paused_reasons[rule_category] = "auto-paused: low verification rate"
                logger.warning(
                    f"[Triggers] Rule '{rule_category}' on camera '{self.camera_id}' "
                    f"auto-paused for 60s (3 consecutive VLM rejections)."
                )
        else:
            self.consecutive_rejections[rule_category] = 0
            self.paused_rules.pop(rule_category, None)
            self.paused_reasons.pop(rule_category, None)

    def _is_rule_paused(self, rule_category: str, current_time: float) -> bool:
        if rule_category in self.paused_rules:
            if current_time < self.paused_rules[rule_category]:
                return True
            else:
                self.paused_rules.pop(rule_category, None)
                self.paused_reasons.pop(rule_category, None)
                self.consecutive_rejections[rule_category] = 0
        return False

    def _can_trigger(self, key: str, current_time: float, cooldown: float = 12.0) -> bool:
        rule_cat = key.rsplit("_", 1)[0] if ("_" in key and key.rsplit("_", 1)[1].isdigit()) else key
        if self._is_rule_paused(rule_cat, current_time):
            return False
        if key not in self.last_trigger_times:
            self.last_trigger_times[key] = current_time
            return True
        last_t = self.last_trigger_times[key]
        if current_time - last_t >= cooldown:
            self.last_trigger_times[key] = current_time
            return True
        return False

    def update(
        self,
        detections: List[Dict[str, Any]],
        current_time: float,
    ) -> List[Dict[str, Any]]:
        """Evaluates rules on detections. Filters young tracks (<1.0s) and handles state machines."""
        # Detect video loop or backward seek — reset tracking state cleanly
        if self.last_update_time > 0 and (current_time < self.last_update_time - 0.5):
            self.tracks.clear()
            self.last_door_crossings.clear()
            self.count_history.clear()
            self.crowd_surge_start = None

        self.last_update_time = current_time
        candidates: List[Dict[str, Any]] = []

        # 1. Update tracks
        active_ids = set()
        active_boxes = []
        for det in detections:
            tid = det["track_id"]
            box = det["box"]
            cx = (box[0] + box[2]) / 2.0
            cy = (box[1] + box[3]) / 2.0
            active_ids.add(tid)
            active_boxes.append((tid, box))

            if tid not in self.tracks:
                self.tracks[tid] = TrackHistory(tid, current_time)

            th = self.tracks[tid]
            th.positions.append((current_time, box, cx, cy))
            h = box[3] - box[1]
            if h > th.max_height:
                th.max_height = h
            th.last_seen = current_time

            # Upright posture tracking
            w = box[2] - box[0]
            if h > 0 and (h / w) >= 1.4:
                th.was_upright = True
                th.upright_last_time = current_time

        # Remove stale tracks older than 6.0 seconds
        stale = [tid for tid, th in self.tracks.items() if current_time - th.last_seen > 6.0]
        for tid in stale:
            del self.tracks[tid]

        # Scene profile settings
        scene_profile = self.get_scene_profile()
        profile_person_down = True
        crowd_baseline_factor = 1.8
        min_crowd_count = 5

        try:
            from backend.server.config import get_taxonomy
            prof = get_taxonomy().get_scene_profile(scene_profile)
            profile_person_down = prof.get("person_down_enabled", True)
            crowd_baseline_factor = prof.get("crowd_baseline_factor", 1.8)
            min_crowd_count = prof.get("min_crowd_count", 5)
        except Exception:
            if scene_profile == "outdoor_street":
                profile_person_down = False
                crowd_baseline_factor = 2.5
                min_crowd_count = 10

        # Allow per-camera override for person_down and crowd
        if self.config.get("person_down_enabled") is not None:
            profile_person_down = bool(self.config.get("person_down_enabled"))
        min_crowd_count = int(self.config.get("crowd_threshold", min_crowd_count))
        crowd_surge_sec = float(self.config.get("crowd_surge_seconds", 1.5))

        # 2. Update rolling crowd baseline and evaluate Crowd Surge
        self.count_history.append((current_time, len(active_ids)))
        prior_counts = [cnt for t, cnt in self.count_history if current_time - t > crowd_surge_sec]
        rolling_baseline = (sum(prior_counts) / len(prior_counts)) if prior_counts else min_crowd_count
        if "crowd_threshold" in self.config:
            dynamic_crowd_thresh = int(self.config["crowd_threshold"])
        else:
            dynamic_crowd_thresh = max(min_crowd_count, int(rolling_baseline * crowd_baseline_factor))

        if len(active_ids) >= dynamic_crowd_thresh:
            if self.crowd_surge_start is None:
                self.crowd_surge_start = current_time
            elif current_time - self.crowd_surge_start >= crowd_surge_sec:
                if self._can_trigger("crowd_incident", current_time, cooldown=20.0):
                    candidates.append({
                        "camera_id": self.camera_id,
                        "category_hint": "crowd_incident",
                        "timestamp": datetime.now().isoformat(timespec="seconds"),
                        "track_ids": list(active_ids),
                        "tags": ["crowd_incident", "dense_gathering", "corridor_blockage"],
                        "evidence": {
                            "active_count": len(active_ids),
                            "rolling_baseline": round(rolling_baseline, 1),
                            "threshold": dynamic_crowd_thresh,
                        },
                    })
        else:
            self.crowd_surge_start = None

        # 3. Check Person Down
        if profile_person_down and not self._is_rule_paused("person_down", current_time):
            still_thresh_sec = float(self.config.get("person_down_still_seconds", 2.0))
            aspect_thresh = float(self.config.get("person_down_aspect_ratio_threshold", 1.15))
            min_track_age = float(self.config.get("person_down_min_track_age", 2.0))
            min_positions = int(self.config.get("person_down_min_positions", 3))

            for tid in active_ids:
                th = self.tracks[tid]
                track_age = current_time - th.first_seen

                # RULE A: Must meet minimum track age (avoid newly spawned fragment boxes)
                if track_age < min_track_age or len(th.positions) < min_positions:
                    continue

                # RULE B: Must have been upright! Never trigger on tracks that were never upright!
                if not th.was_upright:
                    continue

                latest_time, box, cx, cy = th.positions[-1]
                w = box[2] - box[0]
                h = box[3] - box[1]

                # RULE C: Upright to horizontal transition within last 8 seconds
                transitioned_recently = (current_time - th.upright_last_time) <= 8.0
                if not transitioned_recently:
                    continue

                # Check horizontal posture: wider than tall OR significant height drop
                is_horizontal = bool(h > 0 and (w / h) >= aspect_thresh and h <= 0.70 * th.max_height)

                if is_horizontal:
                    # RULE D: Centroid stillness tracking
                    if th.prone_start_time is None:
                        th.prone_start_time = current_time
                        th.prone_start_pos = (cx, cy)
                    else:
                        sx, sy = th.prone_start_pos
                        dist = ((cx - sx) ** 2 + (cy - sy) ** 2) ** 0.5
                        # Relative to box width or absolute threshold
                        norm_dist = dist / max(w, 1.0)
                        if dist > 35.0 or norm_dist > 0.40:
                            # Person is crawling/walking along the floor, not motionless collapse
                            th.prone_start_time = current_time
                            th.prone_start_pos = (cx, cy)
                        else:
                            prone_duration = current_time - th.prone_start_time
                            if prone_duration >= still_thresh_sec:
                                # RULE E: Occlusion check (IoU with other boxes must be < 0.35)
                                heavily_occluded = False
                                for other_tid, other_box in active_boxes:
                                    if other_tid != tid:
                                        if compute_iou(box, other_box) >= 0.35:
                                            heavily_occluded = True
                                            break

                                if not heavily_occluded:
                                    if self._can_trigger(f"person_down_{tid}", current_time, cooldown=15.0):
                                        candidates.append({
                                            "camera_id": self.camera_id,
                                            "category_hint": "person_down",
                                            "timestamp": datetime.now().isoformat(timespec="seconds"),
                                            "track_ids": [tid],
                                            "tags": ["person_down", "slip_fall", "motionless"],
                                            "evidence": {
                                                "prone_duration_sec": round(prone_duration, 1),
                                                "aspect_ratio": round(w / h, 2),
                                                "was_upright": True,
                                            },
                                        })
                else:
                    th.prone_start_time = None
                    th.prone_start_pos = None

        # 4. Check Fighting (Inter-track overlap with erratic kinetic displacement)
        if not self._is_rule_paused("fighting", current_time):
            active_list = [tid for tid in active_ids if (current_time - self.tracks[tid].first_seen) >= 1.0]
            fight_iou_thresh = float(self.config.get("fighting_overlap_iou", 0.35))
            speed_thresh = float(self.config.get("fighting_speed_threshold_pixels_per_sec", 95.0))

            for i in range(len(active_list)):
                for j in range(i + 1, len(active_list)):
                    t1 = self.tracks[active_list[i]]
                    t2 = self.tracks[active_list[j]]
                    if len(t1.positions) < 3 or len(t2.positions) < 3:
                        continue

                    iou = compute_iou(t1.positions[-1][1], t2.positions[-1][1])
                    if iou >= fight_iou_thresh:
                        p1_now, p1_prev = t1.positions[-1], t1.positions[-2]
                        p2_now, p2_prev = t2.positions[-1], t2.positions[-2]
                        dt1 = p1_now[0] - p1_prev[0]
                        dt2 = p2_now[0] - p2_prev[0]

                        if dt1 > 0 and dt2 > 0:
                            s1 = (((p1_now[2] - p1_prev[2]) ** 2 + (p1_now[3] - p1_prev[3]) ** 2) ** 0.5) / dt1
                            s2 = (((p2_now[2] - p2_prev[2]) ** 2 + (p2_now[3] - p2_prev[3]) ** 2) ** 0.5) / dt2
                            avg_speed = (s1 + s2) / 2.0

                            d_now = ((p1_now[2] - p2_now[2]) ** 2 + (p1_now[3] - p2_now[3]) ** 2) ** 0.5
                            d_prev = ((p1_prev[2] - p2_prev[2]) ** 2 + (p1_prev[3] - p2_prev[3]) ** 2) ** 0.5
                            rel_speed = abs(d_now - d_prev) / min(dt1, dt2)

                            if avg_speed >= speed_thresh or rel_speed >= (speed_thresh * 0.75):
                                pair_key = f"fight_{min(t1.track_id, t2.track_id)}_{max(t1.track_id, t2.track_id)}"
                                if self._can_trigger(pair_key, current_time, cooldown=15.0):
                                    candidates.append({
                                        "camera_id": self.camera_id,
                                        "category_hint": "fighting",
                                        "timestamp": datetime.now().isoformat(timespec="seconds"),
                                        "track_ids": [t1.track_id, t2.track_id],
                                        "tags": ["fighting", "physical_altercation", "brawl"],
                                        "evidence": {
                                            "iou": round(iou, 2),
                                            "avg_speed": round(avg_speed, 1),
                                        },
                                    })

        # 5. Check Tailgating (Door line / zone crossing)
        door_zone = self.config.get("door_zone")
        if door_zone and not self._is_rule_paused("tailgating", current_time):
            window_sec = float(self.config.get("tailgating_time_window_seconds", 1.8))
            for tid in active_ids:
                th = self.tracks[tid]
                if not th.positions:
                    continue
                latest_time, box, cx, cy = th.positions[-1]
                in_door = point_in_polygon(cx, cy, door_zone) if len(door_zone) >= 3 else False

                if in_door and th.door_crossing_time is None:
                    th.door_crossing_time = latest_time
                    # Check if another track crossed recently
                    for prev_tid, prev_time in list(self.last_door_crossings):
                        if prev_tid != tid and (latest_time - prev_time) <= window_sec:
                            if self._can_trigger("tailgating", latest_time, cooldown=10.0):
                                candidates.append({
                                    "camera_id": self.camera_id,
                                    "category_hint": "tailgating",
                                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                                    "track_ids": [prev_tid, tid],
                                    "tags": ["tailgating", "unauthorized_entry", "badge_passback"],
                                    "evidence": {"delta_sec": round(latest_time - prev_time, 2)},
                                })
                            break
                    self.last_door_crossings.append((tid, latest_time))
                elif not in_door:
                    th.door_crossing_time = None

        # 6. Check Suspicious Activity (Restricted Zone Loitering)
        restricted_zones = self.config.get("restricted_zones", [])
        if restricted_zones and not self._is_rule_paused("suspicious_activity", current_time):
            for tid in active_ids:
                th = self.tracks[tid]
                if not th.positions:
                    continue
                latest_time, box, cx, cy = th.positions[-1]
                for rzone in restricted_zones:
                    zname = rzone.get("name", "restricted_area")
                    poly = rzone.get("polygon", [])
                    max_dwell = float(rzone.get("max_loitering_seconds", 5.0))
                    if poly and point_in_polygon(cx, cy, poly):
                        if zname not in th.zone_entry_times:
                            th.zone_entry_times[zname] = latest_time
                        dwell = latest_time - th.zone_entry_times[zname]
                        if dwell >= max_dwell:
                            if self._can_trigger(f"suspicious_{zname}_{tid}", latest_time, cooldown=20.0):
                                candidates.append({
                                    "camera_id": self.camera_id,
                                    "category_hint": "suspicious_activity",
                                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                                    "track_ids": [tid],
                                    "tags": ["suspicious_activity", "loitering", "unauthorized_presence"],
                                    "evidence": {"dwell_sec": round(dwell, 1), "zone": zname},
                                })
                    else:
                        th.zone_entry_times.pop(zname, None)

        return candidates
