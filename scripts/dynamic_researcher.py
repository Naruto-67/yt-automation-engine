import os
import json
import traceback
import re

# Corrected Import for Ghost Engine V4.0
from scripts.quota_manager import quota_manager
from scripts.discord_notifier import notify_summary

def run_dynamic_research():
    """
    The Brain of the Engine.
    Uses Gemini's live Google Search grounding to find 21 viral topics 
    and saves them to the content matrix for the daily production to consume.
    """
    print("🔎 [RESEARCHER] Scouring the live web for trending viral topics...")
    # These niches align with your historical high-performance metrics
    niches = ["fact", "brainrot", "short story"]
    
    prompt = f"""
    You are an elite YouTube Strategist. Identify highly trending, viral topics in the USA right now using Google Search.
    Generate exactly 21 unique content ideas (7 per niche).
    NICHES: {', '.join(niches)}
    
    Return ONLY a raw JSON array of objects.
    FORMAT:
    [
        {{"niche": "fact", "topic": "The 1904 Olympic Marathon", "bg_query": "vintage chaotic marathon runners marathon"}},
        {{"niche": "brainrot", "topic": "Gen Alpha Slang explained", "bg_query": "trippy abstract neon colorful dynamic"}}
    ]
    """

    try:
        # task_type="research" forces the router to use Gemini with Google Search enabled
        raw_text = quota_manager.generate_text(prompt, task_type="research")
        
        if not raw_text:
            raise Exception("Master Router failed to return research data.")

        # Robust extraction: Strip Markdown code blocks if the AI includes them
        clean_json_str = raw_text.replace("```json", "").replace("```", "").strip()
        match = re.search(r'\[.*\]', clean_json_str, re.DOTALL)
        
        if match:
            new_matrix = json.loads(match.group(0))
            
            # Ensure memory folder exists
            root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            matrix_path = os.path.join(root_dir, "memory", "content_matrix.json")
            os.makedirs(os.path.dirname(matrix_path), exist_ok=True)
            
            with open(matrix_path, "w", encoding="utf-8") as f:
                json.dump(new_matrix, f, indent=4)
                
            print(f"✅ [RESEARCHER] Research Complete! Matrix updated with {len(new_matrix)} fresh topics.")
            notify_summary(True, f"Scout Protocol Complete: {len(new_matrix)} trending topics locked in memory.")
        else:
            raise ValueError("AI failed to provide a parsable JSON array.")

    except Exception as e:
        print(f"❌ [RESEARCHER] Critical failure in Scouting phase: {e}")
        quota_manager.diagnose_fatal_error("dynamic_researcher.py", e)

if __name__ == "__main__":
    run_dynamic_research()
