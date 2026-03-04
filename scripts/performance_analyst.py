import os
import json
import traceback
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google import genai
from scripts.discord_notifier import send_embed, get_ist_time, notify_error

def get_youtube_client():
    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        print("⚠️ YouTube OAuth Credentials missing.")
        return None

    try:
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret
        )
        return build('youtube', 'v3', credentials=creds)
    except Exception as e:
        print(f"❌ YouTube Authentication Failed: {e}")
        return None

def notify_insight(new_lessons, top_video_title):
    emphasize_str = ", ".join(new_lessons.get('emphasize', ['Fast pacing']))
    avoid_str = ", ".join(new_lessons.get('avoid', ['Long pauses']))
    
    embed = {
        "title": "🧠 AI Memory Updated (Weekly Analytics)",
        "color": 3447003,
        "fields": [
            {"name": "🏆 Top Performing Video", "value": f"└ {top_video_title}", "inline": False},
            {"name": "📈 Emphasize Next Time", "value": f"└ {emphasize_str}", "inline": False},
            {"name": "🛑 Avoid Next Time", "value": f"└ {avoid_str}", "inline": False}
        ],
        "footer": {"text": f"Engine Local Time: {get_ist_time()}"}
    }
    send_embed(embed)

def run_performance_analysis():
    # --- SETUP PATHS ---
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    assets_dir = os.path.join(root_dir, "assets")
    tracker_path = os.path.join(assets_dir, "lessons_learned.json")

    # Force create assets directory if it doesn't exist
    if not os.path.exists(assets_dir):
        os.makedirs(assets_dir)
        print(f"📁 Created missing directory: {assets_dir}")

    youtube = get_youtube_client()
    if not youtube:
        return

    print("📊 Initiating Weekly Performance Analysis...")

    try:
        channel_response = youtube.channels().list(part="contentDetails", mine=True).execute()
        if not channel_response.get("items"):
            print("❌ Could not locate YouTube Channel.")
            return
            
        uploads_playlist_id = channel_response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

        playlist_items = youtube.playlistItems().list(
            part="snippet",
            playlistId=uploads_playlist_id,
            maxResults=20
        ).execute()

        video_ids = [item["snippet"]["resourceId"]["videoId"] for item in playlist_items.get("items", [])]
        
        if not video_ids:
            print("⚠️ No videos found to analyze. Creating default memory file.")
            save_default_memory(tracker_path)
            return

        video_response = youtube.videos().list(
            part="snippet,statistics,status",
            id=",".join(video_ids)
        ).execute()

        performance_data = []
        top_video_title = "None (No Public Videos)"
        highest_views = -1

        for vid in video_response.get("items", []):
            if vid["status"]["privacyStatus"] != "public":
                continue
                
            title = vid["snippet"]["title"]
            stats = vid.get("statistics", {})
            views = int(stats.get("viewCount", 0))
            likes = int(stats.get("likeCount", 0))
            comments = int(stats.get("commentCount", 0))
            
            performance_data.append({
                "title": title,
                "views": views,
                "likes": likes,
                "comments": comments
            })

            if views > highest_views:
                highest_views = views
                top_video_title = title

        # If no public videos, we can't analyze stats, but we should ensure the file exists
        if not performance_data:
            print("⚠️ No public videos available for statistical analysis. Keeping existing memory.")
            if not os.path.exists(tracker_path):
                save_default_memory(tracker_path)
            return

        print(f"📈 Analyzing {len(performance_data)} public videos with Gemini...")

        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            return

        client = genai.Client(api_key=api_key)
        
        prompt = f"""
        You are a YouTube Shorts Strategist. Analyze this data:
        {json.dumps(performance_data, indent=2)}
        
        Update the content rules. What should I 'emphasize' and 'avoid'?
        Return EXACTLY this JSON structure:
        {{
            "emphasize": ["rule1", "rule2"],
            "avoid": ["rule1", "rule2"],
            "preferred_visuals": ["style1", "style2"]
        }}
        """

        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        
        raw_json = response.text.replace("```json", "").replace("```", "").strip()
        new_lessons = json.loads(raw_json)
        
        with open(tracker_path, "w", encoding="utf-8") as f:
            json.dump(new_lessons, f, indent=4)
            
        print(f"✅ AI Memory Updated: {tracker_path}")
        notify_insight(new_lessons, top_video_title)

    except Exception as e:
        print("❌ Analysis Error:")
        traceback.print_exc()
        notify_error("Performance Analyst", "System Error", str(e)[:200])

def save_default_memory(path):
    """Saves a starter memory file so the git commit doesn't fail."""
    default = {
        "emphasize": ["Fast pacing", "Visual hooks"],
        "avoid": ["Long intros", "Slow speech"],
        "preferred_visuals": ["cinematic", "vibrant"]
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(default, f, indent=4)
    print(f"✅ Default memory file created at {path}")

if __name__ == "__main__":
    run_performance_analysis()
