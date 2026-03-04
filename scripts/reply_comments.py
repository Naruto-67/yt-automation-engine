import os
import time
import json
import traceback
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google import genai
from scripts.retry import quota_manager
from scripts.discord_notifier import notify_summary, notify_error, notify_engagement

def get_youtube_client():
    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN")
    try:
        creds = Credentials(token=None, refresh_token=refresh_token, token_uri="https://oauth2.googleapis.com/token", client_id=client_id, client_secret=client_secret)
        return build('youtube', 'v3', credentials=creds)
    except: return None

def generate_ai_reply(video_title, comment_text):
    """Uses the central Quota Manager to generate witty fan replies."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key: return "Thanks for watching! 🙌"

    client = genai.Client(api_key=api_key)
    prompt = f"Reply to this comment: '{comment_text}' on video '{video_title}'. Short, witty, Gen-Z creator tone."

    try:
        response = quota_manager.safe_execute(
            client.models.generate_content,
            model='gemini-2.0-flash',
            contents=prompt
        )
        if response:
            return response.text.strip().replace('"', '')
        return "Appreciate you checking out the short! 🔥"
    except:
        return "Appreciate you checking out the short! 🔥"

def run_engagement_protocol():
    youtube = get_youtube_client()
    if not youtube: return
    print("🔍 Initiating Audience Engagement Protocol...")
    total_replies_sent = 0

    try:
        channel_response = youtube.channels().list(part="contentDetails", mine=True).execute()
        uploads_playlist_id = channel_response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        my_channel_id = channel_response["items"][0]["id"]
        
        playlist_items = youtube.playlistItems().list(part="snippet", playlistId=uploads_playlist_id, maxResults=15).execute()
        video_ids = [item["snippet"]["resourceId"]["videoId"] for item in playlist_items.get("items", [])]
        
        video_status_response = youtube.videos().list(part="status", id=",".join(video_ids)).execute()
        true_status_map = {vid["id"]: vid["status"]["privacyStatus"] for vid in video_status_response.get("items", [])}

        for video_item in playlist_items.get("items", []):
            video_id = video_item["snippet"]["resourceId"]["videoId"]
            video_title = video_item["snippet"]["title"]
            
            if true_status_map.get(video_id) != "public": continue
            
            try:
                comments_response = youtube.commentThreads().list(part="snippet", videoId=video_id, maxResults=10).execute()
                for thread in comments_response.get("items", []):
                    top_comment = thread["snippet"]["topLevelComment"]["snippet"]
                    if top_comment.get("authorChannelId", {}).get("value") == my_channel_id or thread["snippet"]["totalReplyCount"] > 0:
                        continue
                        
                    print(f"💬 Replying to: '{top_comment['textDisplay'][:30]}...'")
                    ai_reply = generate_ai_reply(video_title, top_comment["textDisplay"])
                    
                    youtube.comments().insert(part="snippet", body={"snippet": {"parentId": thread["id"], "textOriginal": ai_reply}}).execute()
                    
                    notify_engagement(video_title, top_comment["textDisplay"], ai_reply)
                    total_replies_sent += 1
                    time.sleep(1) # Extra gap to be safe
                    
                    if total_replies_sent >= 5: break
            except HttpError:
                continue
            if total_replies_sent >= 5: break

        print(f"\n🎉 Engagement Protocol Complete. Total replies: {total_replies_sent}")
        if total_replies_sent > 0:
            notify_summary(True, f"💬 AI successfully engaged with {total_replies_sent} fans.")
            
    except Exception as e:
        notify_error("Engagement Bot", "System Error", str(e)[:200])

if __name__ == "__main__":
    run_engagement_protocol()
