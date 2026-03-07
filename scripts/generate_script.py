import os
import json
import re
import random
from scripts.quota_manager import quota_manager

def extract_scene_data_dynamically(scene_dict, fallback_topic):
    if not isinstance(scene_dict, dict):
        return str(scene_dict), f"cinematic scene of {fallback_topic}", fallback_topic

    narr, prompt, query = None, None, None
    for k, v in scene_dict.items():
        k_lower = k.lower()
        val_str = str(v).strip()
        if any(x in k_lower for x in ['text', 'narr', 'script', 'voice', 'dialog']): narr = val_str
        elif any(x in k_lower for x in ['prompt', 'visual', 'image', 'pic', 'desc']): prompt = val_str
        elif any(x in k_lower for x in ['pexel', 'query', 'keyword', 'search']): query = val_str

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
                if any(t in val.lower() for t in ['shot', 'cinematic', 'photorealistic', 'style', 'render', '3d']):
                    prompt = val
                    unassigned.remove(val)
                    break
        if not narr and unassigned:
            narr = max(unassigned, key=len)

    if not narr: narr = fallback_topic
    if not prompt: prompt = f"High quality shot of {fallback_topic}"
    if not query: 
        clean_str = re.sub(r'(?i)(photorealistic|cinematic|shot|of|a|the|in|with|3d|render)', '', prompt)
        words = [w for w in clean_str.split() if len(w) > 3]
        query = " ".join(words[:2]) if words else fallback_topic
    return narr, prompt, query

def generate_script(niche, topic):
    is_fact_based = any(k in niche.lower() for k in ['fact', 'hack', 'trend', 'brainrot'])
    target_scenes = random.randint(3, 5) if is_fact_based else random.randint(5, 7)
    
    # 🚨 FIX: Context-Aware Dynamic Prompting. No more hard-coded word limits.
    prompt = f"""
    You are an Elite Master Content Creator. Your task is to write a highly viral, engaging YouTube Short.
    NICHE: '{niche}'
    TOPIC: '{topic}'
    
    YOUTUBE SHORTS CONSTRAINTS:
    1. The absolute maximum length is 60 seconds. Write a script that naturally takes about 35 to 50 seconds to read aloud.
    2. Hook the viewer in the very first sentence. No long intros.
    3. NO META-COMMENTARY: NEVER say "In this video", "Welcome back", or "Subscribe". Just dive straight into the content.
    
    DYNAMIC ADAPTATION:
    - If the niche is Facts/Hacks/Brainrot: Make the script extremely fast-paced, punchy, and loopable.
    - If the niche is Story/Lore/Mystery: Build suspense, use atmospheric descriptions, and end on a thought-provoking note.
    
    SCENE STRUCTURE:
    Break the script into EXACTLY {target_scenes} visual scenes.
       - 'text': The actual words spoken by the narrator.
       - 'image_prompt': The specific visual style you deduced for the AI image generator.
       - 'pexels_query': A 1-2 word search term like 'abandoned house'.
    
    FORMAT: Return ONLY valid JSON.
    {{
        "thought_process": "Briefly explain how you structured this to maximize YouTube Shorts audience retention.",
        "estimated_spoken_duration": "e.g., 40 seconds",
        "scenes": [
            {{
                "text": "sentence 1... sentence 2...",
                "image_prompt": "Specific visual style shot of...",
                "pexels_query": "simple keyword"
            }}
        ]
    }}
    """

    try:
        raw_response, provider = quota_manager.generate_text(prompt, task_type="creative")
        if raw_response:
            clean_str = raw_response.replace("```json", "").replace("```", "").strip()
            start_idx = clean_str.find('{')
            end_idx = clean_str.rfind('}')
            
            if start_idx != -1 and end_idx != -1:
                json_str = clean_str[start_idx:end_idx+1]
                data = json.loads(json_str)
                scenes = data.get("scenes", [])
                parsed_scenes = [extract_scene_data_dynamically(s, topic) for s in scenes]
                
                full_script = " ".join([s[0] for s in parsed_scenes])
                prompts = [s[1] for s in parsed_scenes]
                pexels_queries = [s[2] for s in parsed_scenes]
                
                if not full_script.strip() or full_script == topic:
                    print("      ⚠️ [TEXT REJECTED] Failed to parse valid text.")
                    return None, [], [], [], provider
                
                word_count = len(full_script.split())
                print(f"      -> [TEXT PRE-CHECK] Script generated: {word_count} words.")
                
                # Broad, generous safety net. Only rejects extreme hallucinations.
                if word_count > 160:
                    print(f"      ⚠️ [TEXT REJECTED] Script is massively overgrown ({word_count} words). It will exceed 60s. Regenerating...")
                    return None, [], [], [], provider
                if word_count < 15:
                    print(f"      ⚠️ [TEXT REJECTED] Script is absurdly short ({word_count} words). Regenerating...")
                    return None, [], [], [], provider

                total_chars = sum(len(s[0]) for s in parsed_scenes)
                scene_weights = [len(s[0]) / total_chars for s in parsed_scenes] if total_chars > 0 else []
                
                return full_script, prompts, pexels_queries, scene_weights, provider
        return None, [], [], [], "Failed"
    except Exception as e:
        print(f"      ⚠️ [SCRIPT GEN ERROR] {e}")
        return None, [], [], [], "Failed"
