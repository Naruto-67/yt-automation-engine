import json
import re
from scripts.quota_manager import quota_manager

def generate_seo_metadata(niche, script):
    print("🔍 [SEO] Generating optimized metadata...")
    prompt = f"""
    Generate highly optimized, viral YouTube Shorts metadata for this exact script.
    
    SCRIPT: 
    {script}
    
    RULES:
    1. Title must be under 60 characters and highly clickable.
    2. Description must be exactly 2 sentences and include #shorts.
    3. Provide exactly 5 highly relevant tags.
    4. Do not use angle brackets (< or >) anywhere in the text.
    
    FORMAT: Return ONLY valid JSON.
    {{
        "title": "...",
        "description": "...",
        "tags": ["...", "...", "..."]
    }}
    """
    
    try:
        raw_text, provider = quota_manager.generate_text(prompt, task_type="seo")
        if raw_text:
            match = re.search(r'\{.*\}', raw_text.replace("```json", "").replace("```", ""), re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                
                raw_title = data.get("title", f"Amazing {niche} Facts #shorts").replace("<", "").replace(">", "")
                raw_desc = data.get("description", "Mind blowing facts! #shorts").replace("<", "").replace(">", "")
                
                # 🚨 FIX: Algorithmically shields the #shorts hashtag, guaranteeing it survives truncation for the YouTube Feed indexer.
                safe_title = raw_title[:85]
                if len(raw_title) > 85:
                    safe_title = safe_title.rsplit(' ', 1)[0]
                
                if "#shorts" not in safe_title.lower():
                    safe_title = f"{safe_title.strip()} #shorts"
                
                data["title"] = safe_title[:100]
                data["description"] = raw_desc[:4900]
                
                return data, provider
    except Exception as e:
        print(f"⚠️ [SEO] Generation failed: {e}")
        
    return {"title": f"Amazing {niche} Facts #shorts"[:95], "description": "Mind blowing facts! #shorts", "tags": ["shorts", niche]}, "Fallback Defaults"
