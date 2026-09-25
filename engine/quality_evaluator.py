# engine/quality_evaluator.py — Production-Grade Multi-Gate Quality Evaluator
"""
Deterministic Multi-Gate Quality Evaluator for Model Discovery & Diagnostics.
Directly replicates and enforces the production pipeline's mathematical quality gates
(word count calibration, sentence closure, viral hook archetypes, circular loop continuity,
and CTR packaging) to generate empirical 0.0–10.0 quality scores for LLM candidates.
"""

import re
from typing import Dict, Any, Optional, List, Tuple


class QualityEvaluator:
    """
    Evaluates generated scripts and SEO metadata against production viral standards.
    """

    # ── Scriptwriting Quality Gates ───────────────────────────────────────────
    _GOLDEN_WORD_MIN = 85
    _GOLDEN_WORD_MAX = 125
    _ACCEPTABLE_WORD_MIN = 70
    _ACCEPTABLE_WORD_MAX = 135

    _BANNED_CLICHES = [
        "delve", "testament", "tapestry", "beacon", "in conclusion",
        "game-changer", "mind-blowing", "you won't believe",
        "stranger than anything you'd expect", "changes how you see",
        "changes everything you know", "without further ado"
    ]

    _DANGLING_FRAGMENTS = {
        "it was", "there was", "such as", "leading to", "resulting in", "and then",
        "once again", "proving that", "because", "such that", "which is", "so that",
        "and", "but", "or", "so", "as", "while", "that", "which"
    }

    _HOOK_ARCHETYPES = [
        (r'\b(zero|no|never|cannot|impossible|defies?|breaks?|without)\b', "Impossible Juxtaposition"),
        (r'\b(secret|hidden|nobody|never told|they don\'t|government|military)\b', "Forbidden Secret"),
        (r'\b(\d[\d,\.]*\s*(billion|million|trillion|years?|times?|percent|%)|every|entire|all of|outweigh|smallest|oldest|fastest|largest)\b', "Extreme Scale"),
        (r'\b(real(ly)? reason|why your|how your|secretly|silently|every (night|day|second|year))\b', "Hidden Mechanism"),
        (r'\b(kill|die|dead|never do|survive|danger|must not|lethal|fatal|kills? you|stay alive)\b', "Survival Instinct"),
        (r'\b(chose|sacrifice|abandon|despite|was right|lied to|saved \d+|by abandon)\b', "Moral Dilemma"),
        (r'\b(color|colour|frequency|no (word|name)|nameless|humans (can|cannot)|has no word)\b', "Forbidden Knowledge"),
        (r'\b(your body|you (are|were|have)|every human|nobody (knows|tells)|you never|we all)\b', "Identity Challenge"),
    ]

    _CONNECTIVE_LOOP_CUES = [
        "and that is why", "and that's why", "which is why", "which means",
        "that is because", "that's because", "so whenever you", "and it all leads back to",
        "and it all began when", "leading directly to", "and it proves that", "meaning that",
        "so the next time you see", "because in the end", "bringing us right back to"
    ]

    @classmethod
    def audit_script(cls, script_data: Optional[Dict[str, Any]], raw_text: str = "") -> Dict[str, Any]:
        """
        Audits a generated script against 5 deterministic quality gates:
        1. Scene Count & Structure (Target: 4 scenes)
        2. Word Count Calibration (Golden: 85-125 words)
        3. Deterministic Sentence Closure (No trailing punctuation or dangling clauses)
        4. Opening Hook Strength & Archetype Matching (0-10)
        5. Circular Loop Continuity (0-10)
        """
        feedback: List[str] = []
        scenes = []
        if isinstance(script_data, dict):
            scenes = script_data.get("scenes", [])

        scene_count = len(scenes)

        # Reconstruct narrative text
        narration_parts = []
        for s in scenes:
            if isinstance(s, dict):
                text = s.get("text") or s.get("narration") or ""
                if text:
                    narration_parts.append(str(text).strip())
            elif isinstance(s, str):
                narration_parts.append(s.strip())

        full_narr = " ".join(narration_parts).strip()
        if not full_narr and raw_text:
            # Fallback text if dict had empty scenes
            clean_raw = re.sub(r'```.*?```', '', raw_text, flags=re.DOTALL).strip()
            full_narr = clean_raw

        word_count = len(full_narr.split()) if full_narr else 0

        # Gate 1: Scene Count (Weight: 2.0)
        if scene_count == 4:
            scene_pts = 2.0
            feedback.append("✅ 4 Scenes (Ideal)")
        elif scene_count in (3, 5):
            scene_pts = 1.3
            feedback.append(f"⚠️ {scene_count} Scenes (Tolerable)")
        elif scene_count > 0:
            scene_pts = 0.6
            feedback.append(f"❌ {scene_count} Scenes (Suboptimal)")
        else:
            scene_pts = 0.2
            feedback.append("❌ Missing Scene Array")

        # Gate 2: Word Count Calibration (Weight: 2.5)
        if cls._GOLDEN_WORD_MIN <= word_count <= cls._GOLDEN_WORD_MAX:
            word_pts = 2.5
            feedback.append(f"✅ {word_count} Words (Golden Range 85-125)")
        elif cls._ACCEPTABLE_WORD_MIN <= word_count <= cls._ACCEPTABLE_WORD_MAX:
            word_pts = 1.8
            feedback.append(f"⚠️ {word_count} Words (Acceptable Buffer)")
        elif word_count > cls._ACCEPTABLE_WORD_MAX:
            word_pts = 0.8
            feedback.append(f"❌ {word_count} Words (Too Long)")
        elif word_count > 30:
            word_pts = 0.6
            feedback.append(f"❌ {word_count} Words (Too Short)")
        else:
            word_pts = 0.0
            feedback.append(f"❌ {word_count} Words (Incomplete)")

        # Gate 3: Deterministic Sentence Closure (Weight: 2.0)
        closure_passed = False
        if full_narr:
            trimmed = full_narr.strip()
            if trimmed.endswith(",") or trimmed.endswith(";") or trimmed.endswith(":"):
                closure_pts = 0.0
                feedback.append(f"❌ Trailing Punctuation ('{trimmed[-1]}')")
            else:
                clean_end = re.sub(r'["\'”’\.!?]+$', '', trimmed).strip().lower()
                last_words = clean_end.split()
                last_1 = last_words[-1] if last_words else ""
                last_2 = " ".join(last_words[-2:]) if len(last_words) >= 2 else ""

                if last_1 in cls._DANGLING_FRAGMENTS or last_2 in cls._DANGLING_FRAGMENTS:
                    closure_pts = 0.3
                    feedback.append(f"❌ Dangling Fragment ('{last_2 or last_1}')")
                elif trimmed[-1] in {'.', '!', '?'}:
                    closure_passed = True
                    closure_pts = 2.0
                    feedback.append("✅ Clean Sentence Closure")
                else:
                    closure_passed = True
                    closure_pts = 1.5
                    feedback.append("⚠️ Soft Closure")
        else:
            closure_pts = 0.0
            feedback.append("❌ Empty Narration")

        # Gate 4: Opening Hook Strength (Weight: 2.0)
        sentences = [s.strip() for s in re.split(r'[.!?]+', full_narr) if s.strip()]
        first_sentence = sentences[0] if sentences else ""
        hook_score = cls._score_hook(first_sentence)
        hook_pts = round((hook_score / 10.0) * 2.0, 2)
        feedback.append(f"🎯 Hook Score: {hook_score}/10")

        # Gate 5: Circular Loop Continuity (Weight: 1.5)
        last_sentence = sentences[-1] if sentences else ""
        loop_score = cls._score_loop(first_sentence, last_sentence)
        loop_pts = round((loop_score / 10.0) * 1.5, 2)
        feedback.append(f"🔄 Loop Score: {loop_score}/10")

        # Penalty for formulaic clichés
        cliche_deduction = 0.0
        full_lower = full_narr.lower()
        found_cliches = [c for c in cls._BANNED_CLICHES if c in full_lower]
        if found_cliches:
            cliche_deduction = min(1.0, len(found_cliches) * 0.4)
            feedback.append(f"⚠️ Clichés: {', '.join(found_cliches[:2])}")

        total_score = max(0.5, min(10.0, round(scene_pts + word_pts + closure_pts + hook_pts + loop_pts - cliche_deduction, 2)))

        return {
            "score": total_score,
            "word_count": word_count,
            "scene_count": scene_count,
            "closure_passed": closure_passed,
            "hook_score": hook_score,
            "loop_score": loop_score,
            "feedback": feedback
        }

    @classmethod
    def audit_seo(cls, seo_data: Optional[Dict[str, Any]], raw_text: str = "") -> Dict[str, Any]:
        """
        Audits generated YouTube Shorts SEO metadata against 4 quality gates:
        1. Schema Validity (title, description, tags)
        2. Title CTR Packaging & Curiosity (<60 chars, proven archetype)
        3. Tag Count & Depth (5-15 tags)
        4. Output Purity (no markdown leaks, pure JSON structure)
        """
        feedback: List[str] = []
        is_dict = isinstance(seo_data, dict)

        title = str(seo_data.get("title", "") if is_dict else "").strip()
        tags = seo_data.get("tags", []) if is_dict else []
        desc = str(seo_data.get("description", "") if is_dict else "").strip()

        # Gate 1: Schema Compliance (Weight: 3.0)
        has_title = bool(title)
        has_tags = isinstance(tags, (list, tuple)) and len(tags) > 0
        has_desc = bool(desc)

        schema_score = 0.0
        if has_title:
            schema_score += 1.5
        if has_tags:
            schema_score += 1.0
        if has_desc:
            schema_score += 0.5
        feedback.append(f"{'✅' if schema_score >= 2.5 else '⚠️'} Schema Validity: {schema_score:.1f}/3.0")

        # Gate 2: Title Length & CTR Packaging (Weight: 3.5)
        clean_title = re.sub(r'#shorts?\s*', '', title, flags=re.IGNORECASE).strip()
        t_len = len(clean_title)
        t_pts = 0.0

        if 15 <= t_len <= 60:
            t_pts += 2.0
            feedback.append(f"✅ Title Length: {t_len} chars (≤60)")
        elif 60 < t_len <= 80:
            t_pts += 1.2
            feedback.append(f"⚠️ Title Length: {t_len} chars (60-80)")
        elif t_len > 80:
            t_pts += 0.5
            feedback.append(f"❌ Title Length: {t_len} chars (>80)")
        else:
            t_pts += 0.2
            feedback.append("❌ Title Missing / Too Short")

        # Curiosity Archetype Match
        matched_archetype = None
        for pattern, arch_name in cls._HOOK_ARCHETYPES:
            if re.search(pattern, clean_title, re.IGNORECASE):
                matched_archetype = arch_name
                break

        if matched_archetype:
            t_pts += 1.5
            feedback.append(f"🎯 Archetype: {matched_archetype}")
        elif has_title:
            t_pts += 0.8
            feedback.append("⚠️ Standard Title")

        # Gate 3: Tags Volume & Depth (Weight: 2.0)
        tag_count = len(tags) if isinstance(tags, (list, tuple)) else 0
        if 5 <= tag_count <= 15:
            tag_pts = 2.0
            feedback.append(f"✅ {tag_count} Tags (Target: 5-15)")
        elif tag_count > 15:
            tag_pts = 1.4
            feedback.append(f"⚠️ {tag_count} Tags (Slightly Overloaded)")
        elif 1 <= tag_count < 5:
            tag_pts = 1.0
            feedback.append(f"⚠️ {tag_count} Tags (Minimal)")
        else:
            tag_pts = 0.0
            feedback.append("❌ Zero Tags")

        # Gate 4: Output Purity (Weight: 1.5)
        purity_pts = 1.5
        if raw_text:
            if "```" in raw_text:
                purity_pts -= 0.5
            if not raw_text.strip().startswith("{"):
                purity_pts -= 0.5
        purity_pts = max(0.5, purity_pts)

        total_score = max(0.5, min(10.0, round(schema_score + t_pts + tag_pts + purity_pts, 2)))

        return {
            "score": total_score,
            "title": title,
            "title_length": t_len,
            "tag_count": tag_count,
            "archetype": matched_archetype or "None",
            "feedback": feedback
        }

    @classmethod
    def _score_hook(cls, hook_sentence: str) -> float:
        """Scores opening hook on 0-10 scale based on viral psychology triggers."""
        if not hook_sentence:
            return 3.0
        score = 4.0
        h_lower = hook_sentence.lower()
        words = hook_sentence.split()

        # Check viral curiosity archetype
        for pattern, _ in cls._HOOK_ARCHETYPES:
            if re.search(pattern, h_lower):
                score += 2.5
                break

        # Punchy word count (8 to 18 words)
        if 8 <= len(words) <= 18:
            score += 1.5
        elif len(words) < 6:
            score -= 1.0

        # Numbers or proper entities (+1.0)
        if re.search(r'\b\d+\b', hook_sentence):
            score += 1.0

        # Challenge / Curiosity terms
        if any(w in h_lower for w in ["never", "impossible", "nobody", "secret", "why you", "stop"]):
            score += 1.0

        return max(1.0, min(10.0, round(score, 1)))

    @classmethod
    def _score_loop(cls, hook: str, ending: str) -> float:
        """Scores loop seamlessness on 0-10 scale."""
        if not ending or not hook:
            return 4.0
        score = 5.0
        e_lower = ending.lower()

        # Connective bridge cues
        if any(cue in e_lower for cue in cls._CONNECTIVE_LOOP_CUES):
            score += 3.0

        # Penalize traditional sign-offs
        if any(banned in e_lower for banned in ["subscribe", "thanks for watching", "like and follow", "comment below"]):
            score -= 4.0

        # Grammatical complement check
        if ending.endswith("..."):
            score -= 1.0

        return max(1.0, min(10.0, round(score, 1)))
