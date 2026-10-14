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


# ─── @BRAINBLUD 5 KNOWLEDGE PILLARS ──────────────────────────────────────────
PILLARS = [
    {
        "id": "pillar_1",
        "name": "Human Body & Sensory Paradoxes",
        "desc": "Perception quirks, reflexes, optical illusions, sensory glitches, biological oddities."
    },
    {
        "id": "pillar_2",
        "name": "Everyday Objects, Tech & Architecture",
        "desc": "Hidden functions of tools, smartphone physics, building design quirks, everyday engineering."
    },
    {
        "id": "pillar_3",
        "name": "Human Psychology, Relationships & Social Irony",
        "desc": "Awkward social behaviors, cognitive biases, memory tricks, societal paradoxes, relatable quirks."
    },
    {
        "id": "pillar_4",
        "name": "Nature, Animals & Cosmic Realities",
        "desc": "Animal superpowers, ocean depths, time dilation, planetary physics, nature's engineering."
    },
    {
        "id": "pillar_5",
        "name": "Language, Logic, Wordplay & Cognitive Glitches",
        "desc": "Word origins, semantic paradoxes, mathematical curiosities, perspective shifts that break your brain."
    }
]

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

# Mode B Witty Deadpan Closers (Proven high-retention engagement closers)
MODE_B_WITTY_CLOSERS = [
    "If you want to be smarter than everyone you know, subscribe.",
    "If all of you subscribed right now, I would have more subscribers.",
    "You just spent fifty seconds learning facts that won't help you on an exam.",
    "Your brain is now holding information it will never use again.",
    "If you made it this far, your attention span is better than average.",
    "If you subscribe right now, your phone won't explode tomorrow.",
    "You are now one minute closer to knowing everything about nothing."
]

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

    def __init__(self, llm_manager: Any, quality_tracker: Optional[LLMQualityTracker] = None):
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

        # ─── STEP 4: LOOP OUTRO ARCHITECT (Scene N) ──────────────────────────
        print(f"🔁 [ISCG - STEP 4/5] Crafting Loop Outro (Scene {scene_idx})...", flush=True)
        outro_scene = self._generate_loop_outro(
            hook_text=hook_scene["spoken_text"],
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

    def _generate_hook(self, topic: str, channel_premise: str) -> Dict[str, Any]:
        """Generates an undeniable physical reality check hook (Scene 1)."""
        prompt = (
            f"You are the lead viral scriptwriter for @metopato.\n"
            f"Topic: {topic}\n\n"
            f"Write Scene 1: An irresistible, undeniable in-media-res reality check hook (12-16 words).\n"
            f"CRITICAL RULES:\n"
            f"1. Freeze the scroll instantly with a physical, sensory, or biological truth.\n"
            f"2. ZERO greetings ('Hey guys', 'Did you know') and ZERO leading punctuation ('...').\n"
            f"3. Must be testable, relatable, and defensible against a cynical viewer.\n"
            f"4. Return valid JSON: {{\"spoken_text\": \"...\", \"stock_video_query\": \"...\"}}"
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
                if hook_ok and wall_ok:
                    prov_id = getattr(self.llm, "_last_used_provider_id", "unknown")
                    self.qt.record_result(prov_id, wall_test_failures=0, wall_test_replacements=0, passed_first_attempt=True)
                    return {
                        "scene_id": 1,
                        "spoken_text": text,
                        "stock_video_query": self._pick_query(res.get("stock_video_query"))
                    }
            except Exception as e:
                print(f"   ⚠️ Hook attempt {attempt+1} failed ({e}). Retrying...")

        # Vetted fallback hook
        fallback_hook = "The only part of your reflection you can actually lick is your tongue."
        return {
            "scene_id": 1,
            "spoken_text": fallback_hook,
            "stock_video_query": "resin lathe turning wood polishing"
        }

    def _generate_premise_anchor(self, topic: str, hook_text: str) -> Dict[str, Any]:
        """Generates Scene 2: The viral premise anchor line matching the on-screen Title Card."""
        # Pick least-used high-impact premise anchor line
        anchor_line = random.choice(PREMISE_ANCHOR_LINES)
        return {
            "scene_id": 2,
            "spoken_text": anchor_line,
            "stock_video_query": "kinetic sand squishing satisfying"
        }

    def _generate_pillar_scene(
        self,
        pillar: Dict[str, str],
        scene_num: int,
        existing_scenes: List[Dict[str, Any]],
        recent_titles: List[str],
        used_queries: List[str]
    ) -> Dict[str, Any]:
        """Generates a single standalone scene strictly under the assigned knowledge pillar."""
        already_used = [s["spoken_text"] for s in existing_scenes]
        already_used_summary = "\n".join(f"- {t}" for t in already_used[-4:])

        prompt = (
            f"You write viral @BrainBlud listicles for @metopato.\n\n"
            f"ASSIGNED KNOWLEDGE DOMAIN: {pillar['name']} ({pillar['desc']})\n\n"
            f"ALREADY USED THOUGHTS IN THIS VIDEO (DO NOT REPEAT CONCEPTS):\n"
            f"{already_used_summary}\n\n"
            f"Generate Scene {scene_num}: EXACTLY ONE standalone, punchy thought (12-16 words).\n"
            f"CRITICAL RULES:\n"
            f"1. Must be strictly within '{pillar['name']}'. Never write about the same topic as prior scenes.\n"
            f"2. Must be a COMPLETE thought. Do NOT end with dangling words like 'because', 'which means', 'and'.\n"
            f"3. THE WALL TEST: Must be 100% true, defensible, and testable. No fake-deep nihilism or 'nothing is real'.\n"
            f"4. Expressive cadence: incorporate '?', '!', or '—' for natural voice intonation.\n"
            f"5. Return valid JSON: {{\"spoken_text\": \"...\", \"stock_video_query\": \"...\"}}"
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

                # Intra-Script Deduplication Check
                is_duplicate = any(_token_overlap(text, prev["spoken_text"]) > 0.35 for prev in existing_scenes)
                if is_duplicate:
                    print(f"   🔄 [PILLAR DEDUP] Thought overlaps with earlier scene. Regenerating...")
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
        vetted = _load_curated_replacements(count=15)
        for cand in vetted:
            if not any(_token_overlap(cand, prev["spoken_text"]) > 0.30 for prev in existing_scenes):
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

    def _generate_loop_outro(
        self,
        hook_text: str,
        scene_num: int,
        existing_scenes: List[Dict[str, Any]],
        used_queries: List[str]
    ) -> Dict[str, Any]:
        """
        Generates Scene N:
        Inspects Scene 1's grammatical structure:
        - If Scene 1 is an independent question or condition, syntactic loops fail -> Mode B (witty deadpan closer).
        - If Scene 1 is declarative, attempts Mode A (syntactic loop with '...').
        """
        hook_lower = hook_text.lower().strip()
        is_question_or_condition = (
            hook_text.endswith("?") or
            hook_lower.startswith(("if ", "why ", "how ", "when ", "what ", "did ", "have ", "ever "))
        )

        if is_question_or_condition:
            # Mode B: Witty Self-Referential Deadpan Closer
            print("   🎭 Scene 1 is question/conditional — applying Mode B (Witty Deadpan Closer).")
            closer = random.choice(MODE_B_WITTY_CLOSERS)
            return {
                "scene_id": scene_num,
                "spoken_text": closer,
                "stock_video_query": self._pick_query("soap carving cubes ASMR", used_queries)
            }

        # Mode A: Syntactic Seamless Loop
        print("   🔁 Scene 1 is declarative — attempting Mode A (Syntactic Circular Loop)...")
        prompt = (
            f"You write seamless circular outro loops for YouTube Shorts compilations.\n\n"
            f"The video begins with Scene 1: \"{hook_text}\"\n\n"
            f"Write the FINAL SCENE of the video (6-9 words only).\n"
            f"It MUST end mid-sentence with an ellipsis '...' such that when read seamlessly into Scene 1,\n"
            f"it forms a single, grammatically perfect sentence.\n\n"
            f"CRITICAL RULES (ABSOLUTE):\n"
            f"1. ZERO REPETITION: DO NOT repeat, echo, or paraphrase ANY words, subjects, or concepts from Scene 1.\n"
            f"   Scene 1 will be heard immediately after this scene when the video loops back to the start.\n"
            f"   Repeating words from Scene 1 completely ruins the loop!\n"
            f"2. Bridge from compilation: Reference the preceding thoughts (e.g. 'And if that didn't mess with your head, remember that...').\n"
            f"3. Never end on possessives like \"'s...\" or broken fragments.\n"
            f"4. Length must be strictly 6 to 9 words.\n"
            f"Return JSON: {{\"spoken_text\": \"...\", \"stock_video_query\": \"...\"}}"
        )

        for attempt in range(2):
            try:
                res = self.llm.generate_json(
                    system_prompt="Return ONLY a JSON object with 'spoken_text' and 'stock_video_query'.",
                    user_prompt=prompt,
                    temperature=0.5,
                    task_name="script_gen"
                )
                text = res.get("spoken_text", "").strip()
                # Ensure ends with ...
                text = text.rstrip(".!? ")
                if not text.endswith("..."):
                    text = f"{text}..."
                # Guard against possessives like brain's...
                if re.search(r"['’]s\.\.\.$", text):
                    continue
                # Verify loop does NOT repeat hook words
                repeats, reason = check_loop_repeats_hook(text, hook_text)
                if repeats:
                    print(f"   ⚠️ [LOOP OUTRO] Attempt {attempt+1} repeated hook ({reason}). Retrying...")
                    continue
                # Length check: Mode A bridge must not be bloated (> 12 words)
                if len(text.split()) > 12:
                    print(f"   ⚠️ [LOOP OUTRO] Attempt {attempt+1} too long ({len(text.split())} words). Retrying...")
                    continue

                return {
                    "scene_id": scene_num,
                    "spoken_text": text,
                    "stock_video_query": self._pick_query(res.get("stock_video_query"), used_queries)
                }
            except Exception as e:
                print(f"   ⚠️ Loop attempt {attempt+1} failed ({e}).")

        # Fallback to curated compilation bridge or Mode B
        print("   ✅ Selecting curated non-repeating compilation loop bridge.")
        bridge = random.choice(COMPILATION_LOOP_BRIDGES)
        return {
            "scene_id": scene_num,
            "spoken_text": bridge,
            "stock_video_query": self._pick_query("soap carving cubes ASMR", used_queries)
        }

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

