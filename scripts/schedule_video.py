import os
import json
import time
from datetime import datetime, timedelta
from scripts.youtube_manager import get_youtube_client, get_or_create_playlist
from scripts.quota_manager import quota_manager
from scripts.discord_notifier import notify_summary

def publish_vault_videos():
    youtube = get_youtube_client()
    if not youtube: return
    
    try:
        # Load matrix to map video IDs to their exact dynamic Niche
        matrix_path = os.path.join(os.path.dirname(__file__), "..", "memory", "content_matrix.json")
        matrix = []
        if os.path.exists(matrix_path):
            with open(matrix_path, "r") as f: matrix = json.load(f)

        vault_id = get_or_create_playlist(youtube, "Vault Backup")
        items = youtube.playlistItems().list(part="snippet", playlistId=vault_id, maxResults=2).execute().get("items", [])
        
        if len(items) < 2:
            print("⚠️ [PUBLISHER] Not enough videos in the vault to execute dual-release.")
            return

        for idx, item in enumerate(items):
            vid_id = item["snippet"]["resourceId"]["videoId"]
            
            # 🚨 DYNAMIC NICHE MATCHING: No hardcoding. Looks up exact niche from memory.
            niche_tag = "Viral Shorts"
            for m_item in matrix:
                if m_item.get("youtube_id") == vid_id:
                    niche_tag = f"{m_item['niche'].title()} Shorts"
                    break
            
            offset = 4 if idx == 0 else 10
            pub_time = (datetime.utcnow() + timedelta(hours=offset)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            
            youtube.videos().update(part="status", body={"id": vid_id, "status": {"privacyStatus": "private", "publishAt": pub_time}}).execute()
            time.sleep(5)
            
            niche_playlist = get_or_create_playlist(youtube, niche_tag, "public")
            youtube.playlistItems().insert(part="snippet", body={"snippet": {"playlistId": niche_playlist, "resourceId": {"kind": "youtube#video", "videoId": vid_id}}}).execute()
            time.sleep(5)
            
            youtube.playlistItems().delete(id=item["id"]).execute()
            time.sleep(5)
            
        notify_summary(True, f"Publisher released 2 videos. Moved to dynamic Niche Playlists.")
    except Exception as e:
        quota_manager.diagnose_fatal_error("schedule_video.py", e)

if __name__ == "__main__":
    publish_vault_videos()
