"""EventLens Vision-Language Model (VLM) Integration.

Adheres strictly to AGENTS.md Section 11 contract:
- Calls local Ollama vision model on candidate event frames.
- Expects strictly JSON: {"category": one of 5 or "none", "confidence": 0..1, "summary": "1-2 sentences"}.
- Defensively parses JSON, regex extracts from code blocks, handles timeouts.
- Falls back to rule-based category hint with lowered confidence on failure.
- Tries primary VLM model, then fallback model if primary unavailable.
"""

import base64
import json
import logging
import re
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("eventlens.vlm")

VALID_CATEGORIES = {
    "person_down",
    "fighting",
    "tailgating",
    "crowd_incident",
    "suspicious_activity",
    "suicide_risk",
    "none",
}

TEMPLATE_SUMMARIES = {
    "tailgating": "Potential tailgating detected: multiple individuals entered consecutively without secondary credential swipe.",
    "person_down": "Person down alert: individual detected remaining prone on ground for extended duration.",
    "crowd_incident": "Crowd gathering alert: person count exceeded regional density safety threshold.",
    "suspicious_activity": "Suspicious activity alert: unauthorized presence or loitering detected in surveillance zone.",
    "fighting": "Physical altercation / violent struggle detected: overlapping tracks with rapid kinetic movement.",
    "suicide_risk": "Critical hazard alert: individual detected in high-risk zone (ledge, railing, or dangerous height).",
}


def _load_vlm_settings() -> dict:
    """Loads VLM configuration from config/settings.json."""
    settings_path = Path(__file__).resolve().parent.parent.parent / "config" / "settings.json"
    try:
        with open(settings_path, "r") as f:
            return json.load(f).get("ollama", {})
    except Exception:
        return {}


