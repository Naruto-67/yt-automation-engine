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
    # 🚨 FIX: Niche-Aware Logic flags
    is_fact_based = any(k in niche.lower() for k in ['fact', 'hack', 'trend', 'brainrot'])
    target_scenes = random.randint(3, 5) if is_fact_based else random.randint(5, 7)
    
    pacing_rules = """
    PACING: Keep it extremely fast, punchy, and concise. High energy loop.
    WORD COUNT: You MUST write exactly 40 to 65 words in total across all scenes.
    """ if is_fact_based else """
    PACING: Build a deep, engaging, and detailed narrative. Expand on the lore.
    WORD COUNT: You MUST write exactly 90 to 115 words in total across all scenes. Make it highly descriptive.
    """
    
    prompt = f"""
    You are an Elite Master Content Creator. Write a highly viral YouTube Short.
    NICHE: '{niche}'
    TOPIC: '{topic}'
    
    CRITICAL RULES:
    1. DYNAMIC ADAPTATION: Analyze the NICHE. Dynamically deduce the best narrative structure and visual style.
    2. NO META-COMMENTARY: NEVER say "In this video".
    3. {pacing_rules}
    4. DYNAMIC SCENES: Break the script into EXACTLY {target_scenes} scenes.
       - Write the 'text' (the words spoken).
       - Write an 'image_prompt' (the specific visual style you deduced).
       - Write a 'pexels_query' (a 1-2 word search term like 'abandoned house').
    
    VALIDATION: Verify your JSON contains exactly the keys "text", "image_prompt", and "pexels_query". Do not rename them.
    
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
                    raise ValueError("JSON parsed, but no valid text extracted.")
                
                # 🚨 FIX: Instant Text Pre-Validation. Kills bad Llama scripts instantly before wasting Audio API.
                word_count = len(full_script.split())
                if is_fact_based and word_count > 85:
                    raise ValueError(f"Script too long for a fast-paced Fact/Trend ({word_count} words). Regenerating.")
                if not is_fact_based and word_count < 65:
                    raise ValueError(f"Script too short for a Story narrative ({word_count} words). Regenerating.")

                total_chars = sum(len(s[0]) for s in parsed_scenes)
                scene_weights = [len(s[0]) / total_chars for s in parsed_scenes] if total_chars > 0 else []
                
                return full_script, prompts, pexels_queries, scene_weights, provider
        return None, [], [], [], "Failed"
    except Exception as e:
        # Will bounce ValueError back to main.py for a 0-second instant retry
        raise e
