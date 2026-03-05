import os
import json
import re
from scripts.quota_manager import quota_manager

def load_improvement_data():
    """Reads historical performance data to inject into the prompt."""
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    tracker_path = os.path.join(root_dir, "assets", "lessons_learned.json")
    
    if os.path.exists(tracker_path):
        try:
            with open(tracker_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except: pass
    return {"avoid": [], "emphasize": ["Fast pacing", "Strong visual hooks"]}

def generate_script(niche, topic):
    """
    Generates a viral script using the Master Router.
    Enforces the 3-Second Hook Lock and outputs clean JSON.
    """
    improvements = load_improvement_data()
    avoid_list = ", ".join(improvements.get("avoid", []))
    emphasize_list = ", ".join(improvements.get("emphasize", []))
    
    prompt = f"""
    You are an elite YouTube Shorts scriptwriter. Write a viral script for: '{niche}'.
    Topic: '{topic}'
    
    RULES:
    - Emphasize: {emphasize_list}
    - Avoid: {avoid_list}
    - Length: Under 130 words.
    - Format: JSON object {{"hook": "...", "body": "..."}}.
    - Hook: The first 3 seconds. Must be a pattern-interrupt statement.
    """

    try:
        print(f"📝 [WRITER] Drafting viral script for '{topic}'...")
        raw_response = quota_manager.generate_text(prompt, task_type="creative")
        
        if raw_response:
            clean_json = raw_response.replace("```json", "").replace("```", "").strip()
            match = re.search(r'\{.*\}', clean_json, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                full_script = f"{data['hook']} {data['body']}"
                return full_script, data['hook']
        return None, None
    except Exception as e:
        quota_manager.diagnose_fatal_error("generate_script.py", e)
        return None, None