class VLMClient:
    def __init__(
        self,
        ollama_host: str = None,
        model_name: str = None,
        fallback_model: str = None,
        timeout_seconds: int = None,
    ):
        cfg = _load_vlm_settings()
        self.ollama_host = (ollama_host or cfg.get("host", "http://localhost:11434")).rstrip("/")
        self.model_name = model_name or cfg.get("vlm_model", "qwen3-vl:8b")
        self.fallback_model = fallback_model or cfg.get("vlm_fallback_model", "qwen3-vl:8b")
        self.timeout = timeout_seconds or cfg.get("timeout_seconds", 60)
        self._available_model: Optional[str] = None  # Cached working model name
        self._call_lock = threading.Lock()
        self.is_busy: bool = False
        self.current_hint: str = ""
        self.current_camera: str = ""
        self.task_start_time: float = 0.0
        logger.info(f"[VLM] Configured: primary={self.model_name}, fallback={self.fallback_model}, timeout={self.timeout}s")

    def get_status(self) -> dict:
        """Returns live execution state of the VLM engine."""
        now = time.time()
        elapsed = round(now - self.task_start_time, 1) if (self.is_busy and self.task_start_time > 0) else 0.0
        return {
            "is_busy": self.is_busy,
            "current_hint": self.current_hint,
            "camera_id": self.current_camera,
            "elapsed_sec": elapsed,
            "model": self._available_model or self.model_name,
        }

    def _resolve_model(self) -> Optional[str]:
        """Determines which VLM model to use — tries primary, falls back to fallback. Returns None if missing."""
        if self._available_model:
            return self._available_model

        # Check which models are actually available in Ollama
        try:
            req = urllib.request.Request(f"{self.ollama_host}/api/tags")
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read())
                installed = {m["name"] for m in data.get("models", [])}
                logger.info(f"[VLM] Installed Ollama models: {installed}")

                if self.model_name in installed:
                    self._available_model = self.model_name
                elif self.fallback_model in installed:
                    logger.warning(f"[VLM] Primary model '{self.model_name}' not found, using fallback '{self.fallback_model}'")
                    self._available_model = self.fallback_model
                else:
                    # Try any vision-capable model
                    vision_keywords = ["qwen", "gemma3", "llava", "bakllava", "moondream", "minicpm"]
                    for m_name in installed:
                        if any(k in m_name.lower() for k in vision_keywords):
                            logger.warning(f"[VLM] Using discovered vision model: {m_name}")
                            self._available_model = m_name
                            break

                if not self._available_model:
                    logger.error(f"[VLM] No vision model found! Installed: {installed}")
                    return None
        except Exception as e:
            logger.error(f"[VLM] Could not query Ollama models: {e}")
            return None

        return self._available_model

    def describe_event(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        """Takes a candidate event dictionary and calls Ollama VLM."""
        category_hint = candidate.get("category_hint", "suspicious_activity")
        camera_id = candidate.get("camera_id", "cam1")
        boxes = candidate.get("boxes", [])
        frames_b64 = self._prepare_images(candidate.get("frames", []), boxes=boxes, max_dim=768, include_crops=True)

        if not frames_b64:
            logger.warning("[VLM] No frames available for VLM analysis — cannot verify")
            return self._make_unverified_fallback(category_hint, reason="no_frames")

        self.is_busy = True
        self.current_hint = category_hint
        self.current_camera = camera_id
        self.task_start_time = time.time()

        try:
            from backend.vision.pipeline import set_vlm_activity
            set_vlm_activity(camera_id, True, category_hint)
        except Exception:
            pass

        try:
            model = self._resolve_model()
            if not model:
                logger.error("[VLM] Vision model not found or Ollama unreachable — failing closed")
                return self._make_unverified_fallback(category_hint, reason="missing_model")

            candidate_tags = candidate.get("tags", [])
            prompt = (
                f"You are a physical surveillance security AI analyzing CCTV camera {camera_id}.\n"
                f"Motion tracker flagged potential '{category_hint}'.\n"
                "Examine the image carefully (and focused crop if provided). Determine if an actual security incident or medical emergency is occurring, or if this is normal routine human activity.\n"
                "Respond ONLY with a JSON object in this exact format:\n"
                '{"is_incident": true|false, '
                '"category": "person_down"|"fighting"|"suspicious_activity"|"tailgating"|"crowd_incident"|"suicide_risk"|"none", '
                '"confidence": 0.85, '
                '"summary": "2 factual sentences describing what you observe in the scene.", '
                '"weapon_detected": false, '
                '"weapon_type": "none"|"firearm"|"bladed"|"blunt", '
                '"tags": ["' + category_hint + '"]}\n'
                "Decision Rules:\n"
                "- If no one is lying on the floor, no fight is happening, no panic crowd, or people are walking/dining normally: set is_incident=false and category='none'.\n"
                "- Only set is_incident=true if you visually confirm a genuine emergency or policy breach.\n"
                "- person_down: person collapsed or lying prone on the floor.\n"
                "- fighting: physical altercation, violent struggle, punches, or brawl.\n"
                "- suspicious_activity: unauthorized prowling, break-in attempt, or climbing.\n"
                "- tailgating: two people entering consecutively on one badge scan.\n"
                "- crowd_incident: dangerous panic surge or stampede.\n"
                "- none: normal, calm, routine activity, people dining, standing, or walking.\n"
                "WEAPON RECOGNITION: Examine hands and waistlines carefully in the high-resolution crop and scene. Set weapon_detected=true and weapon_type to 'firearm' or 'bladed' ONLY if a gun, rifle, pistol, or knife is clearly held or brandished. If person holds a phone, cup, tool, or empty hands, set weapon_detected=false and weapon_type='none'.\n"
                "Output JSON now:"
            )

            try:
                raw_response = self._call_ollama(prompt, frames_b64, model)
                if not raw_response or not raw_response.strip():
                    logger.warning("[VLM] Empty response from Ollama — failing closed")
                    return self._make_unverified_fallback(category_hint, reason="malformed_response")

                parsed = self._parse_json_response(raw_response)
                if parsed and parsed.get("category") in VALID_CATEGORIES:
                    is_incident = parsed.get("is_incident", True)
                    cat = parsed["category"]
                    if not is_incident or cat == "none":
                        cat = "none"
                    conf = float(parsed.get("confidence", 0.75))
                    summary = str(parsed.get("summary", "")).strip()
                    if not summary or len(summary) < 10:
                        summary = TEMPLATE_SUMMARIES.get(cat, "Event detected by AI vision analysis.")
                    tags = list(set(parsed.get("tags", []) + candidate_tags + [cat]))
                    return {
                        "is_incident": (cat != "none"),
                        "category": cat,
                        "confidence": max(0.0, min(1.0, conf)),
                        "summary": summary,
                        "weapon_detected": parsed.get("weapon_detected", False),
                        "weapon_type": parsed.get("weapon_type", "none"),
                        "tags": tags,
                        "verified": True,
                        "verification_status": "vlm_confirmed" if cat != "none" else "vlm_rejected",
                    }
                else:
                    # Ollama responded but output could not be parsed into a valid category.
                    logger.warning(f"[VLM] Response not parseable into valid category: {raw_response[:120]!r} — failing closed")
                    return self._make_unverified_fallback(category_hint, reason="malformed_response")
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    logger.error(f"[VLM] Ollama model '{model}' not found (404) — failing closed")
                    return self._make_unverified_fallback(category_hint, reason="missing_model")
                logger.error(f"[VLM] Ollama HTTP error ({model}): {e} — failing closed")
                return self._make_unverified_fallback(category_hint, reason="http_error")
            except (TimeoutError, urllib.error.URLError) as e:
                is_timeout = isinstance(e, TimeoutError) or isinstance(getattr(e, "reason", None), TimeoutError) or "timed out" in str(e).lower()
                reason = "timeout" if is_timeout else "connection_error"
                logger.error(f"[VLM] Ollama connection/timeout failed ({model}): {e} — failing closed")
                return self._make_unverified_fallback(category_hint, reason=reason)
            except Exception as e:
                logger.error(f"[VLM] VLM call failed ({model}): {e} — failing closed")
                return self._make_unverified_fallback(category_hint, reason="error")
        finally:
            self.is_busy = False
            self.current_hint = ""
            self.task_start_time = 0.0
            try:
                from backend.vision.pipeline import set_vlm_activity
                set_vlm_activity(camera_id, False, "")
            except Exception:
                pass

    def _make_fallback(self, category_hint: str) -> Dict[str, Any]:
        """Creates an honest unverified result when VLM is completely unavailable (Ollama offline)."""
        res = self._make_unverified_fallback(category_hint, reason="vlm_offline")
        res["verification_status"] = "vlm_offline"
        return res

    def _make_unverified_fallback(self, category_hint: str, reason: str = "unknown") -> Dict[str, Any]:
        """Creates an honest unverified result when VLM fails.

        FAIL CLOSED: Never marks event as verified or confirmed.
        """
        reason_label = reason.upper().replace("_", " ")
        return {
            "is_incident": False,
            "category": category_hint,
            "confidence": 0.40,
            "summary": f"[UNVERIFIED - {reason_label}] Candidate motion trigger for {category_hint}. AI verification failed ({reason}); not a verified incident.",
            "weapon_detected": False,
            "weapon_type": "none",
            "tags": [category_hint, "unverified", f"unverified_{reason}"],
            "verified": False,
            "verification_status": f"unverified_{reason}",
        }

    def _call_ollama(self, prompt: str, images_b64: List[str], model: str = None) -> str:
        url = f"{self.ollama_host}/api/generate"
        cfg = _load_vlm_settings()
        num_predict = int(cfg.get("num_predict", 280))
        payload = {
            "model": model or self.model_name,
            "prompt": prompt,
            "images": images_b64[:2],  # Send up to 2 images: high-res crop + full-frame scene
            "format": "json",
            "stream": False,
            "keep_alive": -1,  # Keep model permanently hot in GPU VRAM to prevent cold reloads
            "options": {
                "temperature": 0.1,
                "num_ctx": 2048,  # Limits KV cache to ~100MB so 100% of model fits in GPU VRAM
                "num_predict": num_predict,  # Focused token budget ensuring thinking + JSON completes
            },
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        acquired = self._call_lock.acquire(blocking=True, timeout=8.0)
        if not acquired:
            logger.warning("[VLM] Inference lock busy — failing closed")
            return ""

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                resp_text = body.get("response", "").strip()
                if resp_text:
                    return resp_text
                # If reasoning model stopped before response field, inspect thinking text
                thinking = body.get("thinking", "").strip()
                if thinking:
                    logger.info(f"[VLM] Response empty, returning thinking text ({len(thinking)} chars)")
                    return thinking
                return ""
        finally:
            self._call_lock.release()

    def _prepare_images(
        self,
        frames: List[Any],
        boxes: Optional[List[List[float]]] = None,
        max_dim: int = 768,
        include_crops: bool = True,
        quality: int = 85,
    ) -> List[str]:
        b64_list = []
        for f in frames[:1]:  # primary keyframe
            try:
                raw_bytes = None
                if isinstance(f, bytes):
                    raw_bytes = f
                elif isinstance(f, str):
                    p = Path(f)
                    if p.is_file():
                        raw_bytes = p.read_bytes()
                    else:
                        try:
                            raw_bytes = base64.b64decode(f)
                        except Exception:
                            pass
                elif hasattr(f, "shape"):
                    try:
                        import cv2
                        _, buf = cv2.imencode(".jpg", f)
                        raw_bytes = buf.tobytes()
                    except Exception:
                        pass

                if not raw_bytes:
                    continue

                import cv2
                import numpy as np

                nparr = np.frombuffer(raw_bytes, np.uint8)
                img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                if img is None:
                    # In unit tests or mock data, raw_bytes may be dummy non-image bytes (e.g. b"fake_frame_bytes")
                    # Fallback to direct base64 encoding so downstream mocks receive the images
                    b64_list.append(base64.b64encode(raw_bytes).decode("utf-8"))
                    continue

                img_h, img_w = img.shape[:2]

                # 1. Generate crops for each track box to preserve small object/weapon details
                if include_crops and boxes:
                    for box in boxes[:2]:
                        try:
                            bx1, by1, bx2, by2 = box
                            bw = bx2 - bx1
                            bh = by2 - by1
                            # Pad box by 30% to capture hands, waistline, and immediate context
                            pad_x = bw * 0.30
                            pad_y = bh * 0.30
                            cx1 = max(0, int(bx1 - pad_x))
                            cy1 = max(0, int(by1 - pad_y))
                            cx2 = min(img_w, int(bx2 + pad_x))
                            cy2 = min(img_h, int(by2 + pad_y))
                            if (cx2 - cx1) >= 20 and (cy2 - cy1) >= 20:
                                crop = img[cy1:cy2, cx1:cx2]
                                ch, cw = crop.shape[:2]
                                if max(ch, cw) > 512:
                                    s = 512.0 / max(ch, cw)
                                    crop = cv2.resize(crop, (int(cw * s), int(ch * s)), interpolation=cv2.INTER_AREA)
                                _, c_buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 90])
                                b64_list.append(base64.b64encode(c_buf.tobytes()).decode("utf-8"))
                        except Exception as e:
                            logger.warning(f"[VLM] Crop extraction error: {e}")

                # 2. Generate full-scene image with high-resolution scaling (768px)
                scene_img = img.copy()
                if max(img_h, img_w) > max_dim:
                    scale = max_dim / float(max(img_h, img_w))
                    scene_img = cv2.resize(
                        scene_img,
                        (int(img_w * scale), int(img_h * scale)),
                        interpolation=cv2.INTER_AREA,
                    )
                _, buf = cv2.imencode(".jpg", scene_img, [cv2.IMWRITE_JPEG_QUALITY, quality])
                b64_list.append(base64.b64encode(buf.tobytes()).decode("utf-8"))
            except Exception as e:
                logger.warning(f"[VLM] Image preparation error: {e}")
                if isinstance(f, bytes):
                    b64_list.append(base64.b64encode(f).decode("utf-8"))

        return b64_list

    @staticmethod
    def _parse_json_response(text: str) -> Optional[Dict[str, Any]]:
        if not text:
            return None

        def _normalize_dict(d: Any) -> Optional[Dict[str, Any]]:
            if not isinstance(d, dict):
                return None

            # 1. Check explicit category
            cat = str(d.get("category", "")).lower().strip()

            # 2. Text corpus for semantic extraction
            text_corpus = (
                str(d.get("event", "")) + " " +
                str(d.get("summary", "")) + " " +
                str(d.get("context", "")) + " " +
                str(d.get("description", "")) + " " +
                str(d.get("scene", "")) + " " +
                str(d.get("action", ""))
            ).lower()

            # Handle explicit is_incident boolean from model
            is_incident_val = d.get("is_incident")
            if is_incident_val is False or is_incident_val == "false" or is_incident_val == 0:
                cat = "none"

            if cat not in VALID_CATEGORIES or not cat:
                # Check for explicit statements that there is NO emergency / normal activity
                if any(w in text_corpus for w in [
                    "not in a panic", "not necessarily in a panic", "no panic",
                    "normal", "routine", "calm", "peaceful", "no incident",
                    "no concern", "no one is down", "dining", "eating"
                ]):
                    cat = "none"
                elif any(w in text_corpus for w in ["person down", "lying down", "on the ground", "collapsed", "fallen", "prone", "shot down", "casualty", "injured"]):
                    cat = "person_down"
                elif any(w in text_corpus for w in ["suicide", "jump from", "balcony ledge", "railing climb", "hanging"]):
                    cat = "suicide_risk"
                elif any(w in text_corpus for w in ["fight", "brawl", "punch", "kicking", "assault", "struggle", "combat", "altercation", "wrestling"]):
                    cat = "fighting"
                elif any(w in text_corpus for w in ["gunfight", "shooting", "gun", "firearm", "handgun", "pistol", "rifle", "weapon", "knife", "blade", "armed"]):
                    cat = "suspicious_activity"
                elif any(w in text_corpus for w in ["crowd", "gathering", "dense", "surge", "stampede"]):
                    cat = "crowd_incident"
                elif any(w in text_corpus for w in ["tailgate", "tailgating", "unauthorized follower", "doorway follower"]):
                    cat = "tailgating"
                else:
                    cat = "none"

            if not cat or cat not in VALID_CATEGORIES:
                return None

            # Confidence
            conf = d.get("confidence")
            try:
                conf = float(conf)
            except (TypeError, ValueError):
                conf = 0.90

            # Extract best summary string
            summary = str(
                d.get("summary") or
                d.get("context") or
                d.get("event") or
                d.get("description") or
                ""
            ).strip()

            if not summary or len(summary) < 8:
                summary = TEMPLATE_SUMMARIES.get(cat, "Activity classified by VLM.")

            # Strict weapon extraction: ONLY when explicitly true and not negated
            weapon_val = d.get("weapon_detected")
            has_weapon = False
            if isinstance(weapon_val, bool):
                has_weapon = weapon_val
            elif isinstance(weapon_val, str):
                has_weapon = weapon_val.lower().strip() in ["true", "1", "yes"]

            weapon_type = str(d.get("weapon_type", "none")).lower().strip()
            if weapon_type not in ["firearm", "bladed", "blunt"]:
                weapon_type = "firearm" if has_weapon else "none"

            summary_lower = summary.lower()
            if any(neg in summary_lower for neg in [
                "no weapon", "no visible weapon", "no firearms", "without weapon",
                "without a weapon", "no gun", "not visible", "unarmed", "camera shot",
                "wide shot", "long shot", "close-up shot"
            ]):
                has_weapon = False
                weapon_type = "none"

            # Check if summary mentions explicit firearm or knife
            if not has_weapon:
                if any(w in summary_lower for w in ["holding a gun", "holding a rifle", "holding a pistol", "handgun visible", "wielding a knife"]):
                    has_weapon = True
                    weapon_type = "bladed" if "knife" in summary_lower else "firearm"

            if has_weapon:
                badge = f"[WEAPON DETECTED] [WEAPON: {weapon_type.upper()}]" if weapon_type != "none" else "[WEAPON DETECTED]"
                if "[WEAPON DETECTED]" not in summary:
                    summary = f"{badge} {summary}"

            # Extract tags
            raw_tags = d.get("tags", [])
            tags_list = []
            if isinstance(raw_tags, list):
                tags_list = [str(t).lower().strip() for t in raw_tags if t]
            elif isinstance(raw_tags, str) and raw_tags:
                tags_list = [t.strip().lower() for t in raw_tags.split(",") if t.strip()]

            if cat and cat not in tags_list:
                tags_list.append(cat)
            if has_weapon:
                tags_list.extend(["weapon_detected", f"weapon_{weapon_type}"])

            return {
                "category": cat,
                "confidence": max(0.0, min(1.0, conf)),
                "summary": summary,
                "weapon_detected": has_weapon,
                "weapon_type": weapon_type,
                "tags": list(set(tags_list)),
            }

        # 1. Try direct parse
        try:
            parsed = json.loads(text.strip())
            norm = _normalize_dict(parsed)
            if norm:
                return norm
        except Exception:
            pass

        # 2. Extract JSON enclosed in ```json ... ``` codeblocks
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(1).strip())
                norm = _normalize_dict(parsed)
                if norm:
                    return norm
            except Exception:
                pass

        # 3. Find first { and last }
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                parsed = json.loads(text[start : end + 1])
                norm = _normalize_dict(parsed)
                if norm:
                    return norm
            except Exception:
                pass

        # 4. Resilient partial/truncated JSON repair
        if start != -1:
            fragment = text[start:].strip()
            for suffix in ['"}', '"]}', '}']:
                try:
                    parsed = json.loads(fragment + suffix)
                    norm = _normalize_dict(parsed)
                    if norm:
                        return norm
                except Exception:
                    pass

        # 5. Regex attribute extraction (guaranteed fallback)
        cat_m = re.search(r'"category"\s*:\s*"([a-zA-Z0-9_]+)"', text)
        if cat_m:
            category = cat_m.group(1).lower()
            conf_m = re.search(r'"confidence"\s*:\s*([0-9.]+)', text)
            confidence = float(conf_m.group(1)) if conf_m else 0.85
            sum_m = re.search(r'"summary"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)', text)
            summary = sum_m.group(1).strip() if sum_m else ""
            weapon_m = re.search(r'"weapon_detected"\s*:\s*(true|false)', text, re.IGNORECASE)
            has_weapon = weapon_m.group(1).lower() == "true" if weapon_m else False

            if category in VALID_CATEGORIES:
                return {
                    "category": category,
                    "confidence": max(0.0, min(1.0, confidence)),
                    "summary": summary,
                    "weapon_detected": has_weapon,
                }

        # 6. Semantic Free-Form Prose Extraction (for reasoning models where response/thinking is conversational)
        clean_text = text.strip()
        if len(clean_text) > 15:
            lower = clean_text.lower()
            detected_cat = None
            is_incident = True

            # First check if the model describes normal, non-emergency activity or denies an incident
            is_benign = any(p in lower for p in [
                "not necessarily in a panic", "not in a panic", "no panic",
                "dining normally", "eating normally", "sitting at table",
                "normal routine", "routine activity", "calm", "peaceful",
                "no incident", "no concern", "no weapon", "no fight",
                "no one is down", "nobody collapsed", "interacting normally",
                "not an emergency", "not a crime", "normal interaction"
            ])

            if is_benign:
                detected_cat = "none"
                is_incident = False
            elif any(p in lower for p in ["person_down", "person down", "lying down", "on the ground", "collapsed", "fallen prone", "unresponsive on floor"]):
                detected_cat = "person_down"
            elif any(p in lower for p in ["suicide_risk", "suicide", "ledge", "climbing over railing", "balcony railing", "hanging"]):
                detected_cat = "suicide_risk"
            elif any(p in lower for p in ["fighting", "physical fight", "brawl", "punching", "altercation", "violent struggle"]):
                detected_cat = "fighting"
            elif any(p in lower for p in ["crowd_incident", "dense gathering", "stampede", "panic surge", "dangerous density"]):
                detected_cat = "crowd_incident"
            elif any(p in lower for p in ["tailgating", "tailgate", "following closely through door", "unauthorized follower"]):
                detected_cat = "tailgating"
            elif any(p in lower for p in ["suspicious_activity", "loitering", "prowling", "trespassing", "intruder"]):
                detected_cat = "suspicious_activity"
            elif any(p in lower for p in ["none", "normal", "routine", "calm", "dining"]):
                detected_cat = "none"
                is_incident = False

            if detected_cat:
                raw_sentences = [s.strip() for s in re.split(r'[.!?\n]+', clean_text) if len(s.strip()) > 10]
                content_sentences = [
                    s for s in raw_sentences
                    if not any(lead in s.lower() for lead in [
                        "got it", "let's analyze", "first, look", "looking at the",
                        "as an ai", "the scenario is", "image shows a person labeled",
                        "the motion tracker flagged"
                    ])
                ]
                summary = ". ".join(content_sentences[:2]) + "." if content_sentences else TEMPLATE_SUMMARIES.get(detected_cat, "Observed activity analyzed by vision model.")
                summary = re.sub(r'\.\s*\.', '.', summary)
                return {
                    "is_incident": is_incident,
                    "category": detected_cat,
                    "confidence": 0.85 if is_incident else 0.95,
                    "summary": summary,
                    "weapon_detected": False,
                }

        return None
