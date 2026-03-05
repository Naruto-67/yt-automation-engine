import os
import json
import re
from scripts.quota_manager import quota_manager

def load_recent_tags():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    path = os.path.join(root_dir, "assets", "lessons_learned.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f).get("recent_tags", [])
        except: pass
    return []

def update_tag_ledger(new_tags):
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    path = os.path.join(root_dir, "assets", "lessons_learned.json")
    try:
        data = {}
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f: data = json.load(f)
        
        current = data.get("recent_tags", [])
        # Append and keep last 40 unique tags
        updated = list(set(current + new_tags))[-40:]
        data["recent_tags"] = updated
        with open(path, "w", encoding="utf-8") as f: json.dump(data, f, indent=4)
    except: pass

def generate_seo_metadata(niche, script_text):
    """Generates viral, anti-shadowban metadata."""
    recent_tags = load_recent_tags()
    prompt = f"""
    Expert YouTube SEO Manager: Write metadata for a '{niche}' video.
    Script: {script_text[:500]}
    Avoid using these recent tags: {", ".join(recent_tags)}
    Return JSON: {{"title": "...", "description": "...", "tags": []}}
    """

    try:
        raw = quota_manager.generate_text(prompt, task_type="creative")
        if raw:
            clean = re.search(r'\{.*\}', raw.replace("```json", "").replace("```", ""), re.DOTALL).group(0)
            meta = json.loads(clean)
            update_tag_ledger(meta.get("tags", []))
            return meta
    except:
        return {"title": f"{niche.title()} Discovery #shorts", "description": "#shorts #viral", "tags": [niche, "viral"]}
