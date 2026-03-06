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
       - Write a 'pexels_query'. This must be a simple 1-2 word search term (e.g. 'golden retriever', 'dark forest') representing the core subject of the scene for a stock footage search.
    
    FORMAT: Return ONLY valid JSON. You MUST use EXACTLY these keys for each scene. Do not rename them.
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

    # 🚨 THE FIX: A 3-Attempt Self-Correction Loop with Heavy Logging
    max_retries = 3
    for attempt in range(max_retries):
        try:
            print(f"🤖 [WRITER] Tasking AI Director for '{topic}' (Attempt {attempt+1}/{max_retries})...")
            raw_response, provider = quota_manager.generate_text(prompt, task_type="creative")
            
            # 🚨 LOGGING: Print exactly what the AI returned to the console so we can debug it
            print("\n📜 --- RAW AI RESPONSE LOG --- 📜")
            print(raw_response)
            print("---------------------------------\n")
            
            if not raw_response:
                raise ValueError("AI returned an empty response.")

            clean_json = raw_response.replace("```json", "").replace("```", "").strip()
            match = re.search(r'\{.*\}', clean_json, re.DOTALL)
            
            if not match:
                raise ValueError("No JSON object could be found in the AI response.")
                
            data = json.loads(match.group(0))
            scenes = data.get("scenes", [])
            
            if not scenes:
                raise ValueError("The 'scenes' array is missing or empty.")
            
            full_script_list = []
            prompts = []
            pexels_queries = []
            
            # STRICT VALIDATION: Check every scene to ensure the AI followed instructions
            for i, s in enumerate(scenes):
                if "narration" not in s or "image_prompt" not in s or "pexels_query" not in s:
                    raise KeyError(f"Scene {i+1} is missing required keys. Keys found by parser: {list(s.keys())}")
                
                full_script_list.append(s["narration"])
                prompts.append(s["image_prompt"])
                pexels_queries.append(s["pexels_query"])
            
            full_script_str = " ".join(full_script_list)
            
            if not full_script_str.strip():
                raise ValueError("The extracted narration was completely blank.")
            
            # Math weights for exact video syncing
            total_chars = sum(len(n) for n in full_script_list)
            scene_weights = [len(n) / total_chars for n in full_script_list] if total_chars > 0 else []
            
            print(f"✅ [WRITER] Script successfully parsed and locked via {provider}!")
            return full_script_str, prompts, pexels_queries, scene_weights, provider
            
        except Exception as e:
            print(f"⚠️ [WRITER] Output Validation Failed: {e}")
            if attempt < max_retries - 1:
                print("🔄 [WRITER] Feeding error back to AI for self-correction...")
                # 🚨 SELF-HEALING: Append the error to the prompt and tell the AI to fix it
                prompt += f"\n\n🚨 CRITICAL ERROR PREVENTING PARSING:\nYour previous response failed with this error: {e}\nYou MUST fix this formatting issue. Return strictly valid JSON using ONLY the keys: 'narration', 'image_prompt', 'pexels_query'."
            else:
                print("❌ [WRITER] Max retries reached. AI failed to correct its formatting.")
                quota_manager.diagnose_fatal_error("generate_script.py", e)
                return None, [], [], [], "Failed"

    return None, [], [], [], "Failed"
