"""EventLens Vision-Language Model (VLM) Integration.

Adheres strictly to AGENTS.md Section 11 contract:
- Calls local Ollama vision model on candidate event frames.
- Expects strictly JSON: {"category": one of 5 or "none", "confidence": 0..1, "summary": "1-2 sentences"}.
- Defensively parses JSON, regex extracts from code blocks, handles timeouts.
- Falls back to rule-based category hint with lowered confidence on failure.
"""

import base64
import json
import re
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional

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
    "suspicious_activity": "Suspicious activity alert: person loitering in restricted surveillance zone.",
    "fighting": "Physical altercation detected: overlapping tracks with rapid kinetic movement.",
}


class VLMClient:
    def __init__(
        self,
        ollama_host: str = "http://localhost:11434",
        model_name: str = "qwen2.5-vl:7b",
        timeout_seconds: int = 12,
    ):
        self.ollama_host = ollama_host.rstrip("/")
        self.model_name = model_name
        self.timeout = timeout_seconds

    def describe_event(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        """Takes a candidate event dictionary:

        {
            "camera_id": "cam1",
            "category_hint": "tailgating",
            "timestamp": "2026-10-15T12:00:00",
            "track_ids": [1, 2],
            "frames": ["base64_jpeg_or_path", ...],
            "keyframe": "path_or_bytes"
        }
        Returns:
            {"category": str, "confidence": float, "summary": str}
        """
        category_hint = candidate.get("category_hint", "suspicious_activity")
        frames_b64 = self._prepare_images(candidate.get("frames", []))

        prompt = (
            f"You are a surveillance security AI analyzing video frames from camera {candidate.get('camera_id', 'cam1')}. "
            f"A potential '{category_hint}' event was flagged. "
            "Examine the scene and classify what is happening into EXACTLY one of these categories:\n"
            "- 'person_down': Someone fell, collapsed, or is lying on the ground\n"
            "- 'fighting': Physical altercation, struggle, or violent contact between people\n"
            "- 'tailgating': Someone following closely behind another person to pass through an access door/turnstile without authorization\n"
            "- 'crowd_incident': Excessive number of people gathering or blocking an area\n"
            "- 'suspicious_activity': Unauthorized presence or prolonged loitering in restricted area\n"
            "- 'none': Normal routine activity or false alarm\n\n"
            "Respond ONLY with a valid JSON object matching this schema:\n"
            '{"category": "category_name", "confidence": 0.85, "summary": "1-2 factual sentences describing what happened."}'
        )

        try:
            raw_response = self._call_ollama(prompt, frames_b64)
            parsed = self._parse_json_response(raw_response)
            if parsed and parsed.get("category") in VALID_CATEGORIES:
                cat = parsed["category"]
                conf = float(parsed.get("confidence", 0.75))
                summary = str(parsed.get("summary", "")).strip() or TEMPLATE_SUMMARIES.get(cat, "")
                return {
                    "category": cat,
                    "confidence": max(0.0, min(1.0, conf)),
                    "summary": summary,
                }
        except Exception as e:
            # Fallback on timeout, connection error, or bad format
            pass

        # Defensive Fallback: use rule category hint with lowered confidence
        return {
            "category": category_hint,
            "confidence": 0.55,
            "summary": f"[Rule Fallback] {TEMPLATE_SUMMARIES.get(category_hint, 'Automated rule triggered event.')}",
        }

    def _call_ollama(self, prompt: str, images_b64: List[str]) -> str:
        url = f"{self.ollama_host}/api/generate"
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "images": images_b64[:3],  # Send at most 3 keyframes to conserve VRAM/latency
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_predict": 128,
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
            return body.get("response", "")

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
        # 1. Try direct parse
        try:
            return json.loads(text.strip())
        except Exception:
            pass

        # 2. Extract JSON enclosed in ```json ... ``` codeblocks
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except Exception:
                pass

        # 3. Find first { and last }
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except Exception:
                pass

        return None
