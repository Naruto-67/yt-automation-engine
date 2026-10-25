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
    "never experience anything",
    "never actually experience",
    "will never actually experience",
    "nothing is ever real",
    "reality is just a simulation",
    "reality is just an illusion",
    "reality is just a lie",
    "reality is just fake",
    "existence is just an illusion",
    "consciousness is just an illusion",
    "life is just a simulation",
    "the present moment doesn't exist",
    "you never actually exist",
]

# ─── BANNED OVERUSED TRIVIA / CLICHÉ TROPES ────────────────────────────────────
# These tropes are heavily overused across AI Shorts and trigger content fatigue.
CLICHE_BANNED_PHRASES = [
    # Alarm clock paradox
    "alarm clock screams",
    "wakes you up to punish you",
    "device you set hoping it fail",
    "only device you set hoping",
    # Conversation rehearsals
    "rehearsing conversations in your head",
    "rehearse conversations in your head",
    "fake arguments in the shower",
    "arguments in your head",
    "conversations in your head",
    # Age paradox clichés
    "oldest you've ever been",
    "youngest you'll ever be",
    "oldest you have ever been",
    "youngest you will ever be",
    # Autopilot / somatic traps
    "manual breathing",
    "manually breathing",
    "manual blinking",
    "manually blinking",
    "tongue doesn't fit comfortably",
    "tongue does not fit comfortably",
    "swallowing your own saliva",
    # Specific biological clichés (avoid blanket bans on 'stomach acid' or 'stomach lining')
    "stomach from digesting itself",
    "stomach lining replaces itself",
    "replaces its own lining",
    "stomach acid would digest",
    "hot water freezes faster",
    "mpemba effect",
    "freezes faster than cold water",
    "cracking your knuckles gives you arthritis",
    "cracking knuckles gives you arthritis",
    "popcorn steam",
    "smell of rain is called petrichor",
    "petrichor",
]

DEFAULT_NEUTRAL_TITLE = "Observations and Perspectives #shorts"

