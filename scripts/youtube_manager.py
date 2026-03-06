import os
import json
import time
import shutil
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from scripts.quota_manager import quota_manager
from scripts.discord_notifier import notify_vault_secure, notify_error

def get_youtube_client():
    client_id, client_secret, refresh_token = os.environ.get("YOUTUBE_CLIENT_ID"), os.environ.get("YOUTUBE_CLIENT_SECRET"), os.environ.get("YOUTUBE_REFRESH_TOKEN")
    if not all([client_id, client_secret, refresh_token]): return None
    try:
        creds = Credentials(None, refresh_token=refresh_token, token_uri="https://oauth2.googleapis.com/token", client_id=client_id, client_secret=client_secret)
        return build('youtube', 'v3', credentials=creds)
    except: return None

def get_channel_name(youtube):
    try: return youtube.channels().list(part="snippet", mine=True).execute()["items"][0]["snippet"]["title"]
    except: return "GhostEngine"

def get_or_create_playlist(youtube, title, privacy_status="private"):
    try:
        for item in youtube.playlists().list(part="snippet", mine=True, maxResults=50).execute().get("items", []):
            if item["snippet"]["title"].lower() == title.lower(): return item["id"]
        return youtube.playlists().insert(part="snippet,status", body={"snippet": {"title": title}, "status": {"privacyStatus": privacy_status}}).execute()["id"]
    except: return None

def get_actual_vault_count(youtube):
    try:
        playlist_id = get_or_create_playlist(youtube, "Vault Backup")
        if not playlist_id: return 0
        response = youtube.playlists().list(part="contentDetails", id=playlist_id).execute()
        quota_manager.consume_points("youtube", 1)
        return response["items"][0]["contentDetails"]["itemCount"]
    except: return 0

def post_creator_comment(youtube, video_id, text):
    try:
        youtube.commentThreads().insert(part="snippet", body={"snippet": {"videoId": video_id, "topLevelComment": {"snippet": {"textOriginal": text}}}}).execute()
        return True
    except: return False

def upload_to_youtube_vault(video_path, topic, metadata):
    if shutil.disk_usage("/").free < (500 * 1024 * 1024): return False, None
    youtube = get_youtube_client()
    if not youtube: return False, None
    
    try:
        media = MediaFileUpload(video_path, chunksize=1024*1024*5, resumable=True, mimetype="video/mp4")
        request = youtube.videos().insert(
            part="snippet,status",
            body={
                "snippet": {"title": metadata.get("title", f"{topic} #shorts")[:100], "description": metadata.get("description", ""), "tags": metadata.get("tags", ["shorts"]), "categoryId": "22"},
                "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False}
            },
            media_body=media
        )
        response = None
        while response is None: status, response = request.next_chunk()
        video_id = response["id"]
        
        quota_manager.consume_points("youtube", 1600)
        
        # 🚨 FIX: Isolate Playlist error so it doesn't nuke a successful upload
        try:
            vault_playlist_id = get_or_create_playlist(youtube, "Vault Backup")
            if vault_playlist_id:
                youtube.playlistItems().insert(part="snippet", body={"snippet": {"playlistId": vault_playlist_id, "resourceId": {"kind": "youtube#video", "videoId": video_id}}}).execute()
                quota_manager.consume_points("youtube", 50)
        except Exception as playlist_err:
            print(f"⚠️ [VAULT] Video uploaded, but playlist assignment failed: {playlist_err}")
            vault_playlist_id = "Failed to Assign"
        
        if post_creator_comment(youtube, video_id, "What myth or story should we cover next? Let us know below and don't forget to subscribe! 🌟"):
            quota_manager.consume_points("youtube", 50)
            
        notify_vault_secure(metadata.get("title", topic), video_id, vault_playlist_id)
        return True, video_id
    except Exception as e:
        quota_manager.diagnose_fatal_error("youtube_manager.py", e)
        return False, None
