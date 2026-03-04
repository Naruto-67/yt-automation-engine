import os
import time
import traceback
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google import genai
from scripts.discord_notifier import notify_summary, notify_error, notify_engagement

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

def generate_ai_reply(video_title, comment_text):
    """Uses Gemini to generate a natural, engaging reply to a viewer's comment."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return "Thanks for watching! 🙌"

    client = genai.Client(api_key=api_key)
    
    prompt = f"""
    You are the creator of a highly popular, fast-paced YouTube Shorts channel. 
    You need to reply to a fan's comment on your recent video.
    
    Video Title: {video_title}
    Viewer's Comment: "{comment_text}"
    
    Rules for your reply:
    1. Keep it very short (1 to 2 sentences max).
    2. Be highly engaging, friendly, and slightly Gen-Z in tone.
    3. Do not sound like a corporate robot. Use a conversational tone.
    4. You can use 1 or 2 emojis if it fits naturally.
    5. Output ONLY the exact text of the reply. No quotes, no markdown.
    """

    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        return response.text.strip().replace('"', '')
    except Exception as e:
        print(f"⚠️ AI Reply generation failed: {e}")
        return "Appreciate you checking out the short! 🔥"

def run_engagement_protocol():
    youtube = get_youtube_client()
    if not youtube:
        return

    print("🔍 Initiating Audience Engagement Protocol...")
    total_replies_sent = 0

    try:
        # 1. Get the Channel's 'Uploads' Playlist ID
        channel_response = youtube.channels().list(part="contentDetails", mine=True).execute()
        if not channel_response.get("items"):
            print("❌ Could not locate your YouTube Channel. Ensure the Brand Account is linked.")
            return
            
        uploads_playlist_id = channel_response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        my_channel_id = channel_response["items"][0]["id"]

        # 2. Get the 15 most recently uploaded videos (including statuses)
        playlist_items = youtube.playlistItems().list(
            part="snippet,status", # ADDED STATUS FETCHING
            playlistId=uploads_playlist_id,
            maxResults=15
        ).execute()

        recent_videos = playlist_items.get("items", [])
        if not recent_videos:
            print("⚠️ No videos found on this channel.")
            return

        for video_item in recent_videos:
            video_id = video_item["snippet"]["resourceId"]["videoId"]
            video_title = video_item["snippet"]["title"]
            privacy_status = video_item["status"]["privacyStatus"]
            
            # THE FIX: Only attempt to engage with PUBLIC videos
            if privacy_status != "public":
                print(f"⏭️ Skipping '{video_title}' (Status: {privacy_status.upper()} - Comments inaccessible)")
                continue
                
            print(f"\n👀 Scanning comments for: '{video_title}'")
            
            try:
                # 3. Fetch top comments for this video
                comments_response = youtube.commentThreads().list(
                    part="snippet",
                    videoId=video_id,
                    maxResults=10,
                    textFormat="plainText"
                ).execute()
                
                for thread in comments_response.get("items", []):
                    top_comment = thread["snippet"]["topLevelComment"]["snippet"]
                    comment_text = top_comment["textDisplay"]
                    author_id = top_comment.get("authorChannelId", {}).get("value", "")
                    reply_count = thread["snippet"]["totalReplyCount"]
                    
                    # 4. Strict Filtering Rules
                    if author_id == my_channel_id:
                        continue
                    if reply_count > 0:
                        continue
                        
                    print(f"💬 Found unanswered comment: '{comment_text[:50]}...'")
                    
                    # 5. Generate AI Reply
                    ai_reply = generate_ai_reply(video_title, comment_text)
                    print(f"🤖 AI generated reply: '{ai_reply}'")
                    
                    # 6. Post the Reply via YouTube API
                    youtube.comments().insert(
                        part="snippet",
                        body={
                            "snippet": {
                                "parentId": thread["id"],
                                "textOriginal": ai_reply
                            }
                        }
                    ).execute()
                    
                    print("✅ Reply successfully posted!")
                    
                    # 7. Ping Discord so you can see the interaction
                    notify_engagement(video_title, comment_text, ai_reply)
                    
                    total_replies_sent += 1
                    time.sleep(2) # Brief pause to respect API limits
                    
                    if total_replies_sent >= 5: 
                        break 
                        
            except HttpError as e:
                if e.resp.status == 403:
                    print("⚠️ Comments disabled for this video (Likely flagged 'Made for Kids'). Skipping.")
                else:
                    print(f"⚠️ API Error reading comments: {e}")
                    
            if total_replies_sent >= 5: 
                break

        print(f"\n🎉 Engagement Protocol Complete. Total replies sent: {total_replies_sent}")
        if total_replies_sent > 0:
            notify_summary(True, f"💬 Audience Engagement executed! AI successfully replied to {total_replies_sent} fan comments.")
        else:
            print("No new public comments needed replies.")

    except Exception as e:
        print("❌ Critical System Error during Engagement:")
        traceback.print_exc()
        notify_error("Audience Engagement", "System Error", str(e)[:200])

if __name__ == "__main__":
    run_engagement_protocol()
