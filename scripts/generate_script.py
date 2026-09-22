# scripts/generate_script.py
import os
import json
import yaml
import re
import traceback
import random
from scripts.quota_manager import quota_manager
from engine.database import db
from engine.config_manager import config_manager
from engine.context import ctx
from engine.logger import logger

_WORDS_PER_SECOND_TTS = 143 / 60.0
# EdgeTTS/Kokoro: 90 words = ~40s, 125 words = ~53s. 
_MAX_VIDEO_SECONDS = 55.0
_MIN_WORD_FLOOR = 80       # Minimum 80 words ensures Short is at least 33.5s (monetization & retention sweet spot)
_ABSOLUTE_WORD_CEILING = 125  # Upper bound prevents exceeding 55s ceiling


# ── Speech timing constants ────────────────────────────────────────────────
# Punctuation pause budgets (milliseconds, empirically measured from TTS output)
_PAUSE_COMMA_MS       = 80    # Brief breath at comma
_PAUSE_PERIOD_MS      = 200   # Sentence-end stop
_PAUSE_QUESTION_MS    = 250   # Rising intonation + stop
_PAUSE_EXCLAMATION_MS = 180   # Punchy stop
_PAUSE_EMDASH_MS      = 150   # Narrative em-dash pause
_PAUSE_ELLIPSIS_MS    = 300   # Trailing ellipsis drag
_TTS_TARGET_MIN_SEC   = 38.0  # Soft floor — warn if below
_TTS_TARGET_MAX_SEC   = 57.0  # Soft ceiling — warn if above


# ── Hook strength archetype patterns ──────────────────────────────────────
# These patterns map to the 8 research-backed viral hook archetypes
_HOOK_ARCHETYPE_PATTERNS = [
    # Impossible Juxtaposition
    (r'\b(zero|no|never|cannot|can\'t|impossible|defies?|breaks?)\b', "Impossible Juxtaposition"),
    # Forbidden Secret
    (r'\b(secret|hidden|nobody|never told|government|military|they don\'t)\b', "Forbidden Secret"),
    # Extreme Scale
    (r'\b(\d+[\.,]?\d*\s*(billion|million|trillion|thousand)|every|all|entire|outweigh|larger|smallest|oldest|fastest)\b', "Extreme Scale"),
    # Hidden Mechanism
    (r'\b(actually|real(ly)? reason|why your|how your|secretly|silently|every night|every day)\b', "Hidden Mechanism"),
    # Survival Instinct
    (r'\b(kill|die|dead|survive|danger|never do|must not|lethal|fatal|kills? you)\b', "Survival Instinct"),
    # Moral Dilemma
    (r'\b(chose|sacrifice|abandon|save \d+|by abandon|despite|was right|lied to)\b', "Moral Dilemma"),
    # Forbidden Knowledge
    (r'\b(color|colour|frequency|no (word|name)|nameless|unnamed|humans (can|cannot))\b', "Forbidden Knowledge"),
    # Identity Challenge
    (r'\b(your body|you (are|were|have)|every human|nobody knows|you never)\b', "Identity Challenge"),
]

# Banned hook openers (clichéd, low-performing)
_BANNED_HOOK_OPENERS = [
    r'^did you know',
    r'^have you ever wonder',
    r'^in this video',
    r'^today (we|i|you)',
    r'^welcome to',
    r'^let me tell you',
    r'^so (you|we|i)',
    r'^discover',
    r'^learn (about|how|why)',
]


def estimate_speech_timing(text: str) -> dict:
    """
    Gate 8 — Speech Timing Estimator.

    Estimates TTS duration using syllable density multiplier + punctuation pause budget.
    More accurate than flat WPM because polysyllabic words slow TTS output and
    punctuation marks add measurable silence in all TTS engines (EdgeTTS, Kokoro).

    Returns:
        dict with keys: estimated_seconds, word_count, syllable_count,
                         pause_budget_ms, is_within_target, warning_message
    """
    words = text.split()
    word_count = len(words)

    # ── Syllable count (pure Python, no NLTK) ─────────────────────────────
    # Heuristic: count vowel groups per word, clamp min to 1
    def _count_syllables(word: str) -> int:
        word = word.lower().strip(".,!?;:'\"-")
        if not word:
            return 1
        vowels = re.findall(r'[aeiou]+', word)
        count = len(vowels)
        # Silent 'e' at end: "make" → 1 syllable not 2
        if word.endswith('e') and count > 1:
            count -= 1
        # Words ending in 'le' after consonant add a syllable: "table" → 2
        if re.search(r'[^aeiou]le$', word):
            count += 1
        return max(1, count)

    syllable_count = sum(_count_syllables(w) for w in words)

    # ── Syllable density multiplier ────────────────────────────────────────
    # Average syllables/word in conversational English ≈ 1.5
    # Polysyllabic scripts (>1.7 avg) slow TTS by ~15-20%
    avg_syllables = syllable_count / max(word_count, 1)
    syllable_multiplier = 1.0
    if avg_syllables > 1.7:
        syllable_multiplier = 1.15   # +15% for dense vocabulary
    elif avg_syllables > 2.0:
        syllable_multiplier = 1.25   # +25% for academic/complex prose

    # ── Base duration from word rate ─────────────────────────────────────
    base_seconds = (word_count / _WORDS_PER_SECOND_TTS) * syllable_multiplier

    # ── Punctuation pause budget ──────────────────────────────────────────
    pause_ms = 0
    pause_ms += text.count(',')  * _PAUSE_COMMA_MS
    pause_ms += text.count('.')  * _PAUSE_PERIOD_MS
    pause_ms += text.count('?')  * _PAUSE_QUESTION_MS
    pause_ms += text.count('!')  * _PAUSE_EXCLAMATION_MS
    pause_ms += text.count('—')  * _PAUSE_EMDASH_MS
    pause_ms += text.count('–')  * _PAUSE_EMDASH_MS
    pause_ms += text.count('...') * _PAUSE_ELLIPSIS_MS

    estimated_seconds = base_seconds + (pause_ms / 1000.0)

    # ── Verdict ────────────────────────────────────────────────────────────
    warning = ""
    if estimated_seconds < _TTS_TARGET_MIN_SEC:
        warning = (
            f"⏱️ Estimated {estimated_seconds:.1f}s — below 38s target. "
            f"Script may feel rushed. Consider expanding Scene 2 or 3."
        )
    elif estimated_seconds > _TTS_TARGET_MAX_SEC:
        warning = (
            f"⏱️ Estimated {estimated_seconds:.1f}s — above 57s ceiling. "
            f"Shorten sentences or remove a build beat."
        )

    return {
        "estimated_seconds": round(estimated_seconds, 1),
        "word_count": word_count,
        "syllable_count": syllable_count,
        "avg_syllables_per_word": round(avg_syllables, 2),
        "pause_budget_ms": pause_ms,
        "is_within_target": not bool(warning),
        "warning_message": warning,
    }


def audit_readability_grade(text: str) -> dict:
    """
    Gate 9 — Flesch-Kincaid Readability Auditor.

    YouTube Shorts viewers are on mobile, watching fast visuals. Scripts that read
    above 8th-grade level cause cognitive overload and swipe-away.

    Formula: FK_grade = 0.39*(words/sentences) + 11.8*(syllables/words) - 15.59
    Pure Python — zero external dependencies.

    Returns:
        dict with keys: grade_level, is_acceptable, top_complex_words, hint_message
    """
    # ── Count sentences ───────────────────────────────────────────────────
    sentence_endings = re.findall(r'[.!?]+', text)
    sentence_count = max(len(sentence_endings), 1)

    # ── Count words ───────────────────────────────────────────────────────
    words = [w.strip(".,!?;:'\"-—") for w in text.split() if w.strip(".,!?;:'\"-—")]
    word_count = max(len(words), 1)

    # ── Count syllables (reuse estimate_speech_timing's approach) ────────
    def _syllables(word: str) -> int:
        word = word.lower()
        if not word:
            return 1
        vowels = re.findall(r'[aeiou]+', word)
        count = len(vowels)
        if word.endswith('e') and count > 1:
            count -= 1
        if re.search(r'[^aeiou]le$', word):
            count += 1
        return max(1, count)

    syllable_count = sum(_syllables(w) for w in words)

    # ── Flesch-Kincaid Grade Level ────────────────────────────────────────
    asl = word_count / sentence_count        # Average Sentence Length
    asw = syllable_count / word_count        # Average Syllables per Word
    fk_grade = 0.39 * asl + 11.8 * asw - 15.59

    # ── Find top polysyllabic offenders (>3 syllables) ───────────────────
    polysyllabic = sorted(
        [(w, _syllables(w)) for w in set(words) if _syllables(w) >= 3],
        key=lambda x: x[1],
        reverse=True
    )[:5]

    hint = ""
    if fk_grade > 8.0:
        offender_list = ", ".join([f"'{w}' ({s} syl)" for w, s in polysyllabic])
        hint = (
            f"Grade {fk_grade:.1f} exceeds 8th-grade target. "
            f"Simplify these polysyllabic words: {offender_list or 'shorten sentences'}."
        )

    return {
        "grade_level": round(fk_grade, 1),
        "is_acceptable": fk_grade <= 8.0,
        "avg_sentence_length": round(asl, 1),
        "avg_syllables_per_word": round(asw, 2),
        "top_complex_words": polysyllabic,
        "hint_message": hint,
    }


