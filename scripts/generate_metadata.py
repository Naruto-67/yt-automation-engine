# scripts/generate_metadata.py
import json
import os
import yaml
from scripts.quota_manager import quota_manager
from engine.database import db

def load_config_prompts():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    with open(os.path.join(root_dir, "config", "prompts.yaml"), "r", encoding="utf-8") as f: return yaml.safe_load(f)

def generate_seo_metadata(niche, script):
    print("🔍 [SEO] Generating optimized metadata...")
    
    channel_id = os.environ.get("CURRENT_CHANNEL_ID", "default")
    intel = db.get_channel_intelligence(channel_id)
    prompts_cfg = load_config_prompts()
    
    tags_str = ", ".join(intel.get("recent_tags", [])) or niche
    vis_str = ", ".join(intel.get("preferred_visuals", [])) or "Cinematic"

    user_msg = prompts_cfg['seo_gen']['user_template'].format(script_text=script, recent_tags=tags_str, visual_preference=vis_str)

    try:
        raw_text, provider = quota_manager.generate_text(user_msg, task_type="seo", system_prompt=prompts_cfg['seo_gen']['system_prompt'])
        if raw_text:
            # God-Tier JSON Extraction (defeats LLM markdown wrappers safely)
            start = raw_text.find('{')
            end = raw_text.rfind('}')
            if start != -1 and end != -1 and end > start:
                data = json.loads(raw_text[start:end+1])
                raw_title = data.get("title", f"Amazing {niche} Facts #shorts").replace("<", "").replace(">", "")
                safe_title = raw_title[:85].rsplit(' ', 1)[0] if len(raw_title) > 85 else raw_title
                if "#shorts" not in safe_title.lower(): safe_title = f"{safe_title.strip()} #shorts"
                
                return {"title": safe_title[:100], "description": data.get("description", "Facts! #shorts").replace("<", "").replace(">", "")[:4900], "tags": data.get("tags", ["shorts", niche])}, provider
    except: pass
    return {"title": f"{niche} #shorts"[:95], "description": "Mind blowing facts! #shorts", "tags": ["shorts", niche]}, "Fallback"
