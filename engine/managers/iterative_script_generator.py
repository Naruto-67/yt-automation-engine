"""
engine/managers/iterative_script_generator.py — Iterative Scene Chain Generator (ISCG v1.0)

Generates viral YouTube Shorts scripts scene-by-scene under the @BrainBlud script constitution:
1. Scene 1: High-voltage in-media-res reality check hook (0-4s).
2. Scene 2: Premise / Title Read Anchor Line (4-7s), matching the on-screen Title Card.
3. Scenes 3 to N-1: Multi-pillar rotation (Body -> Tech -> Psych -> Nature -> Logic).
4. Scene N: Dual Loop Outro (Mode A syntactic loop or Mode B witty deadpan closer).
5. Unified SEO: High-CTR umbrella compilation title and tags.

Features:
- Zero single-topic stretching: Each scene rotates across distinct knowledge domains.
- Zero split thoughts: Every scene is an atomic, self-contained thought.
- Real-time Jaccard deduplication & Wall Test gating on every scene.
- Seamless provider-adaptive routing and dynamic quality tracking via LLMQualityTracker.
"""

from __future__ import annotations

import re
import json
import random
from typing import List, Dict, Any, Tuple, Optional

from engine.managers.editorial_critic import (
    CynicalHumanAuditor,
    PureShowerThoughtAuditor,
    SemanticDeduplicationSkill,
    TitleScriptAlignmentSkill,
    HookAuditorSkill,
    ThoughtCompletenessSkill,
    LoopAuditorSkill,
    check_loop_repeats_hook,
    COMPILATION_LOOP_BRIDGES,
    UMBRELLA_TITLE_TEMPLATES,
    _token_overlap,
    _load_upload_history_titles,
    _load_curated_replacements
)
from engine.managers.llm_quality_tracker import LLMQualityTracker


# ─── @BRAINBLUD 5 SHOWER THOUGHT ANGLES (ZERO TRIVIA FACTS) ───────────────────
SHOWER_THOUGHT_ANGLES = [
    {
        "id": "angle_1",
        "name": "Perception & Sensory Glitches",
        "desc": "Brain filtering quirks, mirror reflection paradoxes, sight vs reality, biological perception shifts, sensory illusions."
    },
    {
        "id": "angle_2",
        "name": "Everyday Objects & Modern Life Ironies",
        "desc": "Absurd ironies of phones, beds, alarms, keys, clothes, showers, cars, coffee, everyday human routines."
    },
    {
        "id": "angle_3",
        "name": "Human Psychology & Social Absurdities",
        "desc": "Awkward unwritten rules, why we do strange things in public, social masks, sleep vs awake, memory glitches."
    },
    {
        "id": "angle_4",
        "name": "Existential Shifts & Time Paradoxes",
        "desc": "Mind-bending realizations about age, history, past/future versions of you, photos, sleep, human existence."
    },
    {
        "id": "angle_5",
        "name": "Language, Wordplay & Logic Paradoxes",
        "desc": "Contradictory phrases, self-referential paradoxes, absurd definitions, linguistic bugs that make no sense."
    }
]
PILLARS = SHOWER_THOUGHT_ANGLES  # Backward compatibility alias

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

# BrainBlud CTA Outro Closers (High-retention engagement closers ending in clean punctuation)
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

# Scene 2 Premise Anchor Templates (The @BrainBlud engaging line)
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


