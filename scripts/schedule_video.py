import os
import time
from datetime import datetime, timedelta
from scripts.youtube_manager import get_youtube_client, get_or_create_playlist
from scripts.quota_manager import quota_manager
from scripts.discord_notifier import notify_summary

def get_optimal_publish_times():
    print("🧠 [PUBLISHER] Asking Gemini CEO for optimal retention times...")
    prompt = """Based on global YouTube Shorts algorithms, what are the two absolute best times (in UTC format: HH:MM) to post a short form video today? Return ONLY a valid JSON array of two time strings, e.g., ["14:30", "22:00"]"""
    response, _ = quota_manager.generate_text(prompt, task_type="analysis")
    try:
        import re
        match = re.search(r'\[.*\]', response.replace("```json", "").replace("```", "").strip(), re.DOTALL)
        if match: return json.loads(match.group(0))
    except: pass
    return ["15:00", "23:00"] 

def publish_vault_videos():
    youtube = get_youtube_client()
    if not youtube: return
    
    try:
        vault_id = get_or_create_playlist(youtube, "Vault Backup")
        items = youtube.playlistItems().list(part="snippet", playlistId=vault_id, maxResults=2).execute().get("items", [])
        
        if len(items) < 2:
            print("⚠️ [PUBLISHER] Not enough videos in the vault to execute dual-release.")
            return

        for idx, item in enumerate(items):
            vid_id = item["snippet"]["resourceId"]["videoId"]
            vid_title = item["snippet"]["title"]
            
            # Determine specific Niche Playlist based on title context
            niche_tag = "Story Shorts" if "Story" in vid_title or "Tale" in vid_title else "Fact Shorts"
            
            offset = 4 if idx == 0 else 10
            pub_time = (datetime.utcnow() + timedelta(hours=offset)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            
            # 1. Schedule Video
            youtube.videos().update(part="status", body={"id": vid_id, "status": {"privacyStatus": "private", "publishAt": pub_time}}).execute()
            time.sleep(5)
            
            # 2. Move to Niche Playlist
            niche_playlist = get_or_create_playlist(youtube, niche_tag, "public")
            youtube.playlistItems().insert(part="snippet", body={"snippet": {"playlistId": niche_playlist, "resourceId": {"kind": "youtube#video", "videoId": vid_id}}}).execute()
            time.sleep(5)
            
            # 3. Remove from Vault Backup
            youtube.playlistItems().delete(id=item["id"]).execute()
            time.sleep(5)
            
        notify_summary(True, f"Publisher released 2 videos. Moved to Niche Playlists.")
    except Exception as e:
        quota_manager.diagnose_fatal_error("schedule_video.py", e)

if __name__ == "__main__":
    publish_vault_videos()
