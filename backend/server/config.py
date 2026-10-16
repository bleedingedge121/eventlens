"""
EventLens Configuration & Taxonomy Loader
Centralized, validated configuration for rules, VLM questions, allowed tags, and camera scene profiles.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml
import json

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"


class TaxonomyConfig:
    def __init__(self, raw: Dict[str, Any]):
        self.raw = raw
        self.categories_list = raw.get("categories", [])
        self.categories = {c["id"]: c for c in self.categories_list}
        self.scene_profiles = raw.get("scene_profiles", {
            "indoor_premises": {
                "description": "Indoor facility lobby, corridor, turnstile entrance",
                "person_down_enabled": True,
                "crowd_baseline_factor": 1.8,
                "min_crowd_count": 5,
                "loiter_seconds": 5.0,
            },
            "outdoor_street": {
                "description": "Outdoor public street, pedestrian walkway, open square",
                "person_down_enabled": False,
                "crowd_baseline_factor": 2.5,
                "min_crowd_count": 10,
                "loiter_seconds": 15.0,
            },
            "custom": {
                "description": "User customized monitoring profile",
                "person_down_enabled": True,
                "crowd_baseline_factor": 2.0,
                "min_crowd_count": 6,
                "loiter_seconds": 8.0,
            }
        })
        self.high_confidence_threshold = float(
            raw.get("confidence", {}).get("high_threshold", 0.75)
        )

    def get_category(self, cat_id: str) -> Optional[Dict[str, Any]]:
        return self.categories.get(cat_id)

    def get_question(self, cat_id: str) -> str:
        cat = self.get_category(cat_id)
        if cat and cat.get("vlm_question"):
            return cat["vlm_question"]
        fallback_questions = {
            "person_down": "Is a person lying flat on the floor or ground and motionless?",
            "fighting": "Are two or more people engaged in an active physical fight, punching, wrestling, or violent struggle?",
            "tailgating": "Did an unauthorized follower closely tailgate through a door or turnstile directly behind another person without swiping?",
            "crowd_incident": "Is there an abnormally dense, agitated, or surging crowd causing a corridor bottleneck or safety hazard?",
            "suspicious_activity": "Is an unauthorized person loitering, trespassing, or trying to access restricted doors?",
        }
        return fallback_questions.get(cat_id, "Is this specific security incident occurring in the frame?")

    def get_allowed_tags(self, cat_id: str) -> List[str]:
        cat = self.get_category(cat_id)
        if cat and cat.get("allowed_tags"):
            return list(cat["allowed_tags"])
        return [cat_id]

    def get_scene_profile(self, profile_name: str) -> Dict[str, Any]:
        return self.scene_profiles.get(profile_name, self.scene_profiles.get("indoor_premises", {}))


_TAXONOMY_INSTANCE: Optional[TaxonomyConfig] = None


def get_taxonomy() -> TaxonomyConfig:
    global _TAXONOMY_INSTANCE
    if _TAXONOMY_INSTANCE is None:
        tax_path = CONFIG_DIR / "taxonomy.yaml"
        if tax_path.exists():
            try:
                with open(tax_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                _TAXONOMY_INSTANCE = TaxonomyConfig(data)
            except Exception:
                _TAXONOMY_INSTANCE = TaxonomyConfig({})
        else:
            _TAXONOMY_INSTANCE = TaxonomyConfig({})
    return _TAXONOMY_INSTANCE


def get_settings() -> Dict[str, Any]:
    settings_path = CONFIG_DIR / "settings.json"
    if settings_path.exists():
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}