class IterativeScriptGenerator:
    """
    Autonomous Iterative Scene Chain Generator.
    Constructs high-retention Shorts scripts one scene at a time with real-time gating.
    """

    def __init__(self, llm_manager: Optional[Any] = None, quality_tracker: Optional[LLMQualityTracker] = None):
        if llm_manager is None:
            from engine.managers.llm_manager import LLMManager
            llm_manager = LLMManager()
        self.llm = llm_manager
        self.qt = quality_tracker or LLMQualityTracker()

    def generate_scene_chain(
        self,
        topic: str,
        channel_premise: str = "",
        target_duration: int = 55,
        target_words_min: int = 150,
        target_words_max: int = 175
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Main pipeline method:
        Executes the 5-step iterative generation workflow.
        Returns (scenes_list, seo_dict).
        """
        print(f"\n🧠 [ISCG] Initiating Iterative Scene Chain Generator for topic: '{topic}'")
        recent_titles = _load_upload_history_titles()
        scenes: List[Dict[str, Any]] = []
        total_words = 0
        used_queries: List[str] = []

        # ─── STEP 1: HOOK ARCHITECT (Scene 1) ────────────────────────────────
        print("🎯 [ISCG - STEP 1/5] Generating Hook (Scene 1)...", flush=True)
        hook_scene = self._generate_hook(topic, channel_premise)
        scenes.append(hook_scene)
        total_words += len(hook_scene["spoken_text"].split())
        used_queries.append(hook_scene["stock_video_query"])
        print(f"   ✅ Scene 1 (Hook): '{hook_scene['spoken_text']}' ({len(hook_scene['spoken_text'].split())}w)")

        # ─── STEP 2: PREMISE ANCHOR (Scene 2) ────────────────────────────────
        print("🎬 [ISCG - STEP 2/5] Generating Premise Anchor Line (Scene 2)...", flush=True)
        premise_scene = self._generate_premise_anchor(topic, hook_scene["spoken_text"])
        scenes.append(premise_scene)
        total_words += len(premise_scene["spoken_text"].split())
        used_queries.append(premise_scene["stock_video_query"])
        print(f"   ✅ Scene 2 (Premise): '{premise_scene['spoken_text']}' ({len(premise_scene['spoken_text'].split())}w)")

        # ─── STEP 3: MULTI-PILLAR ROTATION (Scenes 3 to N-1) ─────────────────
        print(f"🔄 [ISCG - STEP 3/5] Rotating through 5 knowledge pillars (Target: {target_words_min}-{target_words_max} words)...", flush=True)
        pillar_idx = 0
        scene_idx = 3

        while total_words < (target_words_min - 15) and scene_idx <= 12:
            assigned_pillar = PILLARS[pillar_idx % len(PILLARS)]
            print(f"   Generating Scene {scene_idx} [{assigned_pillar['name']}]...", flush=True)

            scene = self._generate_pillar_scene(
                pillar=assigned_pillar,
                scene_num=scene_idx,
                existing_scenes=scenes,
                recent_titles=recent_titles,
                used_queries=used_queries
            )
            scenes.append(scene)
            sc_words = len(scene["spoken_text"].split())
            total_words += sc_words
            used_queries.append(scene["stock_video_query"])
            print(f"   ✅ Scene {scene_idx} ({assigned_pillar['name'][:18]}): '{scene['spoken_text'][:60]}...' ({sc_words}w | cumulative: {total_words}w)")

            pillar_idx += 1
            scene_idx += 1

        # ─── STEP 4: BRAINBLUD CTA OUTRO ARCHITECT (Scene N) ─────────────────
        print(f"🎬 [ISCG - STEP 4/5] Crafting BrainBlud CTA Outro (Scene {scene_idx})...", flush=True)
        outro_scene = self._generate_brainblud_closer(
            scene_num=scene_idx,
            existing_scenes=scenes,
            used_queries=used_queries
        )
        scenes.append(outro_scene)
        total_words += len(outro_scene["spoken_text"].split())
        print(f"   ✅ Scene {scene_idx} (Outro): '{outro_scene['spoken_text']}' ({len(outro_scene['spoken_text'].split())}w)")
        print(f"🎯 [ISCG SCRIPT LOCKED] Final script: {len(scenes)} scenes, {total_words} words (~{total_words / 3.25:.1f}s audio).")

        # ─── STEP 5: UNIFIED UMBRELLA SEO GENERATION ─────────────────────────
        print("🏷️  [ISCG - STEP 5/5] Generating Unified Umbrella SEO...", flush=True)
        seo_data = self._generate_umbrella_seo(
            scenes=scenes,
            topic=topic,
            premise_line=premise_scene["spoken_text"],
            recent_titles=recent_titles
        )
        print(f"   ✅ Final Umbrella Title: '{seo_data.get('title')}'")

        return scenes, seo_data

    # ─── INTERNAL SCENE GENERATORS ───────────────────────────────────────────

    def _generate_hook(self, topic: str, channel_premise: str = "", used_queries: Optional[List[str]] = None) -> Dict[str, Any]:
        """Generates an undeniable physical reality check hook (Scene 1)."""
        prompt = (
            f"You are the lead viral scriptwriter for @metopato.\n\n"
            f"Write Scene 1: An irresistible, undeniable in-media-res reality check hook (12-16 words).\n"
            f"CRITICAL RULES:\n"
            f"1. Freeze the scroll instantly with a mind-bending physical or sensory shower thought.\n"
            f"2. ZERO greetings ('Hey guys', 'Did you know') and ZERO leading punctuation ('...').\n"
            f"3. ZERO TRIVIA FACTS: No animal biology (octopuses, whales), no gadget/hardware trivia. Pure r/Showerthoughts cognitive paradox only.\n"
            f"4. Must be testable, relatable, and defensible against a cynical viewer.\n"
            f"5. Return valid JSON: {{\"spoken_text\": \"...\", \"stock_video_query\": \"...\"}}"
        )
        for attempt in range(3):
            try:
                res = self.llm.generate_json(
                    system_prompt="Return ONLY JSON with 'spoken_text' and 'stock_video_query'.",
                    user_prompt=prompt,
                    temperature=0.5,
                    task_name="script_gen"
                )
                text = res.get("spoken_text", "").strip()
                # Clean leading punctuation
                text = re.sub(r"^[.…\-—\s]+", "", text).strip()
                if text and text[0].islower():
                    text = text[0].upper() + text[1:]

                hook_ok, _ = HookAuditorSkill.audit_hook(text)
                wall_ok, _ = CynicalHumanAuditor.audit_text(text)
                fact_ok, _ = PureShowerThoughtAuditor.audit_thought(text)
                if hook_ok and wall_ok and fact_ok:
                    prov_id = getattr(self.llm, "_last_used_provider_id", "unknown")
                    self.qt.record_result(prov_id, wall_test_failures=0, wall_test_replacements=0, passed_first_attempt=True)
                    return {
                        "scene_id": 1,
                        "spoken_text": text,
                        "stock_video_query": self._pick_query(res.get("stock_video_query"), used_queries)
                    }
            except Exception as e:
                print(f"   ⚠️ Hook attempt {attempt+1} failed ({e}). Retrying...")

        # Vetted fallback hook
        fallback_hook = "The only part of your reflection you can actually lick is your tongue."
        return {
            "scene_id": 1,
            "spoken_text": fallback_hook,
            "stock_video_query": self._pick_query("resin lathe turning wood polishing", used_queries)
        }

    def _generate_premise_anchor(self, topic: str, hook_text: str = "", used_queries: Optional[List[str]] = None) -> Dict[str, Any]:
        """Generates Scene 2: The viral premise anchor line matching the on-screen Title Card."""
        # Pick least-used high-impact premise anchor line
        anchor_line = random.choice(PREMISE_ANCHOR_LINES)
        return {
            "scene_id": 2,
            "spoken_text": anchor_line,
            "stock_video_query": self._pick_query("kinetic sand squishing satisfying", used_queries)
        }

    _generate_premise_card = _generate_premise_anchor  # Studio wizard alias

    def _generate_pillar_scene(
        self,
        pillar: Dict[str, str],
        scene_num: int,
        existing_scenes: List[Dict[str, Any]],
        recent_titles: List[str],
        used_queries: List[str]
    ) -> Dict[str, Any]:
        """Generates a single standalone scene strictly under the assigned shower thought angle."""
        already_used = [s["spoken_text"] for s in existing_scenes]
        already_used_summary = "\n".join(f"- {t}" for t in already_used[-4:])

        prompt = (
            f"You write viral @BrainBlud listicles for @metopato.\n\n"
            f"ASSIGNED ANGLE: {pillar['name']} ({pillar['desc']})\n\n"
            f"ALREADY USED THOUGHTS IN THIS VIDEO (DO NOT REPEAT CONCEPTS):\n"
            f"{already_used_summary}\n\n"
            f"Generate Scene {scene_num}: EXACTLY ONE standalone, viral shower thought (12-16 words).\n"
            f"CRITICAL RULES:\n"
            f"1. Must be strictly within '{pillar['name']}'. Never write about the same topic as prior scenes.\n"
            f"2. ABSOLUTE BAN ON TRIVIA FACTS: Do NOT share animal biology, nature trivia, or hardware trivia. Only pure r/Showerthoughts cognitive paradoxes and perspective flips.\n"
            f"3. Must be a COMPLETE thought. Do NOT end with dangling words like 'because', 'which means', 'and'.\n"
            f"4. THE WALL TEST: Must be 100% true, defensible, and testable. No fake-deep nihilism or 'nothing is real'.\n"
            f"5. Expressive cadence: incorporate '?', '!', or '—' for natural voice intonation.\n"
            f"6. Return valid JSON: {{\"spoken_text\": \"...\", \"stock_video_query\": \"...\"}}"
        )

        for attempt in range(3):
            try:
                res = self.llm.generate_json(
                    system_prompt="Return ONLY a JSON object with 'spoken_text' and 'stock_video_query'.",
                    user_prompt=prompt,
                    temperature=0.5,
                    task_name="script_gen"
                )
                text = res.get("spoken_text", "").strip()
                prov_id = getattr(self.llm, "_last_used_provider_id", "unknown")

                # Pure Shower Thought Check (reject trivia facts)
                fact_ok, fact_reason = PureShowerThoughtAuditor.audit_thought(text)
                if not fact_ok:
                    print(f"   🚫 [PILLAR REJECT] {fact_reason}")
                    continue

                # Wall Test Check
                wall_ok, wall_reason = CynicalHumanAuditor.audit_text(text)
                if not wall_ok:
                    print(f"   🚫 [PILLAR REJECT] {wall_reason}")
                    self.qt.record_result(prov_id, wall_test_failures=1, wall_test_replacements=0, passed_first_attempt=False)
                    continue

                # Thought Completeness Check
                comp_ok, comp_reason = ThoughtCompletenessSkill.audit_completeness(text, is_final_scene=False)
                if not comp_ok:
                    print(f"   🚫 [PILLAR REJECT] {comp_reason}")
                    continue

                # Advanced Semantic & Subject-Core Deduplication Check
                is_duplicate, dup_reason = SemanticDeduplicationSkill.is_duplicate(text, existing_scenes)
                if is_duplicate:
                    print(f"   🔄 [PILLAR DEDUP] {dup_reason}. Regenerating...")
                    continue

                # Upload History Dedup Check
                if recent_titles and any(_token_overlap(text, rt) > 0.50 for rt in recent_titles):
                    print(f"   🔄 [PILLAR DEDUP] Thought overlaps with recent upload. Regenerating...")
                    continue

                self.qt.record_result(prov_id, wall_test_failures=0, wall_test_replacements=0, passed_first_attempt=True)
                return {
                    "scene_id": scene_num,
                    "spoken_text": text,
                    "stock_video_query": self._pick_query(res.get("stock_video_query"), used_queries)
                }
            except Exception as e:
                print(f"   ⚠️ Scene {scene_num} attempt {attempt+1} failed ({e}). Retrying...")

        # Curated Fallback
        vetted = _load_curated_replacements(count=25)
        for cand in vetted:
            is_dup, _ = SemanticDeduplicationSkill.is_duplicate(cand, existing_scenes)
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

    def _generate_single_pillar_scene(
        self,
        scene_num: int,
        pillar: Dict[str, str],
        topic: str = "",
        existing_scenes: Optional[List[Dict[str, Any]]] = None,
        used_queries: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Convenience method for recreating a single pillar scene in the studio wizard."""
        return self._generate_pillar_scene(
            pillar=pillar,
            scene_num=scene_num,
            existing_scenes=existing_scenes or [],
            recent_titles=_load_upload_history_titles(),
            used_queries=used_queries or []
        )

    def _generate_brainblud_closer(
        self,
        scene_num: int,
        existing_scenes: List[Dict[str, Any]],
        used_queries: List[str],
        hook_text: str = ""
    ) -> Dict[str, Any]:
        """
        Generates Scene N:
        BrainBlud signature call-to-action closer ending in a clean period or exclamation mark.
        Never ends in dangling ellipses '...'. Completely eliminates trailing audio cutoff.
        """
        already_used = [s.get("spoken_text", "") for s in existing_scenes]
        available_closers = [c for c in BRAINBLUD_CLOSERS if not any(c.lower() in prev.lower() for prev in already_used)]
        if not available_closers:
            available_closers = BRAINBLUD_CLOSERS

        chosen_closer = random.choice(available_closers)
        # Ensure clean terminal punctuation (. or !)
        chosen_closer = chosen_closer.rstrip(".!?…-— ")
        chosen_closer = f"{chosen_closer}."

        return {
            "scene_id": scene_num,
            "spoken_text": chosen_closer,
            "stock_video_query": self._pick_query("soap carving cubes ASMR", used_queries)
        }

    def _generate_loop_outro(
        self,
        hook_text: str = "",
        scene_num: int = 12,
        existing_scenes: Optional[List[Dict[str, Any]]] = None,
        used_queries: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Backward-compatible alias routing to _generate_brainblud_closer."""
        existing_scenes = existing_scenes or []
        used_queries = used_queries or []
        return self._generate_brainblud_closer(scene_num, existing_scenes, used_queries)

    def _generate_umbrella_seo(
        self,
        scenes: List[Dict[str, Any]],
        topic: str,
        premise_line: str,
        recent_titles: List[str]
    ) -> Dict[str, Any]:
        """Generates unified umbrella compilation SEO matching the multi-pillar content."""
        # Align title through TitleScriptAlignmentSkill
        aligned_title = TitleScriptAlignmentSkill.align_title(
            title=f"{premise_line.rstrip('.!?')} 🤯 #shorts",
            scenes=scenes,
            upload_history_titles=recent_titles
        )

        return {
            "title": aligned_title,
            "description": (
                f"Mind-bending shower thoughts and psychological paradoxes that flip your perspective on reality. "
                f"Which realization broke your brain the most? Drop your thoughts below! 👇\n\n"
                f"Subscribe to @metopato for daily mind-bending shifts.\n\n"
                f"#showerthoughts #psychology #mindblowing #deepthoughts #shorts"
            ),
            "tags": [
                "shower thoughts", "mind blowing facts", "psychology", "paradoxes",
                "brain glitches", "reality check", "deep thoughts", "shorts",
                "topato", "metopato", "facts that break your brain", "satisfying facts"
            ]
        }

    def _pick_query(self, preferred: Optional[str] = None, used: Optional[List[str]] = None) -> str:
        """Picks a unique, high-motion satisfying visual query."""
        used = used or []
        if preferred and preferred.strip() and preferred not in used:
            return preferred.strip()
        available = [q for q in SATISFYING_VISUAL_QUERIES if q not in used]
        if available:
            return random.choice(available)
        return random.choice(SATISFYING_VISUAL_QUERIES)

