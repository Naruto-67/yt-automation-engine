import os
import json
import traceback
from google import genai
from scripts.discord_notifier import send_embed, get_ist_time, notify_error

def get_gemini_client():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("⚠️ GEMINI_API_KEY missing.")
        return None
    # Initialize the newer GenAI client
    return genai.Client(api_key=api_key)

def notify_research_complete(topics_count):
    """Pings Discord to confirm the content matrix has been refreshed."""
    embed = {
        "title": "🕵️ AI Trend Research Complete",
        "color": 15105570, # Orange/Gold
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

    print("🔎 Searching the web for trending viral topics using Google Search Grounding...")

    niches = ["fact", "brainrot", "short story"]
    
    prompt = f"""
    You are a viral content researcher for a top-tier YouTube Shorts channel. 
    Identify the most trending, high-retention topics in the USA right now using Google Search.
    
    Generate exactly 21 unique content ideas (7 per niche).
    NICHES: {', '.join(niches)}
    
    RULES:
    1. 'fact': Focus on bizarre, unknown, or controversial history/science.
    2. 'brainrot': Focus on high-energy Gen-Z memes or chaotic trending lore.
    3. 'short story': Focus on intense parables or extreme self-improvement tales.
    
    Return EXACTLY a JSON array of objects. No markdown, no preamble.
    Structure:
    [
        {{
            "niche": "niche_name",
            "topic": "Specific viral topic title",
            "bg_query": "pexels search term",
            "style": "default"
        }}
    ]
    """

    try:
        # CORRECT SYNTAX: tools must be inside the config dictionary
        response = client.models.generate_content(
            model='gemini-2.0-flash', 
            contents=prompt,
            config={
                'tools': [{'google_search': {}}]
            }
        )
        
        raw_text = response.text.strip()
        
        # Clean up potential markdown formatting
        if "```json" in raw_text:
            raw_text = raw_text.split("```json")[1].split("```")[0].strip()
        elif "```" in raw_text:
            raw_text = raw_text.split("```")[1].split("```")[0].strip()

        new_matrix = json.loads(raw_text)
        
        # --- ROBUST FILE WRITING ---
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        memory_dir = os.path.join(root_dir, "memory")
        
        if not os.path.exists(memory_dir):
            os.makedirs(memory_dir, exist_ok=True)
            
        matrix_path = os.path.join(memory_dir, "content_matrix.json")
        
        with open(matrix_path, "w", encoding="utf-8") as f:
            json.dump(new_matrix, f, indent=4)
            
        print(f"✅ Research Complete! Generated {len(new_matrix)} new topics.")
        print(f"📍 Saved to: {matrix_path}")
        
        notify_research_complete(len(new_matrix))

    except Exception as e:
        print("❌ Research Failed:")
        traceback.print_exc()
        notify_error("Dynamic Researcher", "Generation Error", str(e)[:200])

if __name__ == "__main__":
    run_dynamic_research()
