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
    "none",
}

TEMPLATE_SUMMARIES = {
    "tailgating": "Potential tailgating detected: multiple individuals entered consecutively without secondary credential swipe.",
    "person_down": "Person down alert: individual detected remaining prone on ground for extended duration.",
    "crowd_incident": "Crowd gathering alert: person count exceeded regional density safety threshold.",
    "suspicious_activity": "Suspicious activity alert: unauthorized presence, loitering, or weapon brandishing in surveillance zone.",
    "fighting": "Physical altercation / violent struggle detected: overlapping tracks with rapid kinetic movement.",
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
        self.timeout = timeout_seconds or cfg.get("timeout_seconds", 45)
        self._available_model: Optional[str] = None  # Cached working model name
        logger.info(f"[VLM] Configured: primary={self.model_name}, fallback={self.fallback_model}, timeout={self.timeout}s")

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
        frames_b64 = self._prepare_images(candidate.get("frames", []))

        if not frames_b64:
            logger.warning("[VLM] No frames available for VLM analysis — using rule fallback")
            return self._make_fallback(category_hint)

        prompt = (
            f"You are a surveillance security AI analyzing CCTV frames from camera {candidate.get('camera_id', 'cam1')}.\n"
            f"The rule engine flagged a potential '{category_hint}' event based on motion patterns.\n\n"
            "Look at the image(s) carefully. Describe EXACTLY what you see happening:\n"
            "- How many people are visible?\n"
            "- What are they doing? (walking, running, lying down, struggling, standing still)\n"
            "- Is there any physical contact, violence, or someone on the ground?\n"
            "- Are there any weapons (guns, knives, objects being swung)?\n"
            "- Is the scene normal activity or genuinely concerning?\n\n"
            "Classify into EXACTLY one category:\n"
            "- 'person_down': Someone lying on the ground, collapsed, fallen, or incapacitated\n"
            "- 'fighting': Active physical struggle, punching, kicking, shoving between 2+ people\n"
            "- 'suspicious_activity': Someone brandishing a weapon, loitering in restricted area, or acting threateningly\n"
            "- 'tailgating': Two people passing through a door/gate together where only one should\n"
            "- 'crowd_incident': Dangerously large crowd packing, stampede, or crush risk\n"
            "- 'none': Normal, routine activity — people walking, talking, sitting normally\n\n"
            "CRITICAL: Be honest. If this looks like NORMAL activity (people just walking, sitting, or standing near each other), classify as 'none'.\n"
            "If a weapon is visible, mention '[WEAPON DETECTED]' in summary.\n\n"
            "Respond ONLY with valid JSON:\n"
            '{"category": "category_name", "confidence": 0.85, "summary": "2-3 factual sentences describing what you see in the scene."}'
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
                }
            else:
                logger.warning(f"[VLM] Model returned unparseable response: {raw_response[:200]}")
        except urllib.error.URLError as e:
            logger.error(f"[VLM] Ollama connection failed ({model}): {e}")
        except Exception as e:
            logger.error(f"[VLM] VLM call failed ({model}): {e}")

        # Defensive Fallback: use rule category hint with lowered confidence
        return self._make_fallback(category_hint)

    def _make_fallback(self, category_hint: str) -> Dict[str, Any]:
        """Creates a fallback result when VLM is unavailable."""
        return {
            "category": category_hint,
            "confidence": 0.40,
            "summary": f"[VLM Offline] {TEMPLATE_SUMMARIES.get(category_hint, 'Automated rule triggered event.')} — Ollama vision model not available for visual confirmation.",
        }

    def _call_ollama(self, prompt: str, images_b64: List[str], model: str = None) -> str:
        url = f"{self.ollama_host}/api/generate"
        payload = {
            "model": model or self.model_name,
            "prompt": prompt,
            "images": images_b64[:2],  # Send at most 2 keyframes to conserve VRAM/latency
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_predict": 800,  # Ensure complete reasoning and summary generation
            },
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            resp_text = body.get("response", "").strip()
            # If reasoning model stopped before response field, fall back to thinking text
            if not resp_text and body.get("thinking"):
                return body.get("thinking", "").strip()
            return resp_text

    def _prepare_images(self, frames: List[Any]) -> List[str]:
        b64_list = []
        for f in frames:
            if isinstance(f, bytes):
                b64_list.append(base64.b64encode(f).decode("utf-8"))
            elif isinstance(f, str):
                p = Path(f)
                if p.is_file():
                    b64_list.append(base64.b64encode(p.read_bytes()).decode("utf-8"))
                else:
                    b64_list.append(f)
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

            # Tag weapon if positively detected in context (not negated)
            has_weapon = (
                any(w in text_corpus for w in ["gun", "gunfight", "firearm", "pistol", "rifle", "knife", "blade", "armed"])
                and not any(neg in text_corpus for neg in ["no weapon", "no visible weapon", "no firearms", "without weapon", "no gun", "not visible"])
            )
            if has_weapon and "[WEAPON DETECTED]" not in summary:
                summary = f"[WEAPON DETECTED] {summary}"

            return {
                "category": cat,
                "confidence": max(0.0, min(1.0, conf)),
                "summary": summary,
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
            if category in VALID_CATEGORIES:
                return {
                    "category": category,
                    "confidence": max(0.0, min(1.0, confidence)),
                    "summary": summary,
                }

        return None
