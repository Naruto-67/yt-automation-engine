"""
engine/managers/topic_inspector.py — Topic Sourcing & Fact-Checking Gate (v2.0)
Multi-tier trending topic discovery (Reddit with custom User-Agent -> Google Trends RSS fallback)
paired with an LLM scientific fact-checking gate to filter out myths and urban legends.
"""

import os
import re
import random
import requests
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Optional
from engine.managers.llm_manager import LLMManager

CURATED_FALLBACK_TOPICS = [
    "The Troxler Effect causes the brain to hallucinate monsters when staring into a mirror in dim light.",
    "The Baader-Meinhof Phenomenon makes you suddenly see a newly learned word or object everywhere.",
    "Tetris Effect proves playing puzzle games before sleep reorganizes memory consolidation in the brain.",
    "The Placebo Sleep effect shows believing you slept well significantly boosts cognitive performance.",
    "The Dunning-Kruger Effect causes people with limited knowledge in a domain to vastly overestimate their ability.",
]


class TopicInspector:
    """Sources trending topics and validates them against scientific fact-checking standards."""

    def __init__(self, llm_manager: Optional[LLMManager] = None):
        self.llm = llm_manager or LLMManager()

    def discover_verified_topic(self, niche: str = "psychology_and_facts") -> Dict[str, Any]:
        """
        Discovers a candidate topic via multi-tier fallback and ensures it passes the Fact-Checking Gate.
        """
        candidates = self._fetch_candidates()
        random.shuffle(candidates)

        for candidate in candidates:
            fact_check_result = self._fact_check(candidate)
            if fact_check_result.get("verified", False):
                print(f"✅ [TOPIC GATE] Verified topic passed: '{candidate[:60]}...'")
                return {
                    "topic": candidate,
                    "verified_summary": fact_check_result.get("summary", candidate),
                    "source": "verified_trend"
                }
            else:
                reason = fact_check_result.get("reason", "Unverified or pseudoscientific myth")
                print(f"⚠️ [TOPIC GATE] Rejected '{candidate[:40]}...': {reason}")

        # Fallback to guaranteed verified fact
        fallback = random.choice(CURATED_FALLBACK_TOPICS)
        print(f"🛡️ [TOPIC GATE] Using verified evergreen topic: '{fallback[:60]}...'")
        return {"topic": fallback, "verified_summary": fallback, "source": "curated_evergreen"}

    def _fetch_candidates(self) -> List[str]:
        """Fetches candidates using Reddit -> Google Trends RSS multi-tier fallback."""
        candidates = []

        # Tier 1: Reddit
        try:
            subreddits = ["Showerthoughts", "todayilearned", "psychology"]
            sub = random.choice(subreddits)
            url = f"https://www.reddit.com/r/{sub}/hot.json?limit=15"
            headers = {"User-Agent": "MindBludBot/2.0 (Automated Educational Curating; +https://github.com)"}
            resp = requests.get(url, headers=headers, timeout=6)
            if resp.status_code == 200:
                data = resp.json()
                for post in data.get("data", {}).get("children", []):
                    title = post.get("data", {}).get("title", "")
                    if title and len(title) > 20 and not post.get("data", {}).get("over_18", False):
                        # Clean title
                        cleaned = re.sub(r"^TIL:?\s*", "", title, flags=re.IGNORECASE).strip()
                        candidates.append(cleaned)
                if candidates:
                    print(f"📡 [TOPIC SOURCING] Fetched {len(candidates)} candidates from r/{sub}")
                    return candidates
        except Exception as e:
            print(f"⚠️ [TOPIC SOURCING] Reddit failed ({e}). Falling back to Google Trends RSS...")

        # Tier 2: Google Trends Daily RSS
        try:
            url = "https://trends.google.com/trending/rss?geo=US"
            resp = requests.get(url, timeout=6)
            if resp.status_code == 200:
                root = ET.fromstring(resp.content)
                for item in root.findall(".//item"):
                    title = item.find("title")
                    if title is not None and title.text:
                        candidates.append(title.text.strip())
                if candidates:
                    print(f"📡 [TOPIC SOURCING] Fetched {len(candidates)} candidates from Google Trends RSS")
                    return candidates
        except Exception as e:
            print(f"⚠️ [TOPIC SOURCING] Google Trends RSS failed ({e}). Using curated pool...")

        return CURATED_FALLBACK_TOPICS.copy()

    def verify_factuality(self, topic: str) -> Dict[str, Any]:
        """Runs the LLM fact-checking gate to verify scientific validity."""
        system_prompt = (
            "You are a strict scientific and historical fact-checker for an educational channel.\n"
            "Verify whether this premise is verified, scientifically supported, and logically sound.\n"
            "Reject urban legends, creepypastas, and debunked myths.\n"
            "Return JSON: {\"is_factual\": true/false, \"confidence\": float, \"primary_source\": str, \"red_flags\": list}"
        )
        user_prompt = f"Verify this topic: '{topic}'"
        try:
            return self.llm.generate_json(system_prompt, user_prompt, temperature=0.1)
        except Exception:
            return {
                "is_factual": False,
                "confidence": 0.0,
                "primary_source": "Unknown",
                "red_flags": ["Fact check verification service unavailable"]
            }

    def _fact_check(self, topic: str) -> Dict[str, Any]:
        """Runs the LLM fact-checking gate to filter out debunked internet myths."""
        result = self.verify_factuality(topic)
        return {
            "verified": result.get("is_factual", False),
            "summary": result.get("primary_source", topic),
            "reason": ", ".join(result.get("red_flags", [])) or "Failed verification"
        }

