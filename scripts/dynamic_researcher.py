import os
import json
import traceback
import re
from google import genai
# WE IMPORT OUR NEW MANAGER HERE
from scripts.retry import quota_manager
from scripts.discord_notifier import send_embed, get_ist_time, notify_error

def get_gemini_client():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    return genai.Client(api_key=api_key)

def notify_research_complete(topics_count):
    embed = {
        "title": "🕵️ AI Trend Research Complete",
        "color": 15105570,
        "fields": [
            {"name": "📈 Status", "value": f"└ Scraped web and generated {topics_count} viral topics.", "inline": False},
            {"name": "📂 Storage", "value": "└ Updated memory/content_matrix.json", "inline": False}
        ],
        "footer": {"text": f"Engine Local Time: {get_ist_time()}"}
    }
    send_embed(embed)

def run_dynamic_research():
    client = get_gemini_client()
    if not client:
        return

    print("🔎 Searching the web for trending viral topics...")
    niches = ["fact", "brainrot", "short story"]
    
    prompt = f"""
    Identify trending topics in the USA right now using Google Search.
    Generate exactly 21 unique content ideas (7 per niche).
    NICHES: {', '.join(niches)}
    Return ONLY a raw JSON array of objects.
    """

    try:
        # NOTICE: We wrapped the call inside quota_manager.safe_execute
        # This prevents the 429 crash!
        response = quota_manager.safe_execute(
            client.models.generate_content,
            model='gemini-2.0-flash', 
            contents=prompt,
            config={'tools': [{'google_search': {}}]}
        )
        
        if not response:
            print("❌ Failed to get a response from Gemini after retries.")
            return

        raw_text = response.text.strip()
        match = re.search(r'\[.*\]', raw_text, re.DOTALL)
        clean_json_str = match.group(0) if match else raw_text
        new_matrix = json.loads(clean_json_str)
        
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        memory_dir = os.path.join(root_dir, "memory")
        os.makedirs(memory_dir, exist_ok=True)
        matrix_path = os.path.join(memory_dir, "content_matrix.json")
        
        with open(matrix_path, "w", encoding="utf-8") as f:
            json.dump(new_matrix, f, indent=4)
            
        print(f"✅ Research Complete! Generated {len(new_matrix)} topics.")
        notify_research_complete(len(new_matrix))

    except Exception as e:
        print("❌ Research Failed:")
        traceback.print_exc()
        notify_error("Dynamic Researcher", "Generation Error", str(e)[:200])

if __name__ == "__main__":
    run_dynamic_research()
