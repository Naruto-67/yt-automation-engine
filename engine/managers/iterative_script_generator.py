"""
engine/managers/iterative_script_generator.py — Clean Scene-by-Scene Script Generator (v3.0)

Implements the user's direct, unbloated compilation strategy:
1. Scene 1: Engaging random Reddit thought / intriguing fact (Hook).
2. Scene 2: Video title readout / compilation premise line.
3. Scenes 3 to N-1: Standalone random Reddit thoughts and logical everyday facts.
   Generated 1 scene per LLM call until estimated duration approaches 50s (max 52s).
4. Scene N: Punchy, witty call to action closer.
5. Normalization & Emotion Pass: Sends the assembled script to AI to add expressive
   punctuation (.!?—,) so Kokoro neural TTS synthesizes rich human emotional inflection.
6. Per-scene deduplication checks across every step.
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

# Witty, high-retention call-to-action closers (Mode B BrainBlud style)
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
MODE_B_WITTY_CLOSERS = BRAINBLUD_CLOSERS  # Backward compatibility alias

# Scene 2 Premise Anchor Templates
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

# Backward compatibility alias for pillar rotation
PILLARS = [
    {"name": "Mind-Bending Thought", "desc": "Relatable random Reddit thought or logical fact"}
]


class IterativeScriptGenerator:
    """
    Clean, Scene-by-Scene Script Generator with Duration Budgeting and Normalization.
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
        """
        if not text or not text.strip():
            return True, "Empty text"

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
        max_duration: float = 52.0,
        target_duration: Optional[int] = None,
        **kwargs
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Executes the clean scene-by-scene script generation:
        1. Scene 1: Engaging random Reddit thought / fact (Hook) -> duplicate check.
        2. Scene 2: Video title readout / compilation framing hook -> duplicate check.
        3. Scenes 3 to N-1: Random relatable Reddit thoughts and logical everyday facts -> duplicate check per scene.
           Stops when cumulative duration approaches 50s (max 52s hard limit).
        4. Scene N: Call-to-action closer -> duplicate check.
        5. Strict Duration Guard: Guarantees cumulative duration <= max_duration (52.0s).
        6. Normalization Pass: Adds expressive emotional punctuation (.!?,—) for Kokoro TTS.
        7. SEO Generation: High-CTR umbrella title and metadata.
        """
        print(f"\n🧠 [ISCG v3.0] Generating script scene-by-scene (Duration budget: max {max_duration}s)...")
        recent_titles = _load_upload_history_titles()
        scenes: List[Dict[str, Any]] = []
        used_queries: List[str] = []
        current_duration = 0.0

        # ─── STEP 1: SCENE 1 (HOOK) ──────────────────────────────────────────
        print("🎯 [STEP 1] Generating Scene 1 (Engaging Hook Thought/Fact)...", flush=True)
        hook_scene = self._generate_hook(used_queries=used_queries, recent_titles=recent_titles)
        scenes.append(hook_scene)
        used_queries.append(hook_scene["stock_video_query"])
        current_duration += self._calc_duration(hook_scene["spoken_text"])
        print(f"   ✅ Scene 1 (Checked for duplicates): '{hook_scene['spoken_text']}' (~{self._calc_duration(hook_scene['spoken_text'])}s)")

        # ─── STEP 2: SCENE 2 (TITLE READOUT / PREMISE) ───────────────────────
        print("🎬 [STEP 2] Generating Scene 2 (Title Readout / Compilation Framing)...", flush=True)
        premise_scene = self._generate_premise_anchor(
            hook_text=hook_scene["spoken_text"],
            existing_scenes=scenes,
            used_queries=used_queries,
            recent_titles=recent_titles
        )
        scenes.append(premise_scene)
        used_queries.append(premise_scene["stock_video_query"])
        current_duration += self._calc_duration(premise_scene["spoken_text"])
        print(f"   ✅ Scene 2 (Checked for duplicates): '{premise_scene['spoken_text']}' (~{self._calc_duration(premise_scene['spoken_text'])}s)")

        # ─── STEP 3: SCENES 3 to N-1 (RANDOM RELATABLE THOUGHTS & FACTS) ─────
        # We target staying under 50.0s so adding CTA closer leaves the final video strictly below 52s
        target_duration_limit = min(50.0, max_duration - 2.0)
        print(f"🔄 [STEP 3] Generating random thoughts & facts until ~{target_duration_limit}s (Max ceiling: {max_duration}s)...", flush=True)
        scene_num = 3

        while (current_duration + 4.2 + 3.2 <= target_duration_limit) and scene_num <= 14:
            print(f"   Generating Scene {scene_num} (current: {current_duration:.1f}s)...", flush=True)
            scene = self._generate_random_thought(
                scene_num=scene_num,
                existing_scenes=scenes,
                used_queries=used_queries,
                recent_titles=recent_titles
            )
            scenes.append(scene)
            used_queries.append(scene["stock_video_query"])
            sc_dur = self._calc_duration(scene["spoken_text"])
            current_duration += sc_dur
            print(f"   ✅ Scene {scene_num} (Checked for duplicates): '{scene['spoken_text'][:60]}...' (+{sc_dur}s | cumulative: {current_duration:.1f}s)")
            scene_num += 1

        # ─── STEP 4: SCENE N (CALL TO ACTION CLOSER) ─────────────────────────
        print(f"🎬 [STEP 4] Crafting Final Scene {scene_num} (Call to Action Closer)...", flush=True)
        cta_scene = self._generate_cta_closer(
            scene_num=scene_num,
            existing_scenes=scenes,
            used_queries=used_queries,
            recent_titles=recent_titles
        )
        scenes.append(cta_scene)
        used_queries.append(cta_scene["stock_video_query"])
        current_duration += self._calc_duration(cta_scene["spoken_text"])
        print(f"   ✅ Scene {scene_num} (CTA - Checked for duplicates): '{cta_scene['spoken_text']}' (+{self._calc_duration(cta_scene['spoken_text'])}s)")

        # ─── DURATION GUARD: STRICTLY ENFORCE MAX DURATION (52.0s) ───────────
        while len(scenes) > 3 and sum(self._calc_duration(s.get("spoken_text", "")) for s in scenes) > max_duration:
            popped = scenes.pop(-2)  # Remove the last thought scene before the CTA closer
            print(f"   ✂️ [DURATION GUARD] Popped Scene {popped.get('scene_id')} ('{popped.get('spoken_text', '')[:40]}...') to strictly enforce max {max_duration}s ceiling.")

        # Re-index scene_id sequentially
        for i, sc in enumerate(scenes):
            sc["scene_id"] = i + 1

        # ─── STEP 5: NORMALIZATION & EMOTION PASS (KOKORO AUDIO POLISHER) ────
        print("🎭 [STEP 5] Running Normalization & Emotion Pass for Kokoro TTS...", flush=True)
        scenes = self._normalize_and_emotify_script(scenes)

        total_words = sum(len(s.get("spoken_text", "").split()) for s in scenes)
        final_est_duration = sum(self._calc_duration(s.get("spoken_text", "")) for s in scenes)
        print(f"🎯 [SCRIPT ASSEMBLED] {len(scenes)} scenes, {total_words} words (~{final_est_duration:.1f}s audio, strictly ≤ {max_duration}s).")

        # ─── STEP 6: SEO METADATA GENERATION ─────────────────────────────────
        print("🏷️  [STEP 6] Generating High-CTR SEO Metadata...", flush=True)
        seo_data = self._generate_seo(scenes=scenes, premise_line=premise_scene["spoken_text"], recent_titles=recent_titles)
        print(f"   ✅ Title: '{seo_data.get('title')}'")

        return scenes, seo_data

    # ─── INDIVIDUAL SCENE GENERATION METHODS ──────────────────────────────────

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
                # Clean leading punctuation
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
        """Generates Scene 2: Video title readout / compilation premise framing with duplicate check."""
        # Handle cases where hook_text was passed as first arg
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
                    print(f"   🔄 [DEDUP CHECK] Scene 2 duplicate detected ({reason}). Retrying...")
                    continue

                if text and 4 <= len(text.split()) <= 14:
                    return {
                        "scene_id": 2,
                        "spoken_text": text,
                        "stock_video_query": self._pick_query(res.get("stock_video_query") or "kinetic sand squishing satisfying", used_queries)
                    }
            except Exception:
                pass

        # Vetted fallback premise anchor
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
        already_used_summary = "\n".join(f"- {t}" for t in already_used[-4:])

        sys_prompt = self.prompts.get("thought_scene", {}).get(
            "system_prompt",
            "Give me ONE standalone, mind-bending random Reddit thought or logical fact that makes you stop and think. Simple and relatable, 10-15 words. Return ONLY JSON with 'spoken_text' and 'stock_video_query'."
        )
        user_prompt = f"ALREADY USED THOUGHTS IN THIS VIDEO:\n{already_used_summary}\n\nGenerate Scene {scene_num}: Exactly one standalone thought or logical everyday fact (10-15 words)."

        for attempt in range(3):
            try:
                res = self.llm.generate_json(
                    system_prompt=sys_prompt,
                    user_prompt=user_prompt,
                    temperature=0.6,
                    task_name="script_gen"
                )
                text = res.get("spoken_text", "").strip()
                # Clean leading punctuation
                text = re.sub(r"^[.…\-—\s]+", "", text).strip()

                is_dup, reason = self._is_duplicate_thought(text, existing_scenes, recent_titles)
                if is_dup:
                    print(f"   🔄 [DEDUP CHECK] Duplicate detected: {reason}. Retrying...")
                    continue

                if text and 8 <= len(text.split()) <= 18:
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
        """Generates Scene N: Punchy, witty call to action closer ending cleanly in a period or exclamation mark with duplicate check."""
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
                # Clean punctuation and ensure clean period/exclamation mark
                text = re.sub(r"[.…\-—\s]+$", "", text).strip()

                is_dup, reason = self._is_duplicate_thought(text, existing_scenes, recent_titles)
                if is_dup:
                    print(f"   🔄 [DEDUP CHECK] CTA closer duplicate detected ({reason}). Retrying...")
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

        # Curated fallback
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
                        # Sanity check: don't accept if word count collapsed
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
        """Generates unified umbrella compilation SEO matching the multi-thought script."""
        aligned_title = TitleScriptAlignmentSkill.align_title(
            title=f"{premise_line.rstrip('.!?')} 🤯 #shorts",
            scenes=scenes,
            upload_history_titles=recent_titles or []
        )

        base_description = (
            "Mind-bending shower thoughts and psychological realizations that reset your daily perception.\n\n"
            "Subscribe to @metopato for daily perspective shifts!\n\n"
            "#showerthoughts #psychology #deepthoughts #mindblowing #shorts"
        )
        # Exact title on top always, followed by an empty line, then the SEO description
        full_description = f"{aligned_title}\n\n{base_description}"

        return {
            "title": aligned_title,
            "description": full_description,
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
