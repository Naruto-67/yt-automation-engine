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
    
    # 🚨 INFINITE SCALABILITY FIX: The AI dynamically assigns its own persona and visual style based on the niche.
    prompt = f"""
    You are an Elite Master Content Creator. Your task is to write a highly viral YouTube Short.
    NICHE: '{niche}'
    TOPIC: '{topic}'
    
    CRITICAL RULES:
    1. DYNAMIC ADAPTATION: You MUST adapt your writing and visual style to perfectly match the NICHE.
       - If it is Fiction/Storytelling: Write a magical, emotional narrative with a protagonist. Use vibrant, Pixar-style 3D animation image prompts.
       - If it is Factual/Documentary: Write a gripping, gritty script. Use dark, cinematic, photorealistic image prompts.
       - If it is Brainrot/Internet Culture: Write highly engaging, fast-paced, Gen-Z commentary. Use chaotic, hyper-detailed, saturated image prompts.
       - For ANY OTHER niche: Deduce the most viral narrative tone and the best visual style for that specific audience.
    2. NO META-COMMENTARY: NEVER say "In this video" or "Welcome back".
    3. STRICT LENGTH LIMIT: The total script MUST be exactly 85 to 95 words. This is critical for the 60-second limit.
    4. DYNAMIC SCENES: To sync the video perfectly, break the script into EXACTLY {target_scenes} scenes.
       - For EACH scene, write the 'text' (the actual words spoken).
       - Write an 'image_prompt' that utilizes the visual style you deduced for this niche.
       - Write a 'pexels_query' (a simple 1-2 word search term like 'abandoned house', 'galaxy', or 'running dog' for a stock video fallback).
    
    VALIDATION STEP: Before you output, verify that your JSON contains exactly the keys "text", "image_prompt", and "pexels_query" for every single scene. Do not rename them.
    
    FORMAT: Return ONLY valid JSON.
    {{
        "scenes": [
            {{
                "text": "sentence 1...",
                "image_prompt": "Specific visual style shot of...",
                "pexels_query": "simple keyword"
            }}
        ]
    }}
    """

    try:
        print(f"🤖 [WRITER] Tasking AI Director for '{topic}' (Targeting {target_scenes} scenes)...")
        raw_response, provider = quota_manager.generate_text(prompt, task_type="creative")
        
        # 🚨 RAW LOGGING: Prints the exact response to your GitHub Actions console for debugging
        print("\n📜 --- RAW AI RESPONSE LOG --- 📜")
        print(raw_response if raw_response else "NONE")
        print("---------------------------------\n")
        
        if raw_response:
            clean_json = raw_response.replace("```json", "").replace("```", "").strip()
            match = re.search(r'\{.*\}', clean_json, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                scenes = data.get("scenes", [])
                
                # Resilient One-Shot Extraction: Looks for 'text', falls back to 'narration' just in case.
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
