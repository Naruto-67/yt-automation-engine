"""
engine/managers/editorial_critic.py — Autonomous Editorial Critic Suite (v1.0)

Runs after LLM script generation to enforce @BrainBlud quality standards:
1. CynicalHumanAuditor: "The Wall Test" — blocks solipsism and fake-deep nihilism.
2. TitleScriptAlignmentSkill: "Truth-in-Packaging" — ensures title matches compilation format.
3. HookAuditorSkill: "3-Second Reality Check" — validates Scene 1 is undeniable & testable.
4. audit_and_refine_spec(): Master pipeline hook called from pipeline_runner.py after script gen.
"""

from __future__ import annotations

import re
import json
import os
import random
from typing import List, Dict, Any, Tuple, Optional, Set


# ─── THE WALL TEST: BANNED SOLIPSISTIC / NIHILISTIC TROPES ───────────────────
# These phrases caused real viewer backlash with mocking comments.
# Reference: "walks into wall with eyes closed 'you lied to me'" (@xpstudioss)

SOLIPSISM_BANNED_PHRASES = [
    "doesn't exist when you close your eyes",
    "doesn't exist when you blink",
    "nothing is real",
    "everything is a lie",
    "everything is fake",
    "reality is a simulation",
    "reality is an illusion",
    "life is an illusion",
    "you don't exist",
    "nothing exists",
    "world doesn't exist",
    "universe is fake",
    "everything is predictable",
    "you cannot experience",
    "you will never experience",
    "will never experience",
    "never experience",
    "never actually experience",
    "will never actually",
    "never actually",
    "nothing is ever real",
    "reality is just",
    "existence is just",
    "consciousness is just a",
    "life is just a simulation",
    "the present moment doesn't",
    "you never actually",
]

# Umbrella compilation title templates — proven @BrainBlud formats
UMBRELLA_TITLE_TEMPLATES = [
    "Shower Thoughts That Blow Minds 🤯 #shorts",
    "Shower Thoughts To Mess With Your Head 👀 #shorts",
    "Shower Thoughts Nobody Knows 👀 #shorts",
    "Shower Thoughts You Didn't Know 👀 #shorts",
    "Secret Shower Thoughts Nobody Knew 👀 #shorts",
    "Psychological Tricks Nobody Knew 🧠 #shorts",
    "Psychological Facts That Blow Your Mind 🧠 #shorts",
    "Not So Fun Facts To Blow Your Mind 😳 #shorts",
    "Brain Glitches You Experience Daily 🤯 #shorts",
    "Unsettling Facts That Sound Fake But Are True 😳 #shorts",
    "Mind-Bending Facts About The Human Brain 🧠 #shorts",
    "Facts That Will Break Your Brain 💀 #shorts",
]


