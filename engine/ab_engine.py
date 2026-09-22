# engine/ab_engine.py — Ghost Engine V1.0
"""
A/B Testing Engine for Titles and Thumbnails.

Generates 2 distinct curiosity-archetype title variants and thumbnail concepts
per video. Tracks performance metrics over a 48h evaluation window and feeds
winning patterns back into episodic memory and the prompt evolver.

Persistence:
    memory/ab_tests.json
"""

import os
import re
import json
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Tuple
from engine.logger import logger
from scripts.quota_manager import quota_manager


_AB_FILE = os.path.join(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
    "memory",
    "ab_tests.json"
)


class ABTestEngine:
    """
    Manages A/B variant generation, logging, and evaluation for video packaging.
    """

    def __init__(self, file_path: str = _AB_FILE):
        self.file_path = file_path
        self._ensure_storage()

    def _ensure_storage(self):
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
        if not os.path.exists(self.file_path):
            try:
                with open(self.file_path, "w", encoding="utf-8") as f:
                    json.dump({"tests": {}}, f, indent=2)
            except Exception as e:
                logger.error(f"[AB_ENGINE] Storage init error: {e}")

    def _load_data(self) -> Dict[str, Any]:
        if not os.path.exists(self.file_path):
            return {"tests": {}}
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) and "tests" in data else {"tests": {}}
        except Exception as e:
            logger.debug(f"[AB_ENGINE] Load error: {e}")
            return {"tests": {}}

    def _save_data(self, data: Dict[str, Any]):
        temp_file = f"{self.file_path}.tmp"
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(temp_file, self.file_path)
        except Exception as e:
            logger.error(f"[AB_ENGINE] Save error: {e}")
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception:
                    pass

    def generate_variants(
        self,
        primary_title: str,
        niche: str,
        script_text: str = "",
        base_thumbnail_prompt: str = ""
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Produces Variant A (primary) and Variant B (contrasting curiosity angle).
        Both variants are scored via score_packaging_ctr().
        """
        from scripts.generate_metadata import score_packaging_ctr

        ctr_a = score_packaging_ctr(primary_title, niche)
        thumb_a = base_thumbnail_prompt or f"Ultra high-contrast dramatic cinematic scene illustrating: {primary_title}"

        variant_a = {
            "title": primary_title,
            "thumbnail_prompt": thumb_a,
            "ctr_score": ctr_a["score"],
            "archetype": ctr_a["archetype"] or "Direct Hook"
        }

        # Generate Variant B: Contrasting Curiosity Archetype
        variant_b_title = ""
        try:
            prompt = (
                f"You are a YouTube Shorts CTR packaging master.\n"
                f"Video Niche: '{niche}'\n"
                f"Variant A Title: '{primary_title}' (Archetype: '{variant_a['archetype']}')\n\n"
                f"Create a DISTINCT Variant B title using a COMPLETELY DIFFERENT curiosity archetype "
                f"(e.g. Impossible Juxtaposition, Forbidden Secret, Extreme Scale, Survival Instinct, Identity Challenge).\n"
                f"Rules:\n"
                f"1. Under 55 characters before #shorts\n"
                f"2. Ends with #shorts\n"
                f"3. High viral tension, concrete nouns or numbers, 1 emoji\n"
                f"4. Return ONLY the title string, nothing else."
            )
            raw, _ = quota_manager.generate_text(
                prompt,
                task_type="seo",
                system_prompt="Return ONLY a single punchy YouTube Shorts title under 60 chars ending in #shorts."
            )
            if raw and len(raw.strip()) > 10:
                variant_b_title = raw.strip().replace('"', '').replace("'", "")
                if "#shorts" not in variant_b_title.lower():
                    variant_b_title += " #shorts"
        except Exception as e:
            logger.debug(f"[AB_ENGINE] LLM Variant B generation skipped: {e}")

        # Fallback Variant B if LLM was unavailable
        if not variant_b_title:
            clean_a = re.sub(r'#shorts?\s*', '', primary_title, flags=re.IGNORECASE).strip()
            variant_b_title = f"The Secret Behind {clean_a[:35]} 🤫 #shorts"

        ctr_b = score_packaging_ctr(variant_b_title, niche)
        thumb_b = f"Extreme visual closeup, intense focal lighting, hyper-detailed emotional angle: {variant_b_title}"

        variant_b = {
            "title": variant_b_title,
            "thumbnail_prompt": thumb_b,
            "ctr_score": ctr_b["score"],
            "archetype": ctr_b["archetype"] or "Curiosity Gap"
        }

        print(
            f"   🧪 [A/B ENGINE] Generated 2 Variants:\n"
            f"      🅰️  (Score {variant_a['ctr_score']}/100 | {variant_a['archetype']}): '{variant_a['title']}'\n"
            f"      🅱️  (Score {variant_b['ctr_score']}/100 | {variant_b['archetype']}): '{variant_b['title']}'"
        )

        return variant_a, variant_b

    def create_test(
        self,
        channel_id: str,
        job_id: int,
        video_id: str,
        variant_a: Dict[str, Any],
        variant_b: Dict[str, Any],
        selected_variant: str = "A"
    ) -> Dict[str, Any]:
        """
        Logs an active A/B test in memory/ab_tests.json.
        """
        test_id = video_id or f"job_{job_id}"
        data = self._load_data()
        now_iso = datetime.now(timezone.utc).isoformat()

        test_record = {
            "test_id": test_id,
            "channel_id": channel_id,
            "job_id": job_id,
            "video_id": video_id,
            "created_at": now_iso,
            "selected_variant": selected_variant,
            "status": "active",
            "winner": None,
            "variant_a": variant_a,
            "variant_b": variant_b,
            "metrics": {
                "views": 0,
                "ctr_pct": 0.0,
                "retention_pct": 0.0
            }
        }

        data["tests"][test_id] = test_record
        self._save_data(data)
        logger.engine(f"[AB_ENGINE] Logged A/B test for {test_id} (Selected: {selected_variant})")
        return test_record

    def record_result(
        self,
        video_id: str,
        winner: str,
        metrics: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Records the winner of an A/B test and feeds back winning archetype.
        """
        data = self._load_data()
        test = data.get("tests", {}).get(video_id)
        if not test:
            return False

        test["winner"] = winner.upper()
        test["status"] = "completed"
        test["completed_at"] = datetime.now(timezone.utc).isoformat()
        if metrics:
            test["metrics"].update(metrics)

        self._save_data(data)
        winning_variant = test["variant_a"] if winner.upper() == "A" else test["variant_b"]
        logger.engine(
            f"🏆 [AB_ENGINE] Test {video_id} resolved! Winner: {winner.upper()} "
            f"('{winning_variant.get('title')}' | Archetype: {winning_variant.get('archetype')})"
        )

        # Feed winning archetype into prompt evolver
        try:
            from engine.prompt_evolver import prompt_evolver
            prompt_evolver.log_feedback(
                channel_id=test.get("channel_id", "CH_01"),
                metric="ctr_archetype",
                variant=winning_variant.get("archetype", "unknown"),
                score=winning_variant.get("ctr_score", 85)
            )
        except Exception:
            pass

        return True

    def get_active_tests(self) -> List[Dict[str, Any]]:
        """Returns all currently active tests awaiting 48h evaluation."""
        data = self._load_data()
        return [t for t in data.get("tests", {}).values() if t.get("status") == "active"]


# Global singleton
ab_engine = ABTestEngine()