def score_hook_strength(scene1_text: str) -> dict:
    """
    Gate 10 — Hook Strength Scorer.

    Scores the opening sentence of Scene 1 against 8 proven viral hook archetypes.
    A weak hook is the #1 cause of immediate swipe-away on YouTube Shorts.

    Scoring (0-10):
    - Starts with a banned opener (-3 points hard deduction)
    - Matches at least one of the 8 archetypes (+3 points)
    - First word is a strong noun or verb (not "A"/"The"/"In"/"So") (+1 point)
    - Contains a specific number or proper noun (+1 point)
    - Word count 8-18 (punchy, not too short or rambling) (+2 points)
    - Contains a question mark or direct challenge (+1 point)
    - No banned AI clichés in hook (+2 points base)

    Returns:
        dict with keys: score, archetype_matched, is_strong, feedback
    """
    # Use only the first sentence of scene 1
    first_sentence_match = re.split(r'[.!?]', scene1_text.strip())
    hook = first_sentence_match[0].strip() if first_sentence_match else scene1_text.strip()
    hook_lower = hook.lower()
    words = hook.split()
    score = 2  # Base score (2 points for no clichés by default)

    # ── Check banned openers (hard deduction) ─────────────────────────────
    is_banned = any(re.search(pat, hook_lower) for pat in _BANNED_HOOK_OPENERS)
    if is_banned:
        score -= 3
        feedback = "⚠️ Hook starts with a banned opener (did you know / in this video / today we)."
    else:
        feedback = ""

    # ── Check archetype match (+3 if matches one of the 8) ───────────────
    archetype_matched = None
    for pattern, name in _HOOK_ARCHETYPE_PATTERNS:
        if re.search(pattern, hook_lower):
            archetype_matched = name
            score += 3
            break

    # ── First word strength (+1 if not weak article/preposition) ─────────
    first_word = words[0].lower() if words else ""
    weak_starters = {"a", "an", "the", "in", "so", "and", "but", "or", "if", "as", "it", "this", "that"}
    if first_word not in weak_starters:
        score += 1

    # ── Contains specific number or proper noun (+1) ──────────────────────
    has_number = bool(re.search(r'\b\d+[\.,]?\d*\b', hook))
    has_proper = bool(re.search(r'\b[A-Z][a-z]{2,}\b', hook))  # Proper noun
    if has_number or has_proper:
        score += 1

    # ── Word count in punchy range 8-18 (+2) ─────────────────────────────
    hook_word_count = len(words)
    if 8 <= hook_word_count <= 18:
        score += 2
    elif hook_word_count < 5:
        score -= 1  # Too short to land impact

    # ── Contains question or direct challenge (+1) ─────────────────────────
    if '?' in hook or any(w in hook_lower for w in ['never', 'impossible', 'nobody', 'no one']):
        score += 1

    # ── Clamp to 0-10 ─────────────────────────────────────────────────────
    score = max(0, min(10, score))

    if not archetype_matched and not feedback:
        feedback = "Hook doesn't clearly match any of the 8 viral archetypes — may feel generic."
    elif archetype_matched:
        feedback = f"Archetype: {archetype_matched}."

    return {
        "score": score,
        "archetype_matched": archetype_matched,
        "is_strong": score >= 6,
        "hook_text": hook[:80],
        "feedback": feedback,
    }


def multi_agent_review(
    script_data: dict,
    topic: str,
    is_fictional: bool = False,
    channel_id: str = "",
    active_niche: str = ""
) -> tuple[dict, dict]:
    """
    Multi-Agent Review: Critic Agent (Always Runs) + Conditional Director Agent (Runs if score < 7.0).

    1. Critic Agent (~150 tokens):
       Audits the script on 4 dimensions: Hook, Circular Loop, Readability, and Scene Balance.
       Returns 1-10 scores and 3 concrete improvement notes.
       
    2. Director Agent (Conditional Rewrite):
       Triggers ONLY if average critic score < 7.0.
       Directly fixes the 3 critique points while enforcing 4 scenes and word boundaries.

    Returns:
       tuple: (final_script_data, critic_scores_dict)
    """
    if not isinstance(script_data, dict) or "scenes" not in script_data:
        return script_data, {}

    scenes = script_data.get("scenes", [])
    if not scenes:
        return script_data, {}

    script_text = " ".join([
        (s.get("text") or s.get("narration") or "") if isinstance(s, dict) else str(s)
        for s in scenes
    ]).strip()

    if not script_text:
        return script_data, {}

    critic_scores = {
        "hook_score": 7,
        "loop_score": 7,
        "readability_score": 7,
        "scene_balance_score": 7,
        "average_score": 7.0,
        "improvement_notes": []
    }

    # ── Step 1: Critic Agent Review ──────────────────────────────────────────
    critic_system = (
        "You are an adversarial YouTube Shorts Retention Critic. "
        "Your task is to ruthlessly critique the draft script for mobile retention, hook voltage, "
        "and circular loop continuity. Reply ONLY with a single valid JSON object."
    )

    critic_prompt = f"""Evaluate this YouTube Shorts script for Topic: "{topic}" (Niche: {active_niche}):

"{script_text}"

Score each category from 1 to 10:
1. hook_score: Does Scene 1 hook immediately within 3 seconds? (1-10)
2. loop_score: Does Scene 4 connect seamlessly back to Scene 1 without sign-offs? (1-10)
3. readability_score: Is it conversational and easy to understand on mobile? (1-10)
4. scene_balance_score: Are words well distributed across scenes without one scene monopolizing? (1-10)

Return JSON matching EXACTLY this schema:
{{
  "hook_score": 8,
  "loop_score": 7,
  "readability_score": 8,
  "scene_balance_score": 7,
  "improvement_notes": [
    "Shorten opening hook to under 15 words for higher punch",
    "Increase narrative tension in Scene 2 build",
    "Ensure final sentence connects grammatically to Scene 1"
  ]
}}"""

    try:
        critic_raw, critic_provider = quota_manager.generate_text(
            critic_prompt,
            task_type="analysis",
            system_prompt=critic_system
        )
        if critic_raw:
            from engine.llm_router import UniversalGreedyJSONParser
            parsed_critic = UniversalGreedyJSONParser.extract_json(critic_raw)
            if isinstance(parsed_critic, dict):
                h = int(parsed_critic.get("hook_score", 7))
                l = int(parsed_critic.get("loop_score", 7))
                r = int(parsed_critic.get("readability_score", 7))
                b = int(parsed_critic.get("scene_balance_score", 7))
                notes = parsed_critic.get("improvement_notes", [])
                if isinstance(notes, list):
                    notes = [str(n) for n in notes if str(n).strip()]

                avg = round((h + l + r + b) / 4.0, 1)
                critic_scores = {
                    "hook_score": h,
                    "loop_score": l,
                    "readability_score": r,
                    "scene_balance_score": b,
                    "average_score": avg,
                    "improvement_notes": notes
                }
                print(f"   🕵️ [CRITIC AGENT] Score: {avg}/10 (Hook: {h}, Loop: {l}, Readability: {r}, Balance: {b}) via {critic_provider}")
                if notes:
                    print(f"      Critique Notes: {'; '.join(notes[:2])}")
    except Exception as c_err:
        logger.debug(f"Critic agent skipped: {c_err}")

    # ── Step 2: Conditional Director Agent Rewrite ───────────────────────────
    avg_score = critic_scores.get("average_score", 7.0)
    if avg_score < 7.0 and critic_scores.get("improvement_notes"):
        print(f"   🎬 [DIRECTOR AGENT] Critic score {avg_score}/10 is below 7.0. Triggering Director rewrite...")
        notes_str = "\n".join([f"- {n}" for n in critic_scores.get("improvement_notes", [])])

        director_system = (
            "You are an Executive YouTube Shorts Director. Rewrite the script to address the "
            "critique while maintaining strict 4-scene structure and word limits (95-120 words total). "
            "Return ONLY valid JSON matching the exact scene schema."
        )

        director_prompt = f"""Original Script Data:
{json.dumps(script_data, indent=2)}

Critic Feedback to Fix:
{notes_str}

Topic: "{topic}" | Niche: "{active_niche}"
Requirements:
1. Address all critic feedback directly.
2. Maintain exactly 4 scenes, 95-120 words total.
3. Preserve voice_actor, glow_color, mood, and caption_style fields.
4. Ensure seamless circular loop from Scene 4 to Scene 1.

Return ONLY the revised JSON matching the original schema."""

        try:
            director_raw, dir_provider = quota_manager.generate_text(
                director_prompt,
                task_type="creative",
                system_prompt=director_system
            )
            if director_raw:
                from engine.llm_router import UniversalGreedyJSONParser
                revised_data = UniversalGreedyJSONParser.extract_json(director_raw)
                if isinstance(revised_data, dict) and "scenes" in revised_data and len(revised_data["scenes"]) >= 3:
                    print(f"   ✅ [DIRECTOR AGENT] Successfully improved script via {dir_provider}")
                    return revised_data, critic_scores
        except Exception as d_err:
            logger.debug(f"Director rewrite failed, keeping original: {d_err}")

    return script_data, critic_scores


