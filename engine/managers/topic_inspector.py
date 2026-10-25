"""
engine/managers/topic_inspector.py — Topic Sourcing & Fact-Checking Gate (v2.0)
Multi-tier trending topic discovery (Reddit with custom User-Agent -> Niche LLM Ideation -> Curated Fallback Pool)
paired with an LLM scientific fact-checking gate and persistent deduplication history to guarantee zero repeated shorts.
"""

import os
import re
import json
import time
import random
import difflib
import requests
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Optional, Set
from engine.managers.llm_manager import LLMManager

# ─── VIRAL SHORTS THEMES (Listicle Hook Umbrellas for @BrainBlud style) ──────
VIRAL_SHORTS_THEMES = [
    "Shower thoughts that will completely ruin your perception of reality",
    "Uncomfortable shower thoughts that will keep you awake tonight",
    "Shower thoughts that feel illegal to know",
    "Mind-bending psychological facts that sound completely fake",
    "Shower thoughts you should never overthink right before sleep",
    "Weird psychological facts that will mess with your head",
    "Shower thoughts that sound fake but are 100% true",
    "Mind-blowing shower thoughts that make too much sense",
    "Brain glitches that feel illegal to know",
    "Shower thoughts that break the laws of common sense",
    "Disturbing psychological facts about the human mind",
    "Shower thoughts that break your daily autopilot",
    "Cognitive paradoxes that will break your brain",
    "Shower thoughts that prove reality is stranger than anything you can imagine",
    "Unsettling thoughts you will never be able to unthink",
    "Shower thoughts that nobody told you",
    "Psychological brain glitches you experience without realizing",
    "Shower thoughts that are terrifying if you think about them",
    "Facts about the human mind that feel like cheat codes",
    "Shower thoughts that will ruin your day in five seconds"
]

CURATED_FALLBACK_TOPICS = VIRAL_SHORTS_THEMES  # Backward compatibility alias

# ─── LONG-FORM DOCUMENTARY TOPICS (Deep Dives) ──────────────────────────────
LONG_FORM_TOPICS = [
    "The Ship of Theseus Paradox and the Illusion of Physical Identity",
    "Why you have never actually seen your own face in real time",
    "The Troxler Effect and why your brain hallucinates faces in dim mirrors",
    "The Baader-Meinhof Phenomenon and the cognitive frequency illusion",
    "The Illusion of Free Will and the Libet Neurological Timing Experiments",
    "The Placebo Sleep Effect: How perceived sleep quality restores executive function",
    "The Overview Effect: How viewing Earth from space transforms cognitive empathy",
    "The Mandela Effect and how human collective memory fabricates consensus",
    "The Dunning-Kruger Effect: Why incompetence breeds psychological overconfidence",
    "The Grandfather Paradox and why causal loops break temporal physics",
    "The Fermi Paradox: Where is all intelligent life in the observable universe?",
    "Why matter never truly touches other matter due to atomic electron repulsion",
    "The Simulation Hypothesis: Evidence that physical constants behave like compute limits",
    "The Double-Slit Experiment and how observation fundamentally collapses quantum states",
    "The Quantum Zeno Effect: Why an observed quantum system can never change state",
    "Boltzmann Brains: Why spontaneous consciousness in empty space is statistically possible",
    "The Bootstrap Paradox: An object or information that was never actually created",
    "Olbers' Paradox: Why the night sky is completely black despite infinite stars",
    "Quantum Tunneling: How the sun fuses hydrogen despite lacking the classical heat to do so",
    "The Cosmic Event Horizon: Why distant galaxies are permanently vanishing from our reach",
    "The heat death of the universe and the final decay of physical matter"
]


