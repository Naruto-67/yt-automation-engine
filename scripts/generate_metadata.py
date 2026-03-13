# scripts/generate_metadata.py — Ghost Engine V13.0
import json
import os
import yaml
from scripts.quota_manager import quota_manager
from engine.database import db
from engine.context import ctx
from engine.logger import logger

def load_config_prompts():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    with open(os.path.join(root_dir, "config", "prompts.yaml"), "r", encoding="utf-8") as f: return yaml.safe_load(f)

def _build_hashtags(niche: str) -> str:
    """Return a small set of hashtags appropriate for the niche, appended to description."""
    niche_lower = niche.lower()
    if any(k in niche_lower for k in ['storytelling', 'moral', 'pixar', 'anime', 'animation']):
        return "#shorts #animation #moralstory #storytime #pixar"
    elif any(k in niche_lower for k in ['fact', 'educational', 'education', 'science']):
        return "#shorts #facts #didyouknow #educational #learnontiktok"
    elif any(k in niche_lower for k in ['space', 'cosmic', 'stellar', 'galaxy']):
        return "#shorts #space #universe #spacefacts #astronomy"
    elif any(k in niche_lower for k in ['tech', 'ai', 'future', 'automation']):
        return "#shorts #tech #ai #futuretech #technology"
    elif any(k in niche_lower for k in ['horror', 'terror', 'scary', 'eldritch']):
        return "#shorts #horror #scary #creepy #darkfacts"
    else:
        return "#shorts #viral #fyp #trending"

def generate_seo_metadata(niche, script):
    print("🔍 [SEO] Generating optimized metadata...")
    
    channel_id = ctx.get_channel_id()
    intel = db.get_channel_intelligence(channel_id)
    prompts_cfg = load_config_prompts()
    
    tags_str = ", ".join(intel.get("recent_tags", [])) or niche
    vis_str = ", ".join(intel.get("preferred_visuals", [])) or "Cinematic"

    user_msg = prompts_cfg['seo_gen']['user_template'].format(script_text=script, recent_tags=tags_str, visual_preference=vis_str)

    hashtags = _build_hashtags(niche)

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
                
                # Allow up to 500 chars of tags (YouTube limit) — old 400 cap was leaving value unused
                valid_tags = []
                total_len = 0
                for t in safe_tags:
                    if total_len + len(t) + 1 <= 490:
                        valid_tags.append(t)
                        total_len += len(t) + 1
                    else:
                        break
                
                # Append hashtags to description — YouTube uses these for hashtag search surfacing
                raw_desc = str(data.get("description", "")).replace("<", "").replace(">", "").strip()
                if raw_desc and not raw_desc.endswith(hashtags):
                    full_desc = f"{raw_desc}\n\n{hashtags}"
                else:
                    full_desc = raw_desc or hashtags

                return {
                    "title": final_title, 
                    "description": full_desc[:4900], 
                    "tags": valid_tags
                }, provider
    except Exception as e:
        # GOD-TIER FIX: Do not silently pass on extraction errors. Log them before falling back.
        logger.error(f"SEO Generation encountered an error: {e}. Executing fallback metadata.")
    
    # Fallback — use a niche-appropriate description instead of hardcoded "Mind blowing facts"
    niche_lower = niche.lower()
    if any(k in niche_lower for k in ['storytelling', 'moral', 'pixar', 'anime', 'animation']):
        fallback_desc = f"Watch this short story and discover the lesson hidden inside. {hashtags}"
    else:
        fallback_desc = f"Discover amazing facts you never knew. {hashtags}"

    return {
        "title": f"{niche} #shorts"[:95], 
        "description": fallback_desc, 
        "tags": ["shorts", niche, "viral", "facts", "fyp"]
    }, "Fallback"
