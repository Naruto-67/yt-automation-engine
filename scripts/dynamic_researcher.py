import os
import json
import traceback
import re

# Corrected Import Path
from scripts.quota_manager import quota_manager
from scripts.discord_notifier import notify_summary

def run_dynamic_research():
    """
    Scrapes viral trends using Gemini Search grounding and 
    locks them into the memory/content_matrix.json.
    """
    print("🔎 [RESEARCHER] Searching the live web for trending topics...")
    niches = ["fact", "brainrot", "short story"]
    
    prompt = f"""
    Elite YouTube Strategist: Identify highly trending, viral topics in the USA right now using Google Search.
    Generate exactly 21 unique content ideas (7 per niche).
    NICHES: {', '.join(niches)}
    
    Return ONLY a raw JSON array.
    Format:
    [
        {{"niche": "fact", "topic": "Historical Fact", "bg_query": "visual search query"}},
        {{"niche": "brainrot", "topic": "Gen Z Meme", "bg_query": "trippy visual"}}
    ]
    """

    try:
        # task_type="research" triggers the Gemini + Google Search route
        raw_text = quota_manager.generate_text(prompt, task_type="research")
        
        if not raw_text:
            raise Exception("Master Router failed to return research data.")

        # Clean up Markdown artifacts
        clean_json_str = raw_text.replace("```json", "").replace("```", "").strip()
        match = re.search(r'\[.*\]', clean_json_str, re.DOTALL)
        
        if match:
            new_matrix = json.loads(match.group(0))
            
            # Save to memory/content_matrix.json
            root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            matrix_path = os.path.join(root_dir, "memory", "content_matrix.json")
            
            os.makedirs(os.path.dirname(matrix_path), exist_ok=True)
            with open(matrix_path, "w", encoding="utf-8") as f:
                json.dump(new_matrix, f, indent=4)
                
            print(f"✅ [RESEARCHER] Matrix updated with {len(new_matrix)} fresh topics.")
            notify_summary(True, f"Research Cycle Complete. {len(new_matrix)} viral topics locked in matrix.")
        else:
            raise ValueError("AI response did not contain a valid JSON array.")

    except Exception as e:
        print(f"❌ [RESEARCHER] Failure: {e}")
        quota_manager.diagnose_fatal_error("dynamic_researcher.py", e)

if __name__ == "__main__":
    run_dynamic_research()
