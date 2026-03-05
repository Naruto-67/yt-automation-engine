import os
import json
import re
from scripts.retry import quota_manager

def load_improvement_data():
    """Reads historical performance data to inject into the prompt."""
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    tracker_path = os.path.join(root_dir, "assets", "lessons_learned.json")
    
    if os.path.exists(tracker_path):
        try:
            with open(tracker_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ Warning: Could not read lessons_learned.json: {e}")
            
    return {"avoid": [], "emphasize": ["Fast pacing", "Strong visual hooks"]}

def generate_script(niche, topic):
    """
    Generates a viral script using the Master Router (Groq Primary, Gemini Fallback).
    Enforces the 3-Second Hook Lock and outputs clean JSON.
    """
    improvements = load_improvement_data()
    avoid_list = ", ".join(improvements.get("avoid", []))
    emphasize_list = ", ".join(improvements.get("emphasize", []))
    
    prompt = f"""
    You are an elite YouTube Shorts scriptwriter targeting a USA demographic.
    Write a highly engaging, fast-paced script for the niche: '{niche}'.
    Topic: '{topic}'
    
    CRITICAL RULES:
    - Emphasize: {emphasize_list}
    - Strictly Avoid: {avoid_list}
    - Keep it under 130 words total.
    - Return EXACTLY a JSON object with two keys: "hook" and "body".
    - "hook": The first 3 seconds. MUST be a powerful pattern-interrupt question or bold statement to prevent scrolling.
    - "body": The rest of the script.
    - Do NOT include stage directions, visual notes, or markdown formatting outside the JSON.
    """

    try:
        print(f"🤖 [AI WRITER] Generating script for '{topic}'...")
        
        # The Smart Router takes over! (Groq Llama 3.3 -> Gemini Fallback)
        raw_response = quota_manager.generate_text(prompt, task_type="creative")
        
        if raw_response:
            # Clean up the response in case the AI wrapped it in markdown
            clean_json_str = raw_response.replace("```json", "").replace("```", "").strip()
            
            # Extract just the JSON block
            match = re.search(r'\{.*\}', clean_json_str, re.DOTALL)
            if match:
                script_data = json.loads(match.group(0))
                
                # Combine them for the TTS engine, but we return both so main.py can log the exact hook
                full_script = f"{script_data['hook']} {script_data['body']}"
                print("✅ [AI WRITER] Script generated and JSON parsed successfully.")
                return full_script, script_data['hook']
            else:
                print("⚠️ [AI WRITER] Failed to parse JSON. Falling back to raw text.")
                return clean_json_str, clean_json_str[:50]
                
        return None, None

    except Exception as e:
        # Trigger the AI Doctor if something goes catastrophically wrong
        quota_manager.diagnose_fatal_error("generate_script.py", e)
        return None, None

if __name__ == "__main__":
    # Local testing
    test_script, test_hook = generate_script("fact", "The Great Emu War")
    print(f"HOOK: {test_hook}\n\nFULL: {test_script}")
