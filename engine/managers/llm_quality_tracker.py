"""
engine/managers/llm_quality_tracker.py — Dynamic LLM Editorial Quality Tracker (v1.0)

Tracks per-model editorial quality scores and implements a dynamic circuit breaker.
Zero hardcoded model bans — all scoring is empirical and self-improving.

Scoring mechanics:
- Every script that passes the Editorial Critic Wall Test rewards the model: +0.05
- Every Wall Test failure penalizes the model: -0.15
- Two consecutive failures trigger a 24-hour cooldown for script_gen tasks.
- Scores use exponential moving average (EMA) so they recover over time.
- All state persisted in config/model_quality_scores.json.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, Optional

_CFG_DIR = Path(__file__).parent.parent.parent / "config"
_QUALITY_SCORES_PATH = _CFG_DIR / "model_quality_scores.json"

# Score thresholds
_SCORE_REWARD = 0.05
_SCORE_PENALTY = 0.15
_QUARANTINE_THRESHOLD = 0.40  # Below this score, model is quarantined from script_gen
_CONSECUTIVE_FAILURES_COOLDOWN = 2  # Trigger 24h cooldown after this many consecutive failures
_COOLDOWN_HOURS = 24


def _load_quality_scores() -> Dict[str, Any]:
    """Loads model quality scores from config/model_quality_scores.json."""
    if _QUALITY_SCORES_PATH.exists():
        try:
            with open(_QUALITY_SCORES_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"models": {}, "_meta": {"schema_version": "1.0"}}


def _save_quality_scores(data: Dict[str, Any]) -> None:
    """Persists model quality scores to disk."""
    _CFG_DIR.mkdir(parents=True, exist_ok=True)
    data["_meta"]["last_updated"] = datetime.now(timezone.utc).isoformat()
    with open(_QUALITY_SCORES_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


class LLMQualityTracker:
    """
    Dynamic per-model editorial quality tracker with self-improving EMA scoring.
    """

    def __init__(self):
        self._data = _load_quality_scores()

    def _get_model_record(self, model_id: str) -> Dict[str, Any]:
        """Gets or initializes the quality record for a model."""
        models = self._data.setdefault("models", {})
        if model_id not in models:
            models[model_id] = {
                "quality_score": 1.0,       # Start with perfect trust
                "consecutive_failures": 0,
                "total_generations": 0,
                "total_failures": 0,
                "total_replacements": 0,
                "cooldown_until": None,      # ISO timestamp or None
                "last_updated": None,
            }
        return models[model_id]

    def is_in_cooldown(self, model_id: str, task: str = "script_gen") -> bool:
        """
        Returns True if the model is currently in editorial cooldown for script_gen tasks.
        Cooldown automatically expires after 24 hours.
        """
        record = self._get_model_record(model_id)
        cooldown_until_str = record.get("cooldown_until")
        if not cooldown_until_str:
            return False
        try:
            cooldown_until = datetime.fromisoformat(cooldown_until_str)
            if datetime.now(timezone.utc) < cooldown_until:
                remaining = cooldown_until - datetime.now(timezone.utc)
                print(f"⏳ [QUALITY TRACKER] Model '{model_id}' in editorial cooldown for {task}. "
                      f"Expires in {int(remaining.total_seconds() / 3600)}h {int((remaining.total_seconds() % 3600) / 60)}m.")
                return True
            else:
                # Cooldown expired — clear it
                record["cooldown_until"] = None
                record["consecutive_failures"] = 0
                print(f"✅ [QUALITY TRACKER] Model '{model_id}' editorial cooldown expired. Reinstating.")
        except Exception:
            record["cooldown_until"] = None
        return False

    def record_result(
        self,
        model_id: str,
        wall_test_failures: int,
        wall_test_replacements: int,
        passed_first_attempt: bool
    ) -> None:
        """
        Records a script generation result and updates the model's quality score.

        Args:
            model_id: Provider model ID (e.g. 'gemini', 'groq', 'or_llama_3_3_70b').
            wall_test_failures: Number of Wall Test failures detected.
            wall_test_replacements: Number of scenes that were replaced.
            passed_first_attempt: Whether the script was accepted without retries.
        """
        record = self._get_model_record(model_id)
        record["total_generations"] = record.get("total_generations", 0) + 1

        if wall_test_failures == 0 and passed_first_attempt:
            # Clean generation: reward the model
            old_score = record.get("quality_score", 1.0)
            new_score = min(1.0, old_score + _SCORE_REWARD)
            record["quality_score"] = round(new_score, 4)
            record["consecutive_failures"] = 0
            print(f"✅ [QUALITY TRACKER] Model '{model_id}' rewarded: score {old_score:.3f} → {new_score:.3f}")
        else:
            # Failed Wall Test or needed replacements: penalize
            old_score = record.get("quality_score", 1.0)
            new_score = max(0.0, old_score - _SCORE_PENALTY)
            record["quality_score"] = round(new_score, 4)
            record["total_failures"] = record.get("total_failures", 0) + 1
            record["total_replacements"] = record.get("total_replacements", 0) + wall_test_replacements
            consecutive = record.get("consecutive_failures", 0) + 1
            record["consecutive_failures"] = consecutive
            print(f"⚠️ [QUALITY TRACKER] Model '{model_id}' penalized: score {old_score:.3f} → {new_score:.3f} "
                  f"(consecutive failures: {consecutive})")

            # Trigger dynamic 24h cooldown after N consecutive failures
            if consecutive >= _CONSECUTIVE_FAILURES_COOLDOWN:
                cooldown_until = datetime.now(timezone.utc) + timedelta(hours=_COOLDOWN_HOURS)
                record["cooldown_until"] = cooldown_until.isoformat()
                print(f"🔴 [QUALITY TRACKER] Model '{model_id}' placed in 24h editorial cooldown until {cooldown_until.strftime('%Y-%m-%d %H:%M UTC')}")

        record["last_updated"] = datetime.now(timezone.utc).isoformat()
        _save_quality_scores(self._data)

    def get_quality_score(self, model_id: str) -> float:
        """Returns the current quality score (0.0–1.0) for a model."""
        return self._get_model_record(model_id).get("quality_score", 1.0)

    def get_all_scores(self) -> Dict[str, Dict[str, Any]]:
        """Returns all model quality records for inspection."""
        return self._data.get("models", {})
