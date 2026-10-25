"""
engine/managers/iterative_script_generator.py — High-Retention Circular Script Generator (v4.1)

Implements the ISCG v4.1 Audio-Driven Infinite Circular Loop Architecture:
1. Step 1 (Triplet Anchor Generation): Generates Scene 1 (Hook), Penultimate Scene (Final Fact),
   and the Final Scene (Circular Loopback Bridge) TOGETHER in a single LLM call.
   This guarantees that the loopback sentence logically transitions FROM the final fact AND
   grammatically flows right back into the opening hook words ending with '...'.
2. Step 2 (Audio-Driven Middle Thoughts): Generates standalone random Reddit thoughts and
   logical everyday facts one by one, measuring empirical speech duration via Kokoro TTS
   (VoiceNormalizer.measure_duration_quick). Loops until cumulative duration crosses the 30s mark
   (landing naturally at ~30.0s–33.5s without any trimming or cutting).
3. Step 3 (Script Assembly): Assembles [Scene 1 Hook, Middle Thoughts..., Penultimate Fact, Final Loop Scene].
4. Step 4 (Normalization & Emotion Pass): Polishes punctuation (?, !, ,, —, .) for Kokoro neural TTS
   while synchronizing spoken_text and phonetic_text.
5. Step 5 (Dynamic Video-Specific SEO): Generates unique high-CTR title, custom description, and tags.
"""

from __future__ import annotations

import re
import os
import json
import yaml
import random
import pathlib
import sys
from typing import List, Dict, Any, Tuple, Optional, Union

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from engine.managers.editorial_critic import (
    CynicalHumanAuditor,
    SemanticDeduplicationSkill,
    TitleScriptAlignmentSkill,
    HookAuditorSkill,
    ThoughtCompletenessSkill,
    LoopAuditorSkill,
    check_loop_repeats_hook,
    is_valid_circular_bridge,
    COMPILATION_LOOP_BRIDGES,
    UMBRELLA_TITLE_TEMPLATES,
    _token_overlap,
    _load_upload_history_titles
)
from engine.managers.llm_quality_tracker import LLMQualityTracker


# Curated satisfying visual queries for ASMR b-roll
SATISFYING_VISUAL_QUERIES = [
    "soap carving cubes ASMR",
    "kinetic sand squishing satisfying",
    "pottery wheel clay shaping satisfying",
    "resin lathe turning wood polishing",
    "hot wire foam cutting smooth shapes",
    "fluid acrylic pour art colorful cells",
    "sand pendulum harmonograph geometric",
    "colored pencils sharpening macro",
    "laser rust removal beam metal clean",
    "marble run wooden track kinetic",
    "wax seal stamp melting drip",
    "domino cascade chain reaction smooth",
    "wood turning lathe chisel shavings",
    "honeycomb uncapping scraper golden wax",
    "glitter slime scoop satisfying"
]

# Vetted circular paired anchors (Hook -> Loop Outro) for legacy fallback situations
PAIRED_CIRCULAR_FALLBACKS = [
    (
        "You have never actually seen your own face, only reflections and photos.",
        "Which means the only reason you recognize yourself is because..."
    ),
    (
        "The brain named itself, recognized itself, and is now questioning that exact fact.",
        "And the wildest part is that this whole realization only happens when..."
    ),
    (
        "The only part of your reflection you can actually lick is your tongue.",
        "And you will probably test that right now just to prove that..."
    ),
    (
        "Your future self is currently watching you right now through your memories.",
        "So make sure you don't do something embarrassing, especially since..."
    ),
    (
        "Nothing is ever completely on fire, fire is just on things.",
        "Which sounds completely absurd until you remember that..."
    ),
    (
        "Every single person you see in your dreams has a face you've encountered in real life.",
        "Which means when you wake up, you are always returning to a world where..."
    )
]

# Vetted 3-sentence circular anchors (Hook, Penultimate Fact, Circular Loopback Bridge)
TRIPLET_CIRCULAR_FALLBACKS = [
    (
        "You have never actually seen your own face, only reflections, screens, and photographs.",
        "Every single mirror you purchase is technically used since someone had to test it.",
        "Which means the only reason you recognize yourself is because..."
    ),
    (
        "The brain named itself, recognized itself, and is now questioning that exact fact.",
        "Your mind constantly edits reality before you are even conscious of it.",
        "And the wildest part is that this whole realization only happens when..."
    ),
    (
        "The only part of your reflection you can actually lick is your tongue.",
        "Your teeth are the only visible part of your skeleton that you clean daily.",
        "And you will probably test that right now just to prove that..."
    ),
    (
        "Nothing is ever completely on fire, fire is just on things.",
        "Oxygen is slowly rusting our bodies from the inside out over decades.",
        "Which sounds completely absurd until you remember that..."
    ),
    (
        "Every single person you see in your dreams has a face you've encountered in real life.",
        "Your memory records millions of micro-details you never consciously noticed.",
        "Which means when you wake up, you are always returning to a world where..."
    ),
    (
        "Water is not wet by itself, it only makes other materials wet.",
        "Fire is not technically on fire, it is just actively burning fuel.",
        "Which sounds completely backwards until you remember that..."
    )
]

# Witty, high-retention call-to-action closers (Legacy BrainBlud style fallback)
BRAINBLUD_CLOSERS = [
    "Subscribe for more thoughts that will break your brain.",
    "If you want to be smarter than everyone you know, subscribe.",
    "If all of you subscribed right now, I would have more subscribers.",
    "Subscribe to unlock thoughts nobody told you.",
    "Your brain is now holding information it will never use again.",
    "If you made it this far, your attention span is better than average.",
    "If you subscribe right now, your phone won't explode tomorrow.",
    "Drop your wildest shower thought below, and subscribe for more.",
    "Subscribe if you want your recommended feed to make you question reality.",
    "You are now one minute closer to knowing everything about nothing.",
    "If you want to question reality every single day, subscribe."
]
MODE_B_WITTY_CLOSERS = BRAINBLUD_CLOSERS  # Backward compatibility alias

# Legacy Scene 2 Premise Anchor Templates (kept for backwards compatibility tests)
PREMISE_ANCHOR_LINES = [
    "Shower thoughts that will break your brain.",
    "Shower thoughts nobody told you.",
    "Shower thoughts that sound illegal to know.",
    "Psychological facts that sound completely fake.",
    "Psychological tricks nobody knew.",
    "Not so fun facts to blow your mind.",
    "Mind-bending facts about the human brain.",
    "Brain glitches you experience daily.",
    "Unsettling thoughts that sound fake but are 100% true."
]

PILLARS = [
    {"name": "Mind-Bending Thought", "desc": "Relatable random Reddit thought or logical fact"}
]


