# scripts/generate_metadata.py — Ghost Engine V9.0
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
            start = raw_text.find('{')
            end = raw_text.rfind('}')
            if start != -1 and end != -1 and end > start:
                data = json.loads(raw_text[start:end+1])
                
                if "metadata" in data and isinstance(data["metadata"], dict):
                    data = data["metadata"]
                elif isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                    data = data[0]
                    
                # GOD-TIER FIX: Coerce hallucinated raw string arrays into empty dict 
                # preventing fatal AttributeError: 'list' object has no attribute 'get'
                if not isinstance(data, dict):
                    data = {}
                
                safe_title_raw = data.get("title", f"Amazing {niche} Facts #shorts")
                if isinstance(safe_title_raw, list): 
                    safe_title_raw = safe_title_raw[0] if safe_title_raw else f"Amazing {niche} Facts #shorts"
                
                raw_title = str(safe_title_raw).replace("<", "").replace(">", "").strip()
                
                safe_title = raw_title[:85].rsplit(' ', 1)[0] if len(raw_title) > 85 else raw_title
                if "#shorts" not in safe_title.lower(): 
                    safe_title = f"{safe_title.strip()} #shorts"
                
                final_title = safe_title[:100] if len(safe_title) > 0 else "Amazing Video #shorts"
                
                raw_tags = data.get("tags", ["shorts", niche])
                if isinstance(raw_tags, str):
                    safe_tags = [t.strip().replace("#", "") for t in raw_tags.split(",") if t.strip()]
                elif isinstance(raw_tags, list):
                    safe_tags = [str(t).strip().replace("#", "") for t in raw_tags if str(t).strip()]
                else:
                    safe_tags = ["shorts", niche]
                
                return {
                    "title": final_title, 
                    "description": str(data.get("description", "Facts! #shorts")).replace("<", "").replace(">", "")[:4900], 
                    "tags": safe_tags[:15]
                }, provider
    except: pass
    
    return {
        "title": f"{niche} #shorts"[:95], 
        "description": "Mind blowing facts! #shorts", 
        "tags": ["shorts", niche]
    }, "Fallback"
