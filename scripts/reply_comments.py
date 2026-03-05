import os
import time
import json
import traceback
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Import the new Central Nervous System
from scripts.retry import quota_manager
from scripts.groq_client import groq_client
from scripts.discord_notifier import notify_summary, notify_error, notify_engagement

def get_youtube_client():
    """Authenticates and returns the YouTube API client."""
    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        print("⚠️ [ENGAGEMENT] YouTube OAuth Credentials missing.")
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
        print(f"❌ [ENGAGEMENT] Authentication Failed: {e}")
        return None

def generate_ai_reply(video_title, comment_text):
    """
    Uses the Smart Router to generate a witty Gen-Z reply, 
    then passes it through the Groq Safety Shield before approval.
    """
    fallback_reply = "Appreciate you checking out the short! 🔥"
    
    prompt = f"""
    You are the creator of a viral YouTube Shorts channel.
    Write a short, witty, engaging reply to this viewer's comment.
    Keep it under 15 words. Use Gen-Z creator tone. Include an emoji.
    
    Video Topic: '{video_title}'
    Viewer Comment: '{comment_text}'
    
    Return ONLY the reply text. Do not use quotes or markdown.
    """

    try:
        print("🤖 [ENGAGEMENT] Drafting AI response...")
        # Generates the text using Groq Llama 3.3 (via the Router)
        raw_reply = quota_manager.generate_text(prompt, task_type="creative")
        
        if raw_reply:
            clean_reply = raw_reply.strip().replace('"', '')
            
            # 🛡️ THE GROQ SAFETY SHIELD
            if groq_client.check_safety(clean_reply):
                print(f"✅ [ENGAGEMENT] Reply cleared safety checks.")
                return clean_reply
            else:
                print(f"🛑 [ENGAGEMENT] Reply failed safety checks. Using fallback.")
                return fallback_reply
                
        return fallback_reply
        
    except Exception as e:
        print(f"⚠️ [ENGAGEMENT] Generation error: {e}")
        return fallback_reply

def run_engagement_protocol():
    """Scans recent videos for unreplied comments and deploys the AI responder."""
    youtube = get_youtube_client()
    if not youtube: 
        return
        
    print("🔍 [ENGAGEMENT] Initiating Audience Engagement Protocol...")
    total_replies_sent = 0

    try:
        channel_response = youtube.channels().list(part="contentDetails", mine=True).execute()
        uploads_playlist_id = channel_response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        my_channel_id = channel_response["items"][0]["id"]
        
        playlist_items = youtube.playlistItems().list(part="snippet", playlistId=uploads_playlist_id, maxResults=15).execute()
        video_ids = [item["snippet"]["resourceId"]["videoId"] for item in playlist_items.get("items", [])]
        
        if not video_ids:
            print("⚠️ [ENGAGEMENT] No videos found on channel.")
            return

        video_status_response = youtube.videos().list(part="status", id=",".join(video_ids)).execute()
        true_status_map = {vid["id"]: vid["status"]["privacyStatus"] for vid in video_status_response.get("items", [])}

        for video_item in playlist_items.get("items", []):
            video_id = video_item["snippet"]["resourceId"]["videoId"]
            video_title = video_item["snippet"]["title"]
            
            # Only engage with fully public videos
            if true_status_map.get(video_id) != "public": 
                continue
            
            try:
                comments_response = youtube.commentThreads().list(part="snippet", videoId=video_id, maxResults=10).execute()
                for thread in comments_response.get("items", []):
                    top_comment = thread["snippet"]["topLevelComment"]["snippet"]
                    
                    # Skip if we already replied, or if it's our own comment
                    if top_comment.get("authorChannelId", {}).get("value") == my_channel_id or thread["snippet"]["totalReplyCount"] > 0:
                        continue
                        
                    print(f"\n💬 [ENGAGEMENT] New comment on '{video_title[:20]}...': '{top_comment['textDisplay'][:30]}...'")
                    
                    # Generate and vet the reply
                    ai_reply = generate_ai_reply(video_title, top_comment["textDisplay"])
                    
                    # Post to YouTube
                    youtube.comments().insert(
                        part="snippet", 
                        body={"snippet": {"parentId": thread["id"], "textOriginal": ai_reply}}
                    ).execute()
                    
                    print(f"📤 [ENGAGEMENT] Posted: {ai_reply}")
                    notify_engagement(video_title, top_comment["textDisplay"], ai_reply)
                    
                    total_replies_sent += 1
                    time.sleep(2) # Anti-spam pacing
                    
                    # Limit to 5 replies per run to avoid triggering YouTube bot-detection
                    if total_replies_sent >= 5: 
                        break
                        
            except HttpError as e:
                # Usually means comments are disabled on the video, just skip it
                continue
                
            if total_replies_sent >= 5: 
                break

        print(f"\n🎉 [ENGAGEMENT] Protocol Complete. Total replies deployed: {total_replies_sent}")
        if total_replies_sent > 0:
            notify_summary(True, f"💬 AI successfully engaged with {total_replies_sent} fans safely.")
            
    except Exception as e:
        print("❌ [ENGAGEMENT] Critical System Error:")
        quota_manager.diagnose_fatal_error("reply_comments.py", e)
        notify_error("Engagement Bot", "System Error", str(e)[:200])

if __name__ == "__main__":
    run_engagement_protocol()