def _load_past_spoken_thoughts() -> List[str]:
    """Loads historical spoken thoughts from memory/past_spoken_thoughts.json."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return []
    path = pathlib.Path("memory/past_spoken_thoughts.json")
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("past_thoughts", [])
        except Exception:
            pass
    return []


def save_past_spoken_thoughts(new_thoughts: List[str]) -> None:
    """Appends newly generated spoken thoughts to memory/past_spoken_thoughts.json."""
    path = pathlib.Path("memory/past_spoken_thoughts.json")
    existing_thoughts: List[str] = []
    meta = {
        "description": "Historical registry of spoken lines from previously uploaded videos to prevent thought repetition across runs.",
        "version": "1.0"
    }
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                existing_thoughts = data.get("past_thoughts", [])
                meta = data.get("_meta", meta)
        except Exception:
            pass

    added = 0
    for t in new_thoughts:
        clean_t = t.strip()
        if clean_t and clean_t not in existing_thoughts:
            existing_thoughts.append(clean_t)
            added += 1

    if added > 0:
        from datetime import datetime, timezone
        meta["updated_at"] = datetime.now(timezone.utc).isoformat()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"_meta": meta, "past_thoughts": existing_thoughts}, f, indent=2)
            print(f"💾 [MEMORY] Persisted {added} new spoken thoughts to {path} (total: {len(existing_thoughts)})", flush=True)
        except Exception as e:
            print(f"⚠️ [MEMORY] Failed to save past thoughts: {e}", flush=True)


def _normalize_grounding_facts(grounding: Optional[Union[str, List[Dict[str, Any]]]]) -> str:
    """Normalizes raw grounding facts (text or structured list) into a clean prompt string."""
    if not grounding:
        return ""
    if isinstance(grounding, str):
        return grounding.strip()
    if isinstance(grounding, list):
        lines = []
        for f in grounding:
            if isinstance(f, dict):
                fact = f.get("fact", "") or f.get("text", "")
                src = f.get("source", "Curated Archive")
                if fact:
                    lines.append(f"- {fact} (Source: {src})")
            elif isinstance(f, str) and f.strip():
                lines.append(f"- {f.strip()}")
        if lines:
            return "VERIFIED INSPIRATION & FACTUAL REFERENCES:\n" + "\n".join(lines)
    return ""


def _normalize_num_token(token: str) -> str:
    """
    Deterministically normalizes numerical token formatting using string operations
    without floating-point conversions or precision loss, preserving numerical sign.
    E.g., '-5' -> '-5', '+5' -> '+5', '5' -> '5', '-3.50' -> '-3.5', '10,000' -> '10000'.
    """
    sign = ""
    if token.startswith("-"):
        sign = "-"
        token = token[1:]
    elif token.startswith("+"):
        sign = "+"
        token = token[1:]

    cleaned = token.replace(",", "")
    if "." in cleaned:
        int_part, frac_part = cleaned.split(".", 1)
        int_norm = int_part.lstrip("0") or "0"
        frac_norm = frac_part.rstrip("0")
        if frac_norm:
            norm_mag = f"{int_norm}.{frac_norm}"
        else:
            norm_mag = int_norm
    else:
        norm_mag = cleaned.lstrip("0") or "0"

    return f"{sign}{norm_mag}"


def _extract_number_tokens(text: str) -> List[str]:
    """
    Extracts normalized numerical tokens for fact preservation, preserving numerical sign
    while conservatively distinguishing signed values from range notation (e.g. 16-24, 16 - 24).
    Accounts for integers, high-precision decimals, and comma-formatted values.
    """
    pattern = re.compile(r"([+-]?)(?:\b|\B(?=[+-]))(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\b")
    results = []
    for match in pattern.finditer(text or ""):
        full = match.group(0)
        sign = match.group(1)
        start = match.start()

        if sign:
            # Conservative range disambiguation: if preceded by a digit (e.g. '16-24' or '16 - 24'),
            # the hyphen is a range separator, not a negative sign.
            prefix = text[:start].rstrip()
            if start > 0 and (text[start - 1].isdigit() or (prefix and prefix[-1].isdigit())):
                full = full[1:]
        results.append(_normalize_num_token(full))
    return results


def derive_grounded_fallback_title(scenes: List[Dict[str, Any]], topic: str = "") -> str:
    """
    Derives a concise, grounded YouTube Shorts fallback title from the script's actual substance
    or verified topic without generic sensationalism or unsupported numerical claims.
    """
    from collections import Counter
    full_script_text = " ".join(s.get("spoken_text", "") for s in (scenes or []) if isinstance(s, dict))
    script_counts = Counter(_extract_number_tokens(full_script_text))

    # 1. Try deriving from first non-empty scene thought
    for s in (scenes or []):
        if not isinstance(s, dict):
            continue
        text = s.get("spoken_text", "").strip()
        if not text:
            continue
        # Extract first complete thought or sentence
        first_thought = re.split(r"(?<=[.!?])\s+", text)[0].strip()
        clean = re.sub(r"^[.…\-—\s]+|[.…\-—\s]+$", "", first_thought).strip()
        if clean:
            if len(clean) > 85:
                truncated = clean[:85].rsplit(" ", 1)[0].rstrip(",;:-— ")
                if truncated:
                    clean = truncated
            cand = f"{clean} #shorts" if "#shorts" not in clean.lower() else clean
            # Ensure candidate does not have unsupported numbers
            cand_counts = Counter(_extract_number_tokens(cand))
            if all(cand_counts[n] <= script_counts.get(n, 0) for n in cand_counts):
                return cand

    # 2. Try deriving from topic if topic contains no numbers unsupported by the script
    if topic and topic.strip():
        clean_topic = re.sub(r"^[.…\-—\s]+|[.…\-—\s]+$", "", topic.strip()).strip()
        if clean_topic:
            topic_nums = Counter(_extract_number_tokens(clean_topic))
            if all(topic_nums[n] <= script_counts.get(n, 0) for n in topic_nums):
                return f"{clean_topic} #shorts"

    # 3. If topic had unsupported numbers or no topic/scenes, pick neutral, grounded title
    return "Observations and Perspectives #shorts"


def derive_grounded_fallback_description(scenes: List[Dict[str, Any]], topic: str = "") -> str:
    """
    Derives an accurate, natural fallback description from the script's actual observations,
    using the topic only as supporting context, avoiding boilerplate and unsupported claims.
    """
    scene_texts = [s.get("spoken_text", "").strip() for s in (scenes or []) if isinstance(s, dict) and s.get("spoken_text", "").strip()]
    if scene_texts:
        # Ground directly in the opening thoughts of the script
        substance = " ".join(scene_texts[:2])
        if topic and topic.strip() and topic.lower() not in substance.lower():
            body = f"{topic.strip()} — {substance}"
        else:
            body = substance
        return f"{body}\n\n#shorts"
    elif topic and topic.strip():
        return f"Observations and perspectives on {topic.strip()}.\n\n#shorts"
    else:
        return "Observations and perspectives from this video.\n\n#shorts"


def derive_grounded_fallback_seo(
    scenes: List[Dict[str, Any]],
    topic: str = "",
    recent_titles: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Assembles a complete, grounded SEO metadata dictionary (title, description, tags)
    from the actual script and topic without relying on LLM generation.
    """
    from engine.managers.editorial_critic import TitleScriptAlignmentSkill
    aligned_title = derive_grounded_fallback_title(scenes=scenes, topic=topic)
    aligned_title = TitleScriptAlignmentSkill.align_title(
        title=aligned_title,
        scenes=scenes,
        upload_history_titles=recent_titles or [],
        topic=topic
    )
    base_description = derive_grounded_fallback_description(scenes=scenes, topic=topic)
    full_description = f"{aligned_title}\n\n{base_description}"

    full_script_text = " ".join(s.get("spoken_text", "") for s in (scenes or []) if isinstance(s, dict))
    from engine.managers.pipeline_runner import extract_keywords
    script_kws = extract_keywords(full_script_text, max_keywords=8)
    tags = [topic.lower()] if topic else []
    tags.extend([kw.lower() for kw in script_kws if kw.lower() not in tags])
    if "shorts" not in tags:
        tags.append("shorts")

    return {
        "title": aligned_title,
        "description": full_description,
        "tags": [str(t).strip() for t in tags if str(t).strip()]
    }


