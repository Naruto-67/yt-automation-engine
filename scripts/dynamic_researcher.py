import os
import json
import traceback
import re

from scripts.quota_manager import quota_manager
from scripts.discord_notifier import notify_summary, notify_warning

def run_dynamic_research():
    """
    Elite Scout Module: Finds viral topics.
    Now includes a Fallback Mode if Gemini Quota is exhausted.
    """
    print("🔎 [RESEARCHER] Scouring the live web for trending viral topics...")
    niches = ["fact", "brainrot", "short story"]
    
    prompt = f"""
    Identify 21 highly trending YouTube topics for USA audience.
    NICHES: {', '.join(niches)}
    Return ONLY a raw JSON array of objects:
    [
        {{"niche": "fact", "topic": "Topic Name", "bg_query": "search term"}},
        ...
    ]
    """

    try:
        # Step 1: Try Gemini with Search Grounding (High Quality)
        raw_text = quota_manager.generate_text(prompt, task_type="research")
        
        # Step 2: Fallback to Groq if Gemini fails/quota hit
        if not raw_text:
            print("⚠️ [RESEARCHER] Gemini Quota Hit. Engaging Fallback Brain (Groq)...")
            raw_text = quota_manager.generate_text(prompt, task_type="creative")
            if not raw_text:
                raise Exception("Both Primary and Fallback AI brains are unresponsive.")

        # Robust JSON Extraction
        clean_json_str = raw_text.replace("```json", "").replace("```", "").strip()
        match = re.search(r'\[.*\]', clean_json_str, re.DOTALL)
        
        if match:
            new_matrix = json.loads(match.group(0))
            
            root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            matrix_dir = os.path.join(root_dir, "memory")
            matrix_path = os.path.join(matrix_dir, "content_matrix.json")
            
            os.makedirs(matrix_dir, exist_ok=True)
            with open(matrix_path, "w", encoding="utf-8") as f:
                json.dump(new_matrix, f, indent=4)
                
            print(f"✅ [RESEARCHER] Matrix updated with {len(new_matrix)} topics.")
            notify_summary(True, f"Scout Protocol Successful. Matrix updated via {'Gemini' if 'Search' in raw_text else 'Groq Fallback'}.")
        else:
            raise ValueError("AI returned non-JSON content.")

    except Exception as e:
        print(f"❌ [RESEARCHER] Failure: {e}")
        notify_warning("Researcher", "Research cycle failed. Check Quota or Logs.")
        # Ensure at least an empty list exists to satisfy Git
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        matrix_path = os.path.join(root_dir, "memory", "content_matrix.json")
        if not os.path.exists(matrix_path):
            os.makedirs(os.path.dirname(matrix_path), exist_ok=True)
            with open(matrix_path, "w") as f: json.dump([], f)

if __name__ == "__main__":
    run_dynamic_research()