# Neutral, grounded compilation title templates for fallback alignment
UMBRELLA_TITLE_TEMPLATES = [
    "Shower Thoughts & Daily Perspectives #shorts",
    "Fascinating Realities of Everyday Life #shorts",
    "Grounded Perspectives on Everyday Life #shorts",
    "Fascinating Facts & Observations #shorts",
    "Curious Thoughts & Daily Realities #shorts",
    "Psychological Insights on Human Perception #shorts",
    "Subtle Realities You Experience Daily #shorts",
    "Observations on Common Realities #shorts",
    "Thoughtful Realizations About Daily Life #shorts",
    "Unexpected Insights on Everyday Things #shorts",
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

        # Contextual check: reality, existence, or consciousness asserted as an illusion/simulation/lie
        if re.search(r"\b(reality|existence|consciousness)\s+is\s+just\s+(an?\s+)?(simulation|illusion|lie|fake|hologram|projection)\b", text_lower):
            return False, "Wall Test FAILED: Asserts reality/consciousness is just an illusion or simulation"

        for phrase in CLICHE_BANNED_PHRASES:
            if phrase in text_lower:
                return False, f"Cliché Audit FAILED: Contains overused trope: '{phrase}'"
        return True, "Wall Test PASSED"

    @staticmethod
    def sanitize_scene(
        scene: Dict[str, Any],
        replacement_thoughts: Optional[List[str]] = None,
        llm_manager: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Revises a scene that failed the Wall Test using LLM revision if available,
        or marks it rejected without injecting canned creative content.
        """
        passed, reason = CynicalHumanAuditor.audit_text(scene.get("spoken_text", ""))
        if passed:
            return scene

        print(f"🚫 [EDITORIAL CRITIC] {reason}")
        print(f"   Offending text: '{scene.get('spoken_text', '')[:80]}...'")

        if llm_manager:
            revised, ok, rev_msg = revise_scene_with_llm(scene, reason, llm_manager=llm_manager)
            if ok:
                print(f"   ✅ {rev_msg}")
                return revised

        # For backwards compatibility with legacy unit tests explicitly passing replacement_thoughts:
        if replacement_thoughts:
            for replacement in replacement_thoughts:
                passed_r, _ = CynicalHumanAuditor.audit_text(replacement)
                if passed_r:
                    print(f"   ✅ Applied vetted replacement: '{replacement[:60]}...'")
                    scene = dict(scene)
                    scene["spoken_text"] = replacement
                    from engine.managers.voice_normalizer import VoiceNormalizer
                    scene["phonetic_text"] = VoiceNormalizer.normalize_text(replacement)
                    scene["_editorial_replaced"] = True
                    return scene

        # Do NOT inject hardcoded canned thoughts like 'The brain named itself...'
        scene = dict(scene)
        scene["_editorial_rejected"] = True
        return scene


def _ensure_shorts_suffix(title: str) -> str:
    """
    Ensures title ends with exactly one '#shorts' suffix without duplication.
    Cleans redundant punctuation and whitespace before the suffix.
    E.g.:
    'Atomic Repulsion' -> 'Atomic Repulsion #shorts'
    'Atomic Repulsion #shorts' -> 'Atomic Repulsion #shorts'
    'Atomic Repulsion #shorts #shorts' -> 'Atomic Repulsion #shorts'
    'Atomic Repulsion #SHORTS' -> 'Atomic Repulsion #shorts'
    """
    if not title or not isinstance(title, str) or not title.strip():
        return "Observations and Perspectives #shorts"
    text = title.strip()
    while True:
        stripped = re.sub(r"(?i)\s*#shorts\b", "", text).strip()
        if stripped == text:
            break
        text = stripped
    text = re.sub(r"[.…\-—\s]+$", "", text).strip()
    if not text:
        return "Observations and Perspectives #shorts"
    return f"{text} #shorts"


class TitleScriptAlignmentSkill:
    """
    Truth-in-Packaging:
    Ensures the title reflects the true compilation nature of the video,
    not an extreme isolated claim that the script doesn't prove.
    """

    @staticmethod
    def audit_title(title: Any, scenes: Optional[List[Dict[str, Any]]] = None) -> Tuple[bool, str]:
        """
        Returns (passed: bool, reason: str).
        Fails if title is empty, invalid, or makes a narrow/extreme claim that
        the multi-scene script doesn't substantiate.
        """
        if not title or not isinstance(title, str) or not title.strip():
            return False, "Title Truth-in-Packaging FAILED: Title is empty or not a string"

        title_clean = title.strip()
        title_lower = title_clean.lower()

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

        # Numerical factuality check: Title's numerical claims must be supported by the final script.
        # Uses occurrence-aware token comparison so a number cannot appear in the title more times
        # than it appears in the script.
        # NOTE: This provides deterministic lexical protection against unsupported numerical tokens,
        # preserving formatting equivalence (comma formatting, trailing zeros, sign preservation).
        # It is NOT full semantic verification and does not evaluate misrepresented unit relationships
        # or empirical validity (which remains the domain of ClaimInspector).
        from collections import Counter
        from engine.managers.iterative_script_generator import _extract_number_tokens
        script_text = " ".join(s.get("spoken_text", "") for s in (scenes or []) if isinstance(s, dict))
        script_counts = Counter(_extract_number_tokens(script_text))
        title_counts = Counter(_extract_number_tokens(title_clean))
        unsupported = []
        for num, count in title_counts.items():
            script_count = script_counts.get(num, 0)
            if count > script_count:
                unsupported.extend([num] * (count - script_count))
        if unsupported:
            return False, f"Title Truth-in-Packaging FAILED: Contains numerical claim(s) {unsupported} unsupported by script"

        # Compilation umbrella check: Multi-topic scripts must have umbrella titles
        if scenes and len(scenes) >= 5:
            umbrella_keywords = [
                "thoughts", "facts", "tricks", "glitches", "things", "realities",
                "paradox", "perspectives", "observations", "realizations"
            ]
            has_umbrella_word = any(kw in title_lower for kw in umbrella_keywords)
            if not has_umbrella_word:
                return False, "Title Truth-in-Packaging FAILED: Multi-topic compilation video requires an umbrella title"

        return True, "Title Truth-in-Packaging PASSED"

    @staticmethod
    def align_title(
        title: Optional[str],
        scenes: Optional[List[Dict[str, Any]]] = None,
        upload_history_titles: Optional[List[str]] = None,
        topic: str = ""
    ) -> str:
        """
        If title fails truth-in-packaging or numerical validation, or is too similar
        to recent uploads, selects a safe, grounded title derived from the script or
        verified umbrella templates.
        Guaranteed to always return a non-empty string ending with exactly one '#shorts'.
        """
        safe_scenes = scenes or []
        history = [t.lower().strip() for t in (upload_history_titles or []) if isinstance(t, str)]

        # 1. Evaluate initial candidate if provided
        if title and isinstance(title, str) and title.strip():
            cand_initial = _ensure_shorts_suffix(title)
            passed, reason = TitleScriptAlignmentSkill.audit_title(cand_initial, safe_scenes)
            if passed:
                cand_lower = cand_initial.lower()
                is_dup = any(
                    _token_overlap(cand_lower, recent) > 0.70
                    for recent in history
                )
                if not is_dup:
                    return cand_initial
                else:
                    print(f"🔄 [TITLE DEDUP] Title '{cand_initial[:50]}' is too similar to recent upload. Routing to candidate selection...")
            else:
                print(f"🚫 [TITLE CRITIC] {reason}")
        else:
            print("🚫 [TITLE CRITIC] Title is empty or not a string. Routing to candidate selection...")

        # 2. Priority 1: Validated Script-Grounded Candidate
        try:
            from engine.managers.iterative_script_generator import derive_grounded_fallback_title
            raw_script_cand = derive_grounded_fallback_title(scenes=safe_scenes, topic=topic)
            if raw_script_cand and isinstance(raw_script_cand, str) and raw_script_cand.strip():
                script_cand = _ensure_shorts_suffix(raw_script_cand)
                cand_passed, cand_reason = TitleScriptAlignmentSkill.audit_title(script_cand, safe_scenes)
                if cand_passed:
                    cand_lower = script_cand.lower()
                    is_hist_dup = any(
                        _token_overlap(cand_lower, recent) > 0.70
                        for recent in history
                    )
                    if not is_hist_dup:
                        print(f"   ✅ Title realigned to grounded script thought: '{script_cand}'")
                        return script_cand
                    else:
                        print(f"   🔄 [TITLE CRITIC] Script-derived candidate '{script_cand[:50]}' in upload history. Continuing to umbrella templates...")
                else:
                    print(f"   ⚠️ [TITLE CRITIC] Script-derived candidate failed validation ({cand_reason}). Continuing to umbrella templates...")
        except Exception as e:
            print(f"   ⚠️ [TITLE CRITIC] Grounded title derivation failed ({e}). Continuing to umbrella templates...")

        # 3. Priority 2: Select from neutral umbrella templates not in upload history
        for template in (UMBRELLA_TITLE_TEMPLATES or []):
            if not template or not isinstance(template, str) or not template.strip():
                continue
            cand = _ensure_shorts_suffix(template)
            c_passed, _ = TitleScriptAlignmentSkill.audit_title(cand, safe_scenes)
            if c_passed:
                cand_lower = cand.lower()
                if not any(_token_overlap(cand_lower, recent) > 0.70 for recent in history):
                    print(f"   ✅ Title realigned to neutral umbrella template: '{cand}'")
                    return cand

        # 4. Priority 3: All alternatives in history — select the first valid umbrella template
        for template in (UMBRELLA_TITLE_TEMPLATES or []):
            if not template or not isinstance(template, str) or not template.strip():
                continue
            cand = _ensure_shorts_suffix(template)
            c_passed, _ = TitleScriptAlignmentSkill.audit_title(cand, safe_scenes)
            if c_passed:
                print(f"   ✅ All alternatives in history; reusing valid neutral template: '{cand}'")
                return cand

        # 5. Priority 4: Guaranteed terminal neutral fallback
        neutral_cand = _ensure_shorts_suffix(DEFAULT_NEUTRAL_TITLE)
        n_passed, n_reason = TitleScriptAlignmentSkill.audit_title(neutral_cand, safe_scenes)
        if n_passed:
            print(f"   ✅ Title realigned to verified terminal neutral template: '{neutral_cand}'")
            return neutral_cand

        print(f"   ❌ [TITLE CRITIC] Terminal neutral fallback '{neutral_cand}' failed validation: {n_reason}")
        raise ValueError(f"Terminal neutral fallback title '{neutral_cand}' failed validation: {n_reason}")


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

        if not scene_text or not scene_text.strip():
            return False, "Hook Audit FAILED: Hook is empty"

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
    r'^\s*(did you know that|did you know|have you ever noticed that|have you ever noticed|fun fact:?|did you realize)\b',
    r'^\s*(a little-known fact is that|here is a crazy fact:?|an interesting fact is that)\b',
    r'^\s*(have you ever wondered why)\b'
]


class PureShowerThoughtAuditor:
    """
    Validates that a scene is a genuine, pure Reddit-style Shower Thought.
    Flags formulaic elementary school / clickbait trivia openers ('Did you know', 'Ever wonder why').
    Does NOT prohibit valid observations solely because they mention animals, plants, fungi, or everyday objects.
    """

    @staticmethod
    def audit_thought(text: str) -> Tuple[bool, str]:
        text_lower = text.lower().strip()
        for pat in BANNED_TRIVIA_PATTERNS:
            match = re.search(pat, text_lower)
            if match:
                return False, f"Trivia Fact BANNED: Starts with formulaic trivia opener '{match.group(0).strip()}'"
        return True, "Pure Shower Thought PASSED"

    @staticmethod
    def clean_opener(text: str) -> str:
        """Strips formulaic cheap trivia openers to salvage the underlying thought."""
        cleaned = re.sub(
            r'^\s*(did you know that|did you know|have you ever noticed that|have you ever noticed|fun fact:?|did you realize|a little-known fact is that|here is a crazy fact:?|an interesting fact is that|have you ever wondered why)\s*',
            '',
            text,
            flags=re.IGNORECASE
        ).strip()
        if cleaned and cleaned[0].islower():
            cleaned = cleaned[0].upper() + cleaned[1:]
        return cleaned

    @staticmethod
    def sanitize_scene(
        scene: Dict[str, Any],
        replacement_thoughts: Optional[List[str]] = None,
        llm_manager: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Cleans formulaic trivia openers or delegates to revision.
        Never injects hardcoded canned replacement thoughts.
        """
        text = scene.get("spoken_text", "")
        passed, reason = PureShowerThoughtAuditor.audit_thought(text)
        if passed:
            return scene

        print(f"🚫 [PURE THOUGHT AUDITOR] {reason}")
        cleaned = PureShowerThoughtAuditor.clean_opener(text)
        p_check, _ = PureShowerThoughtAuditor.audit_thought(cleaned)
        if p_check and cleaned.strip():
            scene = dict(scene)
            scene["spoken_text"] = cleaned
            from engine.managers.voice_normalizer import VoiceNormalizer
            scene["phonetic_text"] = VoiceNormalizer.normalize_text(cleaned)
            scene["_editorial_cleaned"] = True
            return scene

        if llm_manager:
            revised, ok, _ = revise_scene_with_llm(scene, reason, llm_manager=llm_manager)
            if ok:
                return revised

        if replacement_thoughts:
            for replacement in replacement_thoughts:
                p_r, _ = PureShowerThoughtAuditor.audit_thought(replacement)
                if p_r:
                    scene = dict(scene)
                    scene["spoken_text"] = replacement
                    from engine.managers.voice_normalizer import VoiceNormalizer
                    scene["phonetic_text"] = VoiceNormalizer.normalize_text(replacement)
                    scene["_editorial_replaced"] = True
                    return scene

        scene = dict(scene)
        scene["_editorial_rejected"] = True
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
        Contextual deduplication that avoids rejecting fresh thoughts merely
        because they share a common phrase or isolated content words.
        """
        c_a, b_a = cls.extract_content_words_and_bigrams(text_a)
        c_b, b_b = cls.extract_content_words_and_bigrams(text_b)

        if not c_a or not c_b:
            return False, "Insufficient content words"

        common_words = c_a & c_b
        common_bigrams = b_a & b_b
        min_len = min(len(c_a), len(c_b))

        # 1. Multi-Bigram Overlap: Sharing 2+ content bigrams indicates structural conceptual duplication
        if len(common_bigrams) >= 2:
            bigram_str = ", ".join(f"{b[0]} {b[1]}" for b in list(common_bigrams)[:3])
            return True, f"Shared subject bigrams detected: [{bigram_str}]"

        # 2. Distinctive single bigram with matching content words (e.g. ("embarrassing", "moments"))
        if len(common_bigrams) == 1 and len(common_words) >= 2:
            bigram = list(common_bigrams)[0]
            return True, f"Shared core bigram detected: [{bigram[0]} {bigram[1]}]"

        # 3. Content Core Lemmas Overlap (>= 4 shared content words, or >= 3 with high proportional match >= 45%)
        if len(common_words) >= 4:
            return True, f"High subject keyword overlap (4+ words): {sorted(list(common_words))}"

        if len(common_words) >= 3 and min_len > 0 and (len(common_words) / min_len) >= 0.45:
            return True, f"Proportional subject overlap (>=45%): {sorted(list(common_words))}"

        # 4. Jaccard content overlap threshold (0.35)
        union_len = len(c_a | c_b)
        if union_len > 0 and (len(common_words) / union_len) >= 0.35:
            return True, f"Jaccard content overlap >= 0.35 ({len(common_words)}/{union_len})"

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
    "You are now one minute closer to knowing everything about nothing.",
    "If you want to question reality every single day, subscribe."
]
COMPILATION_LOOP_BRIDGES = BRAINBLUD_CLOSERS  # Backwards compatibility alias


def is_valid_circular_bridge(loop_text: str, hook_text: str) -> Tuple[bool, str]:
    """
    Validates whether loop_text is a genuine, high-quality circular loopback bridge
    flowing seamlessly into hook_text, distinguishing legitimate thematic overlap
    from defective verbatim echoes or duplicate stutters.
    """
    text_clean = loop_text.strip() if loop_text else ""
    hook_clean = hook_text.strip() if hook_text else ""
    if not text_clean or not hook_clean:
        return False, "Empty text"

    # Must have circular bridge syntax: ends in '...' or a forward transition connector
    has_bridge_syntax = text_clean.endswith("...") or any(
        text_clean.lower().endswith(w) for w in [
            " because", " since", " that", " when", " by", " where",
            " why", " how", " is", " are"
        ]
    )
    if not has_bridge_syntax:
        return False, "Missing circular bridge syntax (must end in '...' or trailing connector)"

    bridge_stopwords = {
        "and", "if", "that", "this", "which", "is", "why", "you", "your",
        "remember", "never", "all", "of", "to", "the", "a", "an", "so",
        "for", "with", "but", "not", "what", "how", "just", "it", "are",
        "was", "were", "be", "been", "these", "those", "we", "us", "our",
        "back", "right", "into", "from", "by", "in", "on", "at", "as",
        "do", "did", "does", "can", "could", "would", "should", "one", "only",
        "even", "more", "most", "about", "there", "then"
    }

    hook_words_clean = re.findall(r"\b\w+\b", hook_text.lower())
    loop_words_clean = re.findall(r"\b\w+\b", loop_text.lower())
    hook_tokens = set(hook_words_clean) - bridge_stopwords
    loop_tokens = set(loop_words_clean) - bridge_stopwords
    overlap = hook_tokens & loop_tokens

    # 1. Reject if loop re-speaks the majority of the hook's core content (>= 50% or >= 4 content words)
    if hook_tokens and (len(overlap) / len(hook_tokens) >= 0.5 or len(overlap) >= 4):
        return False, f"Loop echoes majority of hook content: {sorted(list(overlap))}"

    # 2. Reject meaningful 3-word verbatim sequences from anywhere in hook (ignore pure stopword connectors)
    loop_str = " " + " ".join(loop_words_clean) + " "
    for i in range(len(hook_words_clean) - 2):
        ngram = hook_words_clean[i:i+3]
        if all(w in bridge_stopwords for w in ngram):
            continue
        trigram_str = " " + " ".join(ngram) + " "
        if trigram_str in loop_str:
            return False, f"Loop contains 3-word sequence from hook: '{' '.join(ngram)}'"

    # 3. Reject immediate opening head stutter (3+ words matching opening of hook)
    if len(hook_words_clean) >= 3:
        head_trigram = " " + " ".join(hook_words_clean[:3]) + " "
        if head_trigram in loop_str:
            return False, f"Loop duplicates opening words of hook: '{head_trigram.strip()}'"

    # 4. Overall token similarity threshold
    if _token_overlap(loop_text, hook_text) > 0.45:
        return False, "Overall token similarity to hook exceeds circular bridge threshold"

    return True, "Valid circular bridge"


validate_loop_bridge = is_valid_circular_bridge


def check_loop_repeats_hook(loop_text: str, hook_text: str) -> Tuple[bool, str]:
    """
    Validates that the loop outro does NOT repeat or echo the opening hook.
    Returns (repeats: bool, reason: str).
    True means it REPEATS (bad). False means it is CLEAN (good).
    """
    if not loop_text or not hook_text or not loop_text.strip() or not hook_text.strip():
        return False, "Empty text"

    # A verified valid circular bridge is inherently non-defective
    is_circ, _ = is_valid_circular_bridge(loop_text, hook_text)
    if is_circ:
        return False, "Clean loop (valid circular bridge)"

    bridge_stopwords = {
        "and", "if", "that", "this", "which", "is", "why", "you", "your",
        "remember", "never", "all", "of", "to", "the", "a", "an", "so",
        "for", "with", "but", "not", "what", "how", "just", "it", "are",
        "was", "were", "be", "been", "these", "those", "we", "us", "our",
        "back", "right", "into", "from", "by", "in", "on", "at", "as",
        "do", "did", "does", "can", "could", "would", "should", "one", "only",
        "even", "more", "most", "about", "there", "then"
    }
    hook_tokens = set(re.findall(r"\b\w+\b", hook_text.lower())) - bridge_stopwords
    loop_tokens = set(re.findall(r"\b\w+\b", loop_text.lower())) - bridge_stopwords
    overlap = hook_tokens & loop_tokens

    if len(overlap) >= 2:
        return True, f"Loop repeats hook content words: {sorted(list(overlap))}"
    if hook_tokens and len(overlap) >= 2 and (len(overlap) / len(hook_tokens)) > 0.12:
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
    Audits Scene N (Ending / Closer / Bridge) against Scene 1 (Hook).
    Validates genuine circular loopback bridges (with legitimate topical context)
    and validates standalone endings without forcing canned CTA substitutions.
    """
    @staticmethod
    def audit_loop(
        loop_text: str,
        hook_text: str,
        ending_type: Optional[str] = None
    ) -> Tuple[bool, str]:
        text_clean = loop_text.strip() if loop_text else ""
        hook_clean = hook_text.strip() if hook_text else ""
        if not text_clean or not hook_clean:
            return False, "Loop Audit FAILED: Empty text"

        # Determine loop intent: prefer explicit ending_type; if absent, treat '...' as loop
        etype = str(ending_type).strip().lower() if ending_type else ""
        if etype:
            is_loop = etype in ("circular_loop", "loop", "circular")
        else:
            # Do not infer loop intent merely from trailing words such as is, are, by, or that.
            is_loop = text_clean.endswith("...")

        if is_loop:
            # 1. Structural bridge syntax validation
            is_circ, circ_reason = is_valid_circular_bridge(text_clean, hook_clean)
            if not is_circ:
                return False, f"Loop Audit FAILED: {circ_reason}"

            # 2. Loop-specific anti-repetition validation against hook
            repeats, rep_reason = check_loop_repeats_hook(text_clean, hook_clean)
            if repeats:
                return False, f"Loop Audit FAILED: {rep_reason}"

            return True, "Circular Loopback Bridge PASSED"

        # Standalone ending (punchline, observation, callback, provocation, resolution):
        # Must not be rejected solely because it reuses words from the hook.

        # Terminal punctuation checks
        if text_clean.endswith("..."):
            return False, "Loop Audit FAILED: Ends on dangling ellipsis '...' instead of definitive terminal punctuation ('.', '!', or '?')"

        if not (text_clean.endswith(".") or text_clean.endswith("!") or text_clean.endswith("?")):
            return False, "Loop Audit FAILED: Does not end with valid terminal punctuation ('.', '!', or '?')"

        if re.search(r"['’]s\.$", text_clean):
            return False, "Loop Audit FAILED: Ends on possessive contraction before period"

        # Prevent verbatim duplicate of opening hook
        if text_clean.lower().rstrip(".!?") == hook_clean.lower().rstrip(".!?"):
            return False, "Loop Audit FAILED: Standalone ending duplicates opening hook verbatim"

        return True, "Standalone Ending PASSED"

    @staticmethod
    def sanitize_loop(
        scene: Dict[str, Any],
        hook_text: str = "",
        mode_b: bool = True
    ) -> Dict[str, Any]:
        """
        Normalizes a defective outro scene into an acceptable standalone ending.
        Preserves original content without injecting canned subscription CTAs or artificial loops.
        """
        scene = dict(scene)
        txt = scene.get("spoken_text", "").strip()
        if txt.endswith("..."):
            txt = txt.rstrip(".!? ") + "."
            scene["spoken_text"] = txt
            from engine.managers.voice_normalizer import VoiceNormalizer
            scene["phonetic_text"] = VoiceNormalizer.normalize_text(txt)
            scene["_editorial_normalized"] = True
        return scene


BrainBludCloserAuditorSkill = LoopAuditorSkill  # Modern alias


def _token_overlap(a: str, b: str) -> float:
    """Calculates Jaccard token overlap between two strings."""
    tokens_a = set(re.findall(r"\b\w+\b", a.lower()))
    tokens_b = set(re.findall(r"\b\w+\b", b.lower()))
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def _is_valid_history_record(entry: Any) -> bool:
    """Validates that an upload history entry is a dictionary with a non-empty, non-whitespace string title."""
    if not isinstance(entry, dict):
        return False
    if "title" not in entry:
        return False
    title_val = entry["title"]
    if not isinstance(title_val, str) or not title_val.strip():
        return False
    return True


def _load_upload_history_titles(strict: bool = False, path: Optional[str] = None) -> Optional[List[str]]:
    """Loads recent video titles from data/upload_history.json if it exists.

    If strict=False (default):
        Permissive compatibility mode returning List[str]. Returns [] if file is missing,
        corrupt, unreadable, or structured unexpectedly.

    If strict=True:
        Fails safe when history deduplication cannot be verified:
        - If file does not exist: returns [] (legitimate no-history state).
        - If file exists and contains valid list or dictionary history: returns List[str].
        - Every record in the list or dictionary must be a dict containing a 'title'
          key with a non-empty string value after trimming.
        - If any record is malformed, missing 'title', non-string, or blank: returns None
          (does not silently discard malformed records or continue with partial history).
        - If file exists but is unreadable (I/O error), malformed JSON, or invalid
          structure: returns None (indicating history validation is unavailable).
    """
    target_path = path if path is not None else os.path.join("data", "upload_history.json")
    if not os.path.exists(target_path):
        return []
    try:
        with open(target_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            if strict:
                for entry in data:
                    if not _is_valid_history_record(entry):
                        return None
                return [entry["title"] for entry in data]
            return [entry.get("title", "") for entry in data if isinstance(entry, dict)]
        if isinstance(data, dict):
            if strict and ("videos" not in data or not isinstance(data.get("videos"), list)):
                return None
            videos = data.get("videos", [])
            if isinstance(videos, list):
                if strict:
                    for entry in videos:
                        if not _is_valid_history_record(entry):
                            return None
                    return [entry["title"] for entry in videos]
                return [entry.get("title", "") for entry in videos if isinstance(entry, dict)]
            if strict:
                return None
            return []
        if strict:
            return None
    except Exception:
        if strict:
            return None
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


def _load_editorial_revision_prompt(prompts_cfg: Optional[Dict[str, Any]] = None) -> str:
    """Loads the active editorial revision prompt from configuration or built-in default."""
    if prompts_cfg and isinstance(prompts_cfg, dict):
        ed_rev = prompts_cfg.get("editorial_revision")
        if isinstance(ed_rev, dict):
            p = ed_rev.get("system_prompt", "")
            if p and p.strip():
                return p.strip()
        elif isinstance(ed_rev, str) and ed_rev.strip():
            return ed_rev.strip()
    try:
        import yaml
        path = os.path.join("config", "prompts.yaml")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
                if isinstance(cfg, dict) and "editorial_revision" in cfg:
                    ed_rev = cfg["editorial_revision"]
                    if isinstance(ed_rev, dict):
                        p = ed_rev.get("system_prompt", "")
                        if p and p.strip():
                            return p.strip()
                    elif isinstance(ed_rev, str) and ed_rev.strip():
                        return ed_rev.strip()
    except Exception:
        pass

    return (
        "You are an expert editorial critic and script editor for high-retention YouTube Shorts.\n"
        "A scene failed an editorial quality check. Your task is to perform the SMALLEST EFFECTIVE REPAIR "
        "to resolve the defect, strictly preserving the original idea, distinctive insight, humor, irony, "
        "and factual substance.\n\n"
        "EDITORIAL PRINCIPLES:\n"
        "1. Precision Repair: Fix only the specific defect described in the feedback. Do not rewrite strong, "
        "already-working elements of the line.\n"
        "2. Voice & Cadence: Keep the line grounded, natural, and conversational when heard aloud. "
        "Do not add unearned hype, manufactured astonishment, generic hooks, or forced slang.\n"
        "3. Strict Fact & Numerical Integrity: Never alter, drop, or invent factual claims, statistics, "
        "or numerical figures. Preserve the original degree of certainty and attribution.\n"
        "4. Ending Intent: If this is an ending payoff, keep it as a clean standalone conclusion with definitive "
        "punctuation ('.', '!', '?') unless explicitly requested as a circular loop (ending in '...').\n"
        "5. Completeness: Ensure the thought stands on its own with no dangling conjunctions, prepositions, "
        "or incomplete clauses.\n\n"
        "Return ONLY a valid JSON object matching:\n"
        '{"spoken_text": "<repaired spoken line>", "stock_video_query": "<specific visual b-roll query>"}'
    )


def revise_scene_with_llm(
    scene: Dict[str, Any],
    failure_reason: str,
    llm_manager: Optional[Any] = None,
    existing_scenes: Optional[List[Dict[str, Any]]] = None,
    is_final_scene: bool = False,
    is_hook_scene: bool = False,
    max_attempts: int = 2,
    channel_premise: str = "",
    prompts_cfg: Optional[Dict[str, Any]] = None
) -> Tuple[Dict[str, Any], bool, str]:
    """
    Revision-First Editorial Engine:
    When a generated scene fails an editorial check, preserves the original idea,
    identifies the defect, and invokes the LLM revision mechanism (task_name="rewrite")
    with targeted feedback to make the smallest effective repair.

    Re-validates the candidate through:
    1. Numerical Fact & Polarity Preservation (no altered, dropped, or invented figures)
    2. HookAuditorSkill (if is_hook_scene=True: in-media-res, no banned openers)
    3. LoopAuditorSkill (if is_final_scene=True: loop syntax if loop, terminal punctuation if standalone)
    4. CynicalHumanAuditor (Wall Test / solipsism / cliché)
    5. PureShowerThoughtAuditor (formulaic trivia openers)
    6. ThoughtCompletenessSkill (dangling connectors)
    7. SemanticDeduplicationSkill (duplicate of prior scenes)

    If bounded attempts (max 2) succeed, returns the revised scene with synchronized phonetic_text.
    If attempts exhaust or no LLM is available, returns the scene marked with _editorial_rejected=True.
    NEVER substitutes canned fallback thoughts.
    """
    if not llm_manager:
        rejected = dict(scene)
        rejected["_editorial_rejected"] = True
        return rejected, False, "No LLM manager available for editorial revision"

    original_text = scene.get("spoken_text", "").strip()
    feedback = failure_reason
    last_reason = failure_reason

    system_prompt = _load_editorial_revision_prompt(prompts_cfg=prompts_cfg)

    # Extract original numerical tokens for factual preservation
    from engine.managers.iterative_script_generator import _extract_number_tokens
    orig_nums = _extract_number_tokens(original_text)

    for attempt in range(1, max_attempts + 1):
        premise_section = f"CHANNEL PREMISE / TONE: {channel_premise}\n\n" if channel_premise else ""
        context_section = ""
        if existing_scenes:
            ctx_lines = [
                f"- Scene {s.get('scene_id') or idx+1}: \"{s.get('spoken_text', '').strip()}\""
                for idx, s in enumerate(existing_scenes) if s.get('spoken_text')
            ]
            if ctx_lines:
                context_section = "SURROUNDING SCRIPT CONTEXT (for continuity and non-duplication):\n" + "\n".join(ctx_lines) + "\n\n"

        role_desc = "HOOK SCENE (Opening)" if is_hook_scene else ("ENDING PAYOFF SCENE" if is_final_scene else "MIDDLE THOUGHT SCENE")

        user_prompt = (
            f"{premise_section}"
            f"{context_section}"
            f"SCENE ROLE: {role_desc}\n"
            f"ORIGINAL SPOKEN TEXT:\n\"{original_text}\"\n\n"
            f"EDITORIAL DEFECT TO REPAIR:\n\"{feedback}\"\n\n"
            f"Attempt {attempt} of {max_attempts}: Make the smallest effective repair to correct this defect while strictly preserving the original core idea.\n"
            'Return ONLY JSON: {"spoken_text": "<repaired line>", "stock_video_query": "<specific visual query>"}'
        )

        try:
            result = llm_manager.generate_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.7,
                task_name="rewrite"
            )
        except Exception as e:
            print(f"   ⚠️ [EDITORIAL CRITIC] LLM revision call failed on attempt {attempt}: {e}")
            last_reason = f"LLM generation error: {e}"
            continue

        if not isinstance(result, dict):
            last_reason = "Invalid non-dict JSON returned by LLM"
            continue

        candidate_text = (result.get("spoken_text") or result.get("text") or "").strip()
        candidate_text = re.sub(r'^["\']|["\']$', "", candidate_text).strip()

        if not candidate_text:
            last_reason = "Empty spoken_text in LLM revision"
            continue

        # 1. Numerical Fact & Polarity Preservation
        # The revision must not alter, drop, or invent numerical claims.
        # Original and candidate numerical-token sequences are always compared,
        # including when both or either sequence is empty.
        cand_nums = _extract_number_tokens(candidate_text)
        if orig_nums != cand_nums:
            feedback = f"Attempt {attempt} altered, dropped, or invented numerical claims: expected {orig_nums}, got {cand_nums}"
            last_reason = feedback
            continue

        # 2. Hook Audit (if is_hook_scene)
        if is_hook_scene:
            h_passed, h_reason = HookAuditorSkill.audit_hook(candidate_text)
            if not h_passed:
                feedback = f"Attempt {attempt} failed Hook Audit: {h_reason}"
                last_reason = h_reason
                continue

        # 3. Ending Payoff Audit (if is_final_scene)
        if is_final_scene:
            ending_type = scene.get("ending_type")
            hook_text = ""
            if existing_scenes:
                hook_text = existing_scenes[0].get("spoken_text", "")
            l_passed, l_reason = LoopAuditorSkill.audit_loop(candidate_text, hook_text, ending_type=ending_type)
            if not l_passed:
                feedback = f"Attempt {attempt} failed Ending Audit: {l_reason}"
                last_reason = l_reason
                continue

        # 4. Wall Test & Cliché Audit
        w_passed, w_reason = CynicalHumanAuditor.audit_text(candidate_text)
        if not w_passed:
            feedback = f"Attempt {attempt} failed Wall Test: {w_reason}"
            last_reason = w_reason
            continue

        # 5. Pure Shower Thought (Trivia Opener) Audit
        f_passed, f_reason = PureShowerThoughtAuditor.audit_thought(candidate_text)
        if not f_passed:
            cleaned = PureShowerThoughtAuditor.clean_opener(candidate_text)
            c_passed, _ = PureShowerThoughtAuditor.audit_thought(cleaned)
            if c_passed and cleaned.strip():
                candidate_text = cleaned
            else:
                feedback = f"Attempt {attempt} failed Trivia Check: {f_reason}"
                last_reason = f_reason
                continue

        # 6. Thought Completeness Audit
        c_passed, c_reason = ThoughtCompletenessSkill.audit_completeness(candidate_text, is_final_scene=is_final_scene)
        if not c_passed:
            feedback = f"Attempt {attempt} failed Completeness Check: {c_reason}"
            last_reason = c_reason
            continue

        # 7. Semantic Deduplication against existing scenes
        if existing_scenes:
            is_dup, dup_reason = SemanticDeduplicationSkill.is_duplicate(candidate_text, existing_scenes)
            if is_dup:
                feedback = f"Attempt {attempt} duplicates another scene: {dup_reason}"
                last_reason = dup_reason
                continue

        # All quality audits passed! Accept revision.
        revised = dict(scene)
        revised["spoken_text"] = candidate_text
        from engine.managers.voice_normalizer import VoiceNormalizer
        revised["phonetic_text"] = VoiceNormalizer.normalize_text(candidate_text)
        if result.get("stock_video_query"):
            revised["stock_video_query"] = result["stock_video_query"]
        elif result.get("visual_hook"):
            revised["stock_video_query"] = result["visual_hook"]
        revised["_editorial_revised"] = True
        return revised, True, f"Scene successfully revised by LLM on attempt {attempt}: '{candidate_text[:60]}...'"

    # Bounded retries exhausted — fail safely without canned text
    rejected = dict(scene)
    rejected["_editorial_rejected"] = True
    return rejected, False, f"LLM revision exhausted ({max_attempts} attempts). Last failure: {last_reason}"


def audit_and_refine_spec(
    raw_scenes: List[Dict[str, Any]],
    seo_data: Dict[str, Any],
    topic: str,
    llm_manager: Optional[Any] = None,
    channel_premise: str = "",
    prompts_cfg: Optional[Dict[str, Any]] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, Any]]:
    """
    Master editorial pipeline hook. Called from pipeline_runner.py immediately
    after LLM script generation and calibration, before TTS synthesis.

    Runs the full Editorial Critic suite with revision-first editing:
    1. Hook Auditor on Scene 1.
    2. Wall Test (CynicalHumanAuditor) on all scenes.
    3. Pure Shower Thought Auditor (banning formulaic trivia openers).
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
        "editorial_revisions_attempted": 0,
        "editorial_revisions_succeeded": 0,
        "unresolved_failures": 0,
        "wall_test_replacements": 0,  # Maintained for LLMQualityTracker compatibility
        "title_status": "not_run",
        "loop_status": "not_run",
        "original_title": seo_data.get("title", ""),
        "final_title": seo_data.get("title", ""),
        "status": "passed",
    }

    # Load recent titles for truth-in-packaging deduplication
    upload_history_titles = _load_upload_history_titles()

    print("\n📋 [EDITORIAL CRITIC] Running autonomous quality audit...")

    # 1. Hook Auditor: validate Scene 1
    hook_text = raw_scenes[0].get("spoken_text", "")
    hook_passed, hook_reason = HookAuditorSkill.audit_hook(hook_text)
    if not hook_passed:
        print(f"   🚫 {hook_reason}")
        cleaned = re.sub(r"^[.…\-—\s]+", "", hook_text).strip()
        if cleaned and cleaned[0].islower():
            cleaned = cleaned[0].upper() + cleaned[1:]

        # Re-audit cleaned hook
        re_passed, re_reason = HookAuditorSkill.audit_hook(cleaned)
        if re_passed:
            raw_scenes[0]["spoken_text"] = cleaned
            from engine.managers.voice_normalizer import VoiceNormalizer
            raw_scenes[0]["phonetic_text"] = VoiceNormalizer.normalize_text(cleaned)
            raw_scenes[0]["_editorial_cleaned"] = True
            audit_log["hook_status"] = "passed"
            print(f"   ✅ Hook cleaned and validated to: '{cleaned[:60]}'")
        else:
            # Cleaned hook still fails HookAuditorSkill; attempt revision with hook audit
            print(f"   🚫 Cleaned hook still fails: {re_reason}. Attempting LLM revision...")
            audit_log["editorial_revisions_attempted"] += 1
            revised_sc, ok, rev_msg = revise_scene_with_llm(
                raw_scenes[0], re_reason, llm_manager=llm_manager, is_hook_scene=True,
                channel_premise=channel_premise, prompts_cfg=prompts_cfg
            )
            if ok:
                raw_scenes[0] = revised_sc
                audit_log["editorial_revisions_succeeded"] += 1
                audit_log["hook_status"] = "passed"
                print(f"   ✅ {rev_msg}")
            else:
                raw_scenes[0] = revised_sc
                audit_log["unresolved_failures"] += 1
                audit_log["hook_status"] = f"failed: {re_reason}"
                print(f"   🚫 Hook revision failed: {rev_msg}")
    else:
        audit_log["hook_status"] = "passed"
        print(f"   ✅ Hook: {hook_reason}")

    # Also check Hook against Trivia Openers & Wall Test (if not already rejected)
    if not raw_scenes[0].get("_editorial_rejected"):
        fact_passed, fact_reason = PureShowerThoughtAuditor.audit_thought(raw_scenes[0].get("spoken_text", ""))
        if not fact_passed:
            audit_log["trivia_fact_failures"] += 1
            print(f"   Scene 1 (Hook): 🚫 {fact_reason}")
            cleaned_hook = PureShowerThoughtAuditor.clean_opener(raw_scenes[0].get("spoken_text", ""))
            p_check, _ = PureShowerThoughtAuditor.audit_thought(cleaned_hook)
            h_check, _ = HookAuditorSkill.audit_hook(cleaned_hook)
            if p_check and h_check:
                raw_scenes[0]["spoken_text"] = cleaned_hook
                from engine.managers.voice_normalizer import VoiceNormalizer
                raw_scenes[0]["phonetic_text"] = VoiceNormalizer.normalize_text(cleaned_hook)
                raw_scenes[0]["_editorial_cleaned"] = True
                print(f"   ✅ Cleaned Hook opener to preserve thought: '{cleaned_hook[:60]}...'")
            else:
                audit_log["editorial_revisions_attempted"] += 1
                revised_sc, ok, rev_msg = revise_scene_with_llm(
                    raw_scenes[0], fact_reason, llm_manager=llm_manager, is_hook_scene=True,
                    channel_premise=channel_premise, prompts_cfg=prompts_cfg
                )
                if ok:
                    raw_scenes[0] = revised_sc
                    audit_log["editorial_revisions_succeeded"] += 1
                    print(f"   ✅ {rev_msg}")
                else:
                    raw_scenes[0] = revised_sc
                    audit_log["unresolved_failures"] += 1
                    audit_log["hook_status"] = f"failed: {fact_reason}"
                    print(f"   🚫 Hook revision failed: {rev_msg}")

    if not raw_scenes[0].get("_editorial_rejected"):
        wall_passed, wall_reason = CynicalHumanAuditor.audit_text(raw_scenes[0].get("spoken_text", ""))
        if not wall_passed:
            audit_log["wall_test_failures"] += 1
            print(f"   Scene 1 (Hook): 🚫 {wall_reason}")
            audit_log["editorial_revisions_attempted"] += 1
            revised_sc, ok, rev_msg = revise_scene_with_llm(
                raw_scenes[0], wall_reason, llm_manager=llm_manager, is_hook_scene=True,
                channel_premise=channel_premise, prompts_cfg=prompts_cfg
            )
            if ok:
                raw_scenes[0] = revised_sc
                audit_log["editorial_revisions_succeeded"] += 1
                print(f"   ✅ {rev_msg}")
            else:
                raw_scenes[0] = revised_sc
                audit_log["unresolved_failures"] += 1
                audit_log["hook_status"] = f"failed: {wall_reason}"
                print(f"   🚫 Hook revision failed: {rev_msg}")

    # 2. Audit scenes 2 through N-1 (Middle compilation thoughts)
    for i in range(1, len(raw_scenes) - 1):
        scene = raw_scenes[i]
        text = scene.get("spoken_text", "")
        failed_audit = False

        # A. Trivia Check: strip cheap openers or revise
        f_passed, f_reason = PureShowerThoughtAuditor.audit_thought(text)
        if not f_passed:
            audit_log["trivia_fact_failures"] += 1
            print(f"   Scene {i+1}: 🚫 {f_reason}")
            cleaned_text = PureShowerThoughtAuditor.clean_opener(text)
            p_check, _ = PureShowerThoughtAuditor.audit_thought(cleaned_text)
            if p_check and cleaned_text.strip():
                print(f"   ✅ Cleaned opener to preserve narrative flow: '{cleaned_text[:60]}...'")
                raw_scenes[i]["spoken_text"] = cleaned_text
                from engine.managers.voice_normalizer import VoiceNormalizer
                raw_scenes[i]["phonetic_text"] = VoiceNormalizer.normalize_text(cleaned_text)
                raw_scenes[i]["_editorial_cleaned"] = True
                text = cleaned_text
            else:
                failed_audit = True
                audit_log["editorial_revisions_attempted"] += 1
                revised_sc, ok, rev_msg = revise_scene_with_llm(
                    scene, f_reason, llm_manager=llm_manager, existing_scenes=raw_scenes[:i],
                    channel_premise=channel_premise, prompts_cfg=prompts_cfg
                )
                if ok:
                    raw_scenes[i] = revised_sc
                    scene = revised_sc
                    text = revised_sc.get("spoken_text", "")
                    audit_log["editorial_revisions_succeeded"] += 1
                    print(f"   ✅ {rev_msg}")
                else:
                    raw_scenes[i] = revised_sc
                    scene = revised_sc
                    audit_log["unresolved_failures"] += 1
                    print(f"   🚫 Scene {i+1} revision failed: {rev_msg}")

        # B. Wall Test (ban solipsism & fake-deep nihilism)
        w_passed, w_reason = CynicalHumanAuditor.audit_text(text)
        if not w_passed:
            failed_audit = True
            audit_log["wall_test_failures"] += 1
            print(f"   Scene {i+1}: 🚫 {w_reason}")
            audit_log["editorial_revisions_attempted"] += 1
            revised_sc, ok, rev_msg = revise_scene_with_llm(
                scene, w_reason, llm_manager=llm_manager, existing_scenes=raw_scenes[:i],
                channel_premise=channel_premise, prompts_cfg=prompts_cfg
            )
            if ok:
                raw_scenes[i] = revised_sc
                scene = revised_sc
                text = revised_sc.get("spoken_text", "")
                audit_log["editorial_revisions_succeeded"] += 1
                print(f"   ✅ {rev_msg}")
            else:
                raw_scenes[i] = revised_sc
                scene = revised_sc
                audit_log["unresolved_failures"] += 1
                print(f"   🚫 Scene {i+1} revision failed: {rev_msg}")

        # C. Completeness Check (ban dangling connector endings)
        c_passed, c_reason = ThoughtCompletenessSkill.audit_completeness(text, is_final_scene=False)
        if not c_passed:
            failed_audit = True
            print(f"   Scene {i+1}: 🚫 {c_reason}")
            audit_log["editorial_revisions_attempted"] += 1
            revised_sc, ok, rev_msg = revise_scene_with_llm(
                scene, c_reason, llm_manager=llm_manager, existing_scenes=raw_scenes[:i],
                channel_premise=channel_premise, prompts_cfg=prompts_cfg
            )
            if ok:
                raw_scenes[i] = revised_sc
                scene = revised_sc
                text = revised_sc.get("spoken_text", "")
                audit_log["editorial_revisions_succeeded"] += 1
                print(f"   ✅ {rev_msg}")
            else:
                raw_scenes[i] = revised_sc
                scene = revised_sc
                audit_log["unresolved_failures"] += 1
                print(f"   🚫 Scene {i+1} revision failed: {rev_msg}")

        # D. Semantic Deduplication Check against all preceding scenes
        is_dup, dup_reason = SemanticDeduplicationSkill.is_duplicate(text, raw_scenes[:i])
        if is_dup:
            failed_audit = True
            audit_log["semantic_duplicate_failures"] += 1
            print(f"   Scene {i+1}: 🚫 Semantic Duplicate ({dup_reason})")
            audit_log["editorial_revisions_attempted"] += 1
            revised_sc, ok, rev_msg = revise_scene_with_llm(
                scene, f"Concept duplicates preceding scene: {dup_reason}",
                llm_manager=llm_manager, existing_scenes=raw_scenes[:i],
                channel_premise=channel_premise, prompts_cfg=prompts_cfg
            )
            if ok:
                raw_scenes[i] = revised_sc
                scene = revised_sc
                text = revised_sc.get("spoken_text", "")
                audit_log["editorial_revisions_succeeded"] += 1
                print(f"   ✅ {rev_msg}")
            else:
                raw_scenes[i] = revised_sc
                scene = revised_sc
                audit_log["unresolved_failures"] += 1
                print(f"   🚫 Scene {i+1} revision failed: {rev_msg}")

        if not failed_audit:
            print(f"   ✅ Scene {i+1}: PASSED all quality audits")

    # 3. Ending / Closer Auditor: Validate Scene N against Scene 1 hook
    if len(raw_scenes) >= 2:
        ending_scene = raw_scenes[-1]
        ending_text = ending_scene.get("spoken_text", "")

        # A. Check Wall Test on Ending Scene
        wall_passed, wall_reason = CynicalHumanAuditor.audit_text(ending_text)
        if not wall_passed:
            audit_log["wall_test_failures"] += 1
            print(f"   Scene {len(raw_scenes)} (Ending): 🚫 {wall_reason}")
            audit_log["editorial_revisions_attempted"] += 1
            revised_sc, ok, rev_msg = revise_scene_with_llm(
                ending_scene, wall_reason, llm_manager=llm_manager,
                existing_scenes=raw_scenes[:-1], is_final_scene=True,
                channel_premise=channel_premise, prompts_cfg=prompts_cfg
            )
            if ok:
                raw_scenes[-1] = revised_sc
                ending_scene = revised_sc
                audit_log["editorial_revisions_succeeded"] += 1
                print(f"   ✅ {rev_msg}")
            else:
                raw_scenes[-1] = revised_sc
                audit_log["unresolved_failures"] += 1
                print(f"   🚫 Ending revision failed: {rev_msg}")

        # B. Check Ending Intent & Loop Validity
        loop_passed, loop_reason = LoopAuditorSkill.audit_loop(
            loop_text=raw_scenes[-1].get("spoken_text", ""),
            hook_text=raw_scenes[0].get("spoken_text", ""),
            ending_type=raw_scenes[-1].get("ending_type")
        )
        audit_log["loop_status"] = "passed" if loop_passed else f"failed: {loop_reason}"
        if not loop_passed:
            print(f"   ℹ️ Scene {len(raw_scenes)} (Ending): {loop_reason} -> Preserving standalone ending.")
            raw_scenes[-1] = LoopAuditorSkill.sanitize_loop(
                scene=raw_scenes[-1],
                hook_text=raw_scenes[0].get("spoken_text", "")
            )
        else:
            print(f"   ✅ Scene {len(raw_scenes)} (Ending Payoff): {loop_reason}")

    # 4. Title Truth-in-Packaging + Deduplication
    original_title = seo_data.get("title", "")
    aligned_title = TitleScriptAlignmentSkill.align_title(
        title=original_title,
        scenes=raw_scenes,
        upload_history_titles=upload_history_titles,
        topic=topic
    )
    if aligned_title != original_title:
        seo_data = dict(seo_data)
        seo_data["title"] = aligned_title
        audit_log["title_status"] = f"realigned from '{original_title[:40]}' to '{aligned_title[:40]}'"
    else:
        audit_log["title_status"] = "passed"
    audit_log["final_title"] = seo_data.get("title", "")

    # Synchronize wall_test_replacements for LLMQualityTracker compatibility
    audit_log["wall_test_replacements"] = audit_log["editorial_revisions_succeeded"]

    # Check for unresolvable rejections
    rejected_count = sum(1 for s in raw_scenes if s.get("_editorial_rejected"))
    if rejected_count > 0 or audit_log["unresolved_failures"] > 0:
        audit_log["status"] = "rejected"
        audit_log["unresolved_failures"] = max(rejected_count, audit_log["unresolved_failures"])

    total_issues = (
        audit_log["wall_test_failures"] +
        audit_log["trivia_fact_failures"] +
        audit_log["semantic_duplicate_failures"]
    )
    print(f"\n📋 [EDITORIAL CRITIC] Audit complete: {total_issues} issue(s) detected, {audit_log['editorial_revisions_succeeded']} revision(s), status={audit_log['status']}.")
    print(f"   Title: {audit_log['title_status']}")
    print(f"   Final title: '{audit_log['final_title']}'")

    return raw_scenes, seo_data, audit_log


class EditorialCritic:
    """
    Editorial Critic Suite for YouTube Shorts scripts:
    Assesses the quality of each thought and its role in the Short without enforcing
    formulaic writing, homogenizing strong ideas, or forcing recognizable AI patterns.

    Evaluates:
    - Originality, specificity, and substance (observation, insight, fact, punchline).
    - Clarity when heard aloud and natural spoken rhythm.
    - Curiosity, humor, or emotional resonance appropriate to the specific thought.
    - Logical coherence and payoff quality.
    - Script-level deduplication and redundancy prevention.
    - Separation of concerns: empirical claim verification belongs to ClaimInspector;
      the critic focuses on editorial substance and presentation.
    """

    @staticmethod
    def critique_and_refine_script(
        raw_scenes: List[Dict[str, Any]],
        seo_data: Dict[str, Any],
        topic: str,
        llm_manager: Optional[Any] = None,
        channel_premise: str = "",
        prompts_cfg: Optional[Dict[str, Any]] = None
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, Any]]:
        """
        Audits and refines an entire multi-scene script spec using revision-first editing.
        Strong existing lines that already pass audits remain completely unchanged.
        """
        return audit_and_refine_spec(
            raw_scenes=raw_scenes,
            seo_data=seo_data,
            topic=topic,
            llm_manager=llm_manager,
            channel_premise=channel_premise,
            prompts_cfg=prompts_cfg
        )

    @staticmethod
    def audit_and_refine_spec(
        raw_scenes: List[Dict[str, Any]],
        seo_data: Dict[str, Any],
        topic: str,
        llm_manager: Optional[Any] = None,
        channel_premise: str = "",
        prompts_cfg: Optional[Dict[str, Any]] = None
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, Any]]:
        """
        Audits and refines an entire multi-scene script spec using revision-first editing.
        Exposes audit_and_refine_spec on EditorialCritic for interface compatibility.
        """
        return audit_and_refine_spec(
            raw_scenes=raw_scenes,
            seo_data=seo_data,
            topic=topic,
            llm_manager=llm_manager,
            channel_premise=channel_premise,
            prompts_cfg=prompts_cfg
        )

    @staticmethod
    def audit_and_refine_scene(
        scene: Dict[str, Any],
        defect_reason: str,
        llm_manager: Optional[Any] = None,
        existing_scenes: Optional[List[Dict[str, Any]]] = None,
        is_final_scene: bool = False,
        is_hook_scene: bool = False,
        max_attempts: int = 2,
        channel_premise: str = "",
        prompts_cfg: Optional[Dict[str, Any]] = None
    ) -> Tuple[Dict[str, Any], bool, str]:
        """
        Audits and repairs an individual scene via LLM revision, making the smallest
        effective repair to fix the defect while strictly preserving the underlying idea.
        """
        return revise_scene_with_llm(
            scene=scene,
            failure_reason=defect_reason,
            llm_manager=llm_manager,
            existing_scenes=existing_scenes,
            is_final_scene=is_final_scene,
            is_hook_scene=is_hook_scene,
            max_attempts=max_attempts,
            channel_premise=channel_premise,
            prompts_cfg=prompts_cfg
        )


# Module-level static aliases for backwards compatibility
audit_and_refine_scene = EditorialCritic.audit_and_refine_scene
critique_and_refine_script = EditorialCritic.critique_and_refine_script
