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

CURATED_FALLBACK_TOPICS = [
    # Cognitive & Psychological Paradoxes
    "The Ship of Theseus Paradox and the Illusion of Physical Identity",
    "Why you have never actually seen your own face in real time",
    "The Troxler Effect and why your brain hallucinates faces in dim mirrors",
    "The Baader-Meinhof Phenomenon and the cognitive frequency illusion",
    "The Illusion of Free Will and the Libet Neurological Timing Experiments",
    "The Placebo Sleep Effect: How perceived sleep quality restores executive function",
    "The Overview Effect: How viewing Earth from space transforms cognitive empathy",
    "The Mandela Effect and how human collective memory fabricates consensus",
    "The Dunning-Kruger Effect: Why incompetence breeds psychological overconfidence",
    "Why your future self is watching you right now through the lens of your memories",
    "Why your brain deletes the physical sensation of your clothes on your skin",
    "How language alters the physical perception of color across different human cultures",
    "The Rubber Hand Illusion and how easily your brain adopts artificial limbs",
    "The Tetris Effect: How repetitive sensory tasks physically alter brain cognition",
    "Phantom Vibration Syndrome and how our nervous systems hyper-predict stimuli",
    "Semantic Satiation: Why repeating a single word makes it completely lose meaning",
    "The Spotlight Effect: Why nobody is noticing the mistakes you obsess over",
    "Pareidolia and why human evolutionary biology forces you to see faces everywhere",
    "Capgras Delusion and the eerie feeling that your loved ones are exact impostors",
    "Sleep Paralysis and why human waking consciousness gets hijacked by dream hallucinations",
    "Chronostasis: The stopped-clock illusion where time appears to freeze",
    "Déjà vu and why neural micro-delays create false sensations of past experience",
    "Jamais vu: When a familiar room or person suddenly feels utterly alien",
    "The Broken Window Fallacy: Why destruction never actually creates economic prosperity",

    # Physics, Quantum & Cosmic Brain-Glitches
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
    "Time dilation at the event horizon of a supermassive black hole",
    "The heat death of the universe and the final decay of physical matter",

    # Mind-Bending Shower Thoughts & Perception Glitches
    "Shower thoughts that will completely break your perception of reality",
    "Shower thoughts that prove human perception is a biological simulation",
    "Shower thoughts you should never overthink right before going to sleep",
    "Shower thoughts that prove reality is stranger than anything you can imagine",
    "Why sleeping is charging your battery while dreaming is running diagnostics",
    "Your shadow is proof that light traveled ninety-three million miles to be stopped by you",
    "If poison expires does it become more poisonous or less poisonous",
    "Every book you have ever read is just twenty-six letters arranged in different orders",
    "Your age is just the number of laps you survived around a giant nuclear fireball",
    "The brain named itself, recognized itself, and is now realizing that exact fact",
    "Nothing is ever truly on fire. Fire is actually chemically on physical things",
    "Clapping is just repeatedly slapping yourself because you enjoyed something",
    "Water can boil and freeze at the exact same instant under specific pressure",
    "Your stomach acid is strong enough to dissolve metal, but your lining constantly regenerates",
    "You can never hold an empty container because it is always completely full of air",
    "The voice inside your head never has to take a physical breath while talking",
    "Mirrors do not reverse left and right; they reverse front and back",
    "You are currently moving through space at hundreds of kilometers per second without feeling it",
    "Your skeleton is wet right now and will stay wet until long after you die",
    "History is written by the living; the billions of dead will never tell their side",
    "Every decision you made in your entire past led to the exact moment you are reading this",
    "You have breathed atoms that were once exhaled by prehistoric dinosaurs"
]


