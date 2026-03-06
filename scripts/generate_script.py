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

def extract_scene_data_dynamically(scene_dict, fallback_topic):
    if not isinstance(scene_dict, dict):
        return str(scene_dict), f"cinematic scene of {fallback_topic}", fallback_topic

    narr, prompt, query = None, None, None
    
    for k, v in scene_dict.items():
        k_lower = k.lower()
        val_str = str(v).strip()
        if any(x in k_lower for x in ['text', 'narr', 'script', 'voice', 'dialog']):
            narr = val_str
        elif any(x in k_lower for x in ['prompt', 'visual', 'image', 'pic', 'desc']):
            prompt = val_str
        elif any(x in k_lower for x in ['pexel', 'query', 'keyword', 'search']):
            query = val_str

    if None in (narr, prompt, query):
        unassigned = [str(v).strip() for v in scene_dict.values() if isinstance(v, str)]
        if not query:
            for val in unassigned:
                if len(val.split()) <= 4:
                    query = val
                    unassigned.remove(val)
                    break
        if not prompt:
            for val in unassigned:
                if any(t in val.lower() for t in ['shot', 'cinematic', 'photorealistic', 'style', 'render']):
                    prompt = val
                    unassigned.remove(val)
                    break
        if not narr and unassigned:
            narr = max(unassigned, key=len)

    if not narr: narr = fallback_topic
    if not prompt: prompt = f"Cinematic shot of {fallback_topic}"
    if not query: 
        clean_str = re.sub(r'(?i)(photorealistic|cinematic|shot|of|a|the|in|with)', '', prompt)
        words = [w for w in clean_str.split() if len(w) > 3]
        query = " ".join(words[:2]) if words else fallback_topic

    return narr, prompt, query

def generate_script(niche, topic):
    improvements = load_improvement_data()
    target_scenes = random.randint(4, 7)
    
    prompt = f"""
    You are an Elite Master Content Creator. Write a highly viral YouTube Short.
    NICHE: '{niche}'
    TOPIC: '{topic}'
    
    CRITICAL RULES:
    1. DYNAMIC ADAPTATION: You MUST adapt your writing and visual style to perfectly match the NICHE.
       - If Fiction/Storytelling: Write a magical, emotional narrative with a protagonist. Use vibrant, Pixar-style 3D animation image prompts.
       - If Factual/Documentary: Write a gripping, gritty script. Use dark, cinematic, photorealistic image prompts.
       - For ANY OTHER niche: Deduce the most viral narrative tone and visual style.
    2. NO META-COMMENTARY: NEVER say "In this video".
    3. STRICT LENGTH: The total script MUST be exactly 85 to 95 words.
    4. DYNAMIC SCENES: Break the script into EXACTLY {target_scenes} scenes.
       - Write the 'text' (the words spoken).
       - Write an 'image_prompt' (the specific visual style).
       - Write a 'pexels_query' (a 1-2 word search term like 'abandoned house').
    
    VALIDATION STEP: Verify your JSON contains exactly the keys "text", "image_prompt", and "pexels_query". Do not rename them.
    
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
        print(f"🤖 [WRITER] Tasking AI Director for '{topic}'...")
        raw_response, provider = quota_manager.generate_text(prompt, task_type="creative")
        
        print("\n📜 --- RAW AI RESPONSE LOG --- 📜")
        print(raw_response if raw_response else "NONE")
        print("---------------------------------\n")
        
        if raw_response:
            clean_json = raw_response.replace("```json", "").replace("```", "").strip()
            match = re.search(r'\{.*\}', clean_json, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                scenes = data.get("scenes", [])
                
                parsed_scenes = [extract_scene_data_dynamically(s, topic) for s in scenes]
                
                full_script = " ".join([s[0] for s in parsed_scenes])
                prompts = [s[1] for s in parsed_scenes]
                pexels_queries = [s[2] for s in parsed_scenes]
                
                if not full_script.strip() or full_script == topic:
                    raise ValueError("JSON parsed, but no valid text extracted.")
                
                total_chars = sum(len(s[0]) for s in parsed_scenes)
                scene_weights = [len(s[0]) / total_chars for s in parsed_scenes] if total_chars > 0 else []
                
                print(f"✅ [WRITER] Script secured via {provider}. Synced {len(scenes)} scenes.")
                return full_script, prompts, pexels_queries, scene_weights, provider
                
        return None, [], [], [], "Failed"
    except Exception as e:
        quota_manager.diagnose_fatal_error("generate_script.py", e)
        return None, [], [], [], "Failed"
