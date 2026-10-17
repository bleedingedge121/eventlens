"""EventLens Rule-Based Event Trigger Engine.

Adheres strictly to AGENTS.md Section 10:
- Zones and thresholds come from config/cameras.json.
- Checks:
  1. tailgating: 2 distinct tracks cross the door zone within 1-2 seconds.
  2. person_down: temporal state machine (UPRIGHT -> TRANSITION -> DOWN_CANDIDATE -> CONFIRMED).
  3. crowd_incident: person count in camera view/region > crowd_threshold.
  4. suspicious_activity: person stays inside restricted zone longer than max_loitering_seconds.
  5. fighting: two person tracks overlap (IoU) with high speed/acceleration.
  6. dangerous_terrain & hazard zones: fall hazards, slip/spill hazards, high voltage.

Person-down detection uses a 5-state FSM per track ID with normalized thresholds.
A candidate is only emitted after the FSM reaches CONFIRMED state. The FSM never
silently auto-confirms on missing history.

States:
  UNKNOWN      -- not enough history yet
  UPRIGHT      -- person observed upright, baseline established
  TRANSITION   -- posture change detected, watching for sustained prone
  DOWN_CANDIDATE -- prone posture sustained, confirming stillness
  CONFIRMED    -- event candidate emitted for this episode; waiting for recovery
"""

from collections import deque
from datetime import datetime
from enum import Enum, auto
import time
from typing import Any, Dict, List, Optional, Tuple


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


class PersonDownState(Enum):
    UNKNOWN = auto()        # Not enough history to classify
    UPRIGHT = auto()        # Person observed upright; baseline established
    TRANSITION = auto()     # Posture change in progress; not yet sustained
    DOWN_CANDIDATE = auto() # Prone posture sustained; confirming stillness
    CONFIRMED = auto()      # Candidate emitted; awaiting recovery


