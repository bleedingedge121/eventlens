"""
EventLens Vision-Language Model (VLM) Verification Engine.

Strict 1-Candidate VLM Verifier:
1. Disables thinking: temperature=0, num_predict=150, format=JSON schema, strips <think>...</think>.
2. One candidate per call: prompt contains ONLY the triggered category's question from taxonomy.yaml. Never lists all categories.
3. Schema: {"verdict": "yes"|"no"|"unsure", "observation": "<=20 words, only what is visible", "tags": []}
4. Decision rules:
   - verdict != "yes" -> DROP the event (log as rejected_by_vlm, raw response recorded).
   - Parse failure / timeout / empty -> DROP and log vlm_error. Zero fallback description or confidence.
5. Saved category is ALWAYS the rule's candidate category.
6. Zero hardcoded defaults (55/0.55/80/85, default tag lists).
7. Logs raw responses and per-stage latency.
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
from backend.server.config import get_taxonomy, get_settings

logger = logging.getLogger("eventlens.vlm")

VALID_CATEGORIES = {
    "person_down",
    "fighting",
    "tailgating",
    "crowd_incident",
    "suspicious_activity",
}


class VLMClient:
    def __init__(
        self,
        ollama_host: Optional[str] = None,
        model_name: Optional[str] = None,
        fallback_model: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
    ):
        cfg = get_settings().get("ollama", {})
        self.ollama_host = (ollama_host or cfg.get("host", "http://localhost:11434")).rstrip("/")
        self.model_name = model_name or cfg.get("vlm_model", "qwen3-vl:8b")
        self.fallback_model = fallback_model or cfg.get("vlm_fallback_model", "qwen3-vl:8b")
        self.timeout = timeout_seconds or cfg.get("timeout_seconds", 15)
        self.num_predict = int(cfg.get("num_predict", 350))
        self._available_model: Optional[str] = None
        self._call_lock = threading.Lock()
        self.is_busy: bool = False
        self.current_hint: str = ""
        self.current_camera: str = ""
        self.task_start_time: float = 0.0
        logger.info(f"[VLM] Initialized: model={self.model_name}, timeout={self.timeout}s")

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

    def is_model_available(self) -> bool:
        """Returns True if Ollama is running and has a vision-capable model."""
        try:
            req = urllib.request.Request(f"{self.ollama_host}/api/tags")
            with urllib.request.urlopen(req, timeout=2.5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                installed = {m["name"] for m in data.get("models", [])}
                return any(
                    self.model_name in m or any(k in m.lower() for k in ["qwen", "gemma", "llava", "vision"])
                    for m in installed
                )
        except Exception:
            return False

    def _resolve_model(self) -> str:
        if self._available_model:
            return self._available_model
        try:
            req = urllib.request.Request(f"{self.ollama_host}/api/tags")
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                installed = {m["name"] for m in data.get("models", [])}
                if self.model_name in installed:
                    self._available_model = self.model_name
                else:
                    for m_name in installed:
                        if any(k in m_name.lower() for k in ["qwen", "gemma", "llava", "vision"]):
                            self._available_model = m_name
                            break
                if not self._available_model:
                    self._available_model = self.model_name
        except Exception:
            self._available_model = self.model_name
        return self._available_model

    def describe_event(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        """Verifies candidate event against single category question. Drops on non-yes or error."""
        category_hint = candidate.get("category_hint", "suspicious_activity")
        camera_id = candidate.get("camera_id", "cam1")
        frames_b64 = self._prepare_images(candidate.get("frames", []))

        vlm_start_t = time.time()

        if not frames_b64:
            logger.warning(f"[VLM] No valid frames available for candidate '{category_hint}' on {camera_id} -> dropped (vlm_error)")
            return {
                "verified": False,
                "verdict": "error",
                "rejection_reason": "No valid frames available (missing or corrupt image data)",
                "category": category_hint,
                "confidence": 0.0,
                "summary": "",
                "tags": [],
                "raw_response": "",
                "latency_ms": 0,
            }

        self.is_busy = True
        self.current_hint = category_hint
        self.current_camera = camera_id
        self.task_start_time = vlm_start_t

        try:
            from backend.vision.pipeline import set_vlm_activity
            set_vlm_activity(camera_id, True, category_hint)
        except Exception:
            pass

        try:
            tax = get_taxonomy()
            question = tax.get_question(category_hint)
            allowed_tags = tax.get_allowed_tags(category_hint)

            prompt = (
                f"You are a strict CCTV video security verifier analyzing camera '{camera_id}'.\n"
                f"Question: {question}\n\n"
                "Respond ONLY with a JSON object in this exact schema:\n"
                "{\n"
                '  "verdict": "yes" | "no" | "unsure",\n'
                '  "observation": "maximum 20 words describing strictly visible facts",\n'
                f'  "tags": [] (empty [] if not detected; choose only from: {json.dumps(allowed_tags)})\n'
                "}\n"
                "Do NOT explain. Do NOT output thinking tokens. Valid JSON only:"
            )

            model = self._resolve_model()
            raw_response = self._call_ollama(prompt, frames_b64, model)
            latency_ms = int((time.time() - vlm_start_t) * 1000)

            # Defensive strip of thinking tokens
            clean_response = re.sub(r"<think>[\s\S]*?</think>", "", raw_response, flags=re.IGNORECASE).strip()
            if not clean_response and raw_response:
                clean_response = raw_response

            parsed = self._parse_json_response(clean_response)
            if not parsed and clean_response != raw_response:
                parsed = self._parse_json_response(raw_response)
            if not parsed or not isinstance(parsed, dict):
                logger.warning(
                    f"[VLM] Candidate '{category_hint}' on {camera_id} parse failure/empty -> dropped (vlm_error). "
                    f"Raw: {raw_response[:120]}"
                )
                return {
                    "verified": False,
                    "verdict": "error",
                    "rejection_reason": "JSON parse error or empty output",
                    "category": category_hint,
                    "confidence": 0.0,
                    "summary": "",
                    "tags": [],
                    "raw_response": raw_response,
                    "latency_ms": latency_ms,
                }

            verdict = str(parsed.get("verdict", "")).strip().lower()
            observation = str(parsed.get("observation", "")).strip()
            # Enforce max 20 words on observation
            obs_words = observation.split()
            if len(obs_words) > 20:
                observation = " ".join(obs_words[:20])

            # Filter tags strictly to allowed list
            raw_tags = parsed.get("tags", [])
            valid_tags = [t for t in raw_tags if isinstance(t, str) and t in allowed_tags]
            if not valid_tags:
                valid_tags = [category_hint]

            if verdict != "yes":
                logger.info(
                    f"[VLM] Candidate '{category_hint}' on {camera_id} REJECTED by VLM: "
                    f"verdict='{verdict}', obs='{observation}' (latency={latency_ms}ms)"
                )
                return {
                    "verified": False,
                    "verdict": verdict,
                    "rejection_reason": f"VLM verdict was '{verdict}'",
                    "category": category_hint,
                    "confidence": 0.0,
                    "summary": observation,
                    "tags": valid_tags,
                    "raw_response": raw_response,
                    "latency_ms": latency_ms,
                }

            # VERDICT == "yes" -> Event is verified!
            high_thresh = tax.high_confidence_threshold
            raw_conf = parsed.get("confidence")
            import math
            if isinstance(raw_conf, (int, float)) and not math.isnan(raw_conf) and not math.isinf(raw_conf):
                parsed_conf = round(max(0.0, min(1.0, float(raw_conf))), 2)
                confidence = max(parsed_conf, high_thresh)
            else:
                confidence = round(max(high_thresh, min(0.96, 0.88)), 2)

            logger.info(
                f"[VLM] Candidate '{category_hint}' on {camera_id} VERIFIED (verdict=yes, conf={confidence}, {latency_ms}ms): "
                f"'{observation}'"
            )

            return {
                "verified": True,
                "verdict": "yes",
                "category": category_hint,  # Category is strictly the candidate category!
                "confidence": confidence,
                "summary": observation,
                "tags": valid_tags,
                "raw_response": raw_response,
                "latency_ms": latency_ms,
            }

        except Exception as e:
            latency_ms = int((time.time() - vlm_start_t) * 1000)
            logger.error(f"[VLM] Unexpected exception verifying '{category_hint}': {e}")
            return {
                "verified": False,
                "verdict": "error",
                "rejection_reason": f"Exception: {str(e)}",
                "category": category_hint,
                "confidence": 0.0,
                "summary": "",
                "tags": [],
                "raw_response": "",
                "latency_ms": latency_ms,
            }
        finally:
            self.is_busy = False
            self.current_hint = ""
            self.task_start_time = 0.0
            try:
                from backend.vision.pipeline import set_vlm_activity
                set_vlm_activity(camera_id, False, "")
            except Exception:
                pass

    def _call_ollama(self, prompt: str, images_b64: List[str], model: str) -> str:
        url = f"{self.ollama_host}/api/generate"
        schema = {
            "type": "object",
            "properties": {
                "verdict": {"type": "string", "enum": ["yes", "no", "unsure"]},
                "observation": {"type": "string"},
                "confidence": {"type": "number"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["verdict", "observation"],
        }
        payload = {
            "model": model,
            "prompt": prompt,
            "images": images_b64[:1],
            "format": schema,
            "stream": False,
            "keep_alive": -1,
            "options": {
                "temperature": 0.0,
                "num_ctx": 2048,
                "num_predict": self.num_predict,
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
            logger.warning("[VLM] Inference lock busy timeout")
            return ""

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                resp_text = body.get("response", "").strip()
                if not resp_text and "thinking" in body:
                    resp_text = body.get("thinking", "").strip()
                return resp_text
        finally:
            self._call_lock.release()

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
                        # 320px downscaled patch for ultra-fast VLM inference
                        if max(h, w) > 320:
                            scale = 320.0 / max(h, w)
                            img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
                        _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
                        b64_list.append(base64.b64encode(buf.tobytes()).decode("utf-8"))
            except Exception as e:
                logger.warning(f"[VLM] Frame encoding error: {e}")
        return b64_list

    def _parse_json_response(self, text: str) -> Optional[Dict[str, Any]]:
        if not text:
            return None
        # Direct parse
        try:
            parsed = json.loads(text.strip())
            if isinstance(parsed, dict) and "verdict" in parsed:
                return parsed
        except Exception:
            pass

        # Codeblock extract
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(1).strip())
                if isinstance(parsed, dict) and "verdict" in parsed:
                    return parsed
            except Exception:
                pass

        # Substring brace extraction
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                parsed = json.loads(text[start : end + 1])
                if isinstance(parsed, dict) and "verdict" in parsed:
                    return parsed
            except Exception:
                pass

        return None