def load_config_prompts():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    with open(os.path.join(root_dir, "config", "prompts.yaml"), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)



def extract_scene_data(scene_dict, fallback_topic: str):
    if not isinstance(scene_dict, dict):
        return str(scene_dict), f"Cinematic shot of {fallback_topic}", fallback_topic
    narr   = scene_dict.get("text")         or scene_dict.get("narration") or fallback_topic
    prompt = scene_dict.get("image_prompt") or scene_dict.get("visual")    or f"Cinematic {fallback_topic}"
    query  = scene_dict.get("pexels_query") or fallback_topic
    return narr, prompt, query


def validate_script_quality(script_text: str, prompts_cfg: dict,
                            is_fictional: bool = False,
                            parsed_scenes: list = None) -> tuple[bool, str]:
    """
    Quality gate enforcing YouTube Shorts retention standards:
    1. Word Floor & Ceiling: Strict 85-125 words (40-55s duration).
    2. SentenceClosureCheck: Reject scripts ending in ellipsis, dashes, dangling conjunctions.
    3. AI Cliché & Template Gate: Reject formulaic open-loop clichés and AI filler.
    4. Scene Variation Gate: Reject multi-scene scripts where 1 scene monopolizes >50% words.
    5. Fiction Arc Gate: Require living character protagonist (no inanimate object poetry) and agency.
    6. Factual Integrity Gate: Require concrete mechanism, numbers, or verifiable scientific terminology.
    7. LLM Validation: Require score >= 4/10.
    """
    trimmed = script_text.strip()
    if not trimmed:
        return False, "Script text is empty — retry required."

    words = trimmed.split()
    word_count = len(words)

    # ── 1. HARD WORD FLOOR GATE (40-55s sweet spot) ────────────────────────
    if word_count < _MIN_WORD_FLOOR:
        return False, f"Script under word floor ({word_count} words < {_MIN_WORD_FLOOR} words, target 95-120 words)."

    if word_count > _ABSOLUTE_WORD_CEILING:
        return False, f"Script exceeds word ceiling ({word_count} words > {_ABSOLUTE_WORD_CEILING} words)."

    # ── 2. DETERMINISTIC SENTENCE CLOSURE GATE ─────────────────────────────
    if trimmed.endswith("...") or trimmed.endswith("…") or trimmed.endswith("--") or trimmed.endswith("-"):
        trimmed = re.sub(r'[\.…\-—–\s]+$', '', trimmed) + "."

    if trimmed[-1] not in {'.', '!', '?', '"', "'", '”', '’'}:
        trimmed = trimmed + "."

    clean_end = re.sub(r'["\'”’\.!?]+$', '', trimmed).strip().lower()
    last_words = clean_end.split()
    if last_words:
        last_1 = last_words[-1]
        last_2 = " ".join(last_words[-2:]) if len(last_words) >= 2 else ""
        truncated_fragments = {
            "it was", "there was", "such as", "leading to", "resulting in", "and then"
        }
        if last_1 in truncated_fragments or last_2 in truncated_fragments:
            return False, f"SentenceClosureCheck failed: dangling fragment ('{last_2 or last_1}')."

    # ── 3. AI CLICHÉ & FORMULAIC TEMPLATE GATE ─────────────────────────────
    banned_phrases = [
        "stranger than anything you'd expect",
        "stranger than anything you expect",
        "changes how you see",
        "changes how you view",
        "changes everything you know",
        "you won't believe",
        "delve", "testament", "tapestry", "beacon", "in conclusion",
        "game-changer", "mind-blowing"
    ]
    script_lower = trimmed.lower()
    for bp in banned_phrases:
        if bp in script_lower:
            return False, f"Banned formulaic cliché detected ('{bp}')."

    # ── 4. SCENE VARIATION GATE ────────────────────────────────────────────
    if parsed_scenes and len(parsed_scenes) >= 3:
        for idx, scene in enumerate(parsed_scenes):
            narr = scene[0] if isinstance(scene, (list, tuple)) else str(scene)
            s_words = len(narr.split())
            if (s_words / word_count) > 0.50:
                return False, f"Variation check failed: scene {idx+1} consumes {s_words}/{word_count} words (>50%)."

    # ── 5. FICTION LIVING CHARACTER & ARC GATE ─────────────────────────────
    if is_fictional:
        living_entities = [
            "he", "she", "they", "him", "his", "her", "hers", "them", "their", "who",
            "boy", "girl", "man", "woman", "apprentice", "master", "inventor",
            "keeper", "scout", "pilot", "guardian", "friend", "child", "traveler",
            "warrior", "blacksmith", "sailor", "rival", "creature", "dog", "cat", "bird",
            "hero", "heroine", "villain", "alchemist", "wanderer", "engineer", "architect",
            "monk", "knight", "soldier", "doctor", "scientist", "astronomer", "captain",
            "artisan", "builder", "explorer", "hunter", "stranger", "ruler", "king",
            "queen", "prince", "princess", "wizard", "mage", "witch", "tinker", "scholar",
            "miner", "diver", "clerk", "officer", "fox", "wolf", "dragon", "bear", "lion",
            "tiger", "owl", "beast"
        ]
        has_living = any(re.search(rf"\b{m}\b", script_lower) for m in living_entities) or bool(re.search(r'\b[A-Z][a-z]{2,15}\b', script_text))
        if not has_living:
            return False, "Fiction check failed: lacks living character protagonist (inanimate object poetry is banned)."

        action_verbs = [
            "wants", "wanted", "tries", "tried", "must", "leaps", "leaped", "leapt", "climbs", "climbed",
            "forges", "forged", "forging", "decides", "decided", "steps", "stepped", "discovers",
            "discovered", "finds", "found", "helps", "helped", "meets", "met", "flees", "fled",
            "crosses", "crossed", "searches", "searched", "escapes", "escaped", "saves", "saved",
            "dives", "dove", "slipped", "strapped", "ran", "jumped", "built", "chose", "defied",
            "risked", "confronted", "faced", "learned", "flew", "flies", "wedged", "crafts", "crafted",
            "creates", "created", "rescues", "rescued", "vows", "vowed", "carves", "carved",
            "shapes", "shaped", "protects", "protected", "swore", "turned", "took", "put", "pushed",
            "pulled", "held", "opened", "closed", "looked", "saw", "watched", "heard", "knew", "felt",
            "thought", "spoke", "said", "whispered", "shouted", "called", "walked", "drove", "sailed",
            "rode", "stole", "broke", "fixed", "lost", "won", "fought", "stood", "fell", "sat", "rose",
            "left", "came", "went", "entered", "returned", "placed", "set", "carried", "brought",
            "kept", "gave", "worked", "strove", "struggled", "labored", "painted", "wrote", "cast",
            "drew", "grabbed", "snapped", "lifted", "dropped", "marked", "sealed", "unlocked", "mapped",
            "traced", "ignited", "lit", "bent", "bound", "spent", "dedicated", "pursued", "reached",
            "struck", "clambered", "uncovered", "realized", "demanded", "refused", "insisted",
            "embraced", "clutched", "stared", "ventured", "hoped", "prayed", "wandered", "journeyed",
            "sought", "seized", "raised", "lowered", "gathered", "unlocked", "embarks", "conquers",
            "smuggled", "smuggles", "launched", "launches", "guided", "guides", "secured", "secures",
            "wound", "winds", "piloted", "pilots", "navigated", "navigates", "made", "makes"
        ]
        has_action = any(re.search(rf"\b{a}\b", script_lower) for a in action_verbs)
        if not has_action:
            return False, "Fiction check failed: lacks active protagonist decision/action."

    # ── 6. FACTUAL EMPIRICAL INTEGRITY GATE ────────────────────────────────
    else:
        has_specifics = bool(re.search(r'\b\d+\b', trimmed)) or any(
            k in script_lower for k in [
                "percent", "species", "process", "cells", "temperature", "years",
                "meters", "degrees", "called", "known as", "mechanism", "discovered"
            ]
        )
        if not has_specifics:
            return False, "Factual check failed: lacks concrete numbers, entities, or scientific mechanisms."

    # ── 7. SEAMLESS CIRCULAR LOOP GATE (2026 Playbook) ─────────────────────
    try:
        from engine.loop_engine import loop_engine
        sentences = [s.strip() for s in re.split(r'[.!?]+', trimmed) if s.strip()]
        if len(sentences) >= 2:
            hook_s = sentences[0]
            ending_s = sentences[-1]
            loop_verdict = loop_engine.validate_circular_loop(hook_s, ending_s)
            if not loop_verdict.get("is_valid", True):
                return False, f"Circular loop check failed: {loop_verdict.get('reason')}."
    except Exception as cl_err:
        logger.debug(f"Circular loop check error: {cl_err}")

    # ── 8. SPEECH TIMING GATE ───────────────────────────────────────────────
    try:
        timing = estimate_speech_timing(trimmed)
        if timing["warning_message"]:
            print(f"   ⏱️ [TIMING] {timing['warning_message']}")
            print(f"   ⏱️ [TIMING] Est. {timing['estimated_seconds']}s | {timing['word_count']} words | {timing['syllable_count']} syllables | {timing['pause_budget_ms']}ms pause budget")
        else:
            print(f"   ✅ [TIMING] Est. {timing['estimated_seconds']}s — within 38-57s target.")
    except Exception as t_err:
        logger.debug(f"Speech timing gate error: {t_err}")

    # ── 9. READABILITY GATE (Flesch-Kincaid) ───────────────────────────────
    try:
        readability = audit_readability_grade(trimmed)
        grade = readability["grade_level"]
        if not readability["is_acceptable"]:
            print(f"   ⚠️ [READABILITY] {readability['hint_message']}")
            # Advisory only — does not hard-reject, but adds hint to retry prompt via return reason
        else:
            print(f"   ✅ [READABILITY] Grade {grade} — within 8th-grade target.")
    except Exception as r_err:
        logger.debug(f"Readability gate error: {r_err}")
        readability = {"is_acceptable": True, "grade_level": 0.0, "hint_message": ""}

    # ── 10. HOOK STRENGTH GATE ────────────────────────────────────────────
    try:
        sentences_for_hook = [s.strip() for s in re.split(r'[.!?]+', trimmed) if s.strip()]
        hook_result = score_hook_strength(sentences_for_hook[0] if sentences_for_hook else trimmed)
        hook_score = hook_result["score"]
        hook_archetype = hook_result.get("archetype_matched", "None")
        if hook_result["is_strong"]:
            print(f"   ✅ [HOOK] Score {hook_score}/10 — Archetype: {hook_archetype}. {hook_result['feedback']}")
        else:
            print(f"   ⚠️ [HOOK] Score {hook_score}/10 — {hook_result['feedback']}")
    except Exception as h_err:
        logger.debug(f"Hook strength gate error: {h_err}")
        hook_result = {"score": 0, "is_strong": False, "feedback": "", "archetype_matched": None}

    sys_msg  = prompts_cfg["script_validation"]["system_prompt"]
    user_msg = prompts_cfg["script_validation"]["user_template"].format(
        script_text=script_text
    )

    try:
        raw, _ = quota_manager.generate_text(user_msg, task_type="analysis", system_prompt=sys_msg)
    except Exception:
        return True, "Approved (Validation API call skipped)"

    if not raw:
        return True, "Approved (Empty validator response fail-safe)"

    try:
        numbers = [int(n) for n in re.findall(r'\b\d+\b', raw)]
        if not numbers:
            return True, "Approved (No numeric rating fail-safe)"

        if len(numbers) >= 2 and numbers[-1] == 10 and numbers[-2] <= 10:
            score = numbers[-2]
        else:
            score = numbers[-1]

        passed = score >= 4
        passed = score >= 6
        if not passed:
            return False, f"LLM validator score {score}/10 is below rejection threshold of 4."
            return False, f"LLM validator score {score}/10 is below quality threshold of 6 (Solid & Complete)."
        return True, f"Approved (Score: {score}/10)"

    except Exception:
        return True, "Approved (Validator parsing error fail-safe)"

    except Exception:
        trace = traceback.format_exc()
        logger.error(f"Validation parsing error:\n{trace}")
        return True  # Parsing failure → pass (fail-safe)


