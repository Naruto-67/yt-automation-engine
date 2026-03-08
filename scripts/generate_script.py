# scripts/generate_script.py
import os
import json
import yaml
import re
import random
from scripts.quota_manager import quota_manager

# Biologically-calibrated speech rate constants
_WORDS_PER_SECOND_TTS = 130 / 60.0
_ABSOLUTE_WORD_CEILING = int(59.0 * _WORDS_PER_SECOND_TTS)

def load_config_prompts():
    """Loads central prompt registry."""
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    path = os.path.join(root_dir, "config", "prompts.yaml")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def load_lessons():
    """Load AI-learned rules from performance_analyst."""
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    path = os.path.join(root_dir, "assets", "lessons_learned.json")
    if not os.path.exists(path):
        return {"emphasize": [], "avoid": [], "preferred_visuals": ["Cinematic"]}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def extract_scene_data(scene_dict, fallback_topic):
    """Safely extracts text and prompts from AI response."""
    if not isinstance(scene_dict, dict):
        return str(scene_dict), f"Cinematic shot of {fallback_topic}", fallback_topic
    
    narr = scene_dict.get("text") or scene_dict.get("narration") or fallback_topic
    prompt = scene_dict.get("image_prompt") or scene_dict.get("visual") or f"Cinematic {fallback_topic}"
    query = scene_dict.get("pexels_query") or fallback_topic
    
    return narr, prompt, query

def generate_script(niche, topic):
    """Full implementation of Phase 2 Script Generation."""
    print(f"🎬 [SCRIPT] Orchestrating narrative for: {topic}")
    
    # 1. Load Data
    prompts_cfg = load_config_prompts()
    lessons = load_lessons()
    
    # 2. Prepare Template Variables
    emp = "\n".join([f"- {r}" for r in lessons.get("emphasize", [])[-3:]])
    avo = "\n".join([f"- {r}" for r in lessons.get("avoid", [])[-3:]])
    vis = ", ".join(lessons.get("preferred_visuals", ["Cinematic"])[:3])
    
    # 3. Build Prompt from Central Config
    user_prompt = prompts_cfg['script_gen']['user_template'].format(
        niche=niche,
        topic=topic,
        emphasize_rules=emp,
        avoid_rules=avo,
        visual_preference=vis,
        word_ceiling=_ABSOLUTE_WORD_CEILING
    )
    
    system_msg = prompts_cfg['script_gen']['system_prompt']

    try:
        # 4. Generate via Quota Manager (Gemini/Groq Fallback)
        raw_response, provider = quota_manager.generate_text(
            user_prompt, 
            task_type="creative", 
            system_prompt=system_msg
        )

        if not raw_response:
            return None, [], [], [], "Failed"

        # 5. Clean and Parse JSON
        clean_str = raw_response.replace("```json", "").replace("```", "").strip()
        match = re.search(r'\{.*\}', clean_str, re.DOTALL)
        if not match:
            return None, [], [], [], provider
            
        data = json.loads(match.group(0))
        scenes = data.get("scenes", [])
        
        # 6. Process Scenes
        parsed_scenes = [extract_scene_data(s, topic) for s in scenes]
        full_text = " ".join([s[0] for s in parsed_scenes])
        img_prompts = [s[1] for s in parsed_scenes]
        pexels_queries = [s[2] for s in parsed_scenes]
        
        # 7. Word Count Validation
        word_count = len(full_text.split())
        if word_count > _ABSOLUTE_WORD_CEILING or word_count < 10:
            print(f"⚠️ [SCRIPT] Script length ({word_count} words) failed validation. Retrying...")
            return None, [], [], [], provider

        # 8. Calculate Timing Weights for Render
        total_chars = sum(len(s[0]) for s in parsed_scenes)
        scene_weights = [len(s[0])/total_chars for s in parsed_scenes] if total_chars > 0 else []

        print(f"✅ [SCRIPT] Generated {len(parsed_scenes)} scenes via {provider}")
        return full_text, img_prompts, pexels_queries, scene_weights, provider

    except Exception as e:
        print(f"❌ [SCRIPT ERROR] {e}")
        return None, [], [], [], "Error"
