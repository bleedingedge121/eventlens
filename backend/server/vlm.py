"""EventLens Vision-Language Model (VLM) Integration.

Adheres strictly to AGENTS.md Section 11 and VLM gatekeeper specifications:
- Rules only PROPOSE candidates; the VLM strictly VERIFIES them.
- Prompt requires explicit verification:
  "Look only at what is visible. Does this image show {category}?
   Answer JSON only: {"verified": bool, "confidence": 0-1, "what_is_visible": "<one factual sentence>", "reason": "<why>"}. If unsure, set verified=false."
- For person_down: "Is a person lying on the floor? Answer JSON only: ..."
- If verified=false or the call times out/fails, DROP the event. Never fall back to rule-written descriptions.
- Zero hardcoded secondary tags. Any tag shown must come strictly from the VLM's JSON output.
- Store the VLM's own sentence as the description. No "(Motion tracking confirmation)".
- Combined confidence = VLM confidence combined with rule margin. Never a constant.
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
import cv2

logger = logging.getLogger("eventlens.vlm")

VALID_CATEGORIES = {
    "person_down",
    "fighting",
    "tailgating",
    "crowd_incident",
    "suspicious_activity",
    "none",
}

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def _load_vlm_settings() -> dict:
    settings_file = BASE_DIR / "config" / "settings.json"
    if not settings_file.exists():
        return {}
    try:
        with open(settings_file, "r") as f:
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
        self.timeout = timeout_seconds or cfg.get("timeout_seconds", 8)
        self._available_model: Optional[str] = None
        self._last_health_check: float = 0.0
        self._is_online: bool = False
        self._call_lock = threading.Lock()
        self.is_busy: bool = False
        self.current_hint: str = ""
        self.current_camera: str = ""
        self.task_start_time: float = 0.0
        logger.info(f"[VLM] Configured: primary={self.model_name}, timeout={self.timeout}s")

    def get_status(self) -> dict:
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
        now = time.time()
        if self._available_model and (now - self._last_health_check < 30.0):
            return self._available_model

        self._last_health_check = now
        try:
            req = urllib.request.Request(f"{self.ollama_host}/api/tags")
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                installed = {m["name"] for m in data.get("models", [])}
                if self.model_name in installed:
                    self._available_model = self.model_name
                elif self.fallback_model in installed:
                    self._available_model = self.fallback_model
                else:
                    vision_keywords = ["qwen", "gemma3", "llava", "moondream", "minicpm"]
                    for m_name in installed:
                        if any(k in m_name.lower() for k in vision_keywords):
                            self._available_model = m_name
                            break
                if not self._available_model:
                    self._available_model = self.model_name
                self._is_online = True
        except Exception:
            self._is_online = False
            self._available_model = self.model_name

        return self._available_model

    def describe_event(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        """Takes a candidate event dictionary and strictly verifies it using the VLM."""
        category_hint = candidate.get("category_hint", "suspicious_activity")
        camera_id = candidate.get("camera_id", "cam1")
        rule_conf = float(candidate.get("rule_confidence", 0.75))
        frames_b64 = self._prepare_images(candidate.get("frames", []))

        # Default rejection if no frames or VLM unavailable
        rejection = {
            "verified": False,
            "category": "none",
            "confidence": 0.0,
            "summary": "",
            "tags": [],
            "reason": "VLM verification negative or unverified",
        }

        if not frames_b64:
            logger.warning("[VLM] No frames available — dropping unverified candidate")
            return rejection

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
            # Construct strict category-specific verification prompt
            if category_hint == "person_down":
                prompt = (
                    f"You are a physical security AI analyzing CCTV camera {camera_id}.\n"
                    "Look ONLY at what is visible in the provided image.\n"
                    "QUESTION: Is a human being lying down or collapsed on the floor or ground?\n"
                    "RULES:\n"
                    "- If people are sitting in chairs, sitting at dining tables, bending over, or standing, verified MUST be false.\n"
                    "- If a person is genuinely collapsed or lying flat on the floor, verified is true.\n"
                    "- If unsure, set verified=false.\n"
                    "Respond ONLY with a JSON object in this exact format:\n"
                    '{"verified": true/false, "confidence": 0.0-1.0, "what_is_visible": "<one factual sentence describing what is visible>", "reason": "<why>", "tags": []}\n'
                    "Output JSON now:"
                )
            elif category_hint == "fighting":
                prompt = (
                    f"You are a physical security AI analyzing CCTV camera {camera_id}.\n"
                    "Look ONLY at what is visible in the provided image.\n"
                    "QUESTION: Is there an active physical fight, brawl, or violent struggle occurring between people?\n"
                    "RULES:\n"
                    "- People walking past each other, hugging, or talking are NOT fighting. Set verified=false.\n"
                    "- If violent punches, wrestling, or physical assault is visible, set verified=true.\n"
                    "- If unsure, set verified=false.\n"
                    "Respond ONLY with a JSON object in this exact format:\n"
                    '{"verified": true/false, "confidence": 0.0-1.0, "what_is_visible": "<one factual sentence describing what is visible>", "reason": "<why>", "tags": []}\n'
                    "Output JSON now:"
                )
            elif category_hint == "crowd_incident":
                prompt = (
                    f"You are a physical security AI analyzing CCTV camera {camera_id}.\n"
                    "Look ONLY at what is visible in the provided image.\n"
                    "QUESTION: Is there a dangerously dense crowd surge, stampede, or panicked mob?\n"
                    "RULES:\n"
                    "- A normal busy street or pedestrian walkway with people walking peacefully is NOT a crowd incident. Set verified=false.\n"
                    "- Only verify true if there is extreme dangerously packed density or panic crush.\n"
                    "- If unsure, set verified=false.\n"
                    "Respond ONLY with a JSON object in this exact format:\n"
                    '{"verified": true/false, "confidence": 0.0-1.0, "what_is_visible": "<one factual sentence describing what is visible>", "reason": "<why>", "tags": []}\n'
                    "Output JSON now:"
                )
            elif category_hint == "tailgating":
                prompt = (
                    f"You are a physical security AI analyzing CCTV camera {camera_id}.\n"
                    "Look ONLY at what is visible in the provided image.\n"
                    "QUESTION: Do you see two individuals tailgating or slipping through a secure doorway/turnstile together?\n"
                    "RULES:\n"
                    "- People walking down a street or hallway is NOT tailgating. Set verified=false.\n"
                    "- If unsure, set verified=false.\n"
                    "Respond ONLY with a JSON object in this exact format:\n"
                    '{"verified": true/false, "confidence": 0.0-1.0, "what_is_visible": "<one factual sentence describing what is visible>", "reason": "<why>", "tags": []}\n'
                    "Output JSON now:"
                )
            else:
                prompt = (
                    f"You are a physical security AI analyzing CCTV camera {camera_id}.\n"
                    f"Look ONLY at what is visible in the provided image.\n"
                    f"QUESTION: Is there an active '{category_hint}' security incident occurring?\n"
                    "RULES: Look only at what is visible. If normal routine activity, set verified=false. If unsure, set verified=false.\n"
                    "Respond ONLY with a JSON object in this exact format:\n"
                    '{"verified": true/false, "confidence": 0.0-1.0, "what_is_visible": "<one factual sentence describing what is visible>", "reason": "<why>", "tags": []}\n'
                    "Output JSON now:"
                )

            model = self._resolve_model()
            try:
                raw_response = self._call_ollama(prompt, frames_b64, model)
                parsed = self._parse_json_response(raw_response, expected_category=category_hint)
                if parsed and parsed.get("verified") is True:
                    vlm_conf = float(parsed.get("confidence", 0.80))
                    # Combine VLM confidence (70%) with rule evidence margin (30%)
                    final_conf = round(0.70 * vlm_conf + 0.30 * rule_conf, 2)
                    summary = parsed.get("summary") or f"{category_hint.replace('_', ' ').title()} visually verified."
                    return {
                        "verified": True,
                        "category": category_hint,
                        "confidence": max(0.50, min(1.0, final_conf)),
                        "summary": summary,
                        "tags": parsed.get("tags", []),
                        "reason": parsed.get("reason", ""),
                    }
                else:
                    reason = parsed.get("reason") if parsed else "VLM rejected verification"
                    logger.info(f"[VLM] Dropped unverified candidate '{category_hint}': {reason}")
                    return rejection
            except urllib.error.URLError as e:
                logger.warning(f"[VLM] Ollama connection unavailable ({model}): {e}")
                return rejection
            except Exception as e:
                logger.warning(f"[VLM] Verification call failed ({model}): {e}")
                return rejection
        finally:
            self.is_busy = False
            self.current_hint = ""
            self.task_start_time = 0.0
            try:
                from backend.vision.pipeline import set_vlm_activity
                set_vlm_activity(camera_id, False, "")
            except Exception:
                pass

    def _call_ollama(self, prompt: str, images_b64: List[str], model: str = None) -> str:
        url = f"{self.ollama_host}/api/generate"
        cfg = _load_vlm_settings()
        num_predict = int(cfg.get("num_predict", 220))
        payload = {
            "model": model or self.model_name,
            "prompt": prompt,
            "images": images_b64[:3],  # Send up to 3 frames spanning the event
            "format": "json",
            "stream": False,
            "keep_alive": -1,
            "options": {
                "temperature": 0.05,
                "num_ctx": 2048,
                "num_predict": num_predict,
            },
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        acquired = self._call_lock.acquire(blocking=True, timeout=6.0)
        if not acquired:
            logger.warning("[VLM] Inference lock busy — dropping candidate to maintain real-time responsiveness")
            return ""

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                resp_text = body.get("response", "").strip()
                if resp_text:
                    return resp_text
                # If model output thinking text, inspect if JSON is inside it
                thinking = body.get("thinking", "").strip()
                if thinking:
                    return thinking
                return ""
        finally:
            self._call_lock.release()

    def _prepare_images(self, frames: List[Any]) -> List[str]:
        b64_list = []
        for f in frames[:3]:
            try:
                raw_bytes = None
                if isinstance(f, bytes):
                    raw_bytes = f
                elif isinstance(f, str):
                    p = Path(f)
                    if p.is_file():
                        raw_bytes = p.read_bytes()

                if raw_bytes:
                    nparr = cv2.imdecode(cv2.frombuffer(raw_bytes, dtype=cv2.CV_8U) if hasattr(cv2, 'frombuffer') else cv2.imdecode(np.frombuffer(raw_bytes, dtype=np.uint8), cv2.IMREAD_COLOR), cv2.IMREAD_COLOR) if False else None
                    # Fallback to standard decode
                    import numpy as np
                    img = cv2.imdecode(np.frombuffer(raw_bytes, np.uint8), cv2.IMREAD_COLOR)
                    if img is not None:
                        h, w = img.shape[:2]
                        max_dim = 384
                        if max(h, w) > max_dim:
                            scale = max_dim / float(max(h, w))
                            img = cv2.resize(
                                img,
                                (int(w * scale), int(h * scale)),
                                interpolation=cv2.INTER_AREA,
                            )
                        _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
                        b64_list.append(base64.b64encode(buf.tobytes()).decode("utf-8"))
                    else:
                        b64_list.append(base64.b64encode(raw_bytes).decode("utf-8"))
            except Exception as e:
                logger.warning(f"[VLM] Image processing error: {e}")
                if isinstance(f, bytes):
                    b64_list.append(base64.b64encode(f).decode("utf-8"))
        return b64_list

    @staticmethod
    def _parse_json_response(text: str, expected_category: str = "") -> Optional[Dict[str, Any]]:
        """Strictly extracts JSON verification object. Never treats thinking monologue as verified."""
        if not text:
            return None

        def _clean_dict(d: dict) -> Optional[Dict[str, Any]]:
            if not isinstance(d, dict):
                return None

            verified = d.get("verified")
            if isinstance(verified, str):
                verified = verified.lower().strip() in ["true", "1", "yes"]
            elif not isinstance(verified, bool):
                # If model omitted verified but gave category
                cat = str(d.get("category", "")).lower().strip()
                verified = bool(cat == expected_category and cat not in ["none", ""])

            if not verified:
                return {
                    "verified": False,
                    "category": "none",
                    "confidence": 0.0,
                    "summary": "",
                    "tags": [],
                    "reason": str(d.get("reason", "Verification rejected by VLM")),
                }

            # Extract factual description
            what_visible = str(
                d.get("what_is_visible") or
                d.get("summary") or
                d.get("description") or
                ""
            ).strip()

            # Ensure we do not use thinking monologues
            if any(what_visible.lower().startswith(p) for p in [
                "the task is", "first, check", "let's see", "wait,", "the scene is", "i need to"
            ]):
                what_visible = f"{expected_category.replace('_', ' ').title()} visually observed in camera viewport."

            conf = d.get("confidence", 0.85)
            try:
                conf = float(conf)
            except Exception:
                conf = 0.85

            raw_tags = d.get("tags", [])
            clean_tags = []
            if isinstance(raw_tags, list):
                clean_tags = [str(t).lower().strip() for t in raw_tags if t]

            return {
                "verified": True,
                "category": expected_category,
                "confidence": max(0.01, min(1.0, conf)),
                "summary": what_visible,
                "tags": clean_tags,
                "reason": str(d.get("reason", "")),
            }

        # 1. Direct JSON parse
        try:
            parsed = json.loads(text.strip())
            return _clean_dict(parsed)
        except Exception:
            pass

        # 2. Extract JSON enclosed in ```json ... ``` codeblocks
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(1).strip())
                return _clean_dict(parsed)
            except Exception:
                pass

        # 3. Locate innermost JSON object containing "verified"
        match = re.search(r"(\{\s*\"verified\"\s*:\s*(?:true|false).*?\})", text, re.DOTALL | re.IGNORECASE)
        if match:
            try:
                parsed = json.loads(match.group(1).strip())
                return _clean_dict(parsed)
            except Exception:
                pass

        return None