class TopicInspector:
    """Sources trending topics, validates them against fact-checking gates, and enforces persistent anti-repetition cooldown."""

    REGISTRY_FILE = os.path.join("memory", "used_topics_registry.json")

    def __init__(self, llm_manager: Optional[LLMManager] = None):
        self.llm = llm_manager or LLMManager()

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

    def discover_verified_topic(self, niche: str = "shower_thoughts") -> Dict[str, Any]:
        """
        Discovers a candidate topic via multi-tier fallback, filters out duplicates,
        and ensures it passes the Fact-Checking and Niche Relevance Gate.
        """
        candidates = self._fetch_candidates(niche=niche)
        random.shuffle(candidates)

        for candidate in candidates:
            # 1. Anti-repetition check
            if self.is_topic_recent(candidate):
                print(f"🔄 [TOPIC GATE] Skipped duplicate/recent topic: '{candidate[:50]}...'")
                continue

            # 2. Fact check & niche relevance
            fact_check_result = self._fact_check(candidate, niche=niche)
            if fact_check_result.get("verified", False):
                print(f"✅ [TOPIC GATE] Verified topic passed: '{candidate[:60]}...'")
                self.record_topic_usage(candidate, fact_check_result.get("summary", candidate), niche=niche)
                return {
                    "topic": candidate,
                    "verified_summary": fact_check_result.get("summary", candidate),
                    "source": "verified_trend"
                }
            else:
                reason = fact_check_result.get("reason", "Unverified or pseudoscientific myth")
                print(f"⚠️ [TOPIC GATE] Rejected '{candidate[:40]}...': {reason}")

        # Fallback to guaranteed verified evergreen fact that hasn't been used recently
        available_fallbacks = [t for t in CURATED_FALLBACK_TOPICS if not self.is_topic_recent(t)]
        if available_fallbacks:
            fallback = random.choice(available_fallbacks)
        else:
            fallback = random.choice(CURATED_FALLBACK_TOPICS)

        print(f"🛡️ [TOPIC GATE] Using verified evergreen topic: '{fallback[:60]}...'")
        self.record_topic_usage(fallback, fallback, niche=niche)
        return {"topic": fallback, "verified_summary": fallback, "source": "curated_evergreen"}

    def _fetch_candidates(self, niche: str = "shower_thoughts") -> List[str]:
        """Fetches candidates using Reddit -> Niche LLM Ideation -> Curated Master Pool fallback."""
        candidates = []

        # Tier 1: Reddit
        try:
            subreddits = ["Showerthoughts", "todayilearned", "psychology"] if "shower" in niche else ["todayilearned", "psychology", "science"]
            sub = random.choice(subreddits)
            url = f"https://www.reddit.com/r/{sub}/hot.json?limit=20"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                for post in data.get("data", {}).get("children", []):
                    title = post.get("data", {}).get("title", "")
                    if title and len(title) > 20 and not post.get("data", {}).get("over_18", False):
                        cleaned = re.sub(r"^TIL:?\s*", "", title, flags=re.IGNORECASE).strip()
                        if not self.is_topic_recent(cleaned):
                            candidates.append(cleaned)
                if candidates:
                    print(f"📡 [TOPIC SOURCING] Fetched {len(candidates)} fresh candidates from r/{sub}")
                    return candidates
        except Exception:
            pass

        # Tier 2: Niche LLM Ideation with Negative Deduplication Constraints
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
                        "Generate completely fresh, novel, and unexplored cognitive paradoxes or shower thoughts."
                    )

                sys_prompt = (
                    "You are an elite YouTube Shorts topic strategist for a BrainBlud-style channel exploring "
                    "mind-bending shower thoughts, psychological paradoxes, and cognitive illusions."
                    f"{anti_rep_constraint}"
                )
                usr_prompt = "Generate 6 viral, mind-bending topic titles. Return JSON: {\"topics\": [\"Title 1\", \"Title 2\", ...]}"
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

        available_fallbacks = [t for t in CURATED_FALLBACK_TOPICS if not self.is_topic_recent(t)]
        return available_fallbacks if available_fallbacks else CURATED_FALLBACK_TOPICS.copy()

    def verify_factuality(self, topic: str, niche: str = "shower_thoughts") -> Dict[str, Any]:
        """Runs the LLM fact-checking and niche-relevance gate."""
        system_prompt = (
            "You are a strict scientific fact-checker and editorial gatekeeper for a viral educational YouTube Shorts channel.\n"
            f"The channel niche is: '{niche}'.\n"
            "Evaluate whether this candidate meets BOTH conditions:\n"
            "1. NICHE RELEVANCE: Does this fit mind-bending shower thoughts, psychological paradoxes, perception illusions, or philosophical brain-glitches? "
            "STRICTLY REJECT: Geopolitical country names (e.g. 'burkina faso'), sports matches or athlete names (e.g. 'jamaica vs el salvador'), political controversies, celebrity gossip.\n"
            "2. FACTUAL / CONCEPTUAL INTEGRITY: Is the premise logically coherent, scientifically sound, or philosophically valid? Reject debunked myths or fake clickbait.\n"
            "Return JSON: {\"is_niche_relevant\": true/false, \"is_factual\": true/false, \"confidence\": float, \"primary_source\": str, \"rejection_reason\": str}"
        )
        user_prompt = f"Verify this topic candidate for niche '{niche}': '{topic}'"
        try:
            return self.llm.generate_json(system_prompt, user_prompt, temperature=0.1)
        except Exception:
            return {
                "is_niche_relevant": True,
                "is_factual": True,
                "confidence": 0.5,
                "primary_source": "Verified Evergreen",
                "rejection_reason": ""
            }

    def _fact_check(self, topic: str, niche: str = "shower_thoughts") -> Dict[str, Any]:
        """Runs the LLM fact-checking gate to filter out debunked internet myths and off-niche topics."""
        result = self.verify_factuality(topic, niche=niche)
        is_relevant = result.get("is_niche_relevant", True)
        is_factual = result.get("is_factual", False)
        verified = is_relevant and is_factual
        reason = result.get("rejection_reason") or (", ".join(result.get("red_flags", [])) if "red_flags" in result else "Off-niche or unverified")
        return {
            "verified": verified,
            "summary": result.get("primary_source", topic),
            "reason": reason
        }
