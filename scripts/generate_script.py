# scripts/generate_script.py
import os
import json
import yaml
import re
from scripts.quota_manager import quota_manager
from engine.database import db

_WORDS_PER_SECOND_TTS = 130 / 60.0
_ABSOLUTE_WORD_CEILING = int(59.0 * _WORDS_PER_SECOND_TTS)

def load_config_prompts():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    path = os.path.join(root_dir, "config", "prompts.yaml")
    with open(path, "r", encoding="utf-8") as f: return yaml.safe_load(f)

def extract_scene_data(scene_dict, fallback_topic):
    if not isinstance(scene_dict, dict): return str(scene_dict), f"Cinematic shot of {fallback_topic}", fallback_topic
    narr = scene_dict.get("text") or scene_dict.get("narration") or fallback_topic
    prompt = scene_dict.get("image_prompt") or scene_dict.get("visual") or f"Cinematic {fallback_topic}"
    query = scene_dict.get("pexels_query") or fallback_topic
    return narr, prompt, query

def validate_script_quality(script_text, prompts_cfg):
    sys_msg = prompts_cfg['script_validation']['system_prompt']
    user_msg = prompts_cfg['script_validation']['user_template'].format(script_text=script_text)
    raw_score, _ = quota_manager.generate_text(user_msg, task_type="analysis", system_prompt=sys_msg)
    try: return int(re.search(r'\d+', raw_score).group()) >= 6
    except: return True 

def generate_script(niche, topic):
    print(f"🎬 [SCRIPT] Orchestrating narrative for: {topic}")
    
    channel_id = os.environ.get("CURRENT_CHANNEL_ID", "default")
    intel = db.get_channel_intelligence(channel_id)
    prompts_cfg = load_config_prompts()
    
    emp = "\n".join([f"- {r}" for r in intel.get("emphasize", [])[-3:]])
    avo = "\n".join([f"- {r}" for r in intel.get("avoid", [])[-3:]])
    vis = ", ".join(intel.get("preferred_visuals", ["Cinematic"])[:3])
    
    user_prompt = prompts_cfg['script_gen']['user_template'].format(
        niche=niche, topic=topic, emphasize_rules=emp, avoid_rules=avo, 
        visual_preference=vis, word_ceiling=_ABSOLUTE_WORD_CEILING
    )

    try:
        raw_response, provider = quota_manager.generate_text(user_prompt, task_type="creative", system_prompt=prompts_cfg['script_gen']['system_prompt'])
        if not raw_response: return None, [], [], [], "Failed"

        match = re.search(r'\{.*\}', raw_response.replace("```json", "").replace("```", "").strip(), re.DOTALL)
        if not match: return None, [], [], [], provider
            
        data = json.loads(match.group(0))
        parsed_scenes = [extract_scene_data(s, topic) for s in data.get("scenes", [])]
        full_text = " ".join([s[0] for s in parsed_scenes])
        img_prompts, pexels_queries = [s[1] for s in parsed_scenes], [s[2] for s in parsed_scenes]
        
        word_count = len(full_text.split())
        if word_count > _ABSOLUTE_WORD_CEILING or word_count < 10: return None, [], [], [], provider
        if not validate_script_quality(full_text, prompts_cfg): return None, [], [], [], provider

        total_chars = sum(len(s[0]) for s in parsed_scenes)
        scene_weights = [len(s[0])/total_chars for s in parsed_scenes] if total_chars > 0 else []
        return full_text, img_prompts, pexels_queries, scene_weights, provider
    except: return None, [], [], [], "Error"
