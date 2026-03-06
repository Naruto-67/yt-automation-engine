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
    
    # 🚨 ONE-SHOT PROMPT LOCK: We added a strict "Validation Step" instruction to the AI.
    prompt = f"""
    You are an Elite YouTube Shorts Documentary Writer. Create a script for niche: '{niche}', Topic: '{topic}'.
    
    CRITICAL RULES:
    1. FACTUAL & DIRECT: No random creations. Must be true and logical.
    2. NO META-COMMENTARY: NEVER say "In this video" or "Welcome back".
    3. STRICT LENGTH LIMIT: The total script MUST be exactly 85 to 95 words. This is critical for the 60-second limit.
    4. DYNAMIC SCENES: To sync the video perfectly, break the script into EXACTLY {target_scenes} scenes.
       - For EACH scene, write the 'text' (the words spoken in that scene).
       - Write an 'image_prompt' (begin with a style like 'Dark Cinematic').
       - Write a 'pexels_query' (a simple 1-2 word search term like 'abandoned house').
    
    VALIDATION STEP: Before you output, verify that your JSON contains exactly the keys "text", "image_prompt", and "pexels_query" for every single scene. Do not rename them.
    
    FORMAT: Return ONLY valid JSON.
    {{
        "scenes": [
            {{
                "text": "sentence 1...",
                "image_prompt": "Dark Cinematic shot of...",
                "pexels_query": "simple keyword"
            }}
        ]
    }}
    """

    try:
        print(f"🤖 [WRITER] Tasking AI Director for '{topic}' (Targeting {target_scenes} scenes)...")
        raw_response, provider = quota_manager.generate_text(prompt, task_type="creative")
        
        # 🚨 RAW LOGGING: This will print the exact response to your GitHub Actions console
        print("\n📜 --- RAW AI RESPONSE LOG --- 📜")
        print(raw_response if raw_response else "NONE")
        print("---------------------------------\n")
        
        if raw_response:
            clean_json = raw_response.replace("```json", "").replace("```", "").strip()
            match = re.search(r'\{.*\}', clean_json, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                scenes = data.get("scenes", [])
                
                # Check for the key 'text' (or fallback to 'narration' if it hallucinates the old prompt)
                full_script_list = [s.get("text", s.get("narration", "")) for s in scenes]
                full_script = " ".join(full_script_list).strip()
                
                prompts = [s.get("image_prompt", f"cinematic scene of {topic}") for s in scenes]
                pexels_queries = [s.get("pexels_query", topic) for s in scenes]
                
                if not full_script:
                    raise ValueError("JSON was parsed, but no scene text was found.")
                
                # Math weights for exact video syncing
                total_chars = sum(len(text) for text in full_script_list)
                scene_weights = [len(text) / total_chars for text in full_script_list] if total_chars > 0 else []
                
                print(f"✅ [WRITER] Script secured via {provider}. Synced {len(scenes)} scenes.")
                return full_script, prompts, pexels_queries, scene_weights, provider
                
        return None, [], [], [], "Failed"
    except Exception as e:
        print(f"⚠️ [WRITER] Failed to extract data from AI response: {e}")
        quota_manager.diagnose_fatal_error("generate_script.py", e)
        return None, [], [], [], "Failed"
