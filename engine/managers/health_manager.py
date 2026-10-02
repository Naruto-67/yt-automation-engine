"""
engine/managers/health_manager.py — Health, Quota & Self-Learning Feedback Loop (v2.0)
Monitors API quotas, validates environment tokens, and autonomously adapts dynamic weights based on analytics.
"""

import os
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Tuple

logger = logging.getLogger("HealthManager")

REQUIRED_ENV_VARS = [
    "YOUTUBE_CLIENT_ID",
    "YOUTUBE_CLIENT_SECRET",
    "YOUTUBE_REFRESH_TOKEN",
    "DISCORD_WEBHOOK",
    "PEXELS_API_KEY",
    "PIXABAY_API_KEY",
]

LLM_ENV_VARS = ["GROQ_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY"]


class HealthManager:
    """Pre-flight diagnostics, quota auditing, and adaptive self-learning loop."""

    @staticmethod
    def run_preflight_checks() -> Tuple[bool, list[str]]:
        """
        Validates all essential environment variables before running any pipeline stage.
        Returns (success: bool, issues: list[str]).
        """
        issues = []
        for var in REQUIRED_ENV_VARS:
            if not os.environ.get(var):
                issues.append(f"Missing required environment variable: {var}")

        # At least one LLM key must be present
        if not any(os.environ.get(var) for var in LLM_ENV_VARS):
            issues.append(f"At least one LLM key must be set: {', '.join(LLM_ENV_VARS)}")

        return (len(issues) == 0, issues)

    @staticmethod
    def load_dynamic_weights() -> Dict[str, Any]:
        """Loads adaptive weights and pacing state from memory/dynamic_weights.json."""
        path = os.path.join("memory", "dynamic_weights.json")
        default_state = {
            "sub_formats": {"core_brainblud": 0.80, "listicle": 0.20},
            "pacing": {
                "target_duration_seconds": 52,
                "cut_interval_seconds": 3.5,
                "silence_lead_time_seconds": 1.0,
            },
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
        if not os.path.exists(path):
            return default_state

        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default_state

    @classmethod
    def update_self_learning_loop(cls, analytics_data: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Dynamic self-learning feedback loop:
        Evaluates performance data and updates format weights and pacing.
        """
        weights = cls.load_dynamic_weights()
        if not analytics_data:
            return weights

        sub_formats = weights.get("sub_formats", {"core_brainblud": 0.80, "listicle": 0.20})
        pacing = weights.get("pacing", {"cut_interval_seconds": 3.5})

        # Example optimization: If listicle APV > core BrainBlud APV by 10%, increase listicle weight
        listicle_apv = analytics_data.get("listicle_avg_percentage_viewed", 0.0)
        core_apv = analytics_data.get("core_avg_percentage_viewed", 0.0)

        if listicle_apv > (core_apv * 1.10) and core_apv > 0:
            sub_formats["listicle"] = min(0.40, sub_formats.get("listicle", 0.20) + 0.05)
            sub_formats["core_brainblud"] = 1.0 - sub_formats["listicle"]
            print(f"🧠 [SELF-LEARNING] Upweighted Listicle format to {sub_formats['listicle']:.2f}")

        # If retention drops sharply before second 15, tighten cut interval
        retention_drop_sec = analytics_data.get("retention_drop_timestamp", 0)
        if 0 < retention_drop_sec <= 15:
            pacing["cut_interval_seconds"] = max(2.5, pacing.get("cut_interval_seconds", 3.5) - 0.2)
            print(f"🧠 [SELF-LEARNING] Tightened cut interval to {pacing['cut_interval_seconds']:.1f}s")

        weights["sub_formats"] = sub_formats
        weights["pacing"] = pacing
        weights["last_updated"] = datetime.now(timezone.utc).isoformat()

        # Save state
        os.makedirs("memory", exist_ok=True)
        path = os.path.join("memory", "dynamic_weights.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(weights, f, indent=2)

        return weights

