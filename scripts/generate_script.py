# scripts/generate_script.py
import os
import json
import yaml
import re
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
    query  = scene_dict.get("stock_keyword") or fallback_topic
    return narr, prompt, query

def validate_script_quality(script_text: str, prompts_cfg: dict) -> bool:
    sys_msg  = prompts_cfg["script_validation"]["system_prompt"]
    user_msg = prompts_cfg["script_validation"]["user_template"].format(script_text=script_text)
    raw, _ = quota_manager.generate_text(user_msg, task_type="analysis", system_prompt=sys_msg)
    try:
        numbers = [int(n) for n in re.findall(r'\b\d+\b', raw or "")]
        return numbers[-1] >= 6 if numbers else True
    except:
        return True

def generate_script(niche: str, topic: str, personality: str = "Generic Creator"):
    logger.script(f"Drafting narrative for: {topic} (Personality: {personality})")

    channel_id   = ctx.get_channel_id()
    intel        = db.get_channel_intelligence(channel_id)
    prompts_cfg  = load_config_prompts()
    human_rules  = prompts_cfg.get("human_fingerprint_rules", "")

    emp  = "\n".join([f"- {r}" for r in intel.get("emphasize", [])[-3:]])
    avo  = "\n".join([f"- {r}" for r in intel.get("avoid", [])[-3:]])
    
    evolved      = intel.get("evolved_niche")
    active_niche = evolved or niche
    is_fact      = any(x in active_niche.lower() for x in ["fact", "hack", "tip", "news", "top"])

    target_scenes = random.randint(3, 5) if is_fact else random.randint(5, 7)
    target_dur    = "30-40 seconds"     if is_fact else "45-55 seconds"
    target_words  = "~75 words"         if is_fact else "~120 words"

    user_prompt = prompts_cfg["script_gen"]["user_template"]
    replacements = {
        "{niche}": active_niche,
        "{topic}": topic,
        "{personality}": personality,
        "{emphasize_rules}": emp or "Focus on viewer retention.",
        "{avoid_rules}": avo or "Avoid slow pacing.",
        "{target_duration}": target_dur,
        "{target_word_count}": target_words,
        "{word_ceiling}": str(_ABSOLUTE_WORD_CEILING)
    }
    for k, v in replacements.items():
        user_prompt = user_prompt.replace(k, v)

    user_prompt += f"\n\n🚨 HUMAN-FINGERPRINT PROTOCOL:\n{human_rules}"
    user_prompt += f"\n\nCRITICAL: Break script into EXACTLY {target_scenes} scenes."

    for attempt in range(3):
        try:
            raw, provider = quota_manager.generate_text(
                user_prompt, task_type="creative",
                system_prompt=prompts_cfg["script_gen"]["system_prompt"]
            )
            if not raw: continue

            start, end = raw.find('{'), raw.rfind('}')
            if start == -1 or end == -1: continue

            data = json.loads(raw[start:end + 1])
            clean_data = {str(k).strip(): v for k, v in data.items()}

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

            if not validate_script_quality(full_text, prompts_cfg): continue

            total_chars   = sum(len(s[0]) for s in parsed_scenes)
            scene_weights = [len(s[0]) / total_chars for s in parsed_scenes] if total_chars > 0 else []

            logger.success(f"V26 Directives Loaded. Mood: {creative_meta['mood']}")
            return full_text, img_prompts, pexels_queries, scene_weights, provider, creative_meta

        except Exception as e:
            print(f"⚠️ [SCRIPT] Attempt {attempt + 1} failed: {e}")
            continue

    return ("Fallback narrative for " + topic, [topic], [topic], [1.0], "FALLBACK", {"mood": "NEUTRAL", "music_tag": "upbeat_curiosity", "caption_style": "PUNCHY_YELLOW", "voice_actor": "am_adam", "glow_color": "&H0000D700"})