# ── Valid mood and caption_style values (must match settings.yaml) ─────────────
_VALID_MOODS = {"neutral", "wonder", "excitement", "horror", "warm"}
_VALID_CAPTION_STYLES = {
    "viral_impact", "cinematic", "horror_tight",
    "minimal_clean", "dynamic_upper", "bold_lower", "storytelling"
}

# ── Mood → default caption_style fallback (used if LLM returns invalid style) ─
_MOOD_TO_CAPTION_STYLE = {
    "neutral":    "minimal_clean",
    "wonder":     "cinematic",
    "excitement": "dynamic_upper",
    "horror":     "horror_tight",
    "warm":       "storytelling",
}

# ── Channel-Tailored Default & Fallback Scripts (40-55s, 85-125 words) ─────────
# Handcrafted reference scripts matching the exact narrative rules of each channel.
_CHANNEL_FALLBACK_SCRIPTS = {
    "CH_01": {
        "text": (
            "Before dawn broke over the city of gears, a young apprentice named Leo slipped into the great clocktower, "
            "clutching a brass wing he spent three months forging in secret. "
            "The master watchmaker stepped from the shadows, warning that testing unapproved machinery over the jagged canyon "
            "meant instant expulsion from the guild. "
            "Suddenly, an iron cable snapped with a deafening screech, sending a runaway passenger cart hurtling toward the cliff edge. "
            "Without hesitating, Leo strapped on his untested gliders and dove off the tower into the howling wind. "
            "He wedged the forged wing directly into the emergency track, the metal screaming as the wheels locked inches from the drop. "
            "Through the smoke, the master offered a silent, proud nod. The apprentice was now a master."
        ),
        "mood": "warm",
        "caption_style": "storytelling",
        "glow_color": "&H00FFD700",
        "voice": "af_bella",
        "pexels": ["clockwork gears antique", "ancient workshop clockmaker", "glider flying mountain canyon", "sunrise over fantasy city"],
        "prompts": [
            "3D Pixar-style digital animation, determined young boy holding mechanical brass wing inside enormous clocktower, glowing dawn sunlight through gears, vertical 9:16",
            "3D animated scene, stern elderly master watchmaker looking down at brave boy apprentice, atmospheric shadows, dramatic lighting, vertical 9:16",
            "3D Pixar render, young boy in leather aviator jacket soaring with brass mechanical wings through misty canyon winds, high speed motion blur, vertical 9:16",
            "3D Pixar style emotional climax, smiling young boy apprentice and smiling master standing beside stopped steam cart, golden sunbeam breakthrough, vertical 9:16",
        ],
    },
    "CH_02": {
        "text": (
            "There is an organism on Earth that has achieved biological immortality, and it lives in the Mediterranean Sea. "
            "The tiny jellyfish Turritopsis dohrnii is only four millimeters wide, but when starved, injured, or facing old age, "
            "it does not die. "
            "Instead, it activates a rare cellular process called transdifferentiation, actively reprogramming its adult muscle "
            "and nerve cells directly back into juvenile stem cells. "
            "Over three days, the entire organism absorbs its own tentacles, sinks to the seafloor as a blob, "
            "and regenerates a brand new polyp colony. "
            "In theory, this cellular reset can repeat indefinitely, making it biologically capable of living forever."
        ),
        "mood": "wonder",
        "caption_style": "cinematic",
        "glow_color": "&H0000D7FF",
        "voice": "am_adam",
        "pexels": ["jellyfish glowing underwater ocean", "macro jellyfish tentacles deep sea", "cellular biology regeneration micro", "underwater marine coral life ocean"],
        "prompts": [
            "Photorealistic 8K cinematic underwater, glowing transparent Turritopsis dohrnii jellyfish pulsing in deep blue ocean abyss, bioluminescent tentacles, vertical 9:16",
            "Extreme macro 8K photograph of tiny glowing immortal jellyfish drifting through dark clear sea water, volumetric sun rays, vertical 9:16",
            "Photorealistic 3D scientific visualization of jellyfish cellular transdifferentiation, glowing biological cells transforming and dividing, 8K render, vertical 9:16",
            "Photorealistic 8K underwater shot of fresh polyp colony sprouting on ocean floor, glowing with vibrant life, deep blue marine background, vertical 9:16",
        ],
    },
}

