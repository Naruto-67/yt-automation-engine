"""
engine/managers/iterative_script_generator.py — High-Retention Circular Script Generator (v4.0)

Implements the high-voltage retention architecture:
1. Step 1 (Paired Anchor Generation): Generates Scene 1 (Hook) and the Final Scene (Loopback Outro)
   TOGETHER in a single LLM call. This guarantees a grammatically and logically airtight infinite loop.
2. Step 2 (Middle Fast-Paced Thoughts): Generates standalone random Reddit thoughts and logical everyday facts
   one by one, checking for duplicates, solipsism, and overused clichés across all scenes.
   Continues until total audio duration reaches 25–32s.
3. Step 3 (Assembly & Duration Guard): Assembles [Scene 1, Scene 2, Scene 3, ..., Final Loop Outro].
   Enforces strict duration ceiling (max 32.0s).
4. Step 4 (Normalization & Emotion Pass): Polishes punctuation (?, !, ,, —, .) for Kokoro neural TTS.
5. Step 5 (Dynamic Video-Specific SEO): Generates unique high-CTR title, custom description starting
   with {title}\n\n{description}, and tags tailored to the actual script.
"""

from __future__ import annotations

import re
import os
import json
import yaml
import random
import pathlib
from typing import List, Dict, Any, Tuple, Optional

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

# Vetted circular paired anchors (Hook -> Loop Outro) for fallback situations
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


