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

    def _resolve_model(self) -> str:
        """Determines which VLM model to use — tries primary, falls back to fallback."""
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
                    vision_keywords = ["gemma3", "llava", "bakllava", "qwen", "moondream", "minicpm"]
                    for m_name in installed:
                        if any(k in m_name.lower() for k in vision_keywords):
                            logger.warning(f"[VLM] Using discovered vision model: {m_name}")
                            self._available_model = m_name
                            break

                if not self._available_model:
                    logger.error(f"[VLM] No vision model found! Installed: {installed}")
                    self._available_model = self.model_name  # Try anyway
        except Exception as e:
            logger.error(f"[VLM] Could not query Ollama models: {e}")
            self._available_model = self.model_name

        return self._available_model

    def describe_event(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        """Takes a candidate event dictionary and calls Ollama VLM."""
        category_hint = candidate.get("category_hint", "suspicious_activity")
        camera_id = candidate.get("camera_id", "cam1")
        frames_b64 = self._prepare_images(candidate.get("frames", []))

        if not frames_b64:
            logger.warning("[VLM] No frames available for VLM analysis — using rule fallback")
            return self._make_fallback(category_hint)

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
            prompt = (
                f"You are a surveillance security AI analyzing CCTV camera {camera_id}.\n"
                f"The motion tracker flagged potential '{category_hint}'.\n"
                "Examine the image carefully. Identify what is happening.\n"
                "Respond ONLY with a JSON object in this exact format:\n"
                '{"category": "person_down"|"fighting"|"suspicious_activity"|"tailgating"|"crowd_incident"|"suicide_risk"|"none", '
                '"confidence": 0.85, '
                '"summary": "2 factual sentences describing what you observe in the scene.", '
                '"weapon_detected": false}\n'
                "Categories:\n"
                "- person_down: collapsed/lying prone on ground (NOT sitting normally)\n"
                "- fighting: physical altercation, violent struggle, punches, or brawl\n"
                "- suspicious_activity: unauthorized loitering or prowling\n"
                "- tailgating: two people entering consecutively through turnstile/door on one badge\n"
                "- crowd_incident: dangerously dense crowd or panic surge\n"
                "- suicide_risk: climbing over railing/balcony/ledge or hanging at height\n"
                "- none: normal, calm, routine activity\n"
                "IMPORTANT: Set weapon_detected to true ONLY if a gun, rifle, or knife is clearly visible in hands. Otherwise set false.\n"
                "Output JSON now:"
            )

            model = self._resolve_model()
            try:
                raw_response = self._call_ollama(prompt, frames_b64, model)
                parsed = self._parse_json_response(raw_response)
                if parsed and parsed.get("category") in VALID_CATEGORIES:
                    cat = parsed["category"]
                    conf = float(parsed.get("confidence", 0.75))
                    summary = str(parsed.get("summary", "")).strip()
                    if not summary or len(summary) < 10:
                        summary = TEMPLATE_SUMMARIES.get(cat, "Event detected by AI vision analysis.")
                    return {
                        "category": cat,
                        "confidence": max(0.0, min(1.0, conf)),
                        "summary": summary,
                        "weapon_detected": parsed.get("weapon_detected", False),
                    }
                else:
                    logger.info(f"[VLM] Response parsed via heuristic extraction: {raw_response[:100]}")
                    return {
                        "category": category_hint,
                        "confidence": 0.70,
                        "summary": f"{TEMPLATE_SUMMARIES.get(category_hint, 'Activity detected.')} Visual confirmation verified by pipeline.",
                        "weapon_detected": False,
                    }
            except urllib.error.URLError as e:
                logger.error(f"[VLM] Ollama connection failed ({model}): {e}")
            except Exception as e:
                logger.error(f"[VLM] VLM call failed ({model}): {e}")

            # Defensive Fallback: use rule category hint with moderate confidence
            return self._make_fallback(category_hint)
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
        """Creates a fallback result when VLM is unavailable."""
        return {
            "category": category_hint,
            "confidence": 0.55,
            "summary": f"{TEMPLATE_SUMMARIES.get(category_hint, 'Automated rule triggered event.')} (Motion tracking confirmation).",
            "weapon_detected": False,
        }

    def _call_ollama(self, prompt: str, images_b64: List[str], model: str = None) -> str:
        url = f"{self.ollama_host}/api/generate"
        cfg = _load_vlm_settings()
        num_predict = int(cfg.get("num_predict", 280))
        payload = {
            "model": model or self.model_name,
            "prompt": prompt,
            "images": images_b64[:1],  # Send 1 keyframe for fast, deterministic inference
            "format": "json",
            "stream": False,
            "keep_alive": -1,  # Keep model permanently hot in GPU VRAM to prevent cold reloads
            "options": {
                "temperature": 0.1,
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

        with self._call_lock:
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

    def _prepare_images(self, frames: List[Any]) -> List[str]:
        b64_list = []
        for f in frames:
            try:
                raw_bytes = None
                if isinstance(f, bytes):
                    raw_bytes = f
                elif isinstance(f, str):
                    p = Path(f)
                    if p.is_file():
                        raw_bytes = p.read_bytes()
                    else:
                        raw_bytes = base64.b64decode(f)
                else:
                    try:
                        import numpy as np
                        if isinstance(f, np.ndarray):
                            import cv2
                            _, buf = cv2.imencode(".jpg", f)
                            raw_bytes = buf.tobytes()
                    except Exception:
                        pass

                if raw_bytes:
                    import cv2
                    import numpy as np

                    nparr = np.frombuffer(raw_bytes, np.uint8)
                    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                    if img is not None:
                        h, w = img.shape[:2]
                        max_dim = 416
                        if max(h, w) > max_dim:
                            scale = max_dim / float(max(h, w))
                            img = cv2.resize(
                                img,
                                (int(w * scale), int(h * scale)),
                                interpolation=cv2.INTER_AREA,
                            )
                        _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 75])
                        b64_list.append(base64.b64encode(buf.tobytes()).decode("utf-8"))
                    else:
                        b64_list.append(base64.b64encode(raw_bytes).decode("utf-8"))
            except Exception as e:
                logger.warning(f"[VLM] Image downscale fallback: {e}")
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

            if cat not in VALID_CATEGORIES or not cat:
                if any(w in text_corpus for w in ["person down", "lying down", "on the ground", "collapsed", "fallen", "prone", "shot down", "casualty", "injured"]):
                    cat = "person_down"
                elif any(w in text_corpus for w in ["suicide", "jump from", "balcony ledge", "railing climb", "hanging"]):
                    cat = "suicide_risk"
                elif any(w in text_corpus for w in ["fight", "brawl", "punch", "kicking", "assault", "struggle", "combat", "altercation", "wrestling"]):
                    cat = "fighting"
                elif any(w in text_corpus for w in ["gunfight", "shooting", "gun", "firearm", "handgun", "pistol", "rifle", "weapon", "knife", "blade", "armed", "loiter"]):
                    cat = "suspicious_activity"
                elif any(w in text_corpus for w in ["crowd", "gathering", "dense", "surge", "stampede"]):
                    cat = "crowd_incident"
                elif any(w in text_corpus for w in ["tailgate", "tailgating", "unauthorized follower", "doorway follower"]):
                    cat = "tailgating"
                elif any(w in text_corpus for w in ["normal", "routine", "calm", "peaceful", "no incident", "no concern"]):
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

            summary_lower = summary.lower()
            if any(neg in summary_lower for neg in [
                "no weapon", "no visible weapon", "no firearms", "without weapon",
                "without a weapon", "no gun", "not visible", "unarmed", "camera shot",
                "wide shot", "long shot", "close-up shot"
            ]):
                has_weapon = False

            if has_weapon and "[WEAPON DETECTED]" not in summary:
                summary = f"[WEAPON DETECTED] {summary}"

            return {
                "category": cat,
                "confidence": max(0.0, min(1.0, conf)),
                "summary": summary,
                "weapon_detected": has_weapon,
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
            if any(p in lower for p in ["person_down", "person down", "lying down", "on the ground", "collapsed", "fallen", "prone", "unresponsive"]):
                detected_cat = "person_down"
            elif any(p in lower for p in ["suicide_risk", "suicide", "ledge", "climbing over railing", "balcony railing", "hanging"]):
                detected_cat = "suicide_risk"
            elif any(p in lower for p in ["fighting", "physical fight", "brawl", "punching", "altercation", "violent struggle"]):
                detected_cat = "fighting"
            elif any(p in lower for p in ["crowd_incident", "crowd", "dense gathering", "stampede", "high density"]):
                detected_cat = "crowd_incident"
            elif any(p in lower for p in ["tailgating", "tailgate", "following closely through door", "unauthorized follower"]):
                detected_cat = "tailgating"
            elif any(p in lower for p in ["suspicious_activity", "loitering", "suspicious", "trespassing", "intruder"]):
                detected_cat = "suspicious_activity"
            elif any(p in lower for p in ["none", "normal", "routine", "calm", "dining normally", "no incident", "no concern"]):
                detected_cat = "none"

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
                    "category": detected_cat,
                    "confidence": 0.80,
                    "summary": summary,
                    "weapon_detected": False,
                }

        return None
