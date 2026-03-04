import os
import json
import time
import traceback
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google import genai
from scripts.retry import quota_manager
from scripts.discord_notifier import send_embed, get_ist_time, notify_error

def get_youtube_client():
    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN")
    try:
        creds = Credentials(token=None, refresh_token=refresh_token, token_uri="https://oauth2.googleapis.com/token", client_id=client_id, client_secret=client_secret)
        return build('youtube', 'v3', credentials=creds)
    except: return None

def run_performance_analysis():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    assets_dir = os.path.join(root_dir, "assets")
    os.makedirs(assets_dir, exist_ok=True)
    tracker_path = os.path.join(assets_dir, "lessons_learned.json")

    youtube = get_youtube_client()
    if not youtube: return
    print("📊 Initiating Weekly Performance Analysis...")

    try:
        channel_response = youtube.channels().list(part="contentDetails", mine=True).execute()
        uploads_playlist_id = channel_response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        
        playlist_items = youtube.playlistItems().list(part="snippet", playlistId=uploads_playlist_id, maxResults=20).execute()
        video_ids = [item["snippet"]["resourceId"]["videoId"] for item in playlist_items.get("items", [])]
        
        video_response = youtube.videos().list(part="snippet,statistics,status", id=",".join(video_ids)).execute()
        
        performance_data = []
        for vid in video_response.get("items", []):
            if vid["status"]["privacyStatus"] == "public":
                performance_data.append({
                    "title": vid["snippet"]["title"], 
                    "views": vid["statistics"].get("viewCount", 0)
                })

        if not performance_data: return

        print(f"📈 Sending {len(performance_data)} videos to Gemini for strategy update...")
        client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
        prompt = f"Analyze these stats and return improved 'emphasize' and 'avoid' rules as JSON: {json.dumps(performance_data)}"

        response = quota_manager.safe_execute(
            client.models.generate_content,
            model='gemini-2.0-flash',
            contents=prompt
        )

        if response:
            raw_json = response.text.replace("```json", "").replace("```", "").strip()
            new_lessons = json.loads(raw_json)
            with open(tracker_path, "w", encoding="utf-8") as f:
                json.dump(new_lessons, f, indent=4)
            print("✅ AI Memory successfully rewritten based on real stats.")

    except Exception as e:
        print(f"❌ Analysis failed: {e}")
        notify_error("Analyst", "System Error", str(e)[:200])

if __name__ == "__main__":
    run_performance_analysis()
