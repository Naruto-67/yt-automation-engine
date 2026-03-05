import os
import json
import traceback
import re

# Import the new Central Nervous System
from scripts.retry import quota_manager
from scripts.discord_notifier import send_embed, get_ist_time, notify_error

def notify_research_complete(topics_count):
    """Sends a success ping to Discord when the new matrix is locked."""
    embed = {
        "title": "🕵️ AI Trend Research Complete",
        "color": 15105570,
        "fields": [
            {"name": "📈 Status", "value": f"└ Scraped live web. Generated {topics_count} viral topics.", "inline": False},
            {"name": "📂 Storage", "value": "└ Updated memory/content_matrix.json", "inline": False}
        ],
        "footer": {"text": f"Engine Local Time: {get_ist_time()}"}
    }
    send_embed(embed)

def run_dynamic_research():
    """
    The Brain of the Engine.
    Uses Gemini's live Google Search grounding to find 21 viral topics 
    and saves them to the content matrix for the daily publisher to consume.
    """
    print("🔎 [RESEARCHER] Searching the live web for trending viral topics...")
    niches = ["fact", "brainrot", "short story"]
    
    prompt = f"""
    You are an elite YouTube Shorts strategist.
    Identify highly trending, viral topics in the USA right now using Google Search.
    Generate exactly 21 unique content ideas (7 per niche).
    NICHES: {', '.join(niches)}
    
    Return ONLY a raw JSON array of objects. Do not include markdown formatting.
    Format exactly like this:
    [
        {{"niche": "fact", "topic": "The 1904 Olympic Marathon", "bg_query": "old marathon runner dark", "style": "default"}},
        {{"niche": "brainrot", "topic": "Gen Z slang explained", "bg_query": "trippy abstract colorful", "style": "default"}}
    ]
    """

    try:
        # task_type="research" forces the router to use Gemini with Google Search enabled
        raw_text = quota_manager.generate_text(prompt, task_type="research")
        
        if not raw_text:
            raise Exception("Master Router failed to return research data.")

        # Bulletproof JSON extraction
        clean_json_str = raw_text.replace("```json", "").replace("```", "").strip()
        match = re.search(r'\[.*\]', clean_json_str, re.DOTALL)
        
        if match:
            clean_json_str = match.group(0)
            
        new_matrix = json.loads(clean_json_str)
        
        if not isinstance(new_matrix, list) or len(new_matrix) == 0:
            raise ValueError("AI returned an invalid or empty JSON array.")
            
        # Save to memory vault
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        memory_dir = os.path.join(root_dir, "memory")
        os.makedirs(memory_dir, exist_ok=True)
        matrix_path = os.path.join(memory_dir, "content_matrix.json")
        
        with open(matrix_path, "w", encoding="utf-8") as f:
            json.dump(new_matrix, f, indent=4)
            
        print(f"✅ [RESEARCHER] Research Complete! Matrix updated with {len(new_matrix)} fresh topics.")
        notify_research_complete(len(new_matrix))

    except Exception as e:
        print("❌ [RESEARCHER] Critical Research Failure:")
        quota_manager.diagnose_fatal_error("dynamic_researcher.py", e)
        notify_error("Dynamic Researcher", "Generation Error", str(e)[:200])

if __name__ == "__main__":
    # Local execution test
    run_dynamic_research()
