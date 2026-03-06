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
    
    prompt = f"""
    You are an Elite YouTube Shorts Documentary Writer. Create a script for niche: '{niche}', Topic: '{topic}'.
    
    CRITICAL RULES:
    1. FACTUAL & DIRECT: No random creations. Must be true and logical.
    2. NO META-COMMENTARY: NEVER say "In this video" or "Welcome back".
    3. STRICT LENGTH LIMIT: The total narration MUST be exactly 85 to 95 words. This is critical for the 60-second limit.
    4. DYNAMIC SCENES: Let the natural pacing of the story dictate the scenes. 
       - Break the script down into a sequence of scenes (usually 4 to 6).
       - For EACH scene, write the narration (the words spoken) and a highly specific image prompt.
       - Pick a visual style (e.g. 'Dark Cinematic', 'Photorealistic') and begin EVERY image prompt with that style.
       - The image prompt must perfectly match what is being said in the narration for that exact scene.
    
    FORMAT: Return ONLY valid JSON.
    {{
        "scenes": [
            {{
                "narration": "sentence 1...",
                "image_prompt": "Dark Cinematic shot of..."
            }},
            {{
                "narration": "sentence 2...",
                "image_prompt": "Dark Cinematic shot of..."
            }}
        ]
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
                scenes = data.get("scenes", [])
                
                # Reconstruct the full script for the voice engine
                full_script = " ".join([s["narration"] for s in scenes])
                prompts = [s["image_prompt"] for s in scenes]
                
                # 🚨 THE SYNC MATH: Calculate how much time each scene gets based on text length
                total_chars = sum(len(s["narration"]) for s in scenes)
                scene_weights = [len(s["narration"]) / total_chars for s in scenes] if total_chars > 0 else []
                
                print(f"✅ [WRITER] Script secured via {provider}. Model naturally created {len(scenes)} perfectly synced scenes.")
                return full_script, prompts, scene_weights, provider
                
        return None, [], [], "Failed"
    except Exception as e:
        quota_manager.diagnose_fatal_error("generate_script.py", e)
        return None, [], [], "Failed"
