# scripts/youtube_manager.py
import os
import shutil
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from scripts.quota_manager import quota_manager
from scripts.discord_notifier import notify_error

def get_youtube_client(token_env_var):
    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.environ.get(token_env_var)

    if not all([client_id, client_secret, refresh_token]):
        return None

    try:
        creds = Credentials(None, refresh_token=refresh_token, token_uri="https://oauth2.googleapis.com/token", 
                            client_id=client_id, client_secret=client_secret)
        return build('youtube', 'v3', credentials=creds, static_discovery=False)
    except Exception as e:
        notify_error("YouTube Auth", "Auth Failure", str(e))
        return None

def get_channel_name(youtube):
    """Fetches the live display name for sync logic."""
    try:
        res = youtube.channels().list(part="snippet", mine=True).execute()
        quota_manager.consume_points("youtube", 1)
        return res["items"][0]["snippet"]["title"]
    except:
        return None

def get_or_create_playlist(youtube, title, privacy="private"):
    try:
        res = youtube.playlists().list(part="snippet", mine=True, maxResults=50).execute()
        quota_manager.consume_points("youtube", 1)
        for item in res.get("items", []):
            if item["snippet"]["title"].lower() == title.lower(): return item["id"]
        
        new_pl = youtube.playlists().insert(part="snippet,status", body={"snippet": {"title": title}, "status": {"privacyStatus": privacy}}).execute()
        quota_manager.consume_points("youtube", 50)
        return new_pl["id"]
    except: return None

def get_actual_vault_count(youtube):
    v_id = get_or_create_playlist(youtube, "Vault Backup")
    if not v_id: return 0
    res = youtube.playlists().list(part="contentDetails", id=v_id).execute()
    quota_manager.consume_points("youtube", 1)
    return res["items"][0]["contentDetails"]["itemCount"]

def upload_to_youtube_vault(youtube, video_path, topic, metadata, niche):
    if shutil.disk_usage("/").free < (500 * 1024 * 1024): return False, None
    try:
        media = MediaFileUpload(video_path, chunksize=1024*1024*5, resumable=True, mimetype="video/mp4")
        request = youtube.videos().insert(
            part="snippet,status",
            body={
                "snippet": {
                    "title": metadata.get("title", f"{topic} #shorts")[:100],
                    "description": metadata.get("description", "")[:4900],
                    "tags": metadata.get("tags", ["shorts"])[:15],
                    "categoryId": "22"
                },
                "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False}
            },
            media_body=media
        )
        response = None
        while response is None:
            status, response = request.next_chunk()
        
        video_id = response["id"]
        quota_manager.consume_points("youtube", 1600)
        
        vault_id = get_or_create_playlist(youtube, "Vault Backup")
        if vault_id:
            youtube.playlistItems().insert(part="snippet", body={"snippet": {"playlistId": vault_id, "resourceId": {"kind": "youtube#video", "videoId": video_id}}}).execute()
            quota_manager.consume_points("youtube", 50)
            
        return True, video_id
    except Exception as e:
        quota_manager.diagnose_fatal_error("YouTube Upload", e)
        return False, None
