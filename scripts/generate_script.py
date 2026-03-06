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
    target_scenes = random.randint(4, 7)
    
    prompt = f"""
    You are an Elite YouTube Shorts Documentary Writer. Create a script for niche: '{niche}', Topic: '{topic}'.
    
    CRITICAL RULES:
    1. FACTUAL & DIRECT: No random creations. Must be true and logical.
    2. NO META-COMMENTARY: NEVER say "In this video" or "Welcome back".
    3. STRICT LENGTH LIMIT: The total narration MUST be exactly 85 to 95 words. This is critical for the 60-second limit.
    4. DYNAMIC SCENES: You MUST provide EXACTLY {target_scenes} scenes.
       - For EACH scene, write the 'narration' (the words spoken).
       - Write a highly specific 'image_prompt' for an AI Image Generator (begin with a style like 'Dark Cinematic').
       - 🚨 NEW: Write a 'pexels_query'. This must be a simple 1-2 word search term (e.g. 'golden retriever', 'dark forest', 'galaxy') representing the core subject of the scene for a stock footage search.
    
    FORMAT: Return ONLY valid JSON.
    {{
        "scenes": [
            {{
                "narration": "sentence 1...",
                "image_prompt": "Dark Cinematic shot of...",
                "pexels_query": "simple keyword"
            }}
        ]
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
                scenes = data.get("scenes", [])
                
                full_script = " ".join([s["narration"] for s in scenes])
                prompts = [s["image_prompt"] for s in scenes]
                pexels_queries = [s.get("pexels_query", topic) for s in scenes]
                
                # Math weights for exact video syncing
                total_chars = sum(len(s["narration"]) for s in scenes)
                scene_weights = [len(s["narration"]) / total_chars for s in scenes] if total_chars > 0 else []
                
                print(f"✅ [WRITER] Script secured via {provider}. Synced {len(scenes)} scenes.")
                return full_script, prompts, pexels_queries, scene_weights, provider
                
        return None, [], [], [], "Failed"
    except Exception as e:
        quota_manager.diagnose_fatal_error("generate_script.py", e)
        return None, [], [], [], "Failed"
