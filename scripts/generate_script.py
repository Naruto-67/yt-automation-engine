# scripts/generate_script.py — Ghost Engine V6.3
import os
import json
import yaml
import re
from scripts.quota_manager import quota_manager
from engine.database import db
from engine.config_manager import config_manager

def _compute_word_ceiling() -> int:
    settings        = config_manager.get_settings()
    tts             = settings.get("tts", {})
    base_wpm        = tts.get("base_wpm", 130)
    speed_mult      = tts.get("kokoro_speed_multiplier", 1.1)
    max_dur         = tts.get("max_duration_seconds", 59) 
    effective_wps   = (base_wpm * speed_mult) / 60.0
    return int(max_dur * effective_wps)

def load_config_prompts():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    with open(os.path.join(root_dir, "config", "prompts.yaml"), "r") as f:
        return yaml.safe_load(f)

def extract_scene_data(scene_dict, fallback_topic: str):
    if not isinstance(scene_dict, dict):
        return str(scene_dict), f"Cinematic shot of {fallback_topic}", fallback_topic
    narr   = scene_dict.get("text")     or scene_dict.get("narration") or fallback_topic
    prompt = scene_dict.get("image_prompt") or scene_dict.get("visual") or f"Cinematic {fallback_topic}"
    query  = scene_dict.get("pexels_query") or fallback_topic
    return narr, prompt, query

def validate_script_quality(script_text: str, prompts_cfg: dict) -> bool:
    sys_msg  = prompts_cfg["script_validation"]["system_prompt"]
    user_msg = prompts_cfg["script_validation"]["user_template"].format(
        script_text=script_text
    )
    raw, _ = quota_manager.generate_text(user_msg, task_type="analysis", system_prompt=sys_msg)
    try:
        score = int(re.search(r'\d+', raw or "").group())
        return score >= 6
    except Exception:
        return True 

def generate_script(niche: str, topic: str):
    print(f"🎬 [SCRIPT] Drafting narrative for: {topic}")

    word_ceiling = _compute_word_ceiling()
    channel_id   = os.environ.get("CURRENT_CHANNEL_ID", "default")
    intel        = db.get_channel_intelligence(channel_id)
    prompts_cfg  = load_config_prompts()

    emp   = "\n".join([f"- {r}" for r in intel.get("emphasize", [])[-3:]])
    avo   = "\n".join([f"- {r}" for r in intel.get("avoid", [])[-3:]])
    vis   = ", ".join(intel.get("preferred_visuals", ["Cinematic"])[:3])

    hooks = intel.get("hook_patterns", [])
    hook_context = (
        "\n🎣 PROVEN HOOK PATTERNS (from competitor analysis — adapt these):\n" +
        "\n".join([f"- {h}" for h in hooks[:3]])
        if hooks else ""
    )

    evolved = intel.get("evolved_niche")
    active_niche = evolved or niche
    if evolved and evolved != niche:
        print(f"🧬 [SCRIPT] Using evolved niche: {evolved}")

    user_prompt = prompts_cfg["script_gen"]["user_template"].format(
        niche=active_niche, topic=topic,
        emphasize_rules=emp or "Focus on viewer retention.",
        avoid_rules=avo or "Avoid slow pacing.",
        visual_preference=vis,
        word_ceiling=word_ceiling,
    )

    if hook_context:
        user_prompt += hook_context

    _FAIL = (None, [], [], [], "Error", "am_adam", "&H00FFFFFF")

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
            end = raw.rfind('}')
            if start == -1 or end == -1 or end <= start:
                continue
                
            json_payload = raw[start:end+1]
            data = json.loads(json_payload)

            chosen_voice = data.get("voice_actor", "am_adam")
            chosen_color = data.get("subtitle_color", "&H00FFFFFF")

            parsed_scenes  = [extract_scene_data(s, topic) for s in data.get("scenes", [])]
            full_text      = " ".join([s[0] for s in parsed_scenes])
            img_prompts    = [s[1] for s in parsed_scenes]
            pexels_queries = [s[2] for s in parsed_scenes]

            word_count = len(full_text.split())
            if word_count > word_ceiling:
                print(f"⚠️ [SCRIPT] Too long ({word_count} words, limit {word_ceiling}). Retrying...")
                continue
            if word_count < 10:
                print("⚠️ [SCRIPT] Script too short. Retrying...")
                continue

            if not validate_script_quality(full_text, prompts_cfg):
                print("⚠️ [SCRIPT] Quality validation failed. Retrying...")
                continue

            total_chars  = sum(len(s[0]) for s in parsed_scenes)
            scene_weights = (
                [len(s[0]) / total_chars for s in parsed_scenes]
                if total_chars > 0 else []
            )

            print(
                f"✅ [SCRIPT] Validated via {provider} "
                f"({word_count} words). Voice: {chosen_voice}, Color: {chosen_color}"
            )
            return full_text, img_prompts, pexels_queries, scene_weights, provider, chosen_voice, chosen_color

        except Exception as e:
            print(f"⚠️ [SCRIPT] Attempt {attempt+1} failed: {e}")
            continue

    return _FAIL
