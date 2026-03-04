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

    print("🔎 Searching the web for trending viral topics...")

    # We provide context of our niches so Gemini knows what to look for
    niches = ["fact", "brainrot", "short story"]
    
    prompt = f"""
    You are a viral content researcher for a top-tier YouTube Shorts channel. 
    Using your search tools, identify the most trending, high-retention topics in the USA right now.
    
    Generate exactly 21 unique content ideas (7 per niche).
    NICHES: {', '.join(niches)}
    
    RULES:
    1. 'fact': Focus on bizarre, unknown, or controversial history/science that people will share.
    2. 'brainrot': Focus on high-energy Gen-Z memes, internet lore, or chaotic trending sound-bites.
    3. 'short story': Focus on intense parables, psychological thrillers, or extreme self-improvement tales.
    
    Return EXACTLY this JSON structure and absolutely nothing else. No markdown blocks.
    [
        {{
            "niche": "niche_name",
            "topic": "Specific, detailed viral topic title",
            "bg_query": "specific search terms for Pexels video",
            "style": "default"
        }},
        ...
    ]
    """

    try:
        # Use Google Search grounding to find real-world trends
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            tools=[{ "google_search": {} }]
        )
        
        raw_json = response.text.replace("```json", "").replace("```", "").strip()
        # Handle cases where Gemini adds unexpected leading text
        if "[" in raw_json:
            raw_json = raw_json[raw_json.find("["):raw_json.rfind("]")+1]
            
        new_matrix = json.loads(raw_json)
        
        # Save to memory folder
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        memory_dir = os.path.join(root_dir, "memory")
        if not os.path.exists(memory_dir):
            os.makedirs(memory_dir)
            
        matrix_path = os.path.join(memory_dir, "content_matrix.json")
        
        with open(matrix_path, "w", encoding="utf-8") as f:
            json.dump(new_matrix, f, indent=4)
            
        print(f"✅ Research Complete! Generated {len(new_matrix)} new topics.")
        notify_research_complete(len(new_matrix))

    except Exception as e:
        print("❌ Research Failed:")
        traceback.print_exc()
        notify_error("Dynamic Researcher", "System Error", str(e)[:200])

if __name__ == "__main__":
    run_dynamic_research()
