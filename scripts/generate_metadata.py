import os
import json
import re
from scripts.retry import quota_manager

def load_recent_tags():
    """Reads the 'Tag Ledger' to prevent keyword stuffing shadowbans."""
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    tracker_path = os.path.join(root_dir, "assets", "lessons_learned.json")
    
    if os.path.exists(tracker_path):
        try:
            with open(tracker_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("recent_tags", [])
        except Exception as e:
            print(f"⚠️ [SEO] Could not read recent tags: {e}")
            
    return []

def update_tag_ledger(new_tags):
    """Updates the Tag Ledger with the newest tags, keeping only the last 30 to avoid bloat."""
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    tracker_path = os.path.join(root_dir, "assets", "lessons_learned.json")
    
    try:
        data = {}
        if os.path.exists(tracker_path):
            with open(tracker_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                
        current_tags = data.get("recent_tags", [])
        # Add new tags, convert to set to remove duplicates, then back to list
        updated_tags = list(set(current_tags + new_tags))
        
        # Keep only the 30 most recent unique tags to prevent the prompt from getting too large
        data["recent_tags"] = updated_tags[-30:]
        
        with open(tracker_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
            
    except Exception as e:
        print(f"⚠️ [SEO] Could not update tag ledger: {e}")

def get_fallback_metadata(niche):
    """Failsafe metadata if the AI Generator completely breaks."""
    clean_niche = niche.replace(" ", "")
    return {
        "title": f"The truth about {niche.title()}! 🤯 #shorts",
        "description": f"Check this out! #shorts #viral #{clean_niche}",
        "tags": ["shorts", "viral", clean_niche]
    }

def generate_seo_metadata(niche, script_text):
    """Generates viral, anti-shadowban metadata using the central Quota Manager."""
    
    recent_tags = load_recent_tags()
    avoid_tags_str = ", ".join(recent_tags) if recent_tags else "None"
    
    prompt = f"""
    You are an expert YouTube Shorts SEO manager. 
    Write the Title, Description, and Tags for this script:
    
    NICHE: {niche}
    SCRIPT: {script_text}

    CRITICAL ANTI-SPAM RULE:
    DO NOT use these exact tags (they were used recently): {avoid_tags_str}
    Generate highly unique, specific tags related only to the content of this script.

    Return EXACTLY this JSON structure. Do not include markdown formatting outside the JSON.
    {{
        "title": "Viral Title Here #shorts",
        "description": "Engaging description.\\n\\n#tag1 #tag2",
        "tags": ["key1", "key2"]
    }}
    """

    try:
        print("🔍 [SEO] Generating anti-shadowban metadata...")
        
        # Smart Router: Groq handles this beautifully and fast
        raw_response = quota_manager.generate_text(prompt, task_type="creative")
        
        if raw_response:
            # Bulletproof JSON extraction
            clean_json_str = raw_response.replace("```json", "").replace("```", "").strip()
            match = re.search(r'\{.*\}', clean_json_str, re.DOTALL)
            
            if match:
                metadata = json.loads(match.group(0))
                print(f"✅ [SEO] Metadata locked: {metadata.get('title', 'Unknown Title')}")
                
                # Update the ledger so we don't use these tags tomorrow
                update_tag_ledger(metadata.get('tags', []))
                
                return metadata
            else:
                print("⚠️ [SEO] Regex failed to find JSON block. Using fallback.")
                return get_fallback_metadata(niche)
                
        return get_fallback_metadata(niche)
        
    except Exception as e:
        print(f"❌ [SEO] Failed to parse SEO metadata: {e}")
        # We don't call the AI Doctor here because a metadata failure shouldn't crash the whole pipeline.
        # We just return the safe fallback and let the video upload.
        return get_fallback_metadata(niche)

if __name__ == "__main__":
    #
