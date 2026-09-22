# engine/prompt_evolver.py — Ghost Engine V1.0
"""
Prompt Evolver Engine.

Tracks prompt variant effectiveness across hook scores, circular loop scores,
critic ratings, and CTR archetypes. Stores score pairs in memory/prompt_evolution.json.
Evaluates winning patterns and automatically optimizes prompt guidelines
in config/prompts.yaml during weekly audits.

Persistence:
    memory/prompt_evolution.json
"""

import os
import re
import json
import yaml
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from engine.logger import logger


_EVOLUTION_FILE = os.path.join(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
    "memory",
    "prompt_evolution.json"
)

_PROMPTS_YAML = os.path.join(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
    "config",
    "prompts.yaml"
)


class PromptEvolver:
    """
    Learns from production metrics to iteratively optimize system prompts.
    """

    def __init__(self, file_path: str = _EVOLUTION_FILE):
        self.file_path = file_path
        self._ensure_storage()

    def _ensure_storage(self):
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
        if not os.path.exists(self.file_path):
            try:
                with open(self.file_path, "w", encoding="utf-8") as f:
                    json.dump({
                        "evolution_history": [],
                        "metrics": {},
                        "pending_promotions": []
                    }, f, indent=2)
            except Exception as e:
                logger.error(f"[PROMPT_EVOLVER] Storage init error: {e}")

    def _load_data(self) -> Dict[str, Any]:
        if not os.path.exists(self.file_path):
            return {"evolution_history": [], "metrics": {}, "pending_promotions": []}
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {"evolution_history": [], "metrics": {}, "pending_promotions": []}
        except Exception as e:
            logger.debug(f"[PROMPT_EVOLVER] Load error: {e}")
            return {"evolution_history": [], "metrics": {}, "pending_promotions": []}

    def _save_data(self, data: Dict[str, Any]):
        temp_file = f"{self.file_path}.tmp"
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(temp_file, self.file_path)
        except Exception as e:
            logger.error(f"[PROMPT_EVOLVER] Save error: {e}")
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception:
                    pass

    def log_feedback(
        self,
        channel_id: str,
        metric: str,
        variant: str,
        score: float
    ):
        """
        Records a quality observation for a given prompt variant or archetype.
        Example: metric='hook_archetype', variant='Forbidden Secret', score=8.5
        """
        if not variant or score <= 0:
            return

        data = self._load_data()
        metrics = data.setdefault("metrics", {})
        metric_group = metrics.setdefault(metric, {})

        current = metric_group.setdefault(variant, {
            "samples": 0,
            "total_score": 0.0,
            "avg_score": 0.0,
            "last_updated": ""
        })

        current["samples"] += 1
        current["total_score"] += float(score)
        current["avg_score"] = round(current["total_score"] / current["samples"], 2)
        current["last_updated"] = datetime.now(timezone.utc).isoformat()

        self._save_data(data)
        logger.debug(f"[PROMPT_EVOLVER] Logged {metric}='{variant}': score {score:.1f} (avg: {current['avg_score']:.1f})")

    def evaluate_promotions(self, min_samples: int = 5, score_threshold: float = 8.0) -> List[Dict[str, Any]]:
        """
        Identifies high-performing prompt variants worthy of promotion into prompts.yaml.
        """
        data = self._load_data()
        promotions = []

        metrics = data.get("metrics", {})
        for metric_name, variants in metrics.items():
            for variant_name, stats in variants.items():
                if stats.get("samples", 0) >= min_samples and stats.get("avg_score", 0.0) >= score_threshold:
                    promotions.append({
                        "metric": metric_name,
                        "variant": variant_name,
                        "samples": stats["samples"],
                        "avg_score": stats["avg_score"]
                    })

        promotions.sort(key=lambda x: x["avg_score"], reverse=True)
        return promotions

    def run_weekly_evolution(self) -> Dict[str, Any]:
        """
        Runs during weekly audit (11_weekly_audit.yml).
        Analyzes winning archetypes and injects successful style directives
        into prompts.yaml to continuously compound performance.
        """
        promotions = self.evaluate_promotions(min_samples=3, score_threshold=7.8)
        if not promotions:
            logger.engine("[PROMPT_EVOLVER] No variants meet promotion criteria yet.")
            return {"promoted": 0, "details": "Insufficient high-scoring samples."}

        top_promotions = promotions[:3]
        promoted_count = 0

        # Read prompts.yaml
        if os.path.exists(_PROMPTS_YAML):
            try:
                with open(_PROMPTS_YAML, "r", encoding="utf-8") as f:
                    content = f.read()

                # Build an evolved directive note
                top_archetypes = [p["variant"] for p in top_promotions if p["metric"] in ("hook_archetype", "ctr_archetype")]
                if top_archetypes:
                    archetype_note = f"\n# [PROMPT EVOLUTION NOTICE]: High-converting archetypes: {', '.join(top_archetypes)}"
                    if archetype_note not in content:
                        with open(_PROMPTS_YAML, "a", encoding="utf-8") as f:
                            f.write(archetype_note + "\n")
                        promoted_count += 1
                        logger.engine(f"🚀 [PROMPT_EVOLVER] Promoted winning archetypes into prompts.yaml: {', '.join(top_archetypes)}")

                data = self._load_data()
                data.setdefault("evolution_history", []).append({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "promoted_variants": top_promotions,
                    "count": promoted_count
                })
                self._save_data(data)
            except Exception as e:
                logger.error(f"[PROMPT_EVOLVER] Failed to evolve prompts.yaml: {e}")

        return {
            "promoted": promoted_count,
            "top_variants": top_promotions
        }

    def get_evolution_report(self) -> str:
        """Generates markdown summary of learned prompt intelligence."""
        data = self._load_data()
        metrics = data.get("metrics", {})
        if not metrics:
            return "No prompt evolution metrics recorded yet."

        lines = ["### 🧬 Prompt Evolution Intelligence Report\n"]
        for metric, variants in metrics.items():
            lines.append(f"**Metric: {metric}**")
            sorted_v = sorted(variants.items(), key=lambda x: x[1].get("avg_score", 0), reverse=True)
            for v_name, stats in sorted_v:
                lines.append(f"- `{v_name}`: Avg {stats['avg_score']}/10 ({stats['samples']} samples)")
            lines.append("")

        return "\n".join(lines)


# Global singleton
prompt_evolver = PromptEvolver()
