import os
import json
import re
from scripts.quota_manager import quota_manager
from scripts.discord_notifier import notify_summary
from scripts.youtube_manager import get_youtube_client

def get_channel_context(youtube):
    """Fetches real performance data from your channel to give the AI context."""
    if not youtube: return "No channel data available. Generate broadly appealing viral niches."
    try:
        # Get recent uploads
        uploads_id = youtube.channels().list(part="contentDetails", mine=True).execute()["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        recent_vids = youtube.playlistItems().list(part="snippet", playlistId=uploads_id, maxResults=5).execute()
        
        context = "Recent Channel Performance Context:\n"
        for vid in recent_vids.get("items", []):
            vid_id = vid["snippet"]["resourceId"]["videoId"]
            stats = youtube.videos().list(part="statistics", id=vid_id).execute()["items"][0]["statistics"]
            views = stats.get("viewCount", "0")
            context += f"- Title: '{vid['snippet']['title']}' | Views: {views}\n"
        return context
    except:
        return "Failed to fetch recent stats. Generate broadly appealing viral niches."

def run_dynamic_research():
    print("🔎 [RESEARCHER] Fetching live channel data & generating new matrix...")
    youtube = get_youtube_client()
    channel_context = get_channel_context(youtube)
    
    prompt = f"""
    You are an Elite YouTube Shorts Strategist. 
    Review our recent channel data below. Identify what works, and invent 21 NEW, highly viral YouTube Shorts topics and niches. 
    Be incredibly creative with the 'niche' names (e.g., 'Deep Ocean Horror', 'Cyberpunk Lore', 'Bizarre History').
    
    {channel_context}
    
    Return ONLY a raw JSON array of exactly 21 objects. No intro text. Do not use markdown blocks.
    Format:
    [
        {{"niche": "Cyberpunk Lore", "topic": "The 2077 Neon Incident"}},
        ...
    ]
    """

    try:
        raw_text, provider = quota_manager.generate_text(prompt, task_type="research")
        if not raw_text:
            raise Exception("All AI providers failed to respond.")

        clean_json_str = raw_text.replace("```json", "").replace("```", "").strip()
        match = re.search(r'\[.*\]', clean_json_str, re.DOTALL)
        
        if match:
            new_matrix = json.loads(match.group(0))
            for item in new_matrix: item["processed"] = False # Ensure proper keys
            
            root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            matrix_path = os.path.join(root_dir, "memory", "content_matrix.json")
            os.makedirs(os.path.dirname(matrix_path), exist_ok=True)
            
            with open(matrix_path, "w", encoding="utf-8") as f:
                json.dump(new_matrix, f, indent=4)
                
            print(f"✅ [RESEARCHER] Matrix updated with {len(new_matrix)} completely dynamic topics.")
            notify_summary(True, f"Weekly Research Complete. Matrix generated 21 new dynamic niches via {provider}.")
        else:
            raise ValueError("AI returned non-JSON parsable content.")

    except Exception as e:
        quota_manager.diagnose_fatal_error("dynamic_researcher.py", e)

if __name__ == "__main__":
    run_dynamic_research()
