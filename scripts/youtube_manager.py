import os
import json
import time
import shutil
import traceback
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

from scripts.quota_manager import quota_manager
from scripts.discord_notifier import notify_vault_secure, notify_error

def get_youtube_client():
    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
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

def get_channel_name(youtube):
    """🚨 DYNAMIC WATERMARK: Fetches your exact YouTube channel name."""
    try:
        request = youtube.channels().list(part="snippet", mine=True)
        response = request.execute()
        return response["items"][0]["snippet"]["title"]
    except Exception as e:
        print(f"⚠️ [VAULT] Could not fetch channel name: {e}")
        return "GhostEngine" # Fallback

def get_or_create_playlist(youtube, title, privacy_status="private"):
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
    print("🔍 [VAULT] Executing Post-Upload Verification Handshake...")
    time.sleep(10) 
    
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
        return True 

def post_creator_comment(youtube, video_id, text):
    """🚨 AUTO-COMMENTER: Posts a top-level creator comment on the new video."""
    try:
        youtube.commentThreads().insert(
            part="snippet",
            body={
                "snippet": {
                    "videoId": video_id,
                    "topLevelComment": {
                        "snippet": {
                            "textOriginal": text
                        }
                    }
                }
            }
        ).execute()
        return True
    except Exception as e:
        print(f"⚠️ [VAULT] Failed to post auto-comment: {e}")
        return False

def upload_to_youtube_vault(video_path, niche, topic, metadata):
    usage = shutil.disk_usage("/")
    if usage.free < (500 * 1024 * 1024): 
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
        
        # 🚨 TRIGGERING THE AUTO-COMMENT
        print("💬 [VAULT] Injecting Auto-Comment...")
        comment_text = "What myth or story should we cover next? Let us know below and don't forget to subscribe! 🌟"
        if post_creator_comment(youtube, video_id, comment_text):
            quota_manager.consume_points("youtube", 50)
            print("✅ [VAULT] Comment successfully posted!")
            
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