def synchronize_seo_description_header(
    description: Any,
    old_title: Any,
    new_title: Any
) -> Any:
    """
    Synchronizes the first-line title header of a Shorts SEO description when
    editorial alignment modifies the title.

    Replaces the first line only if it matches the superseded old_title (with
    whitespace and optional case tolerance), preserving the rest of the description
    exactly as-is. If the first line does not match old_title, or if either value
    is missing/invalid, returns the description unchanged.
    """
    if not isinstance(description, str):
        return description
    if not description.strip():
        return description
    if not isinstance(new_title, str) or not new_title.strip():
        return description
    if not isinstance(old_title, str) or not old_title.strip():
        return description

    old_clean = old_title.strip()
    new_clean = new_title.strip()
    if old_clean.lower() == new_clean.lower():
        return description

    lines = description.splitlines(keepends=True)
    if not lines:
        return description

    first_line_raw = lines[0]
    first_line_clean = first_line_raw.strip()

    # Compare first line against old_title
    match_found = False
    if first_line_clean.lower() == old_clean.lower():
        match_found = True
    else:
        # Also check without case-insensitive #shorts suffix
        old_base = re.sub(r"(?i)\s*#shorts\b", "", old_clean).strip()
        first_base = re.sub(r"(?i)\s*#shorts\b", "", first_line_clean).strip()
        if old_base and first_base.lower() == old_base.lower():
            match_found = True

    if not match_found:
        return description

    # Determine original newline style
    if first_line_raw.endswith("\r\n"):
        nl = "\r\n"
    elif first_line_raw.endswith("\n"):
        nl = "\n"
    else:
        nl = ""

    return f"{new_clean}{nl}" + "".join(lines[1:])


