# scripts/generate_metadata.py
# Ghost Engine V26.0.0 — Curiosity-Driven SEO & Metadata Logic
import json
import os
import yaml
from scripts.quota_manager import quota_manager
from engine.database import db
from engine.context import ctx
from engine.logger import logger

def load_config_prompts():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    with open(os.path.join(root_dir, "config", "prompts.yaml"), "r", encoding="utf-8") as f: 
        return yaml.safe_load(f)

def _build_hashtags(niche: str) -> str:
    """
    V26: Expanded hashtag sets for dynamic niche rotation. 
    """
    niche_lower = niche.lower()
    if any(k in niche_lower for k in ['storytelling', 'moral', 'pixar', 'anime', 'animation']):
        return "#shorts #animation #moralstory #storytime #pixar"
    elif any(k in niche_lower for k in ['dark', 'terrifying', 'unsettling', 'horror']):
        return "#shorts #darkfacts #creepy #horror #unsettling"
    elif any(k in niche_lower for k in ['funny', 'ridiculous', 'bizarre', 'quirky']):
        return "#shorts #funny #weirdfacts #humor #randomfacts"
    elif any(k in niche_lower for k in ['space', 'universe', 'cosmic', 'science']):
        return "#shorts #space #science #astronomy #universe"
    elif any(k in niche_lower for k in ['fact', 'educational', 'didyouknow']):
        return "#shorts #facts #didyouknow #educational #curiosity"
    else:
        return "#shorts #viral #trending #fyp"

def generate_seo_metadata(niche, script):
    """
    Orchestrates the AI-generation of viral titles and descriptions. [cite: 244-258]
    """
    print("🔍 [SEO] Generating optimized V26 metadata...")
    
    channel_id = ctx.get_channel_id()
    intel = db.get_channel_intelligence(channel_id)
    prompts_cfg = load_config_prompts()
    
    # Pull previous success patterns from database intelligence
    tags_str = ", ".join(intel.get("recent_tags", [])) or niche
    vis_str = ", ".join(intel.get("preferred_visuals", [])) or "Cinematic"

    user_msg = prompts_cfg['seo_gen']['user_template'].format(
        script_text=script, 
        recent_tags=tags_str, 
        visual_preference=vis_str
    )

    hashtags = _build_hashtags(niche)

    try:
        raw_text, provider = quota_manager.generate_text(
            user_msg, 
            task_type="seo", 
            system_prompt=prompts_cfg['seo_gen']['system_prompt']
        )
        
        if raw_text:
            start = raw_text.find('{')
            end = raw_text.rfind('}')
            if start != -1 and end != -1:
                data = json.loads(raw_text[start:end+1])
                
                # Cleanup and sanitize Title 
                raw_title = str(data.get("title", f"Amazing {niche} Facts")).strip()
                raw_title = raw_title.replace("<", "").replace(">", "").replace('"', '')
                
                # Force #shorts tag into the title for algorithm indexing
                if "#shorts" not in raw_title.lower():
                    raw_title = f"{raw_title[:90]} #shorts"
                
                final_title = raw_title[:100]
                
                # Process Tags (YouTube limit is 500 characters) [cite: 250-253]
                raw_tags = data.get("tags", ["shorts", niche])
                if isinstance(raw_tags, str):
                    safe_tags = [t.strip() for t in raw_tags.split(",")]
                else:
                    safe_tags = [str(t).strip() for t in raw_tags]
                
                valid_tags = []
                total_len = 0
                for t in safe_tags:
                    if total_len + len(t) + 1 <= 490:
                        valid_tags.append(t)
                        total_len += len(t) + 1
                
                # Final Description assembly [cite: 254-255]
                raw_desc = str(data.get("description", "Check this out!")).strip()
                full_desc = f"{raw_desc}\n\n{hashtags}"

                return {
                    "title": final_title, 
                    "description": full_desc[:4900], 
                    "tags": valid_tags
                }, provider
                
    except Exception as e:
        logger.error(f"SEO Generation failed: {e}. Executing V26 fallback.")
    
    # V26 Hard Fallback Logic [cite: 257-258]
    return {
        "title": f"The Truth About {niche} #shorts"[:95], 
        "description": f"You won't believe what we found. {hashtags}", 
        "tags": ["shorts", niche, "viral", "facts"]
    }, "V26-Fallback"
