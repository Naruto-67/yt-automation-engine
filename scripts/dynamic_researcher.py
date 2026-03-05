import os
import json
import traceback
import re

from scripts.quota_manager import quota_manager
from scripts.discord_notifier import notify_summary, notify_warning

def run_dynamic_research():
    """
    Elite Scout Module: Scours the web for viral trends.
    Uses Gemini with Search Grounding as primary, Groq as fallback.
    """
    print("🔎 [RESEARCHER] Scouring the live web for trending viral topics...")
    niches = ["fact", "brainrot", "short story"]
    
    prompt = f"""
    You are an Elite YouTube Strategist. Identify 21 highly trending YouTube topics for a USA audience.
    NICHES: {', '.join(niches)}
    Return ONLY a raw JSON array of objects. No intro text.
    Format:
    [
        {{"niche": "fact", "topic": "Historical Mystery", "bg_query": "cinematic dark history"}},
        ...
    ]
    """

    try:
        # Step 1: Attempt Primary Brain (Gemini + Google Search)
        used_fallback = False
        raw_text = quota_manager.generate_text(prompt, task_type="research")
        
        # Step 2: Engage Fallback Brain if Gemini is exhausted
        if not raw_text:
            print("⚠️ [RESEARCHER] Gemini Quota Hit. Engaging Fallback Brain (Groq)...")
            used_fallback = True
            raw_text = quota_manager.generate_text(prompt, task_type="creative")
            if not raw_text:
                raise Exception("Critical: All AI providers failed to respond.")

        # Robust JSON extraction
        clean_json_str = raw_text.replace("```json", "").replace("```", "").strip()
        match = re.search(r'\[.*\]', clean_json_str, re.DOTALL)
        
        if match:
            new_matrix = json.loads(match.group(0))
            
            # Resolve absolute paths
            root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            matrix_dir = os.path.join(root_dir, "memory")
            matrix_path = os.path.join(matrix_dir, "content_matrix.json")
            
            os.makedirs(matrix_dir, exist_ok=True)
            with open(matrix_path, "w", encoding="utf-8") as f:
                json.dump(new_matrix, f, indent=4)
                
            print(f"✅ [RESEARCHER] Matrix updated with {len(new_matrix)} topics.")
            
            # Final Success Notification
            brain_name = "Groq (Fallback)" if used_fallback else "Gemini (Search)"
            notify_summary(True, f"Scout Cycle Successful. Matrix generated via {brain_name}.")
        else:
            raise ValueError("AI returned non-JSON parsable content.")

    except Exception as e:
        print(f"❌ [RESEARCHER] Scouting Failure: {e}")
        notify_warning("Researcher", f"Research cycle failed: {str(e)[:100]}")
        # Ensure directory exists for Git safety
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        os.makedirs(os.path.join(root_dir, "memory"), exist_ok=True)

if __name__ == "__main__":
    run_dynamic_research()
