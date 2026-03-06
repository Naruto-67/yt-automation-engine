import os
import time
import random
from scripts.quota_manager import quota_manager
from scripts.youtube_manager import get_youtube_client
from scripts.discord_notifier import notify_summary

def generate_ai_reply(video_title, comment_text, attempt_num):
    prompt = f"Creator Reply: Topic '{video_title}', Comment '{comment_text}'. 10 words, witty Gen-Z style with emoji."
    
    # 🚨 QUOTA MANAGEMENT: 1-3 go to Gemini, 4-15 go to Groq.
    if attempt_num <= 3:
        raw_reply, _ = quota_manager.generate_text(prompt, task_type="creative", force_provider="gemini")
    else:
        raw_reply, _ = quota_manager.generate_text(prompt, task_type="comment_reply_groq", force_provider="groq")
        
    if raw_reply: return raw_reply.strip().replace('"', '')
    return "Thanks for watching! 🔥"

def run_engagement_protocol():
    youtube = get_youtube_client()
    if not youtube: return
    
    print("💬 [ENGAGEMENT] Scanning for top unanswered fan interactions...")
    try:
        channel_id = youtube.channels().list(part="id", mine=True).execute()["items"][0]["id"]
        uploads = youtube.channels().list(part="contentDetails", mine=True).execute()["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        vids = youtube.playlistItems().list(part="snippet", playlistId=uploads, maxResults=5).execute()

        replies_count = 0
        target_replies = random.randint(10, 15) # Randomize to mimic human behavior
        
        for vid in vids.get("items", []):
            vid_id = vid["snippet"]["resourceId"]["videoId"]
            try:
                # 🚨 ALGORITHM FIX: order="relevance" guarantees we reply to the highest-voted TOP comments first.
                comments = youtube.commentThreads().list(part="snippet", videoId=vid_id, maxResults=15, order="relevance").execute()
                for thread in comments.get("items", []):
                    top = thread["snippet"]["topLevelComment"]["snippet"]
                    if top.get("authorChannelId", {}).get("value") != channel_id and thread["snippet"]["totalReplyCount"] == 0:
                        replies_count += 1
                        
                        reply_text = generate_ai_reply(vid["snippet"]["title"], top["textDisplay"], replies_count)
                        
                        youtube.comments().insert(
                            part="snippet", 
                            body={"snippet": {"parentId": thread["id"], "textOriginal": reply_text}}
                        ).execute()
                        
                        quota_manager.consume_points("youtube", 50)
                        time.sleep(4) 
                        if replies_count >= target_replies: break
            except: continue
            if replies_count >= target_replies: break
        
        gemini_count = min(replies_count, 3)
        groq_count = max(0, replies_count - 3)
        notify_summary(True, f"Successfully engaged with {replies_count} top comments. ({gemini_count} Gemini / {groq_count} Groq)")
    except Exception as e:
        quota_manager.diagnose_fatal_error("reply_comments.py", e)

if __name__ == "__main__":
    run_engagement_protocol()