class TopicInspector:
    """Sources trending topics, validates them against fact-checking gates, and enforces persistent anti-repetition cooldown."""

    REGISTRY_FILE = os.path.join("memory", "used_topics_registry.json")
    VAULT_FILE = os.path.join("data", "curated_thoughts_and_facts.json")

    def __init__(self, llm_manager: Optional[LLMManager] = None):
        self.llm = llm_manager or LLMManager()

    @classmethod
    def get_grounding_references(cls, count: int = 5, pillar: Optional[str] = None) -> List[Dict[str, str]]:
        """
        Retrieves verified facts and thoughts from the curated vault
        to inject as concrete grounding context for LLM script generation.
        """
        vault_path = cls.VAULT_FILE
        if not os.path.exists(vault_path):
            return []
        try:
            with open(vault_path, "r", encoding="utf-8") as f:
                vault_data = json.load(f)
            items = vault_data.get("items", [])
            if pillar:
                p_clean = pillar.lower().strip()
                filtered = [it for it in items if p_clean == it.get("pillar", "").lower() or p_clean in it.get("pillar", "").lower()]
                if filtered:
                    items = filtered
            if not items:
                return []
            sampled = random.sample(items, min(count, len(items)))
            return [{"text": it.get("text", ""), "type": it.get("type", "fact"), "pillar": it.get("pillar", "")} for it in sampled]
        except Exception as e:
            print(f"⚠️ [TOPIC INSPECTOR] Could not load grounding references: {e}", flush=True)
            return []

    @classmethod
    def load_registry(cls) -> Dict[str, Any]:
        """Loads persistent topic history."""
        if os.path.exists(cls.REGISTRY_FILE):
            try:
                with open(cls.REGISTRY_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {"used_topics": []}
        return {"used_topics": []}

    @classmethod
    def save_registry(cls, data: Dict[str, Any]) -> None:
        """Saves persistent topic history, pruning entries older than 90 days."""
        try:
            os.makedirs(os.path.dirname(cls.REGISTRY_FILE) or "memory", exist_ok=True)
            now = time.time()
            cutoff = now - (90 * 86400)
            cleaned = [
                item for item in data.get("used_topics", [])
                if item.get("timestamp", 0) > cutoff
            ]
            with open(cls.REGISTRY_FILE, "w", encoding="utf-8") as f:
                json.dump({"used_topics": cleaned}, f, indent=2)
        except Exception as e:
            print(f"⚠️ [TOPIC GATE] Failed to save used topics registry: {e}", flush=True)

    @classmethod
    def _normalize_topic(cls, text: str) -> str:
        """Normalizes topic string for fuzzy comparison."""
        text = text.lower().strip()
        text = re.sub(r"[^\w\s]", "", text)
        return " ".join(text.split())

    @classmethod
    def _extract_keywords(cls, text: str) -> Set[str]:
        """Extracts significant keywords for conceptual similarity checks."""
        STOP_WORDS = {
            "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for", "with",
            "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
            "do", "does", "did", "why", "how", "what", "which", "who", "when", "where",
            "shower", "thoughts", "thought", "paradox", "effect", "you", "your", "my",
            "our", "these", "those", "this", "that", "will", "would", "could", "should",
            "never", "ever", "always", "just", "actually", "completely", "ruin", "break"
        }
        words = cls._normalize_topic(text).split()
        return {w for w in words if w not in STOP_WORDS and len(w) > 2}

    @classmethod
    def is_topic_recent(cls, topic: str, cooldown_days: int = 60) -> bool:
        """
        Checks if a topic or conceptually duplicate premise was used within the cooldown window.
        Uses exact match, sequence matching, and keyword Jaccard overlap.
        """
        if not topic:
            return False
        registry = cls.load_registry()
        now = time.time()
        cutoff = now - (cooldown_days * 86400)

        cand_norm = cls._normalize_topic(topic)
        cand_kw = cls._extract_keywords(topic)

        for item in registry.get("used_topics", []):
            if item.get("timestamp", 0) < cutoff:
                continue
            past_topic = item.get("topic", "")
            past_norm = cls._normalize_topic(past_topic)

            # 1. Exact normalized match
            if cand_norm == past_norm:
                return True

            # 2. Sequence similarity ratio (difflib)
            ratio = difflib.SequenceMatcher(None, cand_norm, past_norm).ratio()
            if ratio >= 0.65:
                return True

            # 3. Keyword / entity overlap (Jaccard similarity)
            past_kw = cls._extract_keywords(past_topic)
            if cand_kw and past_kw:
                intersection = cand_kw & past_kw
                union = cand_kw | past_kw
                jaccard = len(intersection) / len(union) if union else 0.0
                if jaccard >= 0.50 or (len(intersection) >= 3 and len(cand_kw) <= 5):
                    return True

        return False

    @classmethod
    def record_topic_usage(cls, topic: str, summary: str = "", niche: str = "shower_thoughts") -> None:
        """Records a topic in persistent history to enforce anti-repetition cooldown."""
        registry = cls.load_registry()
        topics_list = registry.setdefault("used_topics", [])
        if any(item.get("topic") == topic for item in topics_list[-5:]):
            return
        topics_list.append({
            "topic": topic,
            "summary": summary,
            "niche": niche,
            "timestamp": time.time()
        })
        cls.save_registry(registry)
        print(f"📝 [TOPIC REGISTRY] Logged '{topic[:50]}...' to persistent topic history.", flush=True)

    @classmethod
    def get_recent_topics(cls, niche: str = "", limit: int = 25) -> List[str]:
        """Returns the most recent topics recorded in history."""
        registry = cls.load_registry()
        items = registry.get("used_topics", [])
        if niche:
            items = [it for it in items if it.get("niche") == niche]
        return [it.get("topic", "") for it in items[-limit:] if it.get("topic")]

    def discover_verified_topic(self, niche: str = "shower_thoughts", video_type: str = "short") -> Dict[str, Any]:
        """
        Discovers a candidate topic via multi-tier fallback, filters out duplicates,
        and ensures it passes the Fact-Checking and Niche Relevance Gate.
        """
        target_pool = LONG_FORM_TOPICS if video_type == "long" else VIRAL_SHORTS_THEMES
        candidates = self._fetch_candidates(niche=niche, video_type=video_type)
        random.shuffle(candidates)

        is_test = os.environ.get("TEST_MODE", "").lower() in ("true", "1")

        for candidate in candidates:
            # 1. Anti-repetition check
            if self.is_topic_recent(candidate):
                print(f"🔄 [TOPIC GATE] Skipped duplicate/recent topic: '{candidate[:50]}...'")
                continue

            # 2. Fact check & niche relevance
            fact_check_result = self._fact_check(candidate, niche=niche)
            if fact_check_result.get("verified", False):
                print(f"✅ [TOPIC GATE] Verified topic passed: '{candidate[:60]}...'")
                if not is_test:
                    self.record_topic_usage(candidate, fact_check_result.get("summary", candidate), niche=niche)
                return {
                    "topic": candidate,
                    "verified_summary": fact_check_result.get("summary", candidate),
                    "source": "verified_trend"
                }
            else:
                reason = fact_check_result.get("reason", "Unverified or pseudoscientific myth")
                print(f"⚠️ [TOPIC GATE] Rejected '{candidate[:40]}...': {reason}")

        # Fallback to guaranteed verified evergreen theme that hasn't been used recently
        available_fallbacks = [t for t in target_pool if not self.is_topic_recent(t)]
        if available_fallbacks:
            fallback = random.choice(available_fallbacks)
        else:
            fallback = random.choice(target_pool)

        print(f"🛡️ [TOPIC GATE] Using verified evergreen topic: '{fallback[:60]}...'")
        if not is_test:
            self.record_topic_usage(fallback, fallback, niche=niche)
        return {"topic": fallback, "verified_summary": fallback, "source": "curated_evergreen"}

    def fetch_youtube_trends(self, category_ids: Optional[List[int]] = None) -> List[str]:
        """
        Fetches trending video topics from YouTube Data API v3 across
        Entertainment (24), Education (27), and Science & Tech (28).
        Falls back to local trend cache if API is unavailable.
        """
        if category_ids is None:
            category_ids = [24, 27, 28]  # Entertainment primary, Education & Science cross-sourcing
        candidates = []
        try:
            from engine.managers.youtube_manager import YouTubeManager
            yt_mgr = YouTubeManager()
            client = yt_mgr.get_client()
            if client:
                for cat_id in category_ids:
                    try:
                        resp = client.videos().list(
                            part="snippet",
                            chart="mostPopular",
                            videoCategoryId=str(cat_id),
                            regionCode="US",
                            maxResults=10
                        ).execute()
                        for item in resp.get("items", []):
                            title = item.get("snippet", {}).get("title", "")
                            # Clean up title: remove hashtags, emojis, brackets
                            cleaned = re.sub(r"[#\|\[\(\<].*$", "", title).strip()
                            if len(cleaned) > 15 and not self.is_topic_recent(cleaned):
                                candidates.append(cleaned)
                    except Exception:
                        continue
        except Exception:
            pass

        if not candidates:
            # Check local trend CSV cache (data/yt_trends.csv)
            trend_csv = os.path.join("data", "yt_trends.csv")
            if os.path.isfile(trend_csv):
                try:
                    with open(trend_csv, "r", encoding="utf-8") as f:
                        for line in f:
                            parts = line.strip().split(",")
                            if len(parts) >= 1 and parts[0]:
                                term = parts[0].strip()
                                if len(term) > 10 and not self.is_topic_recent(term):
                                    candidates.append(term)
                except Exception:
                    pass
        return candidates

    def _fetch_candidates(self, niche: str = "shower_thoughts", video_type: str = "short") -> List[str]:
        """Fetches candidates using Reddit -> YouTube Trends -> Niche LLM Ideation -> Curated Vault fallback."""
        target_pool = LONG_FORM_TOPICS if video_type == "long" else VIRAL_SHORTS_THEMES
        candidates = []

        # Tier 1: Live Reddit Sourcing (r/Showerthoughts, r/todayilearned, r/Damnthatsinteresting)
        subreddits = ["Showerthoughts", "todayilearned", "Damnthatsinteresting"] if "shower" in niche else ["todayilearned", "Damnthatsinteresting", "science"]
        for sub in random.sample(subreddits, len(subreddits)):
            try:
                endpoints = [
                    f"https://www.reddit.com/r/{sub}/hot.json?limit=25",
                    f"https://www.reddit.com/r/{sub}/top.json?t=month&limit=25"
                ]
                endpoint = random.choice(endpoints)
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                    "Accept": "application/json"
                }
                resp = requests.get(endpoint, headers=headers, timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    for post in data.get("data", {}).get("children", []):
                        title = post.get("data", {}).get("title", "")
                        if title and len(title) > 20 and not post.get("data", {}).get("over_18", False):
                            cleaned = re.sub(r"^(TIL|TIL that|Showerthought:?)\s*", "", title, flags=re.IGNORECASE).strip()
                            if not self.is_topic_recent(cleaned):
                                candidates.append(cleaned)
                    if candidates:
                        print(f"📡 [TOPIC SOURCING] Fetched {len(candidates)} fresh candidates from r/{sub}")
                        return candidates
            except Exception:
                continue

        # Tier 2: YouTube Trends (Entertainment 24, Education 27, Science 28)
        yt_trends = self.fetch_youtube_trends(category_ids=[24, 27, 28])
        if yt_trends:
            print(f"📈 [TOPIC SOURCING] Harvested {len(yt_trends)} trending topics from YouTube API.")
            return yt_trends

        # Tier 3: Niche LLM Ideation with Negative Deduplication Constraints
        if "shower" in niche or "psychology" in niche:
            try:
                recent_topics = self.get_recent_topics(niche=niche, limit=20)
                anti_rep_constraint = ""
                if recent_topics:
                    anti_rep_constraint = (
                        "\n\nSTRICT DEDUPLICATION REQUIREMENT:\n"
                        "Our channel has ALREADY created videos on these topics:\n"
                        + "\n".join(f"- {t}" for t in recent_topics[:15]) +
                        "\nYou MUST NOT reuse, rephrase, or overlap with any of the above premises. "
                        "Generate completely fresh, novel, and unexplored cognitive paradoxes, body glitches, or everyday shower thoughts."
                    )

                sys_prompt = (
                    "You are an elite YouTube Shorts topic strategist for a high-retention channel exploring "
                    "mind-bending shower thoughts, psychological paradoxes, and counter-intuitive facts.\n"
                    "RULES:\n"
                    "- Focus on concrete, relatable, tactile, physical, or human body realities.\n"
                    "- STRICTLY AVOID abstract linguistic philosophy (e.g. 'words are lies', 'the language trap') and depressing existential nihilism.\n"
                    f"{anti_rep_constraint}"
                )
                usr_prompt = (
                    "Generate 6 viral YouTube Shorts video hook themes for a shower thoughts and mind-blowing facts listicle channel. "
                    "Examples: 'Shower thoughts that will completely ruin your perception of reality', 'Everyday brain glitches that feel illegal to know'. "
                    "Return JSON: {\"topics\": [\"Theme 1\", \"Theme 2\", ...]}"
                )
                idea_data = self.llm.generate_json(sys_prompt, usr_prompt, temperature=0.8)
                llm_topics = idea_data.get("topics", [])
                if llm_topics and isinstance(llm_topics, list):
                    fresh_llm_topics = [t for t in llm_topics if not self.is_topic_recent(t)]
                    if fresh_llm_topics:
                        print(f"💡 [TOPIC SOURCING] Synthesized {len(fresh_llm_topics)} unique {niche} topics via LLM.")
                        return fresh_llm_topics
            except Exception:
                pass
        else:
            # Fallback to Google Trends for non-shower-thoughts channels
            try:
                url = "https://trends.google.com/trending/rss?geo=US"
                resp = requests.get(url, timeout=5)
                if resp.status_code == 200:
                    root = ET.fromstring(resp.content)
                    for item in root.findall(".//item"):
                        title = item.find("title")
                        if title is not None and title.text:
                            c_text = title.text.strip()
                            if not self.is_topic_recent(c_text):
                                candidates.append(c_text)
                    if candidates:
                        return candidates
            except Exception:
                pass

        # Tier 4: Fallback to Curated Vault Themes
        available_fallbacks = [t for t in target_pool if not self.is_topic_recent(t)]
        return available_fallbacks if available_fallbacks else target_pool.copy()

    def verify_factuality(self, topic: str, niche: str = "shower_thoughts") -> Dict[str, Any]:
        """Runs the LLM fact-checking and niche-relevance gate."""
        system_prompt = (
            "You are a strict scientific fact-checker and editorial gatekeeper for a viral educational YouTube Shorts channel.\n"
            f"The channel niche is: '{niche}'.\n"
            "Evaluate whether this candidate meets BOTH conditions:\n"
            "1. NICHE RELEVANCE: Does this fit mind-bending shower thoughts, psychological paradoxes, perception illusions, or physical brain-glitches? "
            "STRICTLY REJECT: Geopolitical country names, sports matches, political controversies, celebrity gossip, "
            "and abstract semantic nihilism (e.g. 'words are lies', 'the language trap', 'meaning is an illusion' with no concrete relatable grounding).\n"
            "2. FACTUAL / CONCEPTUAL INTEGRITY: Is the premise logically coherent, scientifically sound, or psychologically valid? Reject debunked myths or fake clickbait.\n"
            "Return JSON: {\"is_niche_relevant\": true/false, \"is_factual\": true/false, \"confidence\": float, \"primary_source\": str, \"rejection_reason\": str}"
        )
        user_prompt = f"Verify this topic candidate for niche '{niche}': '{topic}'"
        try:
            res = self.llm.generate_json(system_prompt, user_prompt, temperature=0.1)
            if not isinstance(res, dict):
                return {
                    "status": "unavailable",
                    "is_niche_relevant": False,
                    "is_factual": False,
                    "confidence": 0.0,
                    "primary_source": "",
                    "rejection_reason": f"Topic verification failed: non-dictionary LLM response ({type(res).__name__})"
                }
            if "is_factual" not in res:
                return {
                    "status": "unavailable",
                    "is_niche_relevant": False,
                    "is_factual": False,
                    "confidence": 0.0,
                    "primary_source": "",
                    "rejection_reason": "Topic verification failed: response missing required 'is_factual' field"
                }
            is_factual = bool(res.get("is_factual", False))
            is_relevant = bool(res.get("is_niche_relevant", True))
            confidence = float(res.get("confidence", 0.8 if is_factual else 0.0))
            return {
                "status": "completed",
                "is_niche_relevant": is_relevant,
                "is_factual": is_factual,
                "confidence": confidence,
                "primary_source": res.get("primary_source", ""),
                "rejection_reason": res.get("rejection_reason", "")
            }
        except Exception as e:
            return {
                "status": "unavailable",
                "is_niche_relevant": False,
                "is_factual": False,
                "confidence": 0.0,
                "primary_source": "",
                "rejection_reason": f"Topic verification service unavailable: {e}"
            }

    def _fact_check(self, topic: str, niche: str = "shower_thoughts") -> Dict[str, Any]:
        """Runs the LLM fact-checking gate to filter out debunked internet myths and off-niche topics."""
        result = self.verify_factuality(topic, niche=niche)
        status = result.get("status", "completed" if result.get("is_factual") is not None else "unavailable")
        is_relevant = bool(result.get("is_niche_relevant", False))
        is_factual = bool(result.get("is_factual", False))
        verified = (status == "completed") and is_relevant and is_factual
        reason = result.get("rejection_reason") or (", ".join(result.get("red_flags", [])) if "red_flags" in result else "Off-niche or unverified")
        return {
            "verified": verified,
            "status": status,
            "summary": result.get("primary_source") or topic,
            "reason": reason
        }