class IterativeScriptGenerator:
    """
    High-Retention Circular Script Generator with Paired Hook-Loop Generation,
    Duration Budgeting (25-32s), and Dynamic SEO.
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
        """Estimates natural spoken duration in seconds (~3.1 words per second + 0.25s pause)."""
        words = len(text.split())
        return round(words / 3.1 + 0.25, 2)

    def _is_duplicate_thought(
        self,
        text: str,
        existing_scenes: List[Dict[str, Any]],
        recent_titles: Optional[List[str]] = None
    ) -> Tuple[bool, str]:
        """
        Validates thought uniqueness against existing scenes in this video
        and recent upload history using both token overlap and semantic deduplication.
        Also blocks solipsism and overused clichés.
        """
        if not text or not text.strip():
            return True, "Empty text"

        # Check solipsism and overused clichés
        passed_wall, wall_reason = CynicalHumanAuditor.audit_text(text)
        if not passed_wall:
            return True, wall_reason

        # Check semantic and token-level deduplication against existing scenes
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

        return False, "Clean"

    def generate_scene_chain(
        self,
        topic: str = "",
        max_duration: float = 32.0,
        target_duration: Optional[int] = None,
        **kwargs
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Executes the high-retention circular script generation (v4.0):
        1. Step 1: Paired Anchor Generation:
           Generates Scene 1 (Hook) and the Final Scene (Loopback Outro) together in one LLM call.
           This locks in a grammatically and logically seamless circular loop back to Scene 1.
        2. Step 2: Middle Thoughts:
           Generates standalone random Reddit thoughts and logical everyday facts one-by-one.
           Checked for duplicates, solipsism, and overused clichés across all scenes.
           Continues until total duration target (25-32s) is reached.
        3. Step 3: Script Assembly:
           Assembles [Scene 1, Scene 2, Scene 3, ..., Final Loop Scene].
           Strict Duration Guard ensures total duration <= max_duration (32.0s).
        4. Step 4: Normalization & Emotion Pass:
           Adds expressive punctuation (? ! , . —) so Kokoro TTS synthesizes natural human inflection.
        5. Step 5: Dynamic Video-Specific SEO:
           Generates unique high-CTR title, custom description formatted as {title}\n\n{description}, and tags.
        """
        print(f"\n🧠 [ISCG v4.0] Generating circular loop script (Duration budget: max {max_duration}s)...")
        recent_titles = _load_upload_history_titles()
        scenes: List[Dict[str, Any]] = []
        used_queries: List[str] = []
        current_duration = 0.0

        # ─── STEP 1: PAIRED ANCHORS (HOOK & LOOPBACK OUTRO) ───────────────────
        print("🎯 [STEP 1] Generating Paired Anchors (Scene 1 Hook & Final Loopback Outro)...", flush=True)
        hook_scene, loop_scene = self._generate_paired_anchors(
            topic=topic,
            used_queries=used_queries,
            recent_titles=recent_titles
        )
        scenes.append(hook_scene)
        used_queries.append(hook_scene["stock_video_query"])
        current_duration += self._calc_duration(hook_scene["spoken_text"])
        loop_dur = self._calc_duration(loop_scene["spoken_text"])
        print(f"   ✅ Scene 1 (Hook): '{hook_scene['spoken_text']}' (~{self._calc_duration(hook_scene['spoken_text'])}s)")
        print(f"   ✅ Final Scene (Loop Outro Anchor): '{loop_scene['spoken_text']}' (~{loop_dur}s)")

        # ─── STEP 2: MIDDLE THOUGHTS (FAST-PACED, NO CATEGORICAL SLOTS) ───────
        target_duration_limit = min(max_duration - loop_dur, 28.0)
        print(f"🔄 [STEP 2] Generating fast-paced middle thoughts until ~{target_duration_limit:.1f}s (Max ceiling: {max_duration}s)...", flush=True)
        scene_num = 2

        max_scenes_limit = 6 if max_duration <= 35.0 else 14
        while (current_duration + 4.0 <= target_duration_limit) and scene_num <= max_scenes_limit:
            print(f"   Generating Scene {scene_num} (current: {current_duration:.1f}s)...", flush=True)
            scene = self._generate_random_thought(
                scene_num=scene_num,
                existing_scenes=scenes + [loop_scene],
                used_queries=used_queries,
                recent_titles=recent_titles
            )
            scenes.append(scene)
            used_queries.append(scene["stock_video_query"])
            sc_dur = self._calc_duration(scene["spoken_text"])
            current_duration += sc_dur
            print(f"   ✅ Scene {scene_num} (Checked for duplicates): '{scene['spoken_text'][:60]}...' (+{sc_dur}s | cumulative: {current_duration:.1f}s)")
            scene_num += 1

        # ─── STEP 3: APPEND FINAL LOOP OUTRO SCENE ────────────────────────────
        loop_scene["scene_id"] = scene_num
        scenes.append(loop_scene)
        used_queries.append(loop_scene["stock_video_query"])
        current_duration += loop_dur
        print(f"   ✅ Appended Final Scene {scene_num} (Loop Outro): '{loop_scene['spoken_text']}' (Total est: {current_duration:.1f}s)")

        # ─── DURATION GUARD: STRICTLY ENFORCE MAX DURATION (32.0s) ────────────
        while len(scenes) > 3 and sum(self._calc_duration(s.get("spoken_text", "")) for s in scenes) > max_duration:
            popped = scenes.pop(-2)  # Remove the last middle thought before the loop closer
            print(f"   ✂️ [DURATION GUARD] Popped Scene {popped.get('scene_id')} ('{popped.get('spoken_text', '')[:40]}...') to enforce max {max_duration}s ceiling.")

        # Re-index scene_id sequentially
        for i, sc in enumerate(scenes):
            sc["scene_id"] = i + 1

        # ─── STEP 4: NORMALIZATION & EMOTION PASS (KOKORO AUDIO POLISHER) ────
        print("🎭 [STEP 4] Running Normalization & Emotion Pass for Kokoro TTS...", flush=True)
        scenes = self._normalize_and_emotify_script(scenes)

        total_words = sum(len(s.get("spoken_text", "").split()) for s in scenes)
        final_est_duration = sum(self._calc_duration(s.get("spoken_text", "")) for s in scenes)
        print(f"🎯 [SCRIPT ASSEMBLED] {len(scenes)} scenes, {total_words} words (~{final_est_duration:.1f}s audio, strictly ≤ {max_duration}s).")

        # ─── STEP 5: DYNAMIC SEO METADATA GENERATION ──────────────────────────
        print("🏷️  [STEP 5] Generating Dynamic, Video-Specific SEO Metadata...", flush=True)
        seo_data = self._generate_seo(scenes=scenes, recent_titles=recent_titles)
        print(f"   ✅ Title: '{seo_data.get('title')}'")

        return scenes, seo_data

    # ─── INDIVIDUAL SCENE GENERATION METHODS ──────────────────────────────────

    def _generate_paired_anchors(
        self,
        topic: str = "",
        used_queries: Optional[List[str]] = None,
        recent_titles: Optional[List[str]] = None
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Generates Scene 1 (Hook) and the Final Scene (Loopback Outro) TOGETHER in a single LLM call.
        This guarantees the closing sentence grammatically and logically flows back into the opening hook.
        """
        sys_prompt = self.prompts.get("paired_anchor_scene", {}).get(
            "system_prompt",
            "You write viral YouTube Shorts with infinite loop potential. Generate TWO scenes that together create a seamless circular loop: 'hook_scene' (10-14 words) and 'loop_outro_scene' (6-12 words). Return ONLY valid JSON."
        )
        user_prompt = "Generate a viral Scene 1 hook thought and a Final Scene loopback bridge that flows seamlessly back into the hook's opening words."
        if topic and topic.strip():
            user_prompt += f" Theme/Vibe: {topic.strip()}."

        for attempt in range(3):
            try:
                res = self.llm.generate_json(
                    system_prompt=sys_prompt,
                    user_prompt=user_prompt,
                    temperature=0.6,
                    task_name="script_gen"
                )
                hook_data = res.get("hook_scene", {})
                loop_data = res.get("loop_outro_scene", {})

                hook_text = hook_data.get("spoken_text", "").strip()
                loop_text = loop_data.get("spoken_text", "").strip()

                hook_text = re.sub(r"^[.…\-—\s]+", "", hook_text).strip()
                if hook_text and hook_text[0].islower():
                    hook_text = hook_text[0].upper() + hook_text[1:]

                is_dup_h, reason_h = self._is_duplicate_thought(hook_text, [], recent_titles)
                is_dup_l, reason_l = self._is_duplicate_thought(loop_text, [{"scene_id": 1, "spoken_text": hook_text}], recent_titles)

                if is_dup_h or is_dup_l:
                    print(f"   🔄 [DEDUP CHECK] Anchor duplicate detected (hook: {reason_h}, loop: {reason_l}). Retrying...")
                    continue

                if hook_text and loop_text and len(hook_text.split()) >= 6 and len(loop_text.split()) >= 4:
                    hook_scene = {
                        "scene_id": 1,
                        "spoken_text": hook_text,
                        "stock_video_query": self._pick_query(hook_data.get("stock_video_query"), used_queries)
                    }
                    loop_scene = {
                        "scene_id": None,
                        "spoken_text": loop_text,
                        "stock_video_query": self._pick_query(loop_data.get("stock_video_query"), used_queries)
                    }
                    return hook_scene, loop_scene
            except Exception as e:
                print(f"   ⚠️ Paired anchor attempt {attempt+1} failed: {e}")

        # Vetted circular fallback pair
        pair = random.choice(PAIRED_CIRCULAR_FALLBACKS)
        hook_scene = {
            "scene_id": 1,
            "spoken_text": pair[0],
            "stock_video_query": self._pick_query("soap carving cubes ASMR", used_queries)
        }
        loop_scene = {
            "scene_id": None,
            "spoken_text": pair[1],
            "stock_video_query": self._pick_query("resin lathe turning wood polishing", used_queries)
        }
        return hook_scene, loop_scene

    def _generate_hook(
        self,
        topic: str = "",
        channel_premise: str = "",
        used_queries: Optional[List[str]] = None,
        recent_titles: Optional[List[str]] = None,
        *args,
        **kwargs
    ) -> Dict[str, Any]:
        """Generates Scene 1: Engaging random Reddit thought or intriguing fact with duplicate check."""
        sys_prompt = self.prompts.get("hook_scene", {}).get(
            "system_prompt",
            "Give me one engaging, relatable Reddit shower thought or intriguing fact that grabs attention immediately. Keep it between 10 and 15 words. Return ONLY JSON with 'spoken_text' and 'stock_video_query'."
        )
        user_prompt = "Generate a viral, scroll-stopping Scene 1 hook thought or fact."

        for attempt in range(3):
            try:
                res = self.llm.generate_json(
                    system_prompt=sys_prompt,
                    user_prompt=user_prompt,
                    temperature=0.6,
                    task_name="script_gen"
                )
                text = res.get("spoken_text", "").strip()
                text = re.sub(r"^[.…\-—\s]+", "", text).strip()
                if text and text[0].islower():
                    text = text[0].upper() + text[1:]

                is_dup, reason = self._is_duplicate_thought(text, [], recent_titles)
                if is_dup:
                    print(f"   🔄 [DEDUP CHECK] Hook duplicate detected ({reason}). Retrying...")
                    continue

                if text and len(text.split()) >= 6:
                    return {
                        "scene_id": 1,
                        "spoken_text": text,
                        "stock_video_query": self._pick_query(res.get("stock_video_query"), used_queries)
                    }
            except Exception as e:
                print(f"   ⚠️ Hook attempt {attempt+1} failed: {e}")

        # Vetted clean fallback hook
        fallback = "The only part of your reflection you can actually lick is your tongue."
        return {
            "scene_id": 1,
            "spoken_text": fallback,
            "stock_video_query": self._pick_query("resin lathe turning wood polishing", used_queries)
        }

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
        if not hook_text and topic and len(topic.split()) > 3:
            hook_text = topic
        sys_prompt = self.prompts.get("title_scene", {}).get(
            "system_prompt",
            "Give me a short, punchy title readout that frames this compilation video. Keep it between 5 and 10 words. Return ONLY JSON with 'spoken_text' and 'stock_video_query'."
        )
        user_prompt = f"Opening hook was: '{hook_text}'. Write Scene 2 as the punchy title readout."

        for attempt in range(2):
            try:
                res = self.llm.generate_json(
                    system_prompt=sys_prompt,
                    user_prompt=user_prompt,
                    temperature=0.6,
                    task_name="script_gen"
                )
                text = res.get("spoken_text", "").strip()
                text = re.sub(r"^[.…\-—\s]+", "", text).strip()

                is_dup, reason = self._is_duplicate_thought(text, existing_scenes or [], recent_titles)
                if is_dup:
                    continue

                if text and 4 <= len(text.split()) <= 14:
                    return {
                        "scene_id": 2,
                        "spoken_text": text,
                        "stock_video_query": self._pick_query(res.get("stock_video_query") or "kinetic sand squishing satisfying", used_queries)
                    }
            except Exception:
                pass

        anchor = random.choice(PREMISE_ANCHOR_LINES)
        return {
            "scene_id": 2,
            "spoken_text": anchor,
            "stock_video_query": self._pick_query("kinetic sand squishing satisfying", used_queries)
        }

    def _generate_random_thought(
        self,
        scene_num: int,
        existing_scenes: List[Dict[str, Any]],
        used_queries: Optional[List[str]] = None,
        recent_titles: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Generates a single standalone random Reddit thought or logical everyday fact."""
        already_used = [s.get("spoken_text", "") for s in existing_scenes]
        already_used_summary = "\n".join(f"- {t}" for t in already_used[-6:])

        sys_prompt = self.prompts.get("thought_scene", {}).get(
            "system_prompt",
            "Give me ONE standalone, mind-bending random Reddit thought or logical fact that makes you stop and think. Simple and relatable, 10-14 words. Return ONLY JSON with 'spoken_text' and 'stock_video_query'."
        )
        user_prompt = f"ALREADY USED THOUGHTS IN THIS VIDEO:\n{already_used_summary}\n\nGenerate Scene {scene_num}: Exactly one standalone thought or logical everyday fact (10-14 words)."

        for attempt in range(3):
            try:
                res = self.llm.generate_json(
                    system_prompt=sys_prompt,
                    user_prompt=user_prompt,
                    temperature=0.6,
                    task_name="script_gen"
                )
                text = res.get("spoken_text", "").strip()
                text = re.sub(r"^[.…\-—\s]+", "", text).strip()

                is_dup, reason = self._is_duplicate_thought(text, existing_scenes, recent_titles)
                if is_dup:
                    print(f"   🔄 [DEDUP CHECK] Duplicate/cliché detected: {reason}. Retrying...")
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
        vetted = _load_curated_replacements(count=25)
        for cand in vetted:
            is_dup, _ = self._is_duplicate_thought(cand, existing_scenes, recent_titles)
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
        sys_prompt = self.prompts.get("cta_closer", {}).get(
            "system_prompt",
            "Give me ONE short, witty, deadpan call to action to subscribe. 6-12 words. End with clean period or exclamation mark. Return ONLY JSON with 'spoken_text' and 'stock_video_query'."
        )
        user_prompt = f"Generate Scene {scene_num}: The final witty YouTube subscription call to action."

        for attempt in range(2):
            try:
                res = self.llm.generate_json(
                    system_prompt=sys_prompt,
                    user_prompt=user_prompt,
                    temperature=0.6,
                    task_name="script_gen"
                )
                text = res.get("spoken_text", "").strip()
                text = re.sub(r"[.…\-—\s]+$", "", text).strip()

                is_dup, reason = self._is_duplicate_thought(text, existing_scenes, recent_titles)
                if is_dup:
                    continue

                if text and 5 <= len(text.split()) <= 16:
                    if not (text.endswith(".") or text.endswith("!")):
                        text = f"{text}."
                    return {
                        "scene_id": scene_num,
                        "spoken_text": text,
                        "stock_video_query": self._pick_query(res.get("stock_video_query") or "soap carving cubes ASMR", used_queries)
                    }
            except Exception:
                pass

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
        for natural Kokoro TTS inflection without altering the core thoughts.
        """
        sys_prompt = self.prompts.get("script_polish", {}).get(
            "system_prompt",
            "You are an audio voiceover director. Take these video scenes and enhance punctuation (?, !, ,, —, .) so Kokoro neural TTS speaks naturally with curiosity and punch. Return JSON with 'scenes'."
        )
        scenes_payload = [{"scene_id": s["scene_id"], "spoken_text": s["spoken_text"]} for s in scenes]
        user_prompt = f"SCENES TO NORMALIZE & EMOTIFY:\n{json.dumps(scenes_payload, indent=2)}\n\nEnhance punctuation for neural voice synthesis while preserving exact meaning."

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
