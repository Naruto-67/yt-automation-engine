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
    avoid_list = ", ".join(improvements.get("avoid", ["Boring intros", "Slow pacing"]))
    emphasize_list = ", ".join(improvements.get("emphasize", ["High energy", "Curiosity"]))
    
    prompt = f"""
    You are an Elite YouTube Shorts Director. Create a viral script for niche: '{niche}', Topic: '{topic}'.
    
    CRITICAL RULES:
    1. STANDALONE SHORT: Do NOT say "Welcome back", "Part 1", or "In this series". This is a standalone micro-documentary.
    2. LENGTH: The script MUST be exactly 130 to 150 words (45 seconds of speech).
    3. STRUCTURE: Start immediately with a shocking hook. Build intense curiosity. 
    4. SYSTEM BRAIN: Emphasize: {emphasize_list}. Strictly Avoid: {avoid_list}.
    5. VISUALS: Pick the best visual aesthetic (e.g. 'Pixar 3D animation', 'Dark Cinematic', 'Cyberpunk'). Provide 4 image prompts starting with that aesthetic.
    
    FORMAT: Return ONLY valid JSON.
    {{
        "hook": "...",
        "body": "...",
        "image_prompts": [
            "...", "...", "...", "..."
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
                
                prompts = data.get('image_prompts', [])
                while len(prompts) < 4:
                    prompts.append(f"cinematic highly detailed scene of {topic}")
                prompts = prompts[:4]
                
                print("✅ [WRITER] Script and Camera Shots secured.")
                return full_script, data['hook'], prompts
        return None, None, []
    except Exception as e:
        return None, None, []
