# scripts/generate_script.py
import os
import json
import yaml
import re
from scripts.quota_manager import quota_manager

_WORDS_PER_SECOND_TTS = 130 / 60.0
_ABSOLUTE_WORD_CEILING = int(59.0 * _WORDS_PER_SECOND_TTS)

def load_config_prompts():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    path = os.path.join(root_dir, "config", "prompts.yaml")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def load_lessons():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    path = os.path.join(root_dir, "assets", "lessons_learned.json")
    if not os.path.exists(path):
        return {"emphasize": [], "avoid": [], "preferred_visuals": ["Cinematic"]}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def extract_scene_data(scene_dict, fallback_topic):
    if not isinstance(scene_dict, dict):
        return str(scene_dict), f"Cinematic shot of {fallback_topic}", fallback_topic
    
    narr = scene_dict.get("text") or scene_dict.get("narration") or fallback_topic
    prompt = scene_dict.get("image_prompt") or scene_dict.get("visual") or f"Cinematic {fallback_topic}"
    query = scene_dict.get("pexels_query") or fallback_topic
    return narr, prompt, query

def validate_script_quality(script_text, prompts_cfg):
    """POINT 12: LLM Multi-layer coherence and quality scoring."""
    sys_msg = prompts_cfg['script_validation']['system_prompt']
    user_msg = prompts_cfg['script_validation']['user_template'].format(script_text=script_text)
    
    raw_score, _ = quota_manager.generate_text(user_msg, task_type="analysis", system_prompt=sys_msg)
    try:
        score = int(re.search(r'\d+', raw_score).group())
        return score >= 6
    except:
        return True # Default pass if parsing fails

def generate_script(niche, topic):
    print(f"🎬 [SCRIPT] Orchestrating narrative for: {topic}")
    
    prompts_cfg = load_config_prompts()
    lessons = load_lessons()
    
    emp = "\n".join([f"- {r}" for r in lessons.get("emphasize", [])[-3:]])
    avo = "\n".join([f"- {r}" for r in lessons.get("avoid", [])[-3:]])
    vis = ", ".join(lessons.get("preferred_visuals", ["Cinematic"])[:3])
    
    user_prompt = prompts_cfg['script_gen']['user_template'].format(
        niche=niche, topic=topic, emphasize_rules=emp, avoid_rules=avo, 
        visual_preference=vis, word_ceiling=_ABSOLUTE_WORD_CEILING
    )
    system_msg = prompts_cfg['script_gen']['system_prompt']

    try:
        raw_response, provider = quota_manager.generate_text(user_prompt, task_type="creative", system_prompt=system_msg)
        if not raw_response: return None, [], [], [], "Failed"

        clean_str = raw_response.replace("```json", "").replace("```", "").strip()
        match = re.search(r'\{.*\}', clean_str, re.DOTALL)
        if not match: return None, [], [], [], provider
            
        data = json.loads(match.group(0))
        scenes = data.get("scenes", [])
        
        parsed_scenes = [extract_scene_data(s, topic) for s in scenes]
        full_text = " ".join([s[0] for s in parsed_scenes])
        img_prompts = [s[1] for s in parsed_scenes]
        pexels_queries = [s[2] for s in parsed_scenes]
        
        word_count = len(full_text.split())
        if word_count > _ABSOLUTE_WORD_CEILING or word_count < 10:
            print(f"⚠️ [SCRIPT] Length ({word_count}w) invalid. Rejecting.")
            return None, [], [], [], provider

        if not validate_script_quality(full_text, prompts_cfg):
            print(f"⚠️ [SCRIPT] Rejected by AI Validator (Score < 6/10).")
            return None, [], [], [], provider

        total_chars = sum(len(s[0]) for s in parsed_scenes)
        scene_weights = [len(s[0])/total_chars for s in parsed_scenes] if total_chars > 0 else []

        print(f"✅ [SCRIPT] Validated & Generated via {provider}")
        return full_text, img_prompts, pexels_queries, scene_weights, provider

    except Exception as e:
        print(f"❌ [SCRIPT ERROR] {e}")
        return None, [], [], [], "Error"
