import os
import json
import re
import random
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
    
    # 🚨 DYNAMIC SCENE FORCER: Stop the AI from lazily picking 4 every time
    target_scenes = random.randint(4, 7)
    
    prompt = f"""
    You are an Elite YouTube Shorts Documentary Writer. Create a script for niche: '{niche}', Topic: '{topic}'.
    
    CRITICAL RULES:
    1. FACTUAL & DIRECT: This is a standalone micro-documentary. It must be 100% true, logical, and factual. No random creations.
    2. NO META-COMMENTARY: NEVER break the fourth wall. NEVER say "In this video", "Our 3D animation shows", or "Imagine a world". Just tell the facts.
    3. STRICT LENGTH LIMIT: The script MUST be exactly 85 to 95 words. Do not exceed 95 words under any circumstances. This ensures the AI voiceover has time for slow, dramatic pauses without exceeding the 60-second YouTube Shorts limit.
    4. DYNAMIC VISUAL PACING: Break the script down into distinct visual scenes based on the narrative flow.
       - You MUST provide EXACTLY {target_scenes} scenes. No more, no less.
       - Provide a highly specific image prompt for EACH scene.
       - Pick a visual style (e.g. 'Pixar 3D animation', 'Dark Cinematic', 'Photorealistic') and begin EVERY prompt with that style.
       - The prompts must perfectly illustrate the action happening in that exact moment of the script.
    
    FORMAT: Return ONLY valid JSON.
    {{
        "hook": "...",
        "body": "...",
        "image_prompts": [ ... exactly {target_scenes} prompts here ... ] 
    }}
    """

    try:
        print(f"🤖 [WRITER] Tasking AI Director for '{topic}' (Targeting {target_scenes} scenes)...")
        raw_response, provider = quota_manager.generate_text(prompt, task_type="creative")
        
        if raw_response:
            clean_json = raw_response.replace("```json", "").replace("```", "").strip()
            match = re.search(r'\{.*\}', clean_json, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                full_script = f"{data['hook']} {data['body']}"
                
                prompts = data.get('image_prompts', [])
                
                # Failsafe: if the AI still disobeys, duplicate the last prompt to hit the target
                while len(prompts) < target_scenes:
                    prompts.append(prompts[-1] if len(prompts) > 0 else f"cinematic highly detailed scene of {topic}")
                
                prompts = prompts[:target_scenes] # Trim if it went over
                
                print(f"✅ [WRITER] Script secured via {provider}. Locked in {len(prompts)} dynamic scenes.")
                return full_script, data['hook'], prompts, provider
        return None, None, [], "Failed"
    except Exception as e:
        quota_manager.diagnose_fatal_error("generate_script.py", e)
        return None, None, [], "Failed"
