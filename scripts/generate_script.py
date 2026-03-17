# scripts/generate_script.py
# Ghost Engine V26.0.0 — Human-Fingerprint & Resilient Directing
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
            # Retention check: Looking for a score >= 6
            score = numbers[-1]
            return score >= 6
        return True
    except Exception as e:
        logger.error(f"Validation parsing error: {e}")
        return True

def generate_script(niche: str, topic: str, personality: str = "Generic Creator"):
    """
    Generate a complete script for a YouTube Short with V26 Human-Fingerprint logic.
    """
    print(f"🎬 [SCRIPT] Drafting narrative for: {topic} (Personality: {personality})")

    channel_id   = ctx.get_channel_id()
    intel        = db.get_channel_intelligence(channel_id)
    prompts_cfg  = load_config_prompts()
    
    # Extract Human-Fingerprint rules to inject into the prompt
    human_rules = prompts_cfg.get("human_fingerprint_rules", "")

    emp  = "\n".join([f"- {r}" for r in intel.get("emphasize", [])[-3:]])
    avo  = "\n".join([f"- {r}" for r in intel.get("avoid", [])[-3:]])
    vis  = ", ".join(intel.get("preferred_visuals", ["Cinematic"])[:3])

    hooks = intel.get("hook_patterns", [])
    hook_context = (
        "\n🎣 PROVEN HOOK PATTERNS (Adapt these):\n" +
        "\n".join([f"- {h}" for h in hooks[:3]])
        if hooks else ""
    )

    evolved      = intel.get("evolved_niche")
    active_niche = evolved or niche
    
    niche_lower  = active_niche.lower()
    is_fact      = any(x in niche_lower for x in ["fact", "hack", "tip", "news", "top", "brainrot"])

    target_scenes = random.randint(3, 5) if is_fact else random.randint(5, 7)
    target_dur    = "30-40 seconds"     if is_fact else "45-55 seconds"
    target_words  = "~75 words"         if is_fact else "~120 words"

    user_prompt = prompts_cfg["script_gen"]["user_template"].format(
        niche=active_niche,
        topic=topic,
        personality=personality,
        emphasize_rules=emp or "Focus on viewer retention.",
        avoid_rules=avo or "Avoid slow pacing.",
        target_duration=target_dur,
        target_word_count=target_words,
        word_ceiling=_ABSOLUTE_WORD_CEILING
    )

    # Injecting V26 Specific Directives
    user_prompt += f"\n\n🚨 HUMAN-FINGERPRINT PROTOCOL:\n{human_rules}"
    user_prompt += (
        f"\n\nCRITICAL: Break script into EXACTLY {target_scenes} scenes."
        f"The text must be a single cohesive narrative.\n{hook_context}"
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
                continue

            start = raw.find('{')
            end   = raw.rfind('}')
            if start == -1 or end == -1:
                continue

            data = json.loads(raw[start:end + 1])

            # 🛠️ V26 FIX: Sanitize keys to handle the '\n  "mood"' crash
            clean_data = {str(k).strip(): v for k, v in data.items()}

            # V26 Creative Extraction
            creative_meta = {
                "mood":          str(clean_data.get("mood", "NEUTRAL")).strip().upper(),
                "music_tag":     str(clean_data.get("music_tag", "upbeat_curiosity")).strip().lower(),
                "caption_style": str(clean_data.get("caption_style", "NEON_HORNET")).strip().upper(),
                "voice_actor":   str(clean_data.get("voice_actor", "am_adam")).strip().lower(),
                "glow_color":    str(clean_data.get("glow_color", "&H0000D700")).strip().upper()
            }

            parsed_scenes  = [extract_scene_data(s, topic) for s in clean_data.get("scenes", [])]
            full_text      = " ".join([s[0] for s in parsed_scenes])
            img_prompts    = [s[1] for s in parsed_scenes]
            pexels_queries = [s[2] for s in parsed_scenes]

            word_count = len(full_text.split())
            
            if word_count > _ABSOLUTE_WORD_CEILING:
                last_error = f"Too long: {word_count} words."
                continue

            if word_count < 15:
                last_error = "Too short."
                continue

            if not validate_script_quality(full_text, prompts_cfg):
                last_error = "Failed retention quality check."
                continue

            total_chars   = sum(len(s[0]) for s in parsed_scenes)
            scene_weights = [len(s[0]) / total_chars for s in parsed_scenes] if total_chars > 0 else []

            print(f"✅ [SCRIPT] V26 Directives Loaded. Mood: {creative_meta['mood']} | Style: {creative_meta['caption_style']}")
            return full_text, img_prompts, pexels_queries, scene_weights, provider, creative_meta

        except Exception as e:
            last_error = str(e)
            print(f"⚠️ [SCRIPT] Attempt {attempt + 1} failed: {last_error}")
            continue

    logger.error("🚨 Script Generation Exhausted. Using V26 Fallback.")
    
    fallback_meta = {
        "mood": "TERRIFYING", "music_tag": "horror_drones", 
        "caption_style": "BOLD_CRITICAL", "voice_actor": "am_adam", 
        "glow_color": "&H000015FF"
    }
    
    return (
        f"The mystery of {topic} is deeper than anyone realized. Most people look at the surface, "
        f"but the truth hidden beneath is actually quite disturbing. What we found changes "
        f"everything we thought we knew about this. Subscribe if you're ready for the truth.",
        [f"Mysterious, cinematic shot of {topic}", "Dark revelation, high detail", "Shocking conclusion"],
        [topic, "mystery"],
        [0.33, 0.33, 0.34],
        "V26 Emergency Fallback",
        fallback_meta
    )