class PersonDownFSM:
    """Per-track finite state machine for person-down detection.

    Uses monotonic video timestamps throughout. All movement and size thresholds
    are normalized by the person's own observed standing height to be independent
    of camera resolution and distance.

    Configuration keys (all from cameras.json, never hard-coded):
        person_down_aspect_ratio_threshold  (default 0.85)
            Width-to-height ratio of the bounding box above which the posture
            is considered horizontal/prone. A standing person is ~0.3-0.5.
        person_down_height_collapse_ratio   (default 0.60)
            Fraction of the person's observed peak standing height. If the
            current box height is below this fraction, the person is deemed to
            have collapsed (height fell more than 40 % from their normal posture).
        person_down_min_upright_frames      (default 6)
            Minimum number of upright observations before any transition can
            be accepted. Prevents triggering on someone who entered the frame
            already lying down.
        person_down_transition_frames       (default 4)
            How many consecutive prone observations are required before we move
            from TRANSITION -> DOWN_CANDIDATE. Prevents single-frame glitches.
        person_down_still_seconds           (default 2.5)
            How many seconds the prone posture must persist with low movement
            before emitting a candidate event.
        person_down_motion_threshold_ratio  (default 0.15)
            Maximum allowed center-of-box movement per unit of the person's
            observed standing box height, per second. E.g. 0.15 means the center
            must not move more than 15% of the person's own height per second.
            Normalized — independent of pixel resolution.
        person_down_recovery_aspect_thresh  (default 0.65)
            If the aspect ratio drops below this value the person is considered
            to have recovered (stood back up), and the FSM resets to UPRIGHT.
    """

    def __init__(self, track_id: int, config: Dict[str, Any]):
        self.track_id = track_id

        # Thresholds from config (with safe defaults)
        self.aspect_thresh: float = float(config.get("person_down_aspect_ratio_threshold", 0.85))
        self.collapse_ratio: float = float(config.get("person_down_height_collapse_ratio", 0.60))
        self.min_upright_frames: int = int(config.get("person_down_min_upright_frames", 6))
        self.transition_frames: int = int(config.get("person_down_transition_frames", 4))
        self.still_seconds: float = float(config.get("person_down_still_seconds", 2.5))
        self.motion_thresh_ratio: float = float(config.get("person_down_motion_threshold_ratio", 0.15))
        self.recovery_aspect: float = float(config.get("person_down_recovery_aspect_thresh", 0.65))

        # FSM state
        self.state: PersonDownState = PersonDownState.UNKNOWN

        # Upright baseline
        self._upright_heights: deque = deque(maxlen=30)  # rolling window of standing heights
        self._upright_frame_count: int = 0
        self._baseline_height: float = 0.0  # median standing box height

        # Transition tracking
        self._transition_frame_count: int = 0
        self._transition_start_time: Optional[float] = None

        # Down-candidate tracking (stillness)
        self._down_start_time: Optional[float] = None
        self._down_start_cx: float = 0.0
        self._down_start_cy: float = 0.0
        self._down_candidate_start_time: Optional[float] = None

    def _is_prone(self, w: float, h: float) -> bool:
        """Returns True if the current box looks horizontal/prone."""
        if h <= 0:
            return False
        aspect = w / h
        if aspect >= self.aspect_thresh:
            return True
        # Also check height-collapse relative to upright baseline
        if self._baseline_height > 0:
            if (h / self._baseline_height) < self.collapse_ratio:
                return True
        return False

    def _is_upright(self, w: float, h: float) -> bool:
        """Returns True if the current box looks clearly upright."""
        if h <= 0:
            return False
        aspect = w / h
        return aspect < self.recovery_aspect

    def _update_baseline(self, h: float) -> None:
        """Update the rolling upright height baseline."""
        self._upright_heights.append(h)
        # Use median of observed heights as a robust baseline
        sorted_h = sorted(self._upright_heights)
        mid = len(sorted_h) // 2
        self._baseline_height = sorted_h[mid] if sorted_h else h

    def update(
        self,
        timestamp: float,
        box: List[float],
        cx: float,
        cy: float,
    ) -> bool:
        """Feed a single observation. Returns True if a candidate event should be emitted.

        A True return indicates the track has just reached CONFIRMED state —
        i.e., this is the first notification for this episode.
        Repeated True returns for the same episode will NOT occur (the FSM
        moves to CONFIRMED and stays there until recovery).
        """
        w = box[2] - box[0]
        h = box[3] - box[1]

        prone = self._is_prone(w, h)
        upright = self._is_upright(w, h)

        if self.state == PersonDownState.UNKNOWN:
            if upright:
                self._upright_frame_count += 1
                self._update_baseline(h)
                if self._upright_frame_count >= self.min_upright_frames:
                    self.state = PersonDownState.UPRIGHT
            elif prone:
                # Entered frame already prone — record but don't confirm
                # (we have no upright baseline for comparison)
                pass
            return False

        if self.state == PersonDownState.UPRIGHT:
            if upright:
                self._upright_frame_count += 1
                self._update_baseline(h)
                return False
            if prone:
                # Posture changed — start transition
                self.state = PersonDownState.TRANSITION
                self._transition_frame_count = 1
                self._transition_start_time = timestamp
            return False

        if self.state == PersonDownState.TRANSITION:
            if prone:
                self._transition_frame_count += 1
                if self._transition_frame_count >= self.transition_frames:
                    # Sustained prone posture confirmed — move to candidate stage
                    self.state = PersonDownState.DOWN_CANDIDATE
                    self._down_candidate_start_time = timestamp
                    self._down_start_cx = cx
                    self._down_start_cy = cy
            else:
                # Posture recovered before transition completed — reset
                if upright:
                    self.state = PersonDownState.UPRIGHT
                    self._upright_frame_count += 1
                    self._update_baseline(h)
                else:
                    # Ambiguous intermediate posture — stay in TRANSITION but reset counter
                    self._transition_frame_count = max(0, self._transition_frame_count - 1)
                    if self._transition_frame_count == 0:
                        self.state = PersonDownState.UPRIGHT
            return False

        if self.state == PersonDownState.DOWN_CANDIDATE:
            if not prone:
                if upright:
                    # Person recovered before stillness threshold
                    self.state = PersonDownState.UPRIGHT
                    self._upright_frame_count = 1
                    self._update_baseline(h)
                    self._transition_frame_count = 0
                else:
                    # Ambiguous — keep candidate state but watch
                    pass
                return False

            # Still prone — check elapsed time and normalized motion
            elapsed = timestamp - (self._down_candidate_start_time or timestamp)

            # Normalized motion: movement relative to the person's own standing height
            if self._baseline_height > 0:
                motion = ((cx - self._down_start_cx) ** 2 + (cy - self._down_start_cy) ** 2) ** 0.5
                motion_ratio = motion / self._baseline_height
            else:
                # No baseline — use a generous fixed fraction of box height
                motion = ((cx - self._down_start_cx) ** 2 + (cy - self._down_start_cy) ** 2) ** 0.5
                motion_ratio = motion / max(h, 1.0)

            if elapsed >= self.still_seconds and motion_ratio < (self.motion_thresh_ratio * elapsed):
                # Sustained prone + low normalized movement → confirmed
                self.state = PersonDownState.CONFIRMED
                return True  # Emit exactly once
            return False

        if self.state == PersonDownState.CONFIRMED:
            # Check for recovery — person stood back up
            if upright:
                # Reset FSM for the next episode
                self.state = PersonDownState.UPRIGHT
                self._upright_frame_count = 1
                self._baseline_height = self._baseline_height  # keep baseline
                self._update_baseline(h)
                self._transition_frame_count = 0
                self._down_candidate_start_time = None
            return False  # No repeated emissions for the same episode

        return False  # Unreachable — safety fallback

    def reset_on_track_loss(self) -> None:
        """Called when a track ID is lost. Preserve upright baseline but reset episode state."""
        if self.state in (PersonDownState.TRANSITION, PersonDownState.DOWN_CANDIDATE):
            # Track lost mid-episode — cautiously drop the candidate
            self.state = PersonDownState.UPRIGHT
        self._transition_frame_count = 0
        self._down_candidate_start_time = None
        self._down_start_cx = 0.0
        self._down_start_cy = 0.0


