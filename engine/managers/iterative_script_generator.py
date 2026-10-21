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
from typing import List, Dict, Any, Tuple, Optional

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
    check_loop_repeats_hook,
    COMPILATION_LOOP_BRIDGES,
    UMBRELLA_TITLE_TEMPLATES,
    _token_overlap,
    _load_upload_history_titles,
    _load_curated_replacements
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


class IterativeScriptGenerator:
    """
    High-Retention Circular Script Generator with Triplet Anchor Generation (v4.1),
    Audio-Driven Dynamic Duration Loop, and Targeted LLM Recreation.
    """

    def __init__(self, llm_manager: Optional[Any] = None, quality_tracker: Optional[LLMQualityTracker] = None):
        if llm_manager is None:
            from engine.managers.llm_manager import LLMManager
            llm_manager = LLMManager()
        self.llm = llm_manager
        self.qt = quality_tracker or LLMQualityTracker()
        self.prompts = self._load_prompts()

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

        used_queries: List[str] = []
        from engine.managers.voice_normalizer import VoiceNormalizer

        # ─── STEP 1: TRIPLET ANCHORS (HOOK, PENULTIMATE FACT, LOOP BRIDGE) ────
        print("🎯 [STEP 1] Generating Triplet Anchors (Scene 1 Hook, Penultimate Fact & Final Loop Bridge)...", flush=True)
        hook_scene, penultimate_scene, loop_scene = self._generate_anchor_bookends(
            topic=topic,
            used_queries=used_queries,
            recent_titles=recent_titles,
            past_thoughts=past_thoughts
        )
        used_queries.append(hook_scene["stock_video_query"])
        used_queries.append(penultimate_scene["stock_video_query"])
        used_queries.append(loop_scene["stock_video_query"])

        d_hook = VoiceNormalizer.measure_duration_quick(hook_scene["spoken_text"], voice=voice, speed=speed)
        d_penult = VoiceNormalizer.measure_duration_quick(penultimate_scene["spoken_text"], voice=voice, speed=speed)
        d_loop = VoiceNormalizer.measure_duration_quick(loop_scene["spoken_text"], voice=voice, speed=speed)
        t_anchors = round(d_hook + d_penult + d_loop, 2)

        print(f"   ⏱️ [ANCHOR TIMINGS] Hook: {d_hook:.2f}s | Penultimate: {d_penult:.2f}s | Loop: {d_loop:.2f}s (Anchors subtotal: {t_anchors:.2f}s)")
        print(f"   ✅ Scene 1 (Hook): '{hook_scene['spoken_text']}'")
        print(f"   ✅ Penultimate Scene: '{penultimate_scene['spoken_text']}'")
        print(f"   ✅ Final Scene (Loop Bridge): '{loop_scene['spoken_text']}'")

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
                existing_scenes=[hook_scene] + middle_scenes + [penultimate_scene, loop_scene],
                used_queries=used_queries,
                recent_titles=recent_titles,
                past_thoughts=past_thoughts
            )
            d_mid = VoiceNormalizer.measure_duration_quick(mid_scene["spoken_text"], voice=voice, speed=speed)
            current_total = round(current_total + d_mid, 2)
            middle_scenes.append(mid_scene)
            used_queries.append(mid_scene["stock_video_query"])
            print(f"   ✅ Middle Thought #{len(middle_scenes)}: '{mid_scene['spoken_text'][:55]}...' (+{d_mid:.2f}s -> projected total: {current_total:.2f}s)")
            scene_counter += 1

        # ─── STEP 3: ASSEMBLE FULL SCRIPT (NO HARD POPPING / TRIMMING) ────────
        # Accept whatever the final duration is without trimming or popping
        scenes: List[Dict[str, Any]] = [hook_scene] + middle_scenes + [penultimate_scene, loop_scene]
        for idx, sc in enumerate(scenes):
            sc["scene_id"] = idx + 1

        final_dur = sum(VoiceNormalizer.measure_duration_quick(s.get("spoken_text", ""), voice=voice, speed=speed) for s in scenes)
        print(f"🧩 [STEP 3] Assembled {len(scenes)} scenes. Projected cumulative audio: {final_dur:.2f}s (Accepted in full without trimming).")

        # ─── STEP 4: NORMALIZATION & EMOTION PASS (KOKORO AUDIO POLISHER) ────
        print("🎭 [STEP 4] Running Normalization & Emotion Pass for Kokoro TTS...", flush=True)
        scenes = self._normalize_and_emotify_script(scenes)

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
        seo_data = self._generate_seo(scenes=scenes, recent_titles=recent_titles)
        print(f"   ✅ Title: '{seo_data.get('title')}'")

        return scenes, seo_data

    # ─── ANCHOR & SCENE GENERATION METHODS ────────────────────────────────────

    def _generate_anchor_bookends(
        self,
        topic: str = "",
        used_queries: Optional[List[str]] = None,
        recent_titles: Optional[List[str]] = None,
        past_thoughts: Optional[List[str]] = None
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        """
        Generates Scene 1 (Hook), Penultimate Scene (Final Standalone Fact), and
        Final Scene (Circular Loopback Bridge) TOGETHER in a single LLM call.
        Ensures the loop bridge transitions from penultimate scene and loops back into hook.
        If duplicates or quality audits fail, passes targeted feedback to the LLM.
        """
        sys_prompt = self.prompts.get("triplet_anchor_scenes", {}).get(
            "system_prompt",
            self.prompts.get("paired_anchor_scene", {}).get(
                "system_prompt",
                "You write viral YouTube Shorts with seamless infinite circular loops. Generate THREE specific scenes that anchor this video: 'hook_scene' (10-14 words), 'penultimate_scene' (10-14 words), and 'loop_scene' (6-12 words ending with ...). Return ONLY valid JSON."
            )
        )
        user_prompt = "Generate a viral Scene 1 hook thought and a Final Scene loopback bridge with a Penultimate Scene thought that flows seamlessly back into the hook's opening words."
        if topic and topic.strip():
            user_prompt += f" Theme/Vibe: {topic.strip()}."

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
                loop_data = res.get("loop_scene", {}) or res.get("loop_outro_scene", {})

                hook_text = hook_data.get("spoken_text", "").strip()
                penultimate_text = penultimate_data.get("spoken_text", "").strip()
                loop_text = loop_data.get("spoken_text", "").strip()

                # Clean hook
                hook_text = re.sub(r"^[.…\-—\s]+", "", hook_text).strip()
                if hook_text and hook_text[0].islower():
                    hook_text = hook_text[0].upper() + hook_text[1:]

                # Clean penultimate
                penultimate_text = re.sub(r"^[.…\-—\s]+", "", penultimate_text).strip()
                if penultimate_text and penultimate_text[0].islower():
                    penultimate_text = penultimate_text[0].upper() + penultimate_text[1:]

                # Clean loop
                loop_text = re.sub(r"^[.…\-—\s]+", "", loop_text).strip()
                if loop_text and not loop_text.endswith("..."):
                    loop_text = loop_text.rstrip(".!? ") + "..."

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
                        existing_scenes=[{"spoken_text": hook_text}, {"spoken_text": loop_text}],
                        used_queries=used_queries,
                        recent_titles=recent_titles,
                        past_thoughts=past_thoughts
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

                # Validate loop bridge
                repeats, rep_reason = check_loop_repeats_hook(loop_text, hook_text)
                if repeats:
                    feedback = f"Loop bridge rejected: repeats hook words ({rep_reason})"
                    print(f"   🔄 [DEDUP CHECK] {feedback}. Retrying...")
                    continue

                if hook_text and penultimate_text and loop_text and len(hook_text.split()) >= 6 and len(loop_text.split()) >= 3:
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
                    loop_scene = {
                        "scene_id": None,
                        "spoken_text": loop_text,
                        "stock_video_query": self._pick_query(loop_data.get("stock_video_query"), used_queries)
                    }
                    return hook_scene, penultimate_scene, loop_scene

            except Exception as e:
                print(f"   ⚠️ Triplet anchor attempt {attempt+1} failed: {e}")

        # Vetted fallback triplet
        available_triplets = [
            t for t in TRIPLET_CIRCULAR_FALLBACKS
            if not any(_token_overlap(t[0], pt) > 0.35 for pt in (past_thoughts or []))
        ]
        chosen = random.choice(available_triplets or TRIPLET_CIRCULAR_FALLBACKS)
        hook_scene = {
            "scene_id": 1,
            "spoken_text": chosen[0],
            "stock_video_query": self._pick_query("soap carving cubes ASMR", used_queries)
        }
        penultimate_scene = {
            "scene_id": None,
            "spoken_text": chosen[1],
            "stock_video_query": self._pick_query("resin lathe turning wood polishing", used_queries)
        }
        loop_scene = {
            "scene_id": None,
            "spoken_text": chosen[2],
            "stock_video_query": self._pick_query("sand pendulum harmonograph geometric", used_queries)
        }
        return hook_scene, penultimate_scene, loop_scene

    def _generate_paired_anchors(
        self,
        topic: str = "",
        used_queries: Optional[List[str]] = None,
        recent_titles: Optional[List[str]] = None
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Backward compatibility wrapper returning (hook_scene, loop_scene)."""
        h, p, l = self._generate_anchor_bookends(
            topic=topic,
            used_queries=used_queries,
            recent_titles=recent_titles,
            past_thoughts=_load_past_spoken_thoughts()
        )
        return h, l

    def _generate_random_thought(
        self,
        scene_num: int,
        existing_scenes: List[Dict[str, Any]],
        used_queries: Optional[List[str]] = None,
        recent_titles: Optional[List[str]] = None,
        past_thoughts: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Generates a single standalone random Reddit thought or logical everyday fact.
        If rejected due to duplication or cynical audit, passes targeted feedback to the LLM.
        """
        already_used = [s.get("spoken_text", "") for s in existing_scenes if s.get("spoken_text")]
        already_used_summary = "\n".join(f"- {t}" for t in already_used[-6:])

        sys_prompt = self.prompts.get("thought_scene", {}).get(
            "system_prompt",
            "Give me ONE standalone, mind-bending random Reddit thought or logical fact that makes you stop and think. Simple and relatable, 10-14 words. Return ONLY JSON with 'spoken_text' and 'stock_video_query'."
        )
        user_prompt = f"ALREADY USED THOUGHTS IN THIS VIDEO:\n{already_used_summary}\n\nGenerate Scene {scene_num}: Exactly one standalone thought or logical everyday fact (10-14 words)."

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

                if text and 7 <= len(text.split()) <= 18:
                    return {
                        "scene_id": scene_num,
                        "spoken_text": text,
                        "stock_video_query": self._pick_query(res.get("stock_video_query"), used_queries)
                    }
            except Exception as e:
                print(f"   ⚠️ Scene {scene_num} attempt {attempt+1} failed: {e}")

        # Draw clean vetted replacement from curated vault if LLM repeats
        vetted = _load_curated_replacements(count=30)
        for cand in vetted:
            is_dup, _ = self._is_duplicate_thought(cand, existing_scenes, recent_titles, past_thoughts)
            if not is_dup:
                return {
                    "scene_id": scene_num,
                    "spoken_text": cand,
                    "stock_video_query": self._pick_query(None, used_queries)
                }

        # Safe default
        return {
            "scene_id": scene_num,
            "spoken_text": "A bus ten minutes early is far worse than a bus ten minutes late.",
            "stock_video_query": self._pick_query(None, used_queries)
        }

    # Backward compatibility aliases
    _generate_pillar_scene = _generate_random_thought
    def _generate_single_pillar_scene(self, scene_num: int, *args, **kwargs) -> Dict[str, Any]:
        existing = kwargs.get("existing_scenes") or []
        queries = kwargs.get("used_queries") or []
        return self._generate_random_thought(scene_num, existing, queries)

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
            past_thoughts=_load_past_spoken_thoughts()
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

    def _normalize_and_emotify_script(self, scenes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Collects the whole assembled script and passes it to the AI
        to normalize the flow and add emotional punctuation (?, !, ,, —, .)
        for natural Kokoro TTS inflection without altering core thoughts or breaking circular loops.
        """
        sys_prompt = self.prompts.get("script_polish", {}).get(
            "system_prompt",
            "You are an audio voiceover director. Take these video scenes and enhance punctuation (?, !, ,, —, .) so Kokoro neural TTS speaks naturally with curiosity and punch. Return JSON with 'scenes'."
        )
        scenes_payload = [{"scene_id": s["scene_id"], "spoken_text": s["spoken_text"]} for s in scenes]
        user_prompt = f"SCENES TO NORMALIZE & EMOTIFY:\n{json.dumps(scenes_payload, indent=2)}\n\nEnhance punctuation for neural voice synthesis while preserving exact meaning. If the final scene ends with '...', you MUST preserve the trailing '...'!"

        try:
            res = self.llm.generate_json(
                system_prompt=sys_prompt,
                user_prompt=user_prompt,
                temperature=0.3,
                task_name="script_gen"
            )
            polished_list = res.get("scenes", [])
            if isinstance(polished_list, list) and len(polished_list) == len(scenes):
                for orig_s, polished_s in zip(scenes, polished_list):
                    if isinstance(polished_s, dict) and polished_s.get("spoken_text"):
                        new_text = polished_s["spoken_text"].strip()
                        if len(new_text.split()) >= len(orig_s["spoken_text"].split()) * 0.7:
                            orig_s["spoken_text"] = new_text

                # Ensure final loop scene ending in '...' is preserved
                if scenes and scenes[-1]["spoken_text"] and not scenes[-1]["spoken_text"].endswith("..."):
                    if scenes[-1]["spoken_text"].endswith((".", "!", "?")):
                        pass
                    else:
                        scenes[-1]["spoken_text"] = scenes[-1]["spoken_text"].rstrip(".!? ") + "..."

                print(f"   ✅ [EMOTION PASS] Successfully enhanced {len(scenes)} scenes with expressive punctuation.")
                return scenes
        except Exception as e:
            print(f"   ⚠️ [EMOTION PASS] Polishing pass skipped due to: {e}. Keeping raw scenes.")

        return scenes

    def _generate_seo(
        self,
        scenes: List[Dict[str, Any]],
        premise_line: str = "",
        recent_titles: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Generates dynamic, video-specific SEO based on the assembled script."""
        full_script = "\n".join(f"Scene {s.get('scene_id')}: {s.get('spoken_text', '')}" for s in scenes)

        sys_prompt = self.prompts.get("seo_gen", {}).get(
            "system_prompt",
            "Generate high-CTR YouTube Shorts metadata tailored to the specific video script provided. Output valid JSON with 'title', 'description', 'tags'."
        )
        user_prompt = f"Generate optimized YouTube metadata for this compilation script:\n{full_script}"

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
            if not isinstance(tags, list) or not tags:
                tags = [
                    "shower thoughts", "mind blowing facts", "psychology", "deep thoughts",
                    "brain glitches", "shorts", "relatable", "facts", "satisfying"
                ]

            if raw_title:
                if "#shorts" not in raw_title.lower():
                    raw_title = f"{raw_title.rstrip('.!?')} 🤯 #shorts"
                aligned_title = TitleScriptAlignmentSkill.align_title(
                    title=raw_title,
                    scenes=scenes,
                    upload_history_titles=recent_titles or []
                )
            else:
                aligned_title = TitleScriptAlignmentSkill.align_title(
                    title="Shower Thoughts That Blow Minds 🤯 #shorts",
                    scenes=scenes,
                    upload_history_titles=recent_titles or []
                )

            # Strip any repeated title from description body
            clean_desc = raw_desc
            if clean_desc.startswith(aligned_title):
                clean_desc = clean_desc[len(aligned_title):].strip()
            elif raw_title and clean_desc.startswith(raw_title):
                clean_desc = clean_desc[len(raw_title):].strip()

            if not clean_desc or len(clean_desc) < 25:
                clean_desc = (
                    "Mind-bending shower thoughts and psychological realizations that reset your perception of reality.\n\n"
                    "Subscribe to @metopato for daily perspective shifts!\n\n"
                    "#showerthoughts #psychology #deepthoughts #mindblowing #shorts"
                )

            # Exact title on top always, followed by an empty line, then the SEO description
            full_description = f"{aligned_title}\n\n{clean_desc}"

            return {
                "title": aligned_title,
                "description": full_description,
                "tags": [str(t).strip() for t in tags if str(t).strip()]
            }
        except Exception as e:
            print(f"⚠️ [SEO] Dynamic SEO generation failed: {e}. Falling back to rule-based SEO.")
            aligned_title = TitleScriptAlignmentSkill.align_title(
                title="Shower Thoughts That Blow Minds 🤯 #shorts",
                scenes=scenes,
                upload_history_titles=recent_titles or []
            )
            base_description = (
                "Mind-bending shower thoughts and psychological realizations that reset your daily perception.\n\n"
                "Subscribe to @metopato for daily perspective shifts!\n\n"
                "#showerthoughts #psychology #deepthoughts #mindblowing #shorts"
            )
            return {
                "title": aligned_title,
                "description": f"{aligned_title}\n\n{base_description}",
                "tags": [
                    "shower thoughts", "mind blowing facts", "psychology", "paradoxes",
                    "brain glitches", "deep thoughts", "shorts", "topato", "facts", "satisfying"
                ]
            }

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
