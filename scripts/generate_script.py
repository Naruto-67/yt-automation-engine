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
    sys_msg  = prompts_cfg["script_validation"]["system_prompt"]
    user_msg = prompts_cfg["script_validation"]["user_template"].format(
        script_text=script_text
    )
    raw, _ = quota_manager.generate_text(user_msg, task_type="analysis", system_prompt=sys_msg)
    try:
        numbers = [int(n) for n in re.findall(r'\b\d+\b', raw or "")]
        if numbers:
            if len(numbers) >= 2 and numbers[-1] == 10 and numbers[-2] <= 10:
                score = numbers[-2]
            else:
                score = numbers[-1]
            return score >= 6
        return True
    except Exception as e:
        trace = traceback.format_exc()
        logger.error(f"Validation parsing error:\n{trace}")
        return True


def generate_script(niche: str, topic: str):
    """
    Generate a complete script for a YouTube Short.

    Returns
    -------
    tuple: (full_text, img_prompts, pexels_queries, scene_weights,
            provider, chosen_voice, chosen_glow)

    chosen_glow is an ASS &HAABBGGRR color code for the caption neon halo.
    It is always sourced from the 'glow_color' key in the LLM JSON response.
    Caption text itself is always white — the glow_color only affects the halo.
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

    target_scenes = random.randint(3, 5) if is_fact else random.randint(5, 7)
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
                print("⚠️ [SCRIPT] Quality validation failed. Retrying...")
                last_error = "Failed ruthless retention quality check."
                continue

            total_chars   = sum(len(s[0]) for s in parsed_scenes)
            scene_weights = (
                [len(s[0]) / total_chars for s in parsed_scenes]
                if total_chars > 0 else []
            )

            print(
                f"✅ [SCRIPT] Validated via {provider} "
                f"({word_count} words). Voice: {chosen_voice}, Glow: {chosen_glow}"
            )
            return full_text, img_prompts, pexels_queries, scene_weights, provider, chosen_voice, chosen_glow

        except Exception as e:
            last_error = str(e)
            trace = traceback.format_exc()
            print(f"⚠️ [SCRIPT] Attempt {attempt + 1} failed:\n{trace}")
            continue

    logger.error("🚨 Script Generation Fatal Exhaustion. Injecting Emergency Fallback Script.")

    fallback_text = (
        f"The story of {topic} is absolutely unbelievable. Most people have no idea what is actually "
        f"happening behind the scenes. Experts are warning that the implications could change everything "
        f"we know. As more details emerge, the truth becomes even more terrifying. Subscribe to stay "
        f"updated on this unfolding mystery."
    )
    fallback_prompts = [
        f"Cinematic, mysterious shot representing {topic}, 8k resolution",
        f"Dark, dramatic revelation about {topic}, photorealistic masterpiece",
        f"Mind-blowing conclusion of {topic}, epic lighting"
    ]
    return (
        fallback_text,
        fallback_prompts,
        [topic, "mystery", "shocking"],
        [0.33, 0.33, 0.34],
        "Emergency Fallback",
        "am_adam",
        "&H0000D700"   # default green glow on emergency fallback
    )