class TrackHistory:
    def __init__(self, track_id: int):
        self.track_id = track_id
        # stores (timestamp_sec, [x1, y1, x2, y2], center_x, center_y)
        self.positions: deque = deque(maxlen=60)
        self.zone_entry_times: Dict[str, float] = {}
        self.hazard_entry_times: Dict[str, float] = {}
        self.door_crossing_time: Optional[float] = None
        self.was_outside_door: bool = False
        self.last_seen: float = time.time()


class TriggerEngine:
    def __init__(self, camera_id: str, config: Dict[str, Any]):
        self.camera_id = camera_id
        self.config = config
        self.tracks: Dict[int, TrackHistory] = {}
        # Per-track person-down FSMs — keyed by track ID
        self._pd_fsms: Dict[int, PersonDownFSM] = {}
        self.last_door_crossings: deque = deque(maxlen=10)  # stores (track_id, timestamp)
        self.last_trigger_times: Dict[str, float] = {}  # debouncing triggers
        self.cooldown_seconds = 8.0
        # Active problems & dangerous terrain occupant tracking
        self.active_zone_occupants: List[Dict[str, Any]] = []
        self.last_update_time: float = -1.0

    def update(
        self,
        detections: List[Dict[str, Any]],
        current_time: float,
    ) -> List[Dict[str, Any]]:
        """Processes current frame detections.

        detections: list of dicts: {"track_id": int, "box": [x1, y1, x2, y2], "confidence": float}
        Returns list of candidate event dicts.
        """
        # Detect video loop or backward seek — reset tracking state cleanly
        if self.last_update_time > 0 and (current_time < self.last_update_time - 0.5):
            self.tracks.clear()
            self._pd_fsms.clear()
            self.last_door_crossings.clear()
            self.active_zone_occupants.clear()

        self.last_update_time = current_time
        candidates: List[Dict[str, Any]] = []
        self.active_zone_occupants = []

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

            if tid not in self._pd_fsms:
                self._pd_fsms[tid] = PersonDownFSM(tid, self.config)

            th = self.tracks[tid]
            th.positions.append((current_time, box, cx, cy))
            th.last_seen = current_time

        # Remove stale tracks older than 8 seconds; notify their FSMs
        stale = [tid for tid, th in self.tracks.items() if current_time - th.last_seen > 8.0]
        for tid in stale:
            fsm = self._pd_fsms.get(tid)
            if fsm:
                fsm.reset_on_track_loss()
                del self._pd_fsms[tid]
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
                    "tags": ["crowd_incident", "crowd_surge", "density_overload"],
                })

        # 3. Check Person Down & Suspicious Activity per person
        door_zone = self.config.get("door_zone")
        restricted_zones = self.config.get("restricted_zones", [])
        hazard_zones = self.config.get("hazard_zones", [])

        for tid in active_ids:
            th = self.tracks[tid]
            if not th.positions:
                continue

            latest_time, box, cx, cy = th.positions[-1]
            w = box[2] - box[0]
            h = box[3] - box[1]

            # --- Person Down: delegate entirely to the state machine ---
            fsm = self._pd_fsms[tid]
            should_emit = fsm.update(latest_time, box, cx, cy)
            if should_emit:
                if self._can_trigger("person_down", current_time, cooldown=15.0):
                    candidates.append({
                        "camera_id": self.camera_id,
                        "category_hint": "person_down",
                        "timestamp": datetime.now().isoformat(timespec="seconds"),
                        "track_ids": [tid],
                        "tags": ["person_down", "slip_and_fall", "medical_emergency"],
                        # Include FSM state metadata for debugging
                        "_fsm_baseline_h": round(fsm._baseline_height, 1),
                        "_fsm_upright_frames": fsm._upright_frame_count,
                    })

            # Check Door Crossing for Tailgating:
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
                                    "tags": ["tailgating", "badge_passback", "access_violation"],
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
                max_loiter = rzone.get("max_loitering_seconds", 4.0)
                if poly and point_in_polygon(cx, cy, poly):
                    if zname not in th.zone_entry_times:
                        th.zone_entry_times[zname] = current_time
                    dwell = round(current_time - th.zone_entry_times[zname], 1)
                    self.active_zone_occupants.append({
                        "track_id": tid,
                        "zone_name": zname,
                        "zone_type": "restricted",
                        "dwell_sec": dwell,
                        "max_sec": max_loiter,
                        "severity": "WARNING" if dwell < max_loiter else "CRITICAL",
                    })
                    if dwell >= max_loiter:
                        if self._can_trigger(f"suspicious_{zname}_{tid}", current_time, cooldown=15.0):
                            candidates.append({
                                "camera_id": self.camera_id,
                                "category_hint": "suspicious_activity",
                                "timestamp": datetime.now().isoformat(timespec="seconds"),
                                "track_ids": [tid],
                                "tags": ["suspicious_activity", "loitering", "restricted_zone"],
                                "zone_name": zname,
                            })
                else:
                    th.zone_entry_times.pop(zname, None)

            # Check Dangerous Terrain & Hazard Zones (Ledges, Slip Hazards, High-Voltage)
            for hzone in hazard_zones:
                zname = hzone.get("name", "hazard")
                htype = hzone.get("hazard_type", "fall_hazard")
                poly = hzone.get("polygon", [])
                max_dwell = hzone.get("max_dwell_seconds", 2.0)
                if poly and point_in_polygon(cx, cy, poly):
                    if zname not in th.hazard_entry_times:
                        th.hazard_entry_times[zname] = current_time
                    dwell = round(current_time - th.hazard_entry_times[zname], 1)
                    self.active_zone_occupants.append({
                        "track_id": tid,
                        "zone_name": zname,
                        "zone_type": "hazard",
                        "hazard_type": htype,
                        "icon": hzone.get("icon", "⚠️"),
                        "dwell_sec": dwell,
                        "max_sec": max_dwell,
                        "severity": hzone.get("severity", "CRITICAL"),
                    })
                    if dwell >= max_dwell:
                        if self._can_trigger(f"hazard_{zname}_{tid}", current_time, cooldown=12.0):
                            cat_hint = "suicide_risk" if htype == "fall_hazard" else "suspicious_activity"
                            candidates.append({
                                "camera_id": self.camera_id,
                                "category_hint": cat_hint,
                                "timestamp": datetime.now().isoformat(timespec="seconds"),
                                "track_ids": [tid],
                                "tags": [
                                    "dangerous_terrain",
                                    htype,
                                    zname.lower().replace(" ", "_"),
                                ],
                                "zone_name": zname,
                            })
                else:
                    th.hazard_entry_times.pop(zname, None)

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
                    # Check velocity and kinetic oscillation
                    if len(t1.positions) >= 2 and len(t2.positions) >= 2:
                        p1_now, p1_prev = t1.positions[-1], t1.positions[-2]
                        p2_now, p2_prev = t2.positions[-1], t2.positions[-2]
                        dt1 = p1_now[0] - p1_prev[0]
                        dt2 = p2_now[0] - p2_prev[0]
                        if dt1 > 0 and dt2 > 0:
                            s1 = (((p1_now[2] - p1_prev[2]) ** 2 + (p1_now[3] - p1_prev[3]) ** 2) ** 0.5) / dt1
                            s2 = (((p2_now[2] - p2_prev[2]) ** 2 + (p2_now[3] - p2_prev[3]) ** 2) ** 0.5) / dt2
                            avg_speed = (s1 + s2) / 2.0

                            # Kinetic oscillation / erratic grappling motion:
                            # Physical altercations exhibit sudden velocity reversals, whereas walking has smooth flow
                            is_erratic = False
                            if len(t1.positions) >= 3 and len(t2.positions) >= 3:
                                p1_old = t1.positions[-3]
                                vx1 = p1_now[2] - p1_prev[2]
                                vy1 = p1_now[3] - p1_prev[3]
                                vx1_old = p1_prev[2] - p1_old[2]
                                vy1_old = p1_prev[3] - p1_old[3]
                                dot1 = vx1 * vx1_old + vy1 * vy1_old
                                if dot1 < 0:
                                    is_erratic = True

                            if (avg_speed >= speed_thresh) or (avg_speed >= speed_thresh * 0.70 and is_erratic):
                                if self._can_trigger("fighting", current_time, cooldown=12.0):
                                    candidates.append({
                                        "camera_id": self.camera_id,
                                        "category_hint": "fighting",
                                        "timestamp": datetime.now().isoformat(timespec="seconds"),
                                        "track_ids": [active_list[i], active_list[j]],
                                        "tags": ["fighting", "physical_violence", "brawl_assault"],
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

    def get_active_zone_status(self) -> List[Dict[str, Any]]:
        """Returns list of currently active zone occupants and hazard dwell statuses."""
        return self.active_zone_occupants

    def _can_trigger(self, key: str, current_time: float, cooldown: Optional[float] = None) -> bool:
        cd = cooldown if cooldown is not None else self.cooldown_seconds
        last_t = self.last_trigger_times.get(key, -1e9)
        if current_time - last_t >= cd:
            self.last_trigger_times[key] = current_time
            return True
        return False
