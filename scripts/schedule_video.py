import os
from datetime import datetime, timedelta
from scripts.youtube_manager import get_youtube_client, get_or_create_playlist
from scripts.quota_manager import quota_manager

def publish_vault_videos():
    youtube = get_youtube_client()
    if not youtube: return
    
    try:
        vault_id = get_or_create_playlist(youtube, "Vault Backup")
        items = youtube.playlistItems().list(part="snippet", playlistId=vault_id, maxResults=2).execute().get("items", [])
        
        for idx, item in enumerate(items):
            vid_id = item["snippet"]["resourceId"]["videoId"]
            offset = 4 if idx == 0 else 10
            pub_time = (datetime.utcnow() + timedelta(hours=offset)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            
            # 1. Schedule
            youtube.videos().update(part="status", body={"id": vid_id, "status": {"privacyStatus": "private", "publishAt": pub_time}}).execute()
            # 2. Move to Public Playlist
            pub_playlist = get_or_create_playlist(youtube, "Viral Shorts", "public")
            youtube.playlistItems().insert(part="snippet", body={"snippet": {"playlistId": pub_playlist, "resourceId": {"kind": "youtube#video", "videoId": vid_id}}}).execute()
            # 3. Cleanup Vault
            youtube.playlistItems().delete(id=item["id"]).execute()
            
        print(f"📅 Successfully scheduled {len(items)} videos for peak hours.")
    except Exception as e:
        quota_manager.diagnose_fatal_error("schedule_video.py", e)
