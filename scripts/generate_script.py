import os
import json
import re
from scripts.quota_manager import quota_manager

def load_improvement_data():
    """Reads historical data to adjust script tone and hooks."""
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
    Generates a viral script using Groq Llama 3.3.
    Ensures a JSON output with a separate hook and body.
    """
    improvements = load_improvement_data()
    avoid_list = ", ".join(improvements.get("avoid", []))
    emphasize_list = ", ".join(improvements.get("emphasize", []))
    
    prompt = f"""
    Elite YouTube Scriptwriter: Write a viral script for niche: '{niche}', Topic: '{topic}'.
    
    CRITICAL RULES:
    - Emphasize: {emphasize_list}
    - Strictly Avoid: {avoid_list}
    - Length: Under 130 words.
    - Format: Return strictly JSON {{"hook": "...", "body": "..."}}.
    - Hook: Pattern-interrupt first 3 seconds.
    """

    try:
        print(f"🤖 [WRITER] Tasking Groq for '{topic}'...")
        raw_response = quota_manager.generate_text(prompt, task_type="creative")
        
        if raw_response:
            clean_json = raw_response.replace("```json", "").replace("```", "").strip()
            match = re.search(r'\{.*\}', clean_json, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                full_script = f"{data['hook']} {data['body']}"
                print("✅ [WRITER] Script successfully parsed.")
                return full_script, data['hook']
        
        return None, None
    except Exception as e:
        quota_manager.diagnose_fatal_error("generate_script.py", e)
        return None, None
