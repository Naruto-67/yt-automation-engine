import os
import json
import re
from scripts.quota_manager import quota_manager

def load_improvement_data():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    tracker_path = os.path.join(root_dir, "assets", "lessons_learned.json")
    if os.path.exists(tracker_path):
        try:
            with open(tracker_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except: pass
    return {"avoid": [], "emphasize": []}

def generate_script(niche, topic):
    improvements = load_improvement_data()
    avoid_list = ", ".join(improvements.get("avoid", ["Boring intros"]))
    emphasize_list = ", ".join(improvements.get("emphasize", ["High energy"]))
    
    prompt = f"""
    You are an Elite YouTube Shorts Documentary Writer. Create a script for niche: '{niche}', Topic: '{topic}'.
    
    CRITICAL RULES:
    1. FACTUAL & DIRECT: This is a standalone micro-documentary. It must be 100% true, logical, and factual. No random creations.
    2. NO META-COMMENTARY: NEVER break the fourth wall. NEVER say "In this video", "Our 3D animation shows", or "Imagine a world". Just tell the facts.
    3. LENGTH: The script MUST be exactly 130 to 150 words.
    4. VISUALS TO AUDIO SYNC: You must provide exactly 4 image prompts. 
       - Prompt 1 must perfectly illustrate exactly what happens in the first 25% of the script.
       - Prompt 2 must perfectly illustrate the next 25%, etc.
       - Pick a visual style (e.g. 'Pixar 3D animation', 'Dark Cinematic') and begin EVERY prompt with that style.
       - Make the prompts literal and highly specific to the action being described.
    
    FORMAT: Return ONLY valid JSON.
    {{
        "hook": "...",
        "body": "...",
        "image_prompts": ["...", "...", "...", "..."]
    }}
    """

    try:
        print(f"🤖 [WRITER] Tasking AI Director for '{topic}'...")
        raw_response, provider = quota_manager.generate_text(prompt, task_type="creative")
        
        if raw_response:
            clean_json = raw_response.replace("```json", "").replace("```", "").strip()
            match = re.search(r'\{.*\}', clean_json, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                full_script = f"{data['hook']} {data['body']}"
                
                prompts = data.get('image_prompts', [])
                while len(prompts) < 4:
                    prompts.append(f"cinematic highly detailed scene of {topic}")
                prompts = prompts[:4]
                
                print(f"✅ [WRITER] Script secured via {provider}.")
                return full_script, data['hook'], prompts, provider
        return None, None, [], "Failed"
    except Exception as e:
        quota_manager.diagnose_fatal_error("generate_script.py", e)
        return None, None, [], "Failed"
