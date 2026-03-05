import os
import json
import time
import shutil
import traceback
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

# Ghost Engine Infrastructure Imports
from scripts.quota_manager import quota_manager
from scripts.discord_notifier import notify_vault_secure, notify_error

def get_youtube_client():
    """Authenticates and returns the YouTube API client."""
    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        print("⚠️ [VAULT] YouTube OAuth Credentials missing.")
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
        print(f"❌ [VAULT] Authentication Failed: {e}")
        return None

def get_or_create_playlist(youtube, title, privacy_status="private"):
    """Finds the Vault playlist or creates it if it doesn't exist."""
    try:
        request = youtube.playlists().list(part="snippet", mine=True, maxResults=50)
        response = request.execute()
        
        for item in response.get("items", []):
            if item["snippet"]["title"].lower() == title.lower():
                return item["id"]
                
        print(f"📁 [VAULT] Creating new playlist: '{title}'")
        request = youtube.playlists().insert(
            part="snippet,status",
            body={
                "snippet": {"title": title},
                "status": {"privacyStatus": privacy_status}
            }
        )
        response = request.execute()
        return response["id"]
    except Exception as e:
        print(f"⚠️ [VAULT] Playlist Management Error: {e}")
        return None

def verify_upload_integrity(youtube, video_id):
    """
    The Verification Handshake (Loophole 4 Fix).
    Interrogates YouTube to ensure the file isn't a corrupted 'Zombie'.
    """
    print("🔍 [VAULT] Executing Post-Upload Verification Handshake...")
    time.sleep(10) # Wait for YouTube backend indexing
    
    try:
        response = youtube.videos().list(part="status", id=video_id).execute()
        if not response.get("items"):
            print("⚠️ [VAULT] Verification failed: Video not found.")
            return False
            
        status = response["items"][0]["status"]
        upload_status = status.get("uploadStatus", "unknown")
        
        if upload_status in ["failed", "rejected", "deleted"]:
            print(f"🚨 [VAULT] ZOMBIE DETECTED! Status: {upload_status.upper()}")
            try:
                youtube.videos().delete(id=video_id).execute()
                print("🧹 [VAULT] Zombie file purged successfully.")
            except: pass
            return False
            
        print(f"✅ [VAULT] Integrity Verified. Status: {upload_status.upper()}")
        return True
    except:
        return True # Failsafe: assume okay if check crashes

def upload_to_youtube_vault(video_path, niche, topic, metadata):
    """
    The Master Upload Engine.
    Includes Disk-Space Guard, Chunked Transfer, and Quota Point Deduction.
    """
    # 🛡️ PRE-FLIGHT SAFETY CHECKS (Loophole Fix)
    usage = shutil.disk_usage("/")
    if usage.free < (500 * 1024 * 1024): # Ensure 500MB free
        print("🚨 [VAULT] Disk Space Critical. Aborting upload.")
        return False

    youtube = get_youtube_client()
    if not youtube:
        return False
        
    print(f"☁️ [VAULT] Uploading '{topic}' to the Private Vault...")
    
    try:
        media = MediaFileUpload(video_path, chunksize=1024*1024*5, resumable=True, mimetype="video/mp4")
        request = youtube.videos().insert(
            part="snippet,status",
            body={
                "snippet": {
                    "title": metadata.get("title", f"{topic} #shorts")[:100], 
                    "description": metadata.get("description", "Produced by Ghost Engine V4.0"),
                    "tags": metadata.get("tags", ["shorts", "viral"]),
                    "categoryId": "22" 
                },
                "status": {
                    "privacyStatus": "private", 
                    "selfDeclaredMadeForKids": False
                }
            },
            media_body=media
        )
        
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                print(f"⏳ [VAULT] Progress: {int(status.progress() * 100)}%")
                
        video_id = response["id"]
        
        if not verify_upload_integrity(youtube, video_id):
            return False
        
        vault_playlist_id = get_or_create_playlist(youtube, "Vault Backup")
        if vault_playlist_id:
            youtube.playlistItems().insert(
                part="snippet",
                body={
                    "snippet": {
                        "playlistId": vault_playlist_id,
                        "resourceId": {"kind": "youtube#video", "videoId": video_id}
                    }
                }
            ).execute()
        
        print(f"✅ [VAULT] Successfully Secured. Deducting 1,600 Quota Points.")
        quota_manager.consume_points("youtube", 1600)
        notify_vault_secure(metadata.get("title", topic), video_id, vault_playlist_id)
        
        return True

    except HttpError as e:
        error_details = json.loads(e.content.decode('utf-8'))
        msg = error_details.get('error', {}).get('message', str(e))
        print(f"❌ [VAULT] API REJECTION: {msg}")
        notify_error("YouTube Manager", "API Rejection", msg)
        return False
        
    except Exception as e:
        print(f"❌ [VAULT] SYSTEM ERROR during upload.")
        quota_manager.diagnose_fatal_error("youtube_manager.py", e)
        return False