class CynicalHumanAuditor:
    """
    Audits script text against "The Wall Test":
    Every statement must be 100% defensible against a cynical, intelligent viewer.
    Blocks solipsism, fake-deep nihilism, and easily debunked claims.
    """

    @staticmethod
    def audit_text(text: str) -> Tuple[bool, str]:
        """
        Returns (passed: bool, reason: str).
        Passed = True means the text is clean.
        """
        text_lower = text.lower()
        for phrase in SOLIPSISM_BANNED_PHRASES:
            if phrase in text_lower:
                return False, f"Wall Test FAILED: Contains banned solipsistic phrase: '{phrase}'"
        return True, "Wall Test PASSED"

    @staticmethod
    def sanitize_scene(
        scene: Dict[str, Any],
        replacement_thoughts: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        If a scene fails the Wall Test, replaces its spoken_text with a
        vetted replacement from the curated vault or fallback pool.
        """
        passed, reason = CynicalHumanAuditor.audit_text(scene.get("spoken_text", ""))
        if passed:
            return scene

        print(f"🚫 [EDITORIAL CRITIC] {reason}")
        print(f"   Offending text: '{scene.get('spoken_text', '')[:80]}...'")

        # Try replacement thoughts
        if replacement_thoughts:
            for replacement in replacement_thoughts:
                passed_r, _ = CynicalHumanAuditor.audit_text(replacement)
                if passed_r:
                    print(f"   ✅ Replaced with vetted thought: '{replacement[:60]}...'")
                    scene = dict(scene)
                    scene["spoken_text"] = replacement
                    scene["_editorial_replaced"] = True
                    return scene

        # Last resort: generic safe fallback
        safe_fallback = "The brain named itself, then recognized itself, and is now questioning that exact fact."
        print(f"   ✅ Replaced with safe fallback.")
        scene = dict(scene)
        scene["spoken_text"] = safe_fallback
        scene["_editorial_replaced"] = True
        return scene


class TitleScriptAlignmentSkill:
    """
    Truth-in-Packaging:
    Ensures the title reflects the true compilation nature of the video,
    not an extreme isolated claim that the script doesn't prove.
    """

    @staticmethod
    def audit_title(title: str, scenes: List[Dict[str, Any]]) -> Tuple[bool, str]:
        """
        Returns (passed: bool, reason: str).
        Fails if title makes a narrow/extreme claim that the multi-scene script
        doesn't substantiate.
        """
        title_lower = title.lower()

        # Check for extreme single-claim title patterns that caused viewer backlash
        extreme_patterns = [
            r"you will never (actually |truly )?(experience|see|feel|touch)",
            r"(the world|reality|everything) doesn't exist",
            r"why you can('t| never) (perceive|experience|see|feel)",
            r"(nothing|everything) is (real|fake|a lie|an illusion|predictable)",
            r"proves? (reality|existence|the world) is",
            r"explode your (brain|head|skull|body)",
            r"kill you (instantly|immediately|in seconds)",
            r"(end|ruin) your life (instantly|in seconds)",
            r"will (destroy|liquefy|melt) your (brain|organs)",
        ]
        for pattern in extreme_patterns:
            if re.search(pattern, title_lower):
                return False, f"Title Truth-in-Packaging FAILED: Contains extreme unproven claim matching '{pattern}'"

        # Compilation umbrella check: Multi-topic scripts must have umbrella titles
        if len(scenes) >= 5:
            umbrella_keywords = ["thoughts", "facts", "tricks", "glitches", "things", "realities", "paradox"]
            has_umbrella_word = any(kw in title_lower for kw in umbrella_keywords)
            if not has_umbrella_word:
                return False, "Title Truth-in-Packaging FAILED: Multi-topic compilation video requires an umbrella title"

        return True, "Title Truth-in-Packaging PASSED"

    @staticmethod
    def align_title(
        title: str,
        scenes: List[Dict[str, Any]],
        upload_history_titles: Optional[List[str]] = None
    ) -> str:
        """
        If title fails truth-in-packaging, selects a safe umbrella title.
        Also deduplicates against recent upload history.
        """
        passed, reason = TitleScriptAlignmentSkill.audit_title(title, scenes)
        if not passed:
            print(f"🚫 [TITLE CRITIC] {reason}")
            # Pick least-recently-used umbrella title
            history = set(t.lower().strip() for t in (upload_history_titles or []))
            for candidate in UMBRELLA_TITLE_TEMPLATES:
                if candidate.lower() not in history:
                    print(f"   ✅ Title realigned to: '{candidate}'")
                    return candidate
            # All templates used recently — return first
            return UMBRELLA_TITLE_TEMPLATES[0]

        # Even if title passes, check for deduplication against upload history
        if upload_history_titles:
            title_lower = title.lower().strip()
            for recent in upload_history_titles:
                if _token_overlap(title_lower, recent.lower().strip()) > 0.70:
                    print(f"🔄 [TITLE DEDUP] Title '{title[:50]}' is too similar to recent upload. Rotating...")
                    history = set(t.lower().strip() for t in upload_history_titles)
                    for candidate in UMBRELLA_TITLE_TEMPLATES:
                        if candidate.lower() not in history:
                            print(f"   ✅ Title rotated to: '{candidate}'")
                            return candidate
                    break

        return title


class HookAuditorSkill:
    """
    3-Second Reality Check:
    Scene 1 must be an undeniable, testable, physical or perceptual fact.
    Rejects abstract or confusing openings.
    """

    BANNED_HOOK_OPENERS = [
        "did you know",
        "hey guys",
        "hey everyone",
        "welcome back",
        "in this video",
        "today we",
        "have you ever wondered",
        "imagine if",
        "what if i told you",
        "scientists say",
        "studies show",
        "research shows",
    ]

    @staticmethod
    def audit_hook(scene_text: str) -> Tuple[bool, str]:
        """
        Returns (passed: bool, reason: str).
        """
        text_lower = scene_text.lower().strip()

        # Check banned openers
        for opener in HookAuditorSkill.BANNED_HOOK_OPENERS:
            if text_lower.startswith(opener):
                return False, f"Hook Audit FAILED: Starts with banned opener '{opener}'"

        # Check for leading punctuation
        if scene_text.startswith((".", "...", "…", "-", "—")):
            return False, "Hook Audit FAILED: Starts with leading punctuation (must be in-media-res)"

        # Check minimum word count for a proper hook
        if len(scene_text.split()) < 7:
            return False, "Hook Audit FAILED: Hook too short (minimum 7 words)"

        return True, "Hook Audit PASSED"


class ThoughtCompletenessSkill:
    """
    Validates that a scene is a single, complete, self-contained thought.
    Blocks dangling conjunctions, prepositions, and fragmented half-sentences.
    """

    DANGLING_ENDINGS = [
        "because", "which means", "and", "so that", "whenever", "due to",
        "since", "whereas", "such as", "that is why", "leading to", "which is",
        "as a result of", "in order to"
    ]

    @staticmethod
    def audit_completeness(scene_text: str, is_final_scene: bool = False) -> Tuple[bool, str]:
        """Returns (passed: bool, reason: str)."""
        text_clean = scene_text.rstrip(".!?…-— ").lower().strip()
        if not is_final_scene:
            for ending in ThoughtCompletenessSkill.DANGLING_ENDINGS:
                if text_clean.endswith(ending):
                    return False, f"Thought Completeness FAILED: Ends with dangling connector '{ending}'"
        return True, "Thought Completeness PASSED"


# ─── PURE SHOWER THOUGHT AUDITOR (PERMANENT TRIVIA FACT BAN) ───────────────────

BANNED_TRIVIA_PATTERNS = [
    r'^\s*(did you know|ever wonder why|have you ever wondered|have you ever noticed|scientists (say|discovered|found)|research (shows|proves)|studies (show|prove)|fun fact|did you realize|in the \d{4}s|according to)',
    r'\b(octopuses?|blue whales?|sharks?|dolphins?|elephants?|cheetahs?|penguins?)\b.*(hearts?|neurons?|arms?|lungs?|swim|aorta|speed)',
    r'\b(trees?|fungi|plants?|mushrooms?)\b.*(underground|fungal|communicate|nutrients?)',
    r'\b(padlock|elevator buttons?|traffic lights?|escalator)\b.*(tiny hole|drain|pressure sensors?|sensors?)',
    r'\b(phone(\'s)? compass|magnetometer|gps signal)\b',
    r'\b(microwave(\'s)? turntable|turntable motor|food(\'s)? inertia)\b'
]


class PureShowerThoughtAuditor:
    """
    Validates that a scene is a genuine, pure Reddit-style Shower Thought.
    Strictly bans encyclopedic science facts, biological trivia, hardware trivia,
    and elementary school trivia openers ('Did you know', 'Ever wonder why').
    """

    @staticmethod
    def audit_thought(text: str) -> Tuple[bool, str]:
        text_lower = text.lower().strip()
        for pat in BANNED_TRIVIA_PATTERNS:
            if re.search(pat, text_lower):
                return False, f"Trivia Fact BANNED: Contains encyclopedic trivia pattern '{pat}'"
        return True, "Pure Shower Thought PASSED"

    @staticmethod
    def sanitize_scene(
        scene: Dict[str, Any],
        replacement_thoughts: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Replaces a trivia fact with a vetted pure shower thought."""
        passed, reason = PureShowerThoughtAuditor.audit_thought(scene.get("spoken_text", ""))
        if passed:
            return scene

        print(f"🚫 [PURE THOUGHT AUDITOR] {reason}")
        print(f"   Offending text: '{scene.get('spoken_text', '')[:80]}...'")

        if replacement_thoughts:
            for replacement in replacement_thoughts:
                passed_r, _ = PureShowerThoughtAuditor.audit_thought(replacement)
                if passed_r:
                    print(f"   ✅ Replaced fact with vetted shower thought: '{replacement[:60]}...'")
                    scene = dict(scene)
                    scene["spoken_text"] = replacement
                    scene["_editorial_replaced"] = True
                    return scene

        fallback = "The brain named itself, recognized itself, and is now questioning that exact realization."
        scene = dict(scene)
        scene["spoken_text"] = fallback
        scene["_editorial_replaced"] = True
        return scene


# ─── SEMANTIC DEDUPLICATION SKILL (SUBJECT-CORE & N-GRAM DE-DUPLICATION) ─────

SEMANTIC_STOPWORDS = {
    'a', 'an', 'the', 'is', 'are', 'was', 'were', 'it', 'to', 'for', 'of',
    'in', 'on', 'at', 'by', 'that', 'this', 'you', 'your', 'just', 'so',
    'be', 'with', 'and', 'or', 'as', 'if', 'its', 'then', 'from', 'we',
    'our', 'they', 'their', 'he', 'she', 'all', 'any', 'but', 'not', 'can',
    'will', 'do', 'does', 'did', 'than', 'more', 'far', 'while', 'when',
    'into', 'until', 'has', 'have', 'had', 'why', 'how', 'what', 'where',
    'who', 'which', 'could', 'would', 'should', 'been', 'about', 'being',
    'only', 'actually', 'literally', 'every', 'never', 'always'
}


class SemanticDeduplicationSkill:
    """
    Advanced semantic and subject-core deduplicator.
    Detects when two scenes discuss the same concept even with completely different wording.
    Prevents duplicates like:
      - 'Your brain ignores your nose' vs 'Your brain filters your nose'
      - 'You remember embarrassing moments' vs 'You remember embarrassing moments from years ago'
    """

    @staticmethod
    def extract_content_words_and_bigrams(text: str) -> Tuple[Set[str], Set[Tuple[str, str]]]:
        clean_words = [w.lower() for w in re.findall(r'\b[a-zA-Z]{3,}\b', text)]
        content = [w for w in clean_words if w not in SEMANTIC_STOPWORDS]
        bigrams = set()
        for i in range(len(content) - 1):
            bigrams.add((content[i], content[i+1]))
        return set(content), bigrams

    @classmethod
    def are_semantically_duplicate(cls, text_a: str, text_b: str) -> Tuple[bool, str]:
        """
        Returns (is_duplicate: bool, reason: str).
        """
        c_a, b_a = cls.extract_content_words_and_bigrams(text_a)
        c_b, b_b = cls.extract_content_words_and_bigrams(text_b)

        if not c_a or not c_b:
            return False, "Insufficient content words"

        # 1. Content Bigram Overlap (e.g. ("ignores", "nose"), ("embarrassing", "moments"))
        common_bigrams = b_a & b_b
        if common_bigrams:
            bigram_str = ", ".join(f"{b[0]} {b[1]}" for b in list(common_bigrams)[:3])
            return True, f"Shared subject bigrams detected: [{bigram_str}]"

        # 2. Content Core Lemmas Overlap (>= 2 shared subject words with high proportional match)
        common_words = c_a & c_b
        if len(common_words) >= 3:
            return True, f"High subject keyword overlap (3+ words): {sorted(list(common_words))}"

        if len(common_words) >= 2:
            min_len = min(len(c_a), len(c_b))
            if min_len > 0 and (len(common_words) / min_len) >= 0.35:
                return True, f"Proportional subject overlap (>=35%): {sorted(list(common_words))}"

        # 3. Tightened Jaccard Threshold (0.25)
        union_len = len(c_a | c_b)
        if union_len > 0 and (len(common_words) / union_len) >= 0.25:
            return True, f"Jaccard content overlap >= 0.25 ({len(common_words)}/{union_len})"

        return False, "Distinct thoughts"

    @classmethod
    def is_duplicate(cls, candidate_text: str, existing_scenes: List[Dict[str, Any]]) -> Tuple[bool, str]:
        """Checks candidate text against all existing scenes."""
        for prev in existing_scenes:
            prev_text = prev.get("spoken_text", "")
            dup, reason = cls.are_semantically_duplicate(candidate_text, prev_text)
            if dup:
                return True, reason
        return False, "Unique"


# ─── BRAINBLUD CLOSERS & LOOP AUDITOR ───────────────────────────────────────
BRAINBLUD_CLOSERS = [
    "Subscribe for more thoughts that will break your brain.",
    "If you want to be smarter than everyone you know, subscribe.",
    "If all of you subscribed right now, I would have more subscribers.",
    "Subscribe to unlock thoughts nobody told you.",
    "You just spent fifty seconds learning thoughts that won't help you on an exam.",
    "Your brain is now holding information it will never use again.",
    "If you made it this far, your attention span is better than average.",
    "If you subscribe right now, your phone won't explode tomorrow.",
    "Drop your wildest shower thought below, and subscribe for more.",
    "Subscribe if you want your recommended feed to make you question reality.",
    "You are now one minute closer to knowing everything about nothing."
]
COMPILATION_LOOP_BRIDGES = BRAINBLUD_CLOSERS  # Backwards compatibility alias


def check_loop_repeats_hook(loop_text: str, hook_text: str) -> Tuple[bool, str]:
    """
    Validates that the loop outro does NOT repeat or echo the opening hook.
    Returns (repeats: bool, reason: str).
    True means it REPEATS (bad). False means it is CLEAN (good).
    """
    if not loop_text or not hook_text:
        return False, "Empty text"

    bridge_stopwords = {
        "and", "if", "that", "this", "which", "is", "why", "you", "your",
        "remember", "never", "all", "of", "to", "the", "a", "an", "so",
        "for", "with", "but", "not", "what", "how", "just", "it", "are",
        "was", "were", "be", "been", "these", "those", "we", "us", "our",
        "back", "right", "into", "from", "by", "in", "on", "at", "as",
        "do", "did", "does", "can", "could", "would", "should", "one"
    }
    hook_tokens = set(re.findall(r"\b\w+\b", hook_text.lower())) - bridge_stopwords
    loop_tokens = set(re.findall(r"\b\w+\b", loop_text.lower())) - bridge_stopwords
    overlap = hook_tokens & loop_tokens

    if len(overlap) >= 2:
        return True, f"Loop repeats hook content words: {sorted(list(overlap))}"
    if hook_tokens and (len(overlap) / len(hook_tokens)) > 0.12:
        return True, f"Loop has high hook content overlap: {sorted(list(overlap))}"

    # Check 3-word n-gram matches (catches verbatim chunks even if stopwords are involved)
    hook_words_clean = re.findall(r"\b\w+\b", hook_text.lower())
    loop_words_clean = " " + " ".join(re.findall(r"\b\w+\b", loop_text.lower())) + " "
    for i in range(len(hook_words_clean) - 2):
        trigram = f" {' '.join(hook_words_clean[i:i+3])} "
        if trigram in loop_words_clean:
            return True, f"Loop contains 3-word sequence from hook: '{trigram.strip()}'"

    return False, "Clean loop"


class LoopAuditorSkill:
    """
    Audits Scene N (BrainBlud Outro Closer) against Scene 1 (Hook).
    Ensures Scene N NEVER repeats or echoes Scene 1 words or concepts.
    Enforces definitive terminal punctuation ('.' or '!') and rejects dangling ellipses '...'.
    """
    @staticmethod
    def audit_loop(loop_text: str, hook_text: str) -> Tuple[bool, str]:
        repeats, reason = check_loop_repeats_hook(loop_text, hook_text)
        if repeats:
            return False, f"Loop Audit FAILED: {reason}"

        text_clean = loop_text.strip()
        if text_clean.endswith("..."):
            return False, "Loop Audit FAILED: Ends on dangling ellipsis '...' instead of definitive terminal punctuation ('.' or '!')"

        if not (text_clean.endswith(".") or text_clean.endswith("!")):
            return False, "Loop Audit FAILED: Does not end with valid terminal punctuation ('.' or '!')"

        if re.search(r"['’]s\.$", text_clean):
            return False, "Loop Audit FAILED: Ends on possessive contraction before period"

        return True, "Loop Audit PASSED"

    @staticmethod
    def sanitize_loop(
        scene: Dict[str, Any],
        hook_text: str = "",
        mode_b: bool = True
    ) -> Dict[str, Any]:
        """Replaces a defective or repeating outro with a vetted BrainBlud CTA closer."""
        scene = dict(scene)
        scene["spoken_text"] = random.choice([
            "Subscribe for more thoughts that will break your brain.",
            "If you want to be smarter than everyone you know, subscribe.",
            "If all of you subscribed right now, I would have more subscribers.",
            "Subscribe to unlock thoughts nobody told you.",
            "You just spent fifty seconds learning thoughts that won't help you on an exam.",
            "Your brain is now holding information it will never use again.",
            "If you made it this far, your attention span is better than average.",
            "If you subscribe right now, your phone won't explode tomorrow.",
            "Drop your wildest shower thought below, and subscribe for more.",
            "Subscribe if you want your recommended feed to make you question reality.",
            "You are now one minute closer to knowing everything about nothing."
        ])
        scene["_editorial_replaced"] = True
        return scene


BrainBludCloserAuditorSkill = LoopAuditorSkill  # Modern alias


def _token_overlap(a: str, b: str) -> float:
    """Calculates Jaccard token overlap between two strings."""
    tokens_a = set(re.findall(r"\b\w+\b", a.lower()))
    tokens_b = set(re.findall(r"\b\w+\b", b.lower()))
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def _load_upload_history_titles() -> List[str]:
    """Loads recent video titles from data/upload_history.json if it exists."""
    path = os.path.join("data", "upload_history.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [entry.get("title", "") for entry in data if isinstance(entry, dict)]
        if isinstance(data, dict):
            return [entry.get("title", "") for entry in data.get("videos", []) if isinstance(entry, dict)]
    except Exception:
        pass
    return []


def _load_curated_replacements(count: int = 20) -> List[str]:
    """Loads vetted pure shower thoughts (zero trivia facts) from data/curated_thoughts_and_facts.json for replacement."""
    path = os.path.join("data", "curated_thoughts_and_facts.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        thoughts = []
        raw_items = []
        if isinstance(data, dict):
            if "items" in data and isinstance(data["items"], list):
                raw_items = data["items"]
            else:
                for val in data.values():
                    if isinstance(val, list):
                        raw_items.extend(val)
        elif isinstance(data, list):
            raw_items = data

        for item in raw_items:
            if isinstance(item, dict):
                # Strictly filter for thoughts only; ban facts completely
                if item.get("type", "").lower() == "fact":
                    continue
                text = item.get("text") or item.get("thought", "")
            elif isinstance(item, str):
                text = item
            else:
                continue
            if text:
                p_audit, _ = PureShowerThoughtAuditor.audit_thought(text)
                w_audit, _ = CynicalHumanAuditor.audit_text(text)
                if p_audit and w_audit:
                    thoughts.append(text)
        return thoughts[:count]
    except Exception:
        return []


def audit_and_refine_spec(
    raw_scenes: List[Dict[str, Any]],
    seo_data: Dict[str, Any],
    topic: str
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, str]]:
    """
    Master editorial pipeline hook. Called from pipeline_runner.py immediately
    after LLM script generation and calibration, before TTS synthesis.

    Runs the full Editorial Critic suite:
    1. Hook Auditor on Scene 1.
    2. Wall Test (CynicalHumanAuditor) on all scenes.
    3. Pure Shower Thought Auditor (banning all science/biology/hardware facts).
    4. Thought Completeness Auditor (banning dangling clauses).
    5. Semantic Deduplication Skill (preventing duplicate concepts across scenes).
    6. Loop Auditor on Scene N against Scene 1.
    7. Title Truth-in-Packaging + Deduplication.

    Returns:
        (refined_scenes, refined_seo, audit_summary_dict)
    """
    if not raw_scenes:
        return raw_scenes, seo_data, {"status": "skipped", "reason": "empty scenes"}

    audit_log = {
        "hook_status": "not_run",
        "wall_test_failures": 0,
        "trivia_fact_failures": 0,
        "semantic_duplicate_failures": 0,
        "wall_test_replacements": 0,
        "title_status": "not_run",
        "loop_status": "not_run",
        "original_title": seo_data.get("title", ""),
        "final_title": seo_data.get("title", ""),
    }

    # Load resources
    replacement_thoughts = _load_curated_replacements(count=40)
    upload_history_titles = _load_upload_history_titles()

    print("\n📋 [EDITORIAL CRITIC] Running autonomous quality audit...")

    # 1. Hook Auditor: validate Scene 1
    hook_text = raw_scenes[0].get("spoken_text", "")
    hook_passed, hook_reason = HookAuditorSkill.audit_hook(hook_text)
    audit_log["hook_status"] = "passed" if hook_passed else f"failed: {hook_reason}"
    if not hook_passed:
        print(f"   🚫 {hook_reason}")
        # Clean the hook — strip leading punctuation and capitalize
        cleaned = re.sub(r"^[.…\-—\s]+", "", hook_text).strip()
        if cleaned and cleaned[0].islower():
            cleaned = cleaned[0].upper() + cleaned[1:]
        raw_scenes[0]["spoken_text"] = cleaned
        print(f"   ✅ Hook cleaned to: '{cleaned[:60]}'")
    else:
        print(f"   ✅ Hook: {hook_reason}")

    # Also check Hook against Trivia Facts & Wall Test
    fact_passed, fact_reason = PureShowerThoughtAuditor.audit_thought(raw_scenes[0].get("spoken_text", ""))
    if not fact_passed:
        audit_log["trivia_fact_failures"] += 1
        print(f"   Scene 1 (Hook): 🚫 {fact_reason}")
        raw_scenes[0] = PureShowerThoughtAuditor.sanitize_scene(raw_scenes[0], replacement_thoughts)
        audit_log["wall_test_replacements"] += 1

    wall_passed, wall_reason = CynicalHumanAuditor.audit_text(raw_scenes[0].get("spoken_text", ""))
    if not wall_passed:
        audit_log["wall_test_failures"] += 1
        print(f"   Scene 1 (Hook): 🚫 {wall_reason}")
        raw_scenes[0] = CynicalHumanAuditor.sanitize_scene(raw_scenes[0], replacement_thoughts)
        audit_log["wall_test_replacements"] += 1

    # 2. Audit scenes 2 through N-1 (Middle compilation thoughts)
    for i in range(1, len(raw_scenes) - 1):
        scene = raw_scenes[i]
        text = scene.get("spoken_text", "")

        # A. Trivia Fact Check (ban facts completely)
        f_passed, f_reason = PureShowerThoughtAuditor.audit_thought(text)
        if not f_passed:
            audit_log["trivia_fact_failures"] += 1
            print(f"   Scene {i+1}: 🚫 {f_reason}")
            raw_scenes[i] = PureShowerThoughtAuditor.sanitize_scene(scene, replacement_thoughts)
            audit_log["wall_test_replacements"] += 1
            text = raw_scenes[i].get("spoken_text", "")

        # B. Wall Test (ban solipsism & fake-deep nihilism)
        w_passed, w_reason = CynicalHumanAuditor.audit_text(text)
        if not w_passed:
            audit_log["wall_test_failures"] += 1
            print(f"   Scene {i+1}: 🚫 {w_reason}")
            raw_scenes[i] = CynicalHumanAuditor.sanitize_scene(raw_scenes[i], replacement_thoughts)
            audit_log["wall_test_replacements"] += 1
            text = raw_scenes[i].get("spoken_text", "")

        # C. Completeness Check (ban dangling connector endings)
        c_passed, c_reason = ThoughtCompletenessSkill.audit_completeness(text, is_final_scene=False)
        if not c_passed:
            print(f"   Scene {i+1}: 🚫 {c_reason}")
            raw_scenes[i] = CynicalHumanAuditor.sanitize_scene(raw_scenes[i], replacement_thoughts)
            audit_log["wall_test_replacements"] += 1
            text = raw_scenes[i].get("spoken_text", "")

        # D. Semantic Deduplication Check against all preceding scenes
        is_dup, dup_reason = SemanticDeduplicationSkill.is_duplicate(text, raw_scenes[:i])
        if is_dup:
            audit_log["semantic_duplicate_failures"] += 1
            print(f"   Scene {i+1}: 🚫 Semantic Duplicate ({dup_reason})")
            # Find an unused replacement that doesn't duplicate any preceding scene
            found_replacement = False
            for rep in replacement_thoughts:
                rep_dup, _ = SemanticDeduplicationSkill.is_duplicate(rep, raw_scenes[:i])
                if not rep_dup:
                    raw_scenes[i] = dict(scene)
                    raw_scenes[i]["spoken_text"] = rep
                    raw_scenes[i]["_editorial_replaced"] = True
                    audit_log["wall_test_replacements"] += 1
                    found_replacement = True
                    print(f"   ✅ Replaced duplicate with unique thought: '{rep[:60]}...'")
                    break
            if not found_replacement:
                # Fallback unique thought
                fallback = f"Your shadow has traveled thousands of miles across the Earth, but you'll never see all of it."
                raw_scenes[i] = dict(scene)
                raw_scenes[i]["spoken_text"] = fallback
                raw_scenes[i]["_editorial_replaced"] = True
                audit_log["wall_test_replacements"] += 1

        if not f_passed or not w_passed or not c_passed or is_dup:
            pass
        else:
            print(f"   ✅ Scene {i+1}: PASSED all quality audits")

    # 3. Loop Auditor: Validate Scene N does NOT repeat Scene 1 hook
    if len(raw_scenes) >= 2:
        loop_passed, loop_reason = LoopAuditorSkill.audit_loop(
            loop_text=raw_scenes[-1].get("spoken_text", ""),
            hook_text=raw_scenes[0].get("spoken_text", "")
        )
        audit_log["loop_status"] = "passed" if loop_passed else f"failed: {loop_reason}"
        if not loop_passed:
            print(f"   🚫 Scene {len(raw_scenes)} (Loop Outro): {loop_reason}")
            raw_scenes[-1] = LoopAuditorSkill.sanitize_loop(
                scene=raw_scenes[-1],
                hook_text=raw_scenes[0].get("spoken_text", "")
            )
            audit_log["wall_test_replacements"] += 1
            print(f"   ✅ Loop Outro replaced with vetted bridge: '{raw_scenes[-1]['spoken_text']}'")
        else:
            print(f"   ✅ Scene {len(raw_scenes)} (Loop Outro): {loop_reason}")

    # 4. Title Truth-in-Packaging + Deduplication
    original_title = seo_data.get("title", "")
    aligned_title = TitleScriptAlignmentSkill.align_title(
        title=original_title,
        scenes=raw_scenes,
        upload_history_titles=upload_history_titles
    )
    if aligned_title != original_title:
        seo_data = dict(seo_data)
        seo_data["title"] = aligned_title
        audit_log["title_status"] = f"realigned from '{original_title[:40]}' to '{aligned_title[:40]}'"
    else:
        audit_log["title_status"] = "passed"
    audit_log["final_title"] = seo_data.get("title", "")

    total_issues = (
        audit_log["wall_test_failures"] +
        audit_log["trivia_fact_failures"] +
        audit_log["semantic_duplicate_failures"]
    )
    print(f"\n📋 [EDITORIAL CRITIC] Audit complete: {total_issues} issue(s) detected, {audit_log['wall_test_replacements']} replacement(s).")
    print(f"   Title: {audit_log['title_status']}")
    print(f"   Final title: '{audit_log['final_title']}'")

    return raw_scenes, seo_data, audit_log
