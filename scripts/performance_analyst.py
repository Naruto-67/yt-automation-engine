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
    """Sends a custom Discord embed showing what the AI learned."""
    emphasize_str = ", ".join(new_lessons.get('emphasize', ['Fast pacing']))
    avoid_str = ", ".join(new_lessons.get('avoid', ['Long pauses']))
    
    embed = {
        "title": "🧠 AI Memory Updated (Weekly Analytics)",
        "color": 3447003, # Blue
        "fields": [
            {"name": "🏆 Top Performing Video", "value": f"└ {top_video_title}", "inline": False},
            {"name": "📈 Emphasize Next Time", "value": f"└ {emphasize_str}", "inline": False},
            {"name": "🛑 Avoid Next Time", "value": f"└ {avoid_str}", "inline": False}
        ],
        "footer": {"text": f"Engine Local Time: {get_ist_time()}"}
    }
    send_embed(embed)

def run_performance_analysis():
    youtube = get_youtube_client()
    if not youtube:
        return

    print("📊 Initiating Weekly Performance Analysis...")

    try:
        # 1. Get Uploads Playlist
        channel_response = youtube.channels().list(part="contentDetails", mine=True).execute()
        if not channel_response.get("items"):
            print("❌ Could not locate YouTube Channel.")
            return
            
        uploads_playlist_id = channel_response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

        # 2. Get the 15 most recent videos
        playlist_items = youtube.playlistItems().list(
            part="snippet",
            playlistId=uploads_playlist_id,
            maxResults=15
        ).execute()

        video_ids = [item["snippet"]["resourceId"]["videoId"] for item in playlist_items.get("items", [])]
        
        if not video_ids:
            print("⚠️ No videos found to analyze.")
            return

        # 3. Fetch Statistics & Status for these videos
        video_response = youtube.videos().list(
            part="snippet,statistics,status",
            id=",".join(video_ids)
        ).execute()

        performance_data = []
        top_video_title = "None yet"
        highest_views = -1

        for vid in video_response.get("items", []):
            # Only analyze public videos
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

        if not performance_data:
            print("⚠️ No public videos available to analyze.")
            return

        print(f"📈 Collected data for {len(performance_data)} public videos. Feeding to Gemini...")

        # 4. Have Gemini Analyze the Data
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            print("⚠️ GEMINI_API_KEY missing.")
            return

        client = genai.Client(api_key=api_key)
        
        prompt = f"""
        You are an elite YouTube Shorts Strategist. I am giving you the performance data of my recent Shorts.
        Analyze the titles that got the most views, likes, and comments versus the ones that flopped.
        
        DATA:
        {json.dumps(performance_data, indent=2)}
        
        Based ONLY on this data, update my channel's content rules. 
        What concepts/styles should I 'emphasize' more of? What should I 'avoid'?
        
        Return EXACTLY this JSON structure and absolutely nothing else. No markdown blocks.
        {{
            "emphasize": ["rule 1", "rule 2", "rule 3"],
            "avoid": ["rule 1", "rule 2", "rule 3"],
            "preferred_visuals": ["dark", "cinematic"] 
        }}
        """

        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        
        raw_json = response.text.replace("```json", "").replace("```", "").strip()
        new_lessons = json.loads(raw_json)
        
        # 5. Save the updated memory to the JSON file
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        tracker_path = os.path.join(root_dir, "assets", "lessons_learned.json")
        
        with open(tracker_path, "w", encoding="utf-8") as f:
            json.dump(new_lessons, f, indent=4)
            
        print("✅ Successfully updated assets/lessons_learned.json with new AI insights!")
        
        # 6. Ping Discord
        notify_insight(new_lessons, top_video_title)

    except Exception as e:
        print("❌ Critical System Error during Analysis:")
        traceback.print_exc()
        notify_error("Performance Analyst", "System Error", str(e)[:200])

if __name__ == "__main__":
    run_performance_analysis()
