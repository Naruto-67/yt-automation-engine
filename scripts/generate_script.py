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
    return {"avoid": [], "emphasize": ["Fast pacing", "Strong visual hooks"]}

def generate_script(niche, topic):
    improvements = load_improvement_data()
    avoid_list = ", ".join(improvements.get("avoid", []))
    emphasize_list = ", ".join(improvements.get("emphasize", []))
    
    prompt = f"""
    You are an Elite YouTube Shorts Director. Create a viral script for niche: '{niche}', Topic: '{topic}'.
    
    CRITICAL RULES:
    - Length: The script MUST be exactly 130 to 150 words to ensure a 45-second video.
    - Structure: Start with a heavy hook, build intense curiosity, and end with a quick call to action.
    - Emphasize: {emphasize_list}
    - Avoid: {avoid_list}
    - Visuals (CRITICAL): Provide EXACTLY 4 highly detailed image prompts. You MUST enforce a 3D animation aesthetic. 
      Every prompt MUST begin with: "3D animated style, Pixar style, Disney style, highly detailed 3D render..." followed by the scene description.
    
    FORMAT: Return ONLY valid JSON.
    {{
        "hook": "...",
        "body": "...",
        "image_prompts": [
            "3D animated style, Pixar style, Disney style, highly detailed 3D render, ...",
            "3D animated style, Pixar style, Disney style, highly detailed 3D render, ...",
            "3D animated style, Pixar style, Disney style, highly detailed 3D render, ...",
            "3D animated style, Pixar style, Disney style, highly detailed 3D render, ..."
        ]
    }}
    """

    try:
        print(f"🤖 [WRITER] Tasking Groq Director for '{topic}'...")
        raw_response = quota_manager.generate_text(prompt, task_type="creative")
        
        if raw_response:
            clean_json = raw_response.replace("```json", "").replace("```", "").strip()
            match = re.search(r'\{.*\}', clean_json, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                full_script = f"{data['hook']} {data['body']}"
                
                prompts = data.get('image_prompts', [])
                while len(prompts) < 4:
                    prompts.append(f"3D animated style, Pixar style, highly detailed 3D render of {topic}")
                prompts = prompts[:4]
                
                print("✅ [WRITER] Script and 4 Camera Shots successfully parsed.")
                return full_script, data['hook'], prompts
        
        return None, None, []
    except Exception as e:
        quota_manager.diagnose_fatal_error("generate_script.py", e)
        return None, None, []
