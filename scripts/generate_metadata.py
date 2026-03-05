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
                return json.loads(match.group(0)), provider
    except Exception as e:
        print(f"⚠️ [SEO] Generation failed: {e}")
        
    return {"title": f"Amazing {niche} Facts #shorts", "description": "Mind blowing facts! #shorts", "tags": ["shorts", niche]}, "Fallback Defaults"