class IterativeScriptGenerator:
    """
    High-Retention Circular Script Generator with Triplet Anchor Generation (v4.1),
    Audio-Driven Dynamic Duration Loop, and Targeted LLM Recreation.
    """

    def __init__(
        self,
        llm_manager: Optional[Any] = None,
        quality_tracker: Optional[LLMQualityTracker] = None,
        prompts_cfg: Optional[Dict[str, Any]] = None,
        channel_premise: str = "",
        channel_cfg: Optional[Dict[str, Any]] = None,
    ):
        if llm_manager is None:
            from engine.managers.llm_manager import LLMManager
            llm_manager = LLMManager()
        self.llm = llm_manager
        self.qt = quality_tracker or LLMQualityTracker()

        # Resolve prompt configuration:
        # If prompts_cfg is supplied, consume it directly (already configured by caller/PipelineRunner).
        # Supplying a configured prompt dictionary does not silently reload or mutate it with duplicate instructions.
        # If omitted, load raw prompts from disk and apply channel_cfg rules if channel_cfg was provided.
        if prompts_cfg is not None and isinstance(prompts_cfg, dict):
            import copy
            self.prompts = copy.deepcopy(prompts_cfg)
        else:
            self.prompts = self._load_prompts()
            if channel_cfg and isinstance(channel_cfg, dict):
                from engine.managers.pipeline_runner import apply_prompt_rules_to_config
                self.prompts = apply_prompt_rules_to_config(self.prompts, channel_cfg)

        # Resolve channel premise: supplied premise, or from channel_cfg, or empty
        resolved_premise = channel_premise
        if not resolved_premise and channel_cfg and isinstance(channel_cfg, dict):
            prompt_settings = channel_cfg.get("prompt_settings", channel_cfg.get("prompt_rules", {}))
            resolved_premise = prompt_settings.get("channel_premise") or channel_cfg.get("channel_premise", "")
        self.channel_premise = (resolved_premise or "").strip()

    def _load_prompts(self) -> Dict[str, Any]:
        """Loads clean prompts from config/prompts.yaml."""
        prompt_file = pathlib.Path("config/prompts.yaml")
        if prompt_file.exists():
            try:
                with open(prompt_file, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
            except Exception:
                pass
        return {}

    def _calc_duration(self, text: str) -> float:
        """Estimates spoken duration using VoiceNormalizer if available, falling back to word math."""
        try:
            from engine.managers.voice_normalizer import VoiceNormalizer
            return VoiceNormalizer.measure_duration_quick(text, speed=1.02)
        except Exception:
            words = len(text.split())
            return round(words / 3.2 + 0.12, 2)

    def _is_duplicate_thought(
        self,
        text: str,
        existing_scenes: List[Dict[str, Any]],
        recent_titles: Optional[List[str]] = None,
        past_thoughts: Optional[List[str]] = None
    ) -> Tuple[bool, str]:
        """
        Validates thought uniqueness against existing scenes in this video,
        recent upload titles, and persistent memory (memory/past_spoken_thoughts.json).
        Also enforces CynicalHumanAuditor (blocking solipsism, overused clichés, etc.).
        """
        if not text or not text.strip():
            return True, "Empty text"

        # Check solipsism and overused clichés
        passed_wall, wall_reason = CynicalHumanAuditor.audit_text(text)
        if not passed_wall:
            return True, wall_reason

        # Check against existing scenes in current video
        if existing_scenes:
            is_sem_dup, sem_reason = SemanticDeduplicationSkill.is_duplicate(text, existing_scenes)
            if is_sem_dup:
                return True, f"Semantic duplicate: {sem_reason}"

            for prev in existing_scenes:
                prev_text = prev.get("spoken_text", "")
                if not prev_text:
                    continue
                if _token_overlap(text, prev_text) > 0.35:
                    return True, f"Overlaps with Scene {prev.get('scene_id')}: '{prev_text[:40]}...'"
                if text.strip().lower() == prev_text.strip().lower():
                    return True, "Exact duplicate of existing scene"

        # Check against recent upload titles
        if recent_titles:
            for rt in recent_titles:
                if _token_overlap(text, rt) > 0.40:
                    return True, f"Overlaps with recent upload: '{rt[:40]}...'"

        # Check against persistent memory of all past video thoughts
        if past_thoughts:
            for pt in past_thoughts:
                if not pt:
                    continue
                if _token_overlap(text, pt) > 0.35:
                    return True, f"Overlaps with past video thought: '{pt[:40]}...'"
                if text.strip().lower() == pt.strip().lower():
                    return True, f"Exact duplicate of past video thought: '{pt[:40]}...'"

        return False, "Clean"

    def generate_scene_chain(
        self,
        topic: str = "",
        voice: str = "am_adam",
        speed: float = 1.02,
        grounding_facts: Optional[Union[str, List[Dict[str, Any]]]] = None,
        channel_premise: str = "",
        **kwargs
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Executes ISCG v4.1 Audio-Driven Infinite Circular Loop generation:
        1. Step 1 (Triplet Anchors): Generates Scene 1 (Hook), Penultimate Scene (Final Fact),
           and Final Scene (Circular Loop Bridge) together. Measures empirical audio duration (T_anchors).
        2. Step 2 (Audio-Driven Middle Thoughts): Generates standalone thoughts one-by-one, measuring
           empirical Kokoro speech duration on each thought. Loops until cumulative duration reaches >= 30.0s.
        3. Step 3 (Script Assembly): Assembles [Hook, Middle Thoughts..., Penultimate Fact, Final Loop Scene].
           Accepts whatever final duration results naturally without hard min/max clamping or trimming.
        4. Step 4 (Normalization & Emotion Pass): Polishes punctuation for Kokoro neural TTS and ensures
           spoken_text and phonetic_text are strictly synchronized.
        5. Step 5 (Dynamic SEO): Generates high-CTR title, custom description, and tags.
        """
        print(f"\n🧠 [ISCG v4.1] Generating audio-driven circular script (Natural stop filter at >= 30.0s, no hard min/max clamping)...")
        recent_titles = _load_upload_history_titles()
        past_thoughts = _load_past_spoken_thoughts()
        grounding_text = _normalize_grounding_facts(grounding_facts or kwargs.get("grounding_facts"))
        resolved_premise = (channel_premise or kwargs.get("channel_premise") or self.channel_premise or "").strip()

        used_queries: List[str] = []
        from engine.managers.voice_normalizer import VoiceNormalizer

        # ─── STEP 1: TRIPLET ANCHORS (HOOK, PENULTIMATE FACT, ENDING PAYOFF) ────
        print("🎯 [STEP 1] Generating Anchors (Scene 1 Hook, Penultimate Fact & Ending Payoff)...", flush=True)
        hook_scene, penultimate_scene, ending_scene = self._generate_anchor_bookends(
            topic=topic,
            used_queries=used_queries,
            recent_titles=recent_titles,
            past_thoughts=past_thoughts,
            grounding_facts=grounding_text,
            channel_premise=resolved_premise
        )
        used_queries.append(hook_scene["stock_video_query"])
        used_queries.append(penultimate_scene["stock_video_query"])
        used_queries.append(ending_scene["stock_video_query"])

        d_hook = VoiceNormalizer.measure_duration_quick(hook_scene["spoken_text"], voice=voice, speed=speed)
        d_penult = VoiceNormalizer.measure_duration_quick(penultimate_scene["spoken_text"], voice=voice, speed=speed)
        d_end = VoiceNormalizer.measure_duration_quick(ending_scene["spoken_text"], voice=voice, speed=speed)
        t_anchors = round(d_hook + d_penult + d_end, 2)

        print(f"   ⏱️ [ANCHOR TIMINGS] Hook: {d_hook:.2f}s | Penultimate: {d_penult:.2f}s | Ending: {d_end:.2f}s (Anchors subtotal: {t_anchors:.2f}s)")
        print(f"   ✅ Scene 1 (Hook): '{hook_scene['spoken_text']}'")
        print(f"   ✅ Penultimate Scene: '{penultimate_scene['spoken_text']}'")
        print(f"   ✅ Final Scene (Ending): '{ending_scene['spoken_text']}'")

        # ─── STEP 2: AUDIO-DRIVEN MIDDLE THOUGHTS LOOP ─────────────────────────
        current_total = t_anchors
        middle_scenes: List[Dict[str, Any]] = []
        scene_counter = 2
        # Natural filter: Generate middle thoughts until cumulative audio crosses 30.0s,
        # then stop and accept whatever final duration is produced (no hard min/max clamping or popping).
        stop_threshold = 30.0
        max_middle_scenes = 15

        print(f"🔄 [STEP 2] Synthesizing middle thoughts until cumulative duration reaches >= {stop_threshold:.1f}s (current: {current_total:.2f}s)...", flush=True)

        while (current_total < stop_threshold) and len(middle_scenes) < max_middle_scenes:
            print(f"   Generating Middle Thought #{len(middle_scenes)+1} (projected total: {current_total:.2f}s)...", flush=True)
            mid_scene = self._generate_random_thought(
                scene_num=scene_counter,
                existing_scenes=[hook_scene] + middle_scenes + [penultimate_scene, ending_scene],
                used_queries=used_queries,
                recent_titles=recent_titles,
                past_thoughts=past_thoughts,
                grounding_facts=grounding_text,
                topic=topic,
                channel_premise=resolved_premise
            )
            d_mid = VoiceNormalizer.measure_duration_quick(mid_scene["spoken_text"], voice=voice, speed=speed)
            current_total = round(current_total + d_mid, 2)
            middle_scenes.append(mid_scene)
            used_queries.append(mid_scene["stock_video_query"])
            print(f"   ✅ Middle Thought #{len(middle_scenes)}: '{mid_scene['spoken_text'][:55]}...' (+{d_mid:.2f}s -> projected total: {current_total:.2f}s)")
            scene_counter += 1

        # ─── STEP 3: ASSEMBLE FULL SCRIPT (NO HARD POPPING / TRIMMING) ────────
        # Accept whatever the final duration is without trimming or popping
        scenes: List[Dict[str, Any]] = [hook_scene] + middle_scenes + [penultimate_scene, ending_scene]
        for idx, sc in enumerate(scenes):
            sc["scene_id"] = idx + 1

        final_dur = sum(VoiceNormalizer.measure_duration_quick(s.get("spoken_text", ""), voice=voice, speed=speed) for s in scenes)
        print(f"🧩 [STEP 3] Assembled {len(scenes)} scenes. Projected cumulative audio: {final_dur:.2f}s (Accepted in full without trimming).")

        # ─── STEP 4: NORMALIZATION & EMOTION PASS (KOKORO AUDIO POLISHER) ────
        print("🎭 [STEP 4] Running Normalization & Emotion Pass for Kokoro TTS...", flush=True)
        scenes = self._normalize_and_emotify_script(scenes, channel_premise=resolved_premise)

        # Strictly synchronize phonetic_text on every scene to eliminate split-brain bugs
        for sc in scenes:
            sc["phonetic_text"] = VoiceNormalizer.normalize_text(sc.get("spoken_text", ""))

        total_words = sum(len(s.get("spoken_text", "").split()) for s in scenes)
        final_measured_duration = sum(
            VoiceNormalizer.measure_duration_quick(s.get("spoken_text", ""), voice=voice, speed=speed)
            for s in scenes
        )
        print(f"🎯 [SCRIPT ASSEMBLED] {len(scenes)} scenes, {total_words} words (Empirical Kokoro duration: ~{final_measured_duration:.1f}s, landing naturally without trimming).")

        # ─── STEP 5: DYNAMIC SEO METADATA GENERATION ──────────────────────────
        print("🏷️  [STEP 5] Generating Dynamic, Video-Specific SEO Metadata...", flush=True)
        seo_data = self._generate_seo(scenes=scenes, topic=topic, recent_titles=recent_titles)
        print(f"   ✅ Title: '{seo_data.get('title')}'")

        return scenes, seo_data

    # ─── ANCHOR & SCENE GENERATION METHODS ────────────────────────────────────

    def _generate_anchor_bookends(
        self,
        topic: str = "",
        used_queries: Optional[List[str]] = None,
        recent_titles: Optional[List[str]] = None,
        past_thoughts: Optional[List[str]] = None,
        grounding_facts: Optional[Union[str, List[Dict[str, Any]]]] = None,
        channel_premise: str = "",
        *args,
        **kwargs
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        """
        Generates Scene 1 (Hook), Penultimate Scene (Setting up conclusion), and
        Final Scene (Intentional Payoff Ending: Punchline, Observation, Provocation,
        Resolution, or Natural Circular Loop) TOGETHER in a single LLM call.
        If duplicates or quality audits fail, passes targeted feedback to the LLM.
        """
        grounding_text = _normalize_grounding_facts(grounding_facts)
        sys_prompt = self.prompts.get("triplet_anchor_scenes", {}).get(
            "system_prompt",
            self.prompts.get("paired_anchor_scene", {}).get(
                "system_prompt",
                "You write high-retention YouTube Shorts scripts. Generate THREE anchor scenes: 'hook_scene', 'penultimate_scene', and 'ending_scene' (which can be a punchline, observation, provocation, resolution, or natural loop). Return ONLY valid JSON."
            )
        )
        user_prompt = "Generate a compelling Scene 1 hook thought and a Final Scene loopback bridge or payoff ending with a Penultimate Scene thought that delivers an intentional conclusion (a punchline, thought-provoking observation, clean resolution, or natural circular loop)."
        resolved_topic = (topic or kwargs.get("topic") or "").strip()
        if resolved_topic:
            user_prompt += f" Theme/Topic: {resolved_topic}."
        premise = (channel_premise or kwargs.get("channel_premise") or self.channel_premise or "").strip()
        if premise:
            user_prompt += f"\n\nChannel Premise / Identity: {premise}"
        if grounding_text:
            user_prompt += f"\n\n{grounding_text}\n(Where relevant, draw upon these verified inspiration references for your hook or penultimate fact. Avoid presenting unverified additions as established facts)."

        feedback = ""
        for attempt in range(4):
            try:
                curr_user_prompt = user_prompt
                if feedback:
                    curr_user_prompt += f"\n\nCRITICAL RETRY INSTRUCTION: The previous attempt was rejected because: '{feedback}'. Please regenerate, ensuring each thought is completely fresh, original, and not a duplicate."

                res = self.llm.generate_json(
                    system_prompt=sys_prompt,
                    user_prompt=curr_user_prompt,
                    temperature=0.7 if attempt > 0 else 0.6,
                    task_name="script_gen"
                )
                hook_data = res.get("hook_scene", {})
                penultimate_data = res.get("penultimate_scene", {})
                ending_data = res.get("ending_scene") or res.get("loop_scene") or res.get("loop_outro_scene") or {}

                hook_text = hook_data.get("spoken_text", "").strip()
                penultimate_text = penultimate_data.get("spoken_text", "").strip()
                ending_text = ending_data.get("spoken_text", "").strip()

                # Clean hook
                hook_text = re.sub(r"^[.…\-—\s]+", "", hook_text).strip()
                if hook_text and hook_text[0].islower():
                    hook_text = hook_text[0].upper() + hook_text[1:]

                # Clean penultimate
                penultimate_text = re.sub(r"^[.…\-—\s]+", "", penultimate_text).strip()
                if penultimate_text and penultimate_text[0].islower():
                    penultimate_text = penultimate_text[0].upper() + penultimate_text[1:]

                # Clean ending
                ending_text = re.sub(r"^[.…\-—\s]+", "", ending_text).strip()

                # Validate hook
                is_dup_h, reason_h = self._is_duplicate_thought(hook_text, [], recent_titles, past_thoughts)
                if is_dup_h:
                    feedback = f"Hook rejected: {reason_h}"
                    print(f"   🔄 [DEDUP CHECK] {feedback}. Retrying...")
                    continue

                # Handle penultimate: if missing (e.g. from 2-scene legacy mock), generate one!
                if not penultimate_text:
                    pen_res = self._generate_random_thought(
                        scene_num=2,
                        existing_scenes=[{"spoken_text": hook_text}, {"spoken_text": ending_text}],
                        used_queries=used_queries,
                        recent_titles=recent_titles,
                        past_thoughts=past_thoughts,
                        grounding_facts=grounding_text,
                        topic=resolved_topic,
                        channel_premise=premise
                    )
                    penultimate_text = pen_res["spoken_text"]
                    penultimate_query = pen_res["stock_video_query"]
                else:
                    is_dup_p, reason_p = self._is_duplicate_thought(
                        penultimate_text,
                        [{"spoken_text": hook_text}],
                        recent_titles,
                        past_thoughts
                    )
                    if is_dup_p:
                        feedback = f"Penultimate scene rejected: {reason_p}"
                        print(f"   🔄 [DEDUP CHECK] {feedback}. Retrying...")
                        continue
                    penultimate_query = penultimate_data.get("stock_video_query")

                # Determine ending intent: prefer explicit ending_type; if absent, treat '...' as loop
                ending_type = str(ending_data.get("ending_type", "")).strip().lower()
                if ending_type:
                    is_intended_loop = ending_type in ("circular_loop", "loop", "circular")
                else:
                    # Legacy response-field compatibility: if ending_type is absent,
                    # treat endings already ending in '...' or legacy loop scene fields as a loop.
                    # Do not infer loop intent merely from trailing words such as is, are, by, or that.
                    is_legacy_loop_field = bool(res.get("loop_scene") or res.get("loop_outro_scene"))
                    is_intended_loop = ending_text.endswith("...") or is_legacy_loop_field

                if is_intended_loop:
                    if not ending_text.endswith("..."):
                        ending_text = ending_text.rstrip(".!? ") + "..."
                    is_circ, circ_reason = is_valid_circular_bridge(ending_text, hook_text)
                    if not is_circ:
                        feedback = f"Circular loop ending rejected: {circ_reason}"
                        print(f"   🔄 [DEDUP CHECK] {feedback}. Retrying...")
                        continue
                else:
                    # Standalone payoff: punchline, observation, provocation, resolution
                    if not (ending_text.endswith(".") or ending_text.endswith("!") or ending_text.endswith("?")):
                        ending_text = ending_text.rstrip(" ,-—") + "."
                    passed, reason = LoopAuditorSkill.audit_loop(ending_text, hook_text, ending_type=ending_type)
                    if not passed:
                        feedback = f"Ending scene rejected: {reason}"
                        print(f"   🔄 [DEDUP CHECK] {feedback}. Retrying...")
                        continue

                if hook_text.strip() and penultimate_text.strip() and ending_text.strip():
                    hook_scene = {
                        "scene_id": 1,
                        "spoken_text": hook_text,
                        "stock_video_query": self._pick_query(hook_data.get("stock_video_query"), used_queries)
                    }
                    penultimate_scene = {
                        "scene_id": None,
                        "spoken_text": penultimate_text,
                        "stock_video_query": self._pick_query(penultimate_query, used_queries)
                    }
                    ending_scene = {
                        "scene_id": None,
                        "spoken_text": ending_text,
                        "stock_video_query": self._pick_query(ending_data.get("stock_video_query"), used_queries),
                        "ending_type": ending_type or ("circular_loop" if is_intended_loop else "standalone")
                    }
                    return hook_scene, penultimate_scene, ending_scene

            except Exception as e:
                print(f"   ⚠️ Triplet anchor attempt {attempt+1} failed: {e}")

        # Exhausted all attempts without producing fresh triplet anchors
        raise RuntimeError(
            f"Failed to generate fresh triplet anchors after 4 attempts (last feedback: {feedback})"
        )

    def _generate_paired_anchors(
        self,
        topic: str = "",
        used_queries: Optional[List[str]] = None,
        recent_titles: Optional[List[str]] = None,
        channel_premise: str = "",
        *args,
        **kwargs
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Backward compatibility wrapper returning (hook_scene, ending_scene)."""
        h, p, e = self._generate_anchor_bookends(
            topic=topic,
            used_queries=used_queries,
            recent_titles=recent_titles,
            past_thoughts=_load_past_spoken_thoughts(),
            channel_premise=channel_premise
        )
        return h, e

    def _generate_random_thought(
        self,
        scene_num: int,
        existing_scenes: List[Dict[str, Any]],
        used_queries: Optional[List[str]] = None,
        recent_titles: Optional[List[str]] = None,
        past_thoughts: Optional[List[str]] = None,
        grounding_facts: Optional[Union[str, List[Dict[str, Any]]]] = None,
        topic: str = "",
        channel_premise: str = "",
        *args,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Generates a single standalone observation, fact, or perspective shift.
        If rejected due to duplication or cynical audit, passes targeted feedback to the LLM.
        """
        grounding_text = _normalize_grounding_facts(grounding_facts)
        already_used = [s.get("spoken_text", "") for s in existing_scenes if s.get("spoken_text")]
        already_used_summary = "\n".join(f"- {t}" for t in already_used[-6:])

        sys_prompt = self.prompts.get("thought_scene", {}).get(
            "system_prompt",
            "Give me ONE standalone, mind-bending random thought, observation, or counterintuitive fact that makes you stop and think. Simple, relatable, and original. Return ONLY JSON with 'spoken_text' and 'stock_video_query'."
        )
        user_prompt = f"ALREADY USED THOUGHTS IN THIS VIDEO:\n{already_used_summary}\n\nGenerate Scene {scene_num}: Exactly one standalone thought, observation, or surprising everyday fact."
        resolved_topic = (topic or kwargs.get("topic") or "").strip()
        if resolved_topic:
            user_prompt += f"\n\nVideo Topic / Thematic Context: {resolved_topic} (Use this as inspiration or context; unexpected or surprising complementary thoughts across psychology, science, or daily life are welcome)."
        premise = (channel_premise or kwargs.get("channel_premise") or self.channel_premise or "").strip()
        if premise:
            user_prompt += f"\n\nChannel Premise / Identity: {premise}"
        if grounding_text:
            user_prompt += f"\n\n{grounding_text}\n(Where relevant, draw upon these verified inspiration references. Avoid presenting unsupported additions as established facts)."

        feedback = ""
        for attempt in range(4):
            try:
                curr_user_prompt = user_prompt
                if feedback:
                    curr_user_prompt += f"\n\nCRITICAL RETRY REQUIREMENT: The previous thought was REJECTED because: '{feedback}'. You must generate a completely DIFFERENT, unique thought with a fresh premise and zero duplicate words."

                res = self.llm.generate_json(
                    system_prompt=sys_prompt,
                    user_prompt=curr_user_prompt,
                    temperature=0.7 if attempt > 0 else 0.6,
                    task_name="script_gen"
                )
                text = res.get("spoken_text", "").strip()
                text = re.sub(r"^[.…\-—\s]+", "", text).strip()

                is_dup, reason = self._is_duplicate_thought(text, existing_scenes, recent_titles, past_thoughts)
                if is_dup:
                    print(f"   🔄 [DEDUP CHECK] Duplicate/cliché detected: {reason}. Asking LLM to recreate...")
                    feedback = reason
                    continue

                if text and text.strip():
                    return {
                        "scene_id": scene_num,
                        "spoken_text": text,
                        "stock_video_query": self._pick_query(res.get("stock_video_query"), used_queries)
                    }
            except Exception as e:
                print(f"   ⚠️ Scene {scene_num} attempt {attempt+1} failed: {e}")

        # Exhausted all attempts without producing a fresh standalone thought
        raise RuntimeError(
            f"Failed to generate fresh standalone thought for Scene {scene_num} after 4 attempts (last feedback: {feedback})"
        )

    # Backward compatibility aliases
    _generate_pillar_scene = _generate_random_thought
    def _generate_single_pillar_scene(self, scene_num: int, *args, **kwargs) -> Dict[str, Any]:
        existing = kwargs.get("existing_scenes") or []
        queries = kwargs.get("used_queries") or []
        grounding = kwargs.get("grounding_facts")
        topic = kwargs.get("topic") or ""
        premise = kwargs.get("channel_premise") or ""
        return self._generate_random_thought(
            scene_num=scene_num,
            existing_scenes=existing,
            used_queries=queries,
            grounding_facts=grounding,
            topic=topic,
            channel_premise=premise
        )

    def _generate_hook(
        self,
        topic: str = "",
        channel_premise: str = "",
        used_queries: Optional[List[str]] = None,
        recent_titles: Optional[List[str]] = None,
        *args,
        **kwargs
    ) -> Dict[str, Any]:
        """Legacy helper: Generates Scene 1 hook with duplicate check."""
        h, _, _ = self._generate_anchor_bookends(
            topic=topic,
            used_queries=used_queries,
            recent_titles=recent_titles,
            past_thoughts=_load_past_spoken_thoughts(),
            channel_premise=channel_premise
        )
        return h

    def _generate_premise_anchor(
        self,
        topic: str = "",
        hook_text: str = "",
        existing_scenes: Optional[List[Dict[str, Any]]] = None,
        used_queries: Optional[List[str]] = None,
        recent_titles: Optional[List[str]] = None,
        *args,
        **kwargs
    ) -> Dict[str, Any]:
        """Legacy helper kept for backwards compatibility tests."""
        anchor = random.choice(PREMISE_ANCHOR_LINES)
        return {
            "scene_id": 2,
            "spoken_text": anchor,
            "stock_video_query": self._pick_query("kinetic sand squishing satisfying", used_queries)
        }

    def _generate_cta_closer(
        self,
        scene_num: int,
        existing_scenes: List[Dict[str, Any]],
        used_queries: Optional[List[str]] = None,
        recent_titles: Optional[List[str]] = None,
        hook_text: str = "",
        *args,
        **kwargs
    ) -> Dict[str, Any]:
        """Legacy call-to-action closer generator kept for backward compatibility."""
        already_used = [s.get("spoken_text", "") for s in existing_scenes]
        available_closers = [c for c in BRAINBLUD_CLOSERS if not any(c.lower() in prev.lower() for prev in already_used)]
        chosen = random.choice(available_closers or BRAINBLUD_CLOSERS)
        chosen = chosen.rstrip(".!?…-— ") + "."

        return {
            "scene_id": scene_num,
            "spoken_text": chosen,
            "stock_video_query": self._pick_query("soap carving cubes ASMR", used_queries)
        }

    # Backward compatibility aliases
    _generate_brainblud_closer = _generate_cta_closer
    _generate_loop_outro = _generate_cta_closer

    def _normalize_and_emotify_script(
        self,
        scenes: List[Dict[str, Any]],
        channel_premise: str = ""
    ) -> List[Dict[str, Any]]:
        """
        Collects the whole assembled script and passes it to the AI
        to normalize the flow, eliminate formulaic/AI writing patterns,
        and add natural conversational punctuation (?, !, ,, —, .)
        for neural TTS inflection without altering factual details or breaking endings.
        """
        polish_entry = self.prompts.get("script_polish", {})
        if isinstance(polish_entry, dict):
            sys_prompt = polish_entry.get("system_prompt", "")
        elif isinstance(polish_entry, str):
            sys_prompt = polish_entry
        else:
            sys_prompt = ""
        if not sys_prompt:
            sys_prompt = (
                "You are an audio voiceover director. Take these video scenes and enhance "
                "punctuation (?, !, ,, —, .) so neural TTS speaks naturally with curiosity and punch. Return JSON with 'scenes'."
            )
        scenes_payload = [{"scene_id": s["scene_id"], "spoken_text": s["spoken_text"]} for s in scenes]

        premise = (channel_premise or self.channel_premise or "").strip()
        premise_section = f"CHANNEL PREMISE / TONE: {premise}\n\n" if premise else ""

        user_prompt = (
            f"{premise_section}SCENES TO NORMALIZE & POLISH:\n"
            f"{json.dumps(scenes_payload, indent=2)}\n\n"
            "Refine each scene for natural spoken cadence, removing formulaic AI crutches, hype, and stiff phrasing "
            "while strictly preserving factual substance and numerical figures. "
            "If the final scene ends with '...', you MUST preserve the trailing '...'! "
            "If the final scene ends with '.', '!', or '?', preserve clean terminal punctuation."
        )

        try:
            res = self.llm.generate_json(
                system_prompt=sys_prompt,
                user_prompt=user_prompt,
                temperature=0.3,
                task_name="script_gen"
            )
            polished_list = res.get("scenes", [])
            if isinstance(polished_list, list) and len(polished_list) == len(scenes):
                # Detect whether final scene was intentionally circular before polish pass
                final_scene = scenes[-1] if scenes else {}
                final_ending_type = str(final_scene.get("ending_type", "")).strip().lower()
                if final_ending_type:
                    final_was_circular = final_ending_type in ("circular_loop", "loop", "circular")
                else:
                    final_was_circular = bool(final_scene.get("spoken_text", "").strip().endswith("..."))

                for orig_s, polished_s in zip(scenes, polished_list):
                    if isinstance(polished_s, dict) and polished_s.get("spoken_text"):
                        new_text = polished_s["spoken_text"].strip()
                        orig_text = orig_s.get("spoken_text", "").strip()

                        # Guard: Factuality / number preservation
                        # The normalization stage must neither drop, alter, reorder, nor invent numerical claims.
                        orig_nums = _extract_number_tokens(orig_text)
                        new_nums = _extract_number_tokens(new_text)
                        if orig_nums != new_nums:
                            # Numbers were dropped, altered, reordered, or invented — safely retain original text
                            continue

                        # Guard: Non-empty and reasonable length (at least 70% of original word count)
                        if new_text and len(new_text.split()) >= len(orig_text.split()) * 0.7:
                            orig_s["spoken_text"] = new_text

                # Preserve ending intent: circular loop (...) vs standalone ending (., !, ?)
                if scenes:
                    final_text = scenes[-1].get("spoken_text", "").strip()
                    if final_was_circular:
                        if not final_text.endswith("..."):
                            scenes[-1]["spoken_text"] = final_text.rstrip(".!? ") + "..."
                    else:
                        # Standalone ending: ensure it does not end with accidental ellipsis
                        if final_text.endswith("..."):
                            scenes[-1]["spoken_text"] = final_text.rstrip(".!? ") + "."
                        elif not (final_text.endswith(".") or final_text.endswith("!") or final_text.endswith("?")):
                            scenes[-1]["spoken_text"] = final_text.rstrip(" ,-—") + "."

                print(f"   ✅ [NATURAL VOICE PASS] Successfully refined {len(scenes)} scenes for natural spoken cadence.")
        except Exception as e:
            print(f"   ⚠️ [NATURAL VOICE PASS] Polishing pass skipped due to: {e}. Keeping raw scenes.")

        # Synchronize phonetic_text on all scenes to preserve pipeline contract and avoid split-brain audio
        from engine.managers.voice_normalizer import VoiceNormalizer
        for s in scenes:
            s["phonetic_text"] = VoiceNormalizer.normalize_text(s.get("spoken_text", ""))

        return scenes

    def _generate_seo(
        self,
        scenes: List[Dict[str, Any]],
        topic: str = "",
        premise_line: str = "",
        recent_titles: Optional[List[str]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Generates dynamic, video-specific SEO grounded in the topic and assembled script."""
        full_script = "\n".join(f"Scene {s.get('scene_id') or idx+1}: {s.get('spoken_text', '')}" for idx, s in enumerate(scenes))
        active_topic = topic or premise_line or ""

        seo_prompt_entry = self.prompts.get("seo_gen", {})
        sys_prompt = seo_prompt_entry.get(
            "system_prompt",
            "You generate accurate, compelling, and natural YouTube Shorts metadata (title, description, tags) grounded strictly in the provided script and topic. Output valid JSON with 'title', 'description', 'tags'."
        )
        user_template = seo_prompt_entry.get("user_template", "")
        if user_template:
            try:
                user_prompt = user_template.format(script_text=full_script, topic=active_topic or "General")
            except KeyError:
                user_prompt = f"TOPIC: {active_topic or 'General'}\nSCRIPT:\n{full_script}\n\nGenerate accurate, compelling YouTube Shorts metadata reflecting this specific script."
        else:
            user_prompt = f"TOPIC: {active_topic or 'General'}\nSCRIPT:\n{full_script}\n\nGenerate accurate, compelling YouTube Shorts metadata reflecting this specific script."

        try:
            res = self.llm.generate_json(
                system_prompt=sys_prompt,
                user_prompt=user_prompt,
                temperature=0.3,
                task_name="seo_gen"
            )
            raw_title = res.get("title", "").strip()
            raw_desc = res.get("description", "").strip()
            tags = res.get("tags", [])

            if raw_title:
                if "#shorts" not in raw_title.lower():
                    raw_title = f"{raw_title.rstrip('.!?')} #shorts"
                aligned_title = TitleScriptAlignmentSkill.align_title(
                    title=raw_title,
                    scenes=scenes,
                    upload_history_titles=recent_titles or [],
                    topic=active_topic
                )
            else:
                fallback_base = derive_grounded_fallback_title(scenes=scenes, topic=active_topic)
                aligned_title = TitleScriptAlignmentSkill.align_title(
                    title=fallback_base,
                    scenes=scenes,
                    upload_history_titles=recent_titles or [],
                    topic=active_topic
                )

            # Numerical Factuality Check: Ensure title's numerical claims are supported by the final script.
            # Multiplicity-aware: token counts in title cannot exceed token counts in full_script.
            # Topic alone cannot justify numbers absent from the script.
            # (Lexical token check; does not verify semantic unit relationships).
            from collections import Counter
            from engine.managers.iterative_script_generator import _extract_number_tokens
            script_counts = Counter(_extract_number_tokens(full_script))
            title_counts = Counter(_extract_number_tokens(aligned_title))
            unsupported_title_nums = []
            for num, count in title_counts.items():
                if count > script_counts.get(num, 0):
                    unsupported_title_nums.extend([num] * (count - script_counts.get(num, 0)))

            if unsupported_title_nums:
                # Realign using script-grounded fallback title that has no unsupported numbers
                fallback_cand = derive_grounded_fallback_title(scenes=scenes, topic=active_topic)
                aligned_title = TitleScriptAlignmentSkill.align_title(
                    title=fallback_cand,
                    scenes=scenes,
                    upload_history_titles=recent_titles or [],
                    topic=active_topic
                )

            # Strip any repeated title from description body
            clean_desc = raw_desc
            if clean_desc.startswith(aligned_title):
                clean_desc = clean_desc[len(aligned_title):].strip()
            elif raw_title and clean_desc.startswith(raw_title):
                clean_desc = clean_desc[len(raw_title):].strip()

            if not clean_desc or len(clean_desc) < 20:
                clean_desc = derive_grounded_fallback_description(scenes=scenes, topic=active_topic)

            # Exact title on top always, followed by an empty line, then the SEO description
            full_description = f"{aligned_title}\n\n{clean_desc}"

            if not isinstance(tags, list) or not tags:
                from engine.managers.pipeline_runner import extract_keywords
                script_kws = extract_keywords(full_script, max_keywords=8)
                tags = [active_topic.lower()] if active_topic else []
                tags.extend([kw.lower() for kw in script_kws if kw.lower() not in tags])
                if "shorts" not in tags:
                    tags.append("shorts")

            return {
                "title": aligned_title,
                "description": full_description,
                "tags": [str(t).strip() for t in tags if str(t).strip()]
            }
        except Exception as e:
            print(f"⚠️ [SEO] Dynamic SEO generation failed: {e}. Falling back to rule-based SEO.")
            return derive_grounded_fallback_seo(
                scenes=scenes,
                topic=active_topic,
                recent_titles=recent_titles
            )

    _derive_grounded_fallback_title = staticmethod(derive_grounded_fallback_title)
    _derive_grounded_fallback_description = staticmethod(derive_grounded_fallback_description)
    _derive_grounded_fallback_seo = staticmethod(derive_grounded_fallback_seo)
    _synchronize_seo_description_header = staticmethod(synchronize_seo_description_header)
    _generate_umbrella_seo = _generate_seo  # Backward compatibility alias

    def _pick_query(self, preferred: Optional[str] = None, used: Optional[List[str]] = None) -> str:
        """Picks a unique, high-motion satisfying visual query."""
        used = used or []
        if preferred and preferred.strip() and preferred not in used:
            return preferred.strip()
        available = [q for q in SATISFYING_VISUAL_QUERIES if q not in used]
        if available:
            return random.choice(available)
        return random.choice(SATISFYING_VISUAL_QUERIES)
