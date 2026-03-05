import os
import json
import re
from scripts.quota_manager import quota_manager

def load_recent_tags():
    """Fetches recently used tags to rotate keywords."""
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    path = os.path.join(root_dir, "assets", "lessons_learned.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f).get("recent_tags", [])
        except: pass
    return []

def update_tag_ledger(new_tags):
    """Updates the ledger with the newest tags to avoid repetition."""
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    path = os.path.join(root_dir, "assets", "lessons_learned.json")
    try:
        data = {}
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f: data = json.load(f)
        
        current = data.get("recent_tags", [])
        # Append and keep last 40 unique tags to stay under token limits
        updated = list(set(current + new_tags))[-40:]
        data["recent_tags"] = updated
        with open(path, "w", encoding="utf-8") as f: json.dump(data, f, indent=4)
    except: pass

def generate_seo_metadata(niche, script_text):
    """Generates high-CTR Title, Description, and Tags."""
    recent_tags = load_recent_tags()
    prompt = f"""
    Expert YouTube SEO: Write viral metadata for a '{niche}' video.
    Script: {script_text[:500]}
    Rule: Avoid these recent tags: {", ".join(recent_tags)}
    Return strictly JSON: {{"title": "...", "description": "...", "tags": []}}
    """

    try:
        print("🔍 [SEO] Optimizing metadata...")
        raw = quota_manager.generate_text(prompt, task_type="creative")
        if raw:
            match = re.search(r'\{.*\}', raw.replace("```json", "").replace("```", ""), re.DOTALL)
            if match:
                meta = json.loads(match.group(0))
                update_tag_ledger(meta.get("tags", []))
                return meta
        return None
    except:
        return {"title": f"{topic} #shorts", "description": "#shorts", "tags": ["viral"]}