# ── 8 varied emergency fallback scripts (advertiser-safe, no CTAs, mood-varied) ─
# These are only triggered if ALL 3 LLM attempts fail — extremely rare.
# Each is a different mood/tone so even failures produce varied output.
_FALLBACK_SCRIPTS = [
    # neutral/factual
    {
        "text": (
            "Something extraordinary hides in the most ordinary places. "
            "Scientists have spent decades studying what most people walk past every day. "
            "The closer you look, the stranger reality becomes. "
            "Every surface, every shadow, every ordinary moment holds a story waiting to be found. "
            "The world is far stranger than it appears."
        ),
        "mood": "neutral",
        "caption_style": "minimal_clean",
        "glow_color": "&H0000D700",
        "voice": "am_michael",
        "pexels": ["science laboratory", "microscope detail", "nature close up"],
        "prompts": [
            "Macro photograph of ordinary surface revealing hidden complexity, photorealistic 8K",
            "Scientist examining extraordinary detail in mundane object, cinematic lighting",
            "Abstract visualization of hidden world within everyday environment, stunning"
        ],
    },
    # wonder/discovery
    {
        "text": (
            "In the deepest ocean trenches, creatures produce their own light — "
            "living lanterns in permanent darkness. "
            "Ninety-five percent of the ocean has never been explored. "
            "Entire mountain ranges, vast plains, and species we have never seen "
            "wait beneath two miles of cold, crushing black water. "
            "The last great frontier is not space. It is directly beneath our feet."
        ),
        "mood": "wonder",
        "caption_style": "cinematic",
        "glow_color": "&H00FF8040",
        "voice": "af_bella",
        "pexels": ["deep ocean bioluminescence", "underwater exploration", "ocean trench"],
        "prompts": [
            "Bioluminescent deep sea creatures glowing in pitch black ocean, photorealistic 8K",
            "Submarine exploring vast unexplored ocean trench, cinematic blue light",
            "Vast underwater mountain range hidden beneath ocean surface, stunning aerial view"
        ],
    },
    # excitement/high energy
    {
        "text": (
            "The human body replaces ninety-eight percent of its atoms every single year. "
            "The skeleton completely rebuilds itself every decade. "
            "You are not the same physical person you were ten years ago — "
            "almost every atom has been exchanged. "
            "Your body is a machine that continuously rebuilds itself from scratch while you sleep."
        ),
        "mood": "excitement",
        "caption_style": "dynamic_upper",
        "glow_color": "&H00FFD700",
        "voice": "am_michael",
        "pexels": ["human body cells", "atom structure", "biological regeneration"],
        "prompts": [
            "3D visualization of human cells rapidly regenerating, vibrant colors, cinematic 8K",
            "Atomic structure of human body glowing with energy, photorealistic masterpiece",
            "Time-lapse concept of body rebuilding itself, dynamic lighting, stunning"
        ],
    },
    # horror/dark educational
    {
        "text": (
            "Tardigrades — microscopic animals — have survived all five mass extinctions. "
            "They can endure the vacuum of space, boiling water, and radiation one thousand times "
            "the dose that would kill a human. "
            "They survive by turning themselves into glass — suspending all biological processes "
            "for decades until conditions improve. "
            "They have been on Earth for over five hundred million years. "
            "They will almost certainly outlive us."
        ),
        "mood": "horror",
        "caption_style": "horror_tight",
        "glow_color": "&H000015FF",
        "voice": "am_adam",
        "pexels": ["tardigrade microscope", "mass extinction", "space vacuum"],
        "prompts": [
            "Extreme close-up of tardigrade under electron microscope, highly detailed photorealistic",
            "Microscopic creature surviving in space vacuum, dark dramatic lighting, 8K",
            "Ancient creature outlasting extinction events, dark atmospheric cinematic"
        ],
    },
    # warm/story
    {
        "text": (
            "In 1969, a NASA engineer named Jack Garman noticed a single software error "
            "that could have aborted the moon landing eleven minutes before touchdown. "
            "He made a split-second decision to continue. "
            "That choice — made by one person in a room full of people — "
            "is why Neil Armstrong walked on the moon. "
            "History is full of moments that changed everything, "
            "decided by ordinary people trusting their instincts."
        ),
        "mood": "warm",
        "caption_style": "storytelling",
        "glow_color": "&H00FFD700",
        "voice": "af_bella",
        "pexels": ["moon landing NASA", "Apollo 11 mission control", "astronaut moon"],
        "prompts": [
            "NASA mission control 1969 with engineers watching moon landing, cinematic warm lighting",
            "Apollo 11 lunar module descending toward moon surface, photorealistic 8K",
            "Astronaut footstep on moon surface, historic moment, beautiful cinematic"
        ],
    },
    # neutral/science
    {
        "text": (
            "Trees communicate through an underground fungal network called mycorrhizae — "
            "nicknamed the Wood Wide Web. "
            "Older trees send sugars and nutrients to younger, struggling seedlings through this network. "
            "When a tree is dying, it floods the network with its remaining carbon, "
            "passing resources to its neighbors. "
            "Forests are not collections of individual trees. "
            "They are one interconnected, cooperative organism."
        ),
        "mood": "wonder",
        "caption_style": "cinematic",
        "glow_color": "&H0000D700",
        "voice": "af_bella",
        "pexels": ["forest mycorrhizae network", "tree roots underground", "forest canopy"],
        "prompts": [
            "Underground fungal network connecting tree roots glowing with energy, photorealistic 8K",
            "Ancient forest with visible bioluminescent root connections, cinematic atmosphere",
            "Aerial view of vast interconnected forest canopy, golden hour lighting, stunning"
        ],
    },
    # excitement/space
    {
        "text": (
            "Every second, the sun converts four million tons of matter into pure energy. "
            "That energy takes one hundred thousand years to travel from the sun's core to its surface — "
            "then only eight minutes to reach Earth. "
            "The sunlight warming your skin right now began its journey "
            "before modern humans existed. "
            "You are being warmed by one-hundred-thousand-year-old light."
        ),
        "mood": "excitement",
        "caption_style": "bold_lower",
        "glow_color": "&H00FFD700",
        "voice": "am_michael",
        "pexels": ["sun solar flare", "sunlight earth atmosphere", "solar energy"],
        "prompts": [
            "Massive solar flare erupting from sun surface in space, photorealistic 8K stunning",
            "Sunlight traveling through space toward Earth, cinematic cosmic visualization",
            "Person standing in warm golden sunlight, ancient light concept, beautiful cinematic"
        ],
    },
    # horror/dark history
    {
        "text": (
            "The Tunguska event of 1908 — a cosmic explosion over Siberia — "
            "flattened eighty million trees across two thousand square kilometers "
            "with no crater, no meteorite, no warning. "
            "Scientists still debate the exact cause. "
            "The object — estimated at fifty to eighty meters across — "
            "never even reached the ground. "
            "An event like this over a major city would end it entirely. "
            "It happens. We just got lucky where it landed."
        ),
        "mood": "horror",
        "caption_style": "horror_tight",
        "glow_color": "&H000015FF",
        "voice": "am_adam",
        "pexels": ["tunguska explosion forest", "meteor atmosphere explosion", "siberian forest devastation"],
        "prompts": [
            "Massive atmospheric explosion over Siberian forest, dark dramatic cinematic 8K",
            "Eighty million trees flattened in circular pattern, aerial view, photorealistic",
            "Cosmic object exploding in atmosphere above empty landscape, terrifying scale"
        ],
    },
]


