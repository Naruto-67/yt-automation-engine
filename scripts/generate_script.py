# ================================================
# FILE: scripts/generate_script.py
# ================================================
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
    Returns the full script, the hook, and exactly 4 image prompts.
    """
    improvements = load_improvement_data()
    avoid_list = ", ".join(improvements.get("avoid", []))
    emphasize_list = ", ".join(improvements.get("emphasize", []))
    
    prompt = f"""
    You are an Elite YouTube Shorts Director. Create a viral script for niche: '{niche}', Topic: '{topic}'.
    
    CRITICAL RULES:
    - Length: Under 120 words total.
    - Hook: Must be a pattern-interrupt in the first 3 seconds.
    - Emphasize: {emphasize_list}
    - Avoid: {avoid_list}
    - Visuals: Provide EXACTLY 4 highly detailed image generation prompts that match the chronological flow of the story. 
      Make them descriptive (e.g., "hyper realistic dark cinematic 8k ancient city at night").
    
    FORMAT: Return ONLY valid JSON. No markdown, no intro.
    {{
        "hook": "...",
        "body": "...",
        "image_prompts": [
            "prompt for part 1",
            "prompt for part 2",
            "prompt for part 3",
            "prompt for part 4"
        ]
    }}
    """

    try:
        print(f"🤖 [WRITER] Tasking Groq Director for '{topic}'...")
        raw_response = quota_manager.generate_text(prompt, task_type="creative")
        
        if raw_response:
            clean_json = raw_response.replace("```json", "").replace("```", "").strip()
            match = re.search(r'\{.*\}', clean_json, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                full_script = f"{data['hook']} {data['body']}"
                
                # Failsafe: Ensure we have exactly 4 prompts, pad with the topic if AI messes up
                prompts = data.get('image_prompts', [])
                while len(prompts) < 4:
                    prompts.append(f"cinematic dark atmospheric scene about {topic}")
                prompts = prompts[:4] # Cap at 4
                
                print("✅ [WRITER] Script and 4 Camera Shots successfully parsed.")
                return full_script, data['hook'], prompts
        
        return None, None, []
    except Exception as e:
        quota_manager.diagnose_fatal_error("generate_script.py", e)
        return None, None, []
