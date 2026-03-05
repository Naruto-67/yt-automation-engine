import os
import time
from scripts.quota_manager import quota_manager
from scripts.groq_client import groq_client
from scripts.youtube_manager import get_youtube_client
from scripts.discord_notifier import notify_summary

def generate_ai_reply(video_title, comment_text):
    prompt = f"Creator Reply: Topic '{video_title}', Comment '{comment_text}'. 10 words, witty Gen-Z style with emoji."
    raw_reply = quota_manager.generate_text(prompt, task_type="creative")
    
    if raw_reply:
        reply = raw_reply.strip().replace('"', '')
        # 🛡️ SAFETY SHIELD
        if groq_client.check_safety(reply):
            return reply
    return "Thanks for watching! 🔥"

def run_engagement_protocol():
    youtube = get_youtube_client()
    if not youtube: return
    
    print("💬 [ENGAGEMENT] Scanning for fan interactions...")
    try:
        channel_id = youtube.channels().list(part="id", mine=True).execute()["items"][0]["id"]
        # Fetch 5 recent videos
        uploads = youtube.channels().list(part="contentDetails", mine=True).execute()["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        vids = youtube.playlistItems().list(part="snippet", playlistId=uploads, maxResults=5).execute()

        replies_count = 0
        for vid in vids.get("items", []):
            vid_id = vid["snippet"]["resourceId"]["videoId"]
            try:
                comments = youtube.commentThreads().list(part="snippet", videoId=vid_id, maxResults=5).execute()
                for thread in comments.get("items", []):
                    top = thread["snippet"]["topLevelComment"]["snippet"]
                    if top.get("authorChannelId", {}).get("value") != channel_id and thread["snippet"]["totalReplyCount"] == 0:
                        reply_text = generate_ai_reply(vid["snippet"]["title"], top["textDisplay"])
                        youtube.comments().insert(part="snippet", body={"snippet": {"parentId": thread["id"], "textOriginal": reply_text}}).execute()
                        replies_count += 1
                        time.sleep(3) # Anti-spam pace
                        if replies_count >= 5: break
            except: continue
            if replies_count >= 5: break
        
        notify_summary(True, f"Engaged with {replies_count} viewers safely.")
    except Exception as e:
        quota_manager.diagnose_fatal_error("reply_comments.py", e)