def generate_script(niche: str, topic: str):
    """
    Generate a complete script for a YouTube Short.

    Returns
    -------
    tuple: (full_text, img_prompts, pexels_queries, scene_weights,
            provider, chosen_voice, chosen_glow, chosen_mood, chosen_caption_style)

    chosen_glow         : ASS &HAABBGGRR color code for caption neon halo
    chosen_mood         : mood string ("neutral" | "wonder" | "excitement" | "horror" | "warm")
    chosen_caption_style: preset key from caption_style_presets in settings.yaml
    """
    print(f"🎬 [SCRIPT] Drafting narrative for: {topic}")

    channel_id   = ctx.get_channel_id()
    intel        = db.get_channel_intelligence(channel_id)
    prompts_cfg  = load_config_prompts()

    # ── Read pre-written hook and content_format from job metadata ────────────
    # The researcher stores a pre-written hook sentence and a format hint
    # (fact/quiz/story) in the job's metadata JSON. If present, we inject the
    # hook into the script prompt so the LLM uses it as its opening line
    # instead of generating a weaker generic opener.
    researcher_hook   = ""
    researcher_format = "fact"
    try:
        current_job = db.get_job_by_topic(channel_id, topic)
        if current_job and current_job.metadata:
            job_meta = json.loads(current_job.metadata)
            researcher_hook   = job_meta.get("hook", "")
            researcher_format = job_meta.get("content_format", "fact")
    except Exception:
        pass  # If metadata is missing or malformed, continue normally

    emp  = "\n".join([f"- {r}" for r in intel.get("emphasize", [])[-3:]])
    avo  = "\n".join([f"- {r}" for r in intel.get("avoid",     [])[-3:]])
    vis  = ", ".join(intel.get("preferred_visuals", ["Cinematic"])[:3])

    hooks = intel.get("hook_patterns", [])
    hook_context = (
        "\n🎣 PROVEN HOOK PATTERNS (from competitor analysis — adapt these):\n" +
        "\n".join([f"- {h}" for h in hooks[:3]])
        if hooks else ""
    )

    # ── BUG FIX: Use the channel's configured content_type as the PRIMARY signal ──
    # The old code only checked if the niche STRING contained keywords like "fact".
    # Problem: the channel_intelligence `evolved_niche` can drift far from the
    # original configured niche (e.g. "trending facts" → "cosmic abyss dossiers").
    # Once drifted, the string no longer matches "fact" and the engine incorrectly
    # switches to fictional/storytelling mode — producing cinematic story scripts
    # instead of factual shorts. This compounds over time.
    #
    # Fix: read the channel's configured `content_type` from channels.yaml so
    # factual channels always get factual treatment regardless of niche drift.
    configured_content_type = None
    configured_niche        = None
    for _ch in config_manager.get_active_channels():
        if _ch.channel_id == channel_id:
            configured_content_type = getattr(_ch, "content_type", None)
            configured_niche        = _ch.niche
            break

    evolved      = intel.get("evolved_niche")
    niche_lower  = (evolved or niche or "").lower()

    # Primary signal: content_type ("factual") — set in channels.yaml.
    # Fallback: keyword detection on the niche string (backward compatible).
    is_fact = configured_content_type == "factual"
    if configured_content_type is None:
        is_fact = any(x in niche_lower for x in ["fact", "hack", "tip", "news", "top", "brainrot"])
    is_fictional = configured_content_type == "fictional"

    # Override is_fact/is_fictional based on researcher's format hint if present
    if researcher_format == "story" and not is_fictional:
        is_fictional = True
        is_fact      = False
        print(f"📋 [SCRIPT] Researcher requested story format — using storytelling mode.")
    elif researcher_format == "quiz":
        print(f"📋 [SCRIPT] Researcher requested quiz format.")

    # ── Niche selection for prompting ──────────────────────────────────────────
    # BUG FIX: For FACUTAL channels, always prompt with the CONFIGURED niche,
    # NOT the evolved_niche. The evolved_niche accumulates LLM drift over time
    # (e.g. "trending facts" → "cosmic abyss dossiers: alien tech & optical
    # warfare"), which hijacks every future topic generation and production.
    # We reset the prompt anchor to the operator's intended niche so the LLM
    # produces the educational/random-fun-facts content the channel was built for.
    # The evolved_niche is still used as *supplementary context* so the system
    # doesn't fully ignore learnings — it just can't override the configured anchor.
    if is_fact and configured_niche:
        active_niche = configured_niche.strip()
        print(f"📌 [SCRIPT] Factual channel — anchoring prompt to configured niche: '{active_niche}'")
        if evolved and evolved != active_niche:
            print(f"   🧬 [SCRIPT] (Evolved niche '{evolved}' used as context only.)")
    else:
        active_niche = evolved or niche or configured_niche or "General content"

    if is_fact:
        print(f"📌 [SCRIPT] Content type: factual — using short/educational format ({active_niche})")
    else:
        print(f"🎬 [SCRIPT] Content type: fictional — using storytelling format ({active_niche})")

    target_scenes = random.randint(4, 5) if is_fact else random.randint(4, 5)
    target_dur    = "40-50 seconds"     if is_fact else "45-55 seconds"
    target_words  = "95-115 words"      if is_fact else "100-120 words"

    # ── Load brand identity for this channel ─────────────────────────────────
    channel_brand_voice      = ""
    channel_personality      = []
    channel_narrator_persona = {}
    channel_language         = "en"
    channel_locale           = "en-US"
    for _ch in config_manager.get_active_channels():
        if _ch.channel_id == channel_id:
            channel_brand_voice      = getattr(_ch, "brand_voice", "")
            channel_personality      = getattr(_ch, "personality", [])
            channel_narrator_persona = getattr(_ch, "narrator_persona", {})
            channel_language         = getattr(_ch, "language", "en")
            channel_locale           = getattr(_ch, "locale", "en-US")
            break

    # ── Prompt Sharding & Constitution Injection ─────────────────────────────
    shards_cfg = prompts_cfg.get("script_gen", {}).get("shards", {})
    constitution_cfg = prompts_cfg.get("script_gen", {}).get("constitution", "")

    if researcher_format == "quiz":
        active_shard = shards_cfg.get("quiz", "")
    elif is_fictional:
        active_shard = shards_cfg.get("fictional", "")
    else:
        active_shard = shards_cfg.get("factual", "")

    base_user_prompt = prompts_cfg["script_gen"]["user_template"].format(
        niche=active_niche,
        topic=topic,
        emphasize_rules=emp or "Focus on viewer retention.",
        avoid_rules=avo or "Avoid slow pacing.",
        visual_preference=vis,
        target_duration=target_dur,
        target_word_count=target_words,
        word_ceiling=_ABSOLUTE_WORD_CEILING
    )

    if constitution_cfg:
        base_user_prompt += f"\n\n{constitution_cfg.strip()}\n"

    if active_shard:
        base_user_prompt += f"\n\n{active_shard.strip()}\n"

    # ── Self-Learning Golden Trajectories (Empirical Few-Shot Injection) ─────
    try:
        from engine.self_learning import self_learning
        trajectories_block = self_learning.format_trajectories_for_prompt(
            channel_id=channel_id,
            content_type="fictional" if is_fictional else "factual",
            limit=2
        )
        if trajectories_block:
            base_user_prompt += f"\n\n{trajectories_block.strip()}\n"
            print(f"🧠 [SELF-LEARNING] Injected golden trajectory exemplars for {channel_id}")
    except Exception as sle_err:
        logger.debug(f"Self-learning prompt injection skipped: {sle_err}")

    # ── Real-Time Fact Grounding & Anti-Hallucination Gate (Topato Mandate) ───
    if is_fact:
        try:
            from engine.fact_grounding import fact_grounding
            grounding_data = fact_grounding.verify_topic(topic)
            if grounding_data and grounding_data.get("verified"):
                grounding_block = fact_grounding.format_grounding_prompt_block(grounding_data)
                if grounding_block:
                    base_user_prompt += f"\n\n{grounding_block.strip()}\n"
                    print(f"🔬 [FACT GROUNDING] Verified empirical mechanisms injected via {grounding_data.get('engine', 'Search')}")
        except Exception as fg_err:
            logger.debug(f"Fact grounding prompt injection skipped: {fg_err}")

    # ── Brand identity injection ──────────────────────────────────────────────

    # ── P2.2: Narrator Persona Card & Brand Identity Injection ───────────────
    if channel_narrator_persona:
        p_name = channel_narrator_persona.get("name", "")
        p_tone = channel_narrator_persona.get("tone", "")
        p_vocab = channel_narrator_persona.get("vocabulary", [])
        p_forbidden = channel_narrator_persona.get("forbidden_words", [])

        persona_block = "\n\n🎭 NARRATOR PERSONA CARD (Embody this character completely):\n"
        if p_name:
            persona_block += f"• Persona Identity: {p_name}\n"
        if p_tone:
            persona_block += f"• Tone & Cadence: {p_tone}\n"
        if p_vocab:
            persona_block += "• Voice Directives:\n" + "\n".join([f"  - {v}" for v in p_vocab]) + "\n"
        if p_forbidden:
            persona_block += "• Strictly Forbidden Words & Clichés (NEVER use these):\n  " + ", ".join(p_forbidden) + "\n"
        base_user_prompt += persona_block
    elif channel_brand_voice or channel_personality:
        brand_block = "\n\n🎙️ CHANNEL BRAND VOICE (write in this style — every word):\n"
        if channel_brand_voice:
            brand_block += f"Voice: {channel_brand_voice}\n"
        if channel_personality:
            brand_block += "Personality traits: " + " | ".join(channel_personality) + "\n"
        brand_block += (
            "Every sentence should sound like THIS channel, not like a generic AI. "
            "If reading it aloud doesn't match this voice, rewrite it."
        )
        base_user_prompt += brand_block

    base_user_prompt += (
        f"\n\nCRITICAL INSTRUCTION: Break the script into EXACTLY {target_scenes} visual scenes. "
        f"The combined text across all scenes MUST be a detailed, multi-sentence narrative. {hook_context}"
    )

    # ── Inject researcher's pre-written hook if available ────────────────────
    if researcher_hook:
        base_user_prompt += (
            f"\n\n🎣 OPENING HOOK (USE THIS AS SCENE 1's FIRST SENTENCE — do not change it):\n"
            f"\"{researcher_hook}\"\n"
            f"Build the rest of the script to deliver on the promise this hook makes."
        )
        print(f"🎣 [SCRIPT] Injecting researcher hook: {researcher_hook[:80]}")

    # ── Quiz format: add extra instructions for quiz-style Shorts ────────────
    if researcher_format == "quiz":
        base_user_prompt += (
            f"\n\n❓ QUIZ FORMAT INSTRUCTIONS:\n"
            f"• Scene 1: Open with a direct question to the viewer (from the hook above).\n"
            f"• Scenes 2-4: Build suspense. Give 1-2 wrong guesses most people make.\n"
            f"• Scene 5+: Reveal the real answer dramatically. Then deliver the surprising context.\n"
            f"• Final scene: End with a mind-expanding 'and here's why that matters' kicker.\n"
            f"This is a QUIZ Short — viewer is playing along, not just listening."
        )


    if is_fictional:
        base_user_prompt += (
            f"\n\n🎬 FICTION STORY ARC (this is a STORY channel — a mini-movie, "
            f"not a fact narration):\n"
            f"• The topic IS a logline — dramatize it as a real short story.\n"
            f"• Open MID-ACTION on the protagonist and their obstacle "
            f"(no 'once upon a time', no throat-clearing).\n"
            f"• Follow a 3-beat arc: setup → escalating conflict → earned "
            f"RESOLUTION that lands the emotional/moral payoff.\n"
            f"• ONE clear protagonist with a want. Every scene advances the "
            f"conflict or deepens the character.\n"
            f"• End with a single, felt emotional beat — the lesson is shown, "
            f"never stated as a lecture.\n"
            f"• Keep it WARM and cinematic. Vary sentence rhythm. "
            f"No AI filler words ('remarkable', 'fascinating', 'truly').\n"
            f"• Visuals (image_prompt fields) MUST match the story scenes: "
            f"3D-Pixar-style animation stills of the actual characters/setting."
        )

    # ── P3.6: Multi-Language Narration Instruction ───────────────────────────
    if channel_language and channel_language != "en":
        base_user_prompt += (
            f"\n\n🌍 TARGET LANGUAGE MANDATE:\n"
            f"The channel's target audience requires narration strictly in '{channel_language}' (Locale: '{channel_locale}').\n"
            f"• All spoken dialogue and narration text across all scenes MUST be in fluent, natural {channel_language}.\n"
            f"• Keep 'image_prompt' and 'pexels_query' in English so text-to-image AI interprets them perfectly.\n"
            f"• Maintain punchy sentence pacing and emotional retention in {channel_language}."
        )
        print(f"🌍 [SCRIPT] Injected target language requirement: {channel_language} ({channel_locale})")

    # ── Circular Script Seamless Loop Engine (2026 Playbook) ─────────────────
    try:
        from engine.loop_engine import loop_engine
        loop_block = loop_engine.get_loop_prompt_instructions()
        if loop_block:
            base_user_prompt += f"\n\n{loop_block.strip()}\n"
    except Exception as le_err:
        logger.debug(f"Loop engine prompt injection skipped: {le_err}")

    # ── P3.1: Chain-of-Thought Pre-Draft Reasoning ───────────────────────────
    # Executes one focused planning reasoning step before drafting scenes.
    # Thinks through: hook mechanism, narrative escalation, counter-intuitive twist, circular loop.
    # Skips gracefully if quota is exhausted or on any exception.
    try:
        cot_prompt = (
            f"You are a master YouTube Shorts storytelling architect.\n"
            f"Plan a viral 4-scene Short on the topic: '{topic}' (Niche: '{active_niche}').\n\n"
            f"Think step-by-step:\n"
            f"1. Hook Mechanism: What exact curiosity gap or pattern interrupt hooks in seconds 0-3?\n"
            f"2. Narrative Tension: How does Scene 2 escalate the stakes or test assumptions?\n"
            f"3. Counter-Intuitive Climax: What surprising truth or bold action lands in Scene 3?\n"
            f"4. Circular Loop Anchor: How does the final sentence of Scene 4 loop back to Scene 1?\n\n"
            f"Keep your strategic plan under 90 words total. Be razor-sharp and punchy."
        )
        cot_raw, cot_provider = quota_manager.generate_text(
            cot_prompt,
            task_type="reasoning",
            system_prompt="You are a YouTube Shorts retention strategist. Provide a brief 4-beat blueprint."
        )
        if cot_raw and len(cot_raw.strip()) > 25:
            cot_plan = cot_raw.strip()
            print(f"   🧠 [COT PRE-DRAFT] Strategic blueprint generated via {cot_provider}")
            base_user_prompt += f"\n\n🧭 DIRECTORS STRATEGIC BLUEPRINT (Follow this story arc closely):\n{cot_plan}\n"
    except Exception as cot_err:
        logger.debug(f"CoT pre-draft reasoning skipped: {cot_err}")

    last_error = "Unknown Error"

    for attempt in range(3):
        # ── BUG #4 FIX: Progressive word-limit constraints on retry ───────────
        # Original code sent the exact same prompt all 3 times. If the LLM
        # ignored the word ceiling on attempt 1 (as it did today: 207→198→239),
        # all 3 retries were guaranteed to fail, burning 3 Gemini quota points
        # and falling to the emergency fallback script.
        #
        # Strategy:
        #   Attempt 0 (first try) → base prompt, no extra constraint
        #   Attempt 1 (first retry) → inject an explicit bolded hard-limit banner
        #   Attempt 2 (last chance) → banner + hard-truncate the JSON text ourselves
        #                             before the word-count check (never fails)
        if attempt == 0:
            user_prompt = base_user_prompt
        else:
            err_lower = last_error.lower()
            if "under word floor" in err_lower or "too short" in err_lower:
                word_limit_banner = (
                    f"\n\n🚨 PREVIOUS ATTEMPT UNDER WORD FLOOR ({last_error}) 🚨\n"
                    f"Your previous response was TOO SHORT. Do NOT write brief 60-70 word scripts.\n"
                    f"Expand the story/explanation with deeper details, sensory descriptions, or step-by-step mechanisms.\n"
                    f"Target word count: {target_words} (minimum {_MIN_WORD_FLOOR} words, maximum {_ABSOLUTE_WORD_CEILING} words)."
                )
            elif "exceeds" in err_lower or "too long" in err_lower:
                word_limit_banner = (
                    f"\n\n🚨 PREVIOUS ATTEMPT EXCEEDED WORD CEILING ({last_error}) 🚨\n"
                    f"Your previous response was too long. Keep sentences concise.\n"
                    f"Target word count: {target_words} (maximum {_ABSOLUTE_WORD_CEILING} words)."
                )
            else:
                word_limit_banner = (
                    f"\n\n🚨 PREVIOUS ATTEMPT REJECTED ({last_error}) 🚨\n"
                    f"Fix the violation above. Ensure a complete, self-contained final sentence, "
                    f"proper word count ({_MIN_WORD_FLOOR}-{_ABSOLUTE_WORD_CEILING} words), and active storytelling."
                )
            user_prompt = base_user_prompt + word_limit_banner

        try:
            raw, provider = quota_manager.generate_text(
                user_prompt,
                task_type="creative",
                system_prompt=prompts_cfg["script_gen"]["system_prompt"]
            )
            if not raw:
                last_error = "API returned empty response."
                continue

            import re
            think_match = re.search(r"<THINKING>(.*?)</THINKING>", raw, flags=re.DOTALL | re.IGNORECASE)
            if think_match:
                logger.generation(f"🧠 [THINKING]\n{think_match.group(1).strip()}\n")

            from engine.llm_router import UniversalGreedyJSONParser
            data = UniversalGreedyJSONParser.extract_json(raw)
            if not data or not isinstance(data, dict):
                start = raw.find('{')
                end   = raw.rfind('}')
                if start == -1 or end == -1 or end <= start:
                    last_error = "Malformed JSON boundary returned by AI."
                    continue
                json_payload = raw[start:end + 1]
                data = json.loads(json_payload)

            # ── P2.1: Multi-Agent Review (Critic Agent + Conditional Director) ──
            # On initial draft (attempt == 0), Critic Agent evaluates retention metrics.
            # If avg critic score < 7.0, Director Agent rewrites to repair weak spots.
            if attempt == 0 and isinstance(data, dict) and "scenes" in data:
                try:
                    data, critic_review_data = multi_agent_review(
                        script_data=data,
                        topic=topic,
                        is_fictional=is_fictional,
                        channel_id=channel_id,
                        active_niche=active_niche
                    )
                except Exception as mar_err:
                    logger.debug(f"Multi-agent review skipped: {mar_err}")

            chosen_voice = data.get("voice_actor", "am_adam")

            # ── glow_color: the neon halo color for captions ─────────────────
            # Accept either the new key ('glow_color') or the legacy key
            # ('subtitle_color') in case an older cached response is replayed.
            chosen_glow = (
                data.get("glow_color")
                or data.get("subtitle_color")
                or "&H0000D700"   # default: green glow
            )

            # ── mood: emotional register of this video ────────────────────────
            chosen_mood = data.get("mood", "neutral")
            if chosen_mood not in _VALID_MOODS:
                chosen_mood = "neutral"

            # ── caption_style: visual subtitle preset ────────────────────────
            chosen_caption_style = data.get("caption_style", "viral_impact")
            if chosen_caption_style not in _VALID_CAPTION_STYLES:
                # Fallback: derive from mood
                chosen_caption_style = _MOOD_TO_CAPTION_STYLE.get(chosen_mood, "viral_impact")

            parsed_scenes  = [extract_scene_data(s, topic) for s in data.get("scenes", [])]
            full_text      = " ".join([s[0] for s in parsed_scenes])
            img_prompts    = [s[1] for s in parsed_scenes]
            pexels_queries = [s[2] for s in parsed_scenes]

            word_count = len(full_text.split())
            print(f"      -> [TEXT PRE-CHECK] Script generated: {word_count} words (Mathematical Limit: {_ABSOLUTE_WORD_CEILING}).")

            # ── BUG #4 FIX (continued): On the last attempt, hard-truncate the
            # assembled text rather than failing. This guarantees we never hit
            # the emergency fallback just because the LLM is verbose — we trim
            # cleanly at the word boundary and continue with a valid (shorter) script.
            if word_count > _ABSOLUTE_WORD_CEILING:
                if attempt == 2:
                    print(f"      ✂️ [SCRIPT] Last attempt still too long ({word_count} words). Truncating cleanly to {_ABSOLUTE_WORD_CEILING} words...")
                    words         = full_text.split()
                    candidate     = " ".join(words[:_ABSOLUTE_WORD_CEILING])
                    last_punct    = max(candidate.rfind('.'), candidate.rfind('!'), candidate.rfind('?'))
                    if last_punct > int(len(candidate) * 0.6):
                        full_text = candidate[:last_punct + 1]
                    else:
                        full_text = candidate.rstrip(' ,;:-') + "."
                    word_count    = len(full_text.split())
                    # Rebuild scene text proportionally (keep prompts/queries intact)
                    total_chars   = sum(len(s[0]) for s in parsed_scenes) or 1
                    char_budget   = len(full_text)
                    rebuilt       = []
                    chars_used    = 0
                    for i, (narr, prompt, query) in enumerate(parsed_scenes):
                        share      = len(narr) / total_chars
                        allotted   = int(char_budget * share)
                        trimmed    = narr[:allotted].rsplit(' ', 1)[0] if len(narr) > allotted else narr
                        chars_used += len(trimmed)
                        rebuilt.append((trimmed, prompt, query))
                    parsed_scenes = rebuilt
                else:
                    print(f"      ⚠️ [SCRIPT] Too long ({word_count} words, limit {_ABSOLUTE_WORD_CEILING}). Retrying with tighter constraint...")
                    last_error = "Script exceeded maximum mathematical word count."
                    continue

            passed, val_reason = validate_script_quality(full_text, prompts_cfg, is_fictional=is_fictional, parsed_scenes=parsed_scenes)

            sentences = [s.strip() for s in re.split(r'[.!?]+', full_text) if s.strip()]
            hook_s = sentences[0] if sentences else ""
            ending_s = sentences[-1] if sentences else ""

            box_width = 76
            status_symbol = "✅ APPROVED" if passed else "❌ REJECTED"
            print(f"\n┌{'─' * box_width}┐")
            print(f"│ [SCRIPT GENERATION] Attempt {attempt + 1}/3 | Provider: {provider}")
            print(f"├{'─' * box_width}┤")
            print(f"│ Status    : {status_symbol}")
            print(f"│ Word Count: {word_count} words (Target: {_MIN_WORD_FLOOR}-{_ABSOLUTE_WORD_CEILING})")
            print(f"│ Details   : {val_reason}")
            print(f"│ Loop Hook : \"{ending_s[:35]}…\" ➔ \"{hook_s[:35]}…\"")
            print(f"├{'─' * box_width}┤")
            print(f"│ GENERATED SCRIPT TEXT:")
            for line in full_text.split("\n"):
                print(f"│ \"{line}\"")
            print(f"└{'─' * box_width}┘\n")

            if not passed:
                last_error = val_reason
                continue

            total_chars   = sum(len(s[0]) for s in parsed_scenes)
            scene_weights = (
                [len(s[0]) / total_chars for s in parsed_scenes]
                if total_chars > 0 else []
            )

            # ── P1.8: Character Anchor — apply visual consistency to fictional channels ──
            # Extracts a per-video character lock from the script (1 LLM call) and prepends
            # the channel's permanent style card + character descriptor to every image prompt.
            # This prevents visual drift between scenes (same character looks different in each scene).
            try:
                from engine.character_anchor import character_anchor
                channel_data = config_manager.get_channel()
                content_type = channel_data.get("content_type", "factual") if channel_data else "factual"
                channel_id   = channel_data.get("id", "") if channel_data else ""
                if content_type == "fictional" and img_prompts:
                    img_prompts = character_anchor.apply_to_all_scenes(
                        script_text=full_text,
                        topic=topic,
                        channel_id=channel_id,
                        image_prompts=img_prompts,
                        content_type=content_type,
                    )
            except Exception as _ca_err:
                logger.debug(f"Character anchor skipped: {_ca_err}")

            return (
                full_text, img_prompts, pexels_queries, scene_weights,
                provider, chosen_voice, chosen_glow, chosen_mood, chosen_caption_style
            )

        except Exception as e:
            last_error = str(e)
            trace = traceback.format_exc()
            print(f"⚠️ [SCRIPT] Attempt {attempt + 1} failed:\n{trace}")
            continue

    # ── Emergency Fallback ─────────────────────────────────────────────────────
    # All 3 LLM attempts exhausted. Pick a random varied fallback script.
    # These are advertiser-safe, contain no CTAs, and cover all mood categories.
    logger.error(f"🚨 Script Generation Fatal Exhaustion ({last_error}). Checking Emergency Vault...")

    # ── P2.6: Emergency Vault Buffer ──────────────────────────────────────────
    try:
        from engine.emergency_vault import emergency_vault
        vault_script = emergency_vault.get_script(channel_id)
        if vault_script and "text" in vault_script and "prompts" in vault_script:
            print(f"   🛡️ [EMERGENCY VAULT] Successfully retrieved evergreen script: '{vault_script.get('topic')}'")
            v_prompts = vault_script["prompts"]
            v_weights = [1.0 / len(v_prompts)] * len(v_prompts)
            if v_weights:
                v_weights[-1] = 1.0 - sum(v_weights[:-1])
            return (
                vault_script["text"],
                v_prompts,
                vault_script.get("pexels", ["nature", "science", "cinematic"]),
                v_weights,
                f"Emergency Vault ({vault_script.get('topic')})",
                vault_script.get("target_voice", "am_adam"),
                vault_script.get("glow_color", "&H0000D700"),
                vault_script.get("mood", "neutral"),
                vault_script.get("caption_style", "viral_impact"),
            )
    except Exception as ev_err:
        logger.debug(f"[SCRIPT] Emergency vault retrieval skipped: {ev_err}")

    fb = _CHANNEL_FALLBACK_SCRIPTS.get(channel_id)
    fallback_source = f"Handcrafted {channel_id} Exemplar"
    if not fb:
        fb = _CHANNEL_FALLBACK_SCRIPTS.get("CH_01" if is_fictional else "CH_02")
        fallback_source = "Handcrafted Channel Exemplar"
    if not fb:
        fb = random.choice(_FALLBACK_SCRIPTS)
        fallback_source = "Handcrafted Generic Exemplar"

    fallback_weights = [1.0 / len(fb["prompts"])] * len(fb["prompts"])
    if fallback_weights:
        fallback_weights[-1] = 1.0 - sum(fallback_weights[:-1])

    exact_provider_name = f"{fallback_source} (Fallback: {last_error})"

    return (
        fb["text"],
        fb["prompts"],
        fb["pexels"],
        fallback_weights,
        exact_provider_name,
        fb["voice"],
        fb["glow_color"],
        fb["mood"],
        fb["caption_style"],
    )
