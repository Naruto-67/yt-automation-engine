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
_MAX_VIDEO_SECONDS = 59.0
_ABSOLUTE_WORD_CEILING = int(_MAX_VIDEO_SECONDS * _WORDS_PER_SECOND_TTS)


def load_config_prompts():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    with open(os.path.join(root_dir, "config", "prompts.yaml"), "r") as f:
        return yaml.safe_load(f)


def extract_scene_data(scene_dict, fallback_topic: str):
    if not isinstance(scene_dict, dict):
        return str(scene_dict), f"Cinematic shot of {fallback_topic}", fallback_topic
    narr   = scene_dict.get("text")         or scene_dict.get("narration") or fallback_topic
    prompt = scene_dict.get("image_prompt") or scene_dict.get("visual")    or f"Cinematic {fallback_topic}"
    query  = scene_dict.get("pexels_query") or fallback_topic
    return narr, prompt, query


def validate_script_quality(script_text: str, prompts_cfg: dict) -> bool:
    """
    Quality gate: reject only genuinely bad scripts (score 1-3 out of 10).

    Threshold is intentionally LOW (4) because:
    - Storytelling scripts (AnimeRise) naturally score lower on "viral hook" criteria
    - A score of 4-5 is "decent" — not worth discarding and wasting 2 more LLM calls
    - Only score 1-3 indicates a truly broken or incoherent script
    - If the validation API fails or returns no number: always PASS (fail-safe)

    Root cause of previous over-rejection: threshold was 6, which caused 128-word
    well-structured storytelling scripts to fail 3/3 times and trigger fallback.
    """
    sys_msg  = prompts_cfg["script_validation"]["system_prompt"]
    user_msg = prompts_cfg["script_validation"]["user_template"].format(
        script_text=script_text
    )

    try:
        raw, _ = quota_manager.generate_text(user_msg, task_type="analysis", system_prompt=sys_msg)
    except Exception:
        # If validation API call itself fails, pass the script — don't waste retries
        return True

    if not raw:
        return True  # Empty response → pass (fail-safe)

    try:
        numbers = [int(n) for n in re.findall(r'\b\d+\b', raw)]
        if not numbers:
            return True  # No number found → pass (fail-safe, not a failure)

        # Handle "7/10" or "Score: 7 out of 10" format → take the score, not the denominator
        if len(numbers) >= 2 and numbers[-1] == 10 and numbers[-2] <= 10:
            score = numbers[-2]
        else:
            score = numbers[-1]

        # Only reject truly bad scripts (1, 2, or 3 out of 10)
        # Scores 4-10 all pass — we trust the LLM's generation over the validator's harsh rating
        passed = score >= 4
        if not passed:
            print(f"⚠️ [SCRIPT] Quality validator returned {score}/10 — below rejection threshold of 4. Retrying...")
        return passed

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

    emp  = "\n".join([f"- {r}" for r in intel.get("emphasize", [])[-3:]])
    avo  = "\n".join([f"- {r}" for r in intel.get("avoid",     [])[-3:]])
    vis  = ", ".join(intel.get("preferred_visuals", ["Cinematic"])[:3])

    hooks = intel.get("hook_patterns", [])
    hook_context = (
        "\n🎣 PROVEN HOOK PATTERNS (from competitor analysis — adapt these):\n" +
        "\n".join([f"- {h}" for h in hooks[:3]])
        if hooks else ""
    )

    evolved      = intel.get("evolved_niche")
    active_niche = evolved or niche
    if evolved and evolved != niche:
        print(f"🧬 [SCRIPT] Using evolved niche: {evolved}")

    niche_lower  = active_niche.lower()
    is_fact      = any(x in niche_lower for x in ["fact", "hack", "tip", "news", "top", "brainrot"])

    target_scenes = random.randint(6, 9) if is_fact else random.randint(8, 12)
    target_dur    = "30-40 seconds"     if is_fact else "45-55 seconds"
    target_words  = "~75 words"         if is_fact else "~120 words"

    user_prompt = prompts_cfg["script_gen"]["user_template"].format(
        niche=active_niche,
        topic=topic,
        emphasize_rules=emp or "Focus on viewer retention.",
        avoid_rules=avo or "Avoid slow pacing.",
        visual_preference=vis,
        target_duration=target_dur,
        target_word_count=target_words,
        word_ceiling=_ABSOLUTE_WORD_CEILING
    )

    user_prompt += (
        f"\n\nCRITICAL INSTRUCTION: Break the script into EXACTLY {target_scenes} visual scenes. "
        f"The combined text across all scenes MUST be a detailed, multi-sentence narrative. {hook_context}"
    )

    last_error = "Unknown Error"

    for attempt in range(3):
        try:
            raw, provider = quota_manager.generate_text(
                user_prompt,
                task_type="creative",
                system_prompt=prompts_cfg["script_gen"]["system_prompt"]
            )
            if not raw:
                last_error = "API returned empty response."
                continue

            start = raw.find('{')
            end   = raw.rfind('}')
            if start == -1 or end == -1 or end <= start:
                last_error = "Malformed JSON boundary returned by AI."
                continue

            json_payload = raw[start:end + 1]
            data         = json.loads(json_payload)

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

            if word_count > _ABSOLUTE_WORD_CEILING:
                print(f"      ⚠️ [SCRIPT] Too long ({word_count} words, limit {_ABSOLUTE_WORD_CEILING}). Retrying...")
                last_error = "Script exceeded maximum mathematical word count."
                continue

            if word_count < 15:
                print(f"      ⚠️ [SCRIPT] Script critically short ({word_count} words). Retrying...")
                last_error = "Script generated below functional minimum."
                continue

            if not validate_script_quality(full_text, prompts_cfg):
                last_error = "Failed quality check (score < 4/10)."
                continue

            total_chars   = sum(len(s[0]) for s in parsed_scenes)
            scene_weights = (
                [len(s[0]) / total_chars for s in parsed_scenes]
                if total_chars > 0 else []
            )

            print(
                f"✅ [SCRIPT] Validated via {provider} "
                f"({word_count} words). Voice: {chosen_voice}, "
                f"Glow: {chosen_glow}, Mood: {chosen_mood}, Style: {chosen_caption_style}"
            )
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
    logger.error("🚨 Script Generation Fatal Exhaustion. Injecting Emergency Fallback Script.")

    fb = random.choice(_FALLBACK_SCRIPTS)

    fallback_weights = [1.0 / len(fb["prompts"])] * len(fb["prompts"])
    # Make last weight absorb rounding error
    if fallback_weights:
        fallback_weights[-1] = 1.0 - sum(fallback_weights[:-1])

    return (
        fb["text"],
        fb["prompts"],
        fb["pexels"],
        fallback_weights,
        "Emergency Fallback",
        fb["voice"],
        fb["glow_color"],
        fb["mood"],
        fb["caption_style"],
    )
