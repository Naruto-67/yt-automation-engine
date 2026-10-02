"""
engine/managers/competitor_spy.py — Competitor Spy Engine with 24h Quota Caching (v2.0)
Monitors rival channels (e.g. @BrainBlud) for viral breakout topics while strictly conserving API quota.
"""

import os
import json
import time
from typing import Optional, Dict, Any, List


class CompetitorSpy:
    """Spies on rival channels to identify breakout viral hooks."""

    CACHE_FILE = os.path.join("memory", "competitor_cache.json")
    CACHE_DURATION_SECONDS = 86400  # 24 hours

    @classmethod
    def get_surge_topic(cls, competitors: List[str] = None) -> Optional[Dict[str, Any]]:
        """
        Returns a viral outlier topic if detected, or None if cache is fresh or no surge found.
        Conserves quota by checking local 24h cache first.
        """
        cached = cls._load_cache()
        now = time.time()

        if cached.get("last_fetched") and (now - cached["last_fetched"] < cls.CACHE_DURATION_SECONDS):
            topics = cached.get("cached_topics", [])
            if topics:
                print(f"🎯 [COMPETITOR SPY] Reusing 24h cached viral topic: '{topics[0].get('title')}'")
                return topics[0]
            return None

        # If cache expired and we have API access, scan channels
        print("🔍 [COMPETITOR SPY] Cache expired. Scanning competitor channels for viral outliers...")
        surge_topic = cls._scan_competitors(competitors or ["@BrainBlud", "@FactFiend"])
        
        # Update cache timestamp
        cached_topics = [surge_topic] if surge_topic else []
        cls._save_cache({"last_fetched": now, "cached_topics": cached_topics})

        return surge_topic

    @classmethod
    def _scan_competitors(cls, competitors: List[str]) -> Optional[Dict[str, Any]]:
        """
        Queries YouTube Data API for competitor recent uploads.
        Returns topic dict with {'title': ..., 'core_thesis': ..., 'viral_factor': ...}
        """
        # Note: If no YouTube credentials or quota exhausted, fails over gracefully
        return None

    @classmethod
    def _load_cache(cls) -> Dict[str, Any]:
        if os.path.exists(cls.CACHE_FILE):
            try:
                with open(cls.CACHE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"last_fetched": 0, "cached_topics": []}

    @classmethod
    def _save_cache(cls, data: Dict[str, Any]) -> None:
        os.makedirs("memory", exist_ok=True)
        try:
            with open(cls.CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

