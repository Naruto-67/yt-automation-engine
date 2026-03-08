import json
import os
import re
import yaml
from scripts.quota_manager import quota_manager

def load_config_prompts():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    path = os.path.join(root_dir, "config", "prompts.yaml")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def _load_lessons_context():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    lessons_path = os.path.join(root_dir, "assets", "lessons_learned.json")
    try:
        if os.path.exists(lessons_path):
            with open(lessons_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("recent_tags", [])[-10:], data.get("preferred_visuals", [])[:3]
    except Exception: pass
    return [], []

def generate_seo_metadata(niche, script):
    print("🔍 [SEO] Generating optimized metadata...")
    prompts_cfg = load_config_prompts()
    recent_tags, preferred_visuals = _load_lessons_context()
    
    tags_str = ", ".join(recent_tags) if recent_tags else niche
    vis_str = ", ".join(preferred_visuals) if preferred_visuals else "Cinematic"

    sys_msg = prompts_cfg['seo_gen']['system_prompt']
    user_msg = prompts_cfg['seo_gen']['user_template'].format(
        script_text=script, recent_tags=tags_str, visual_preference=vis_str
    )

    try:
        raw_text, provider = quota_manager.generate_text(user_msg, task_type="seo", system_prompt=sys_msg)
        if raw_text:
            match = re.search(r'\{.*\}', raw_text.replace("```json", "").replace("```", ""), re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                raw_title = data.get("title", f"Amazing {niche} Facts #shorts").replace("<", "").replace(">", "")
                safe_title = raw_title[:85].rsplit(' ', 1)[0] if len(raw_title) > 85 else raw_title
                if "#shorts" not in safe_title.lower(): safe_title = f"{safe_title.strip()} #shorts"
                
                return {
                    "title": safe_title[:100],
                    "description": data.get("description", "Mind blowing facts! #shorts").replace("<", "").replace(">", "")[:4900],
                    "tags": data.get("tags", ["shorts", niche])
                }, provider
    except Exception as e:
        print(f"⚠️ [SEO] Generation failed: {e}")

    return {"title": f"{niche} #shorts"[:95], "description": "Mind blowing facts! #shorts", "tags": ["shorts", niche]}, "Fallback"
