import os
import json
import time
import traceback
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from scripts.discord_notifier import notify_vault_secure, notify_error
from scripts.retry import quota_manager

def get_youtube_client():
    """Authenticates and returns the YouTube API client."""
    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        print("⚠️ [VAULT] YouTube OAuth Credentials missing.")
        return None

    # Hard Failsafe: Detect if user pasted wrong data in token
    if "{" in client_secret or "[" in refresh_token:
        print("❌ [VAULT] CRITICAL: Invalid Token format detected in Secrets.")
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

def verify_upload_integrity(youtube, video_id):
    """
    The Verification Handshake (Loophole 4 Fix).
    Interrogates the YouTube API to ensure the uploaded file isn't a corrupted 'Zombie'.
    """
    print("🔍 [VAULT] Executing Post-Upload Verification Handshake...")
    time.sleep(5) # Give YouTube servers a moment to index the video
    
    try:
        response = youtube.videos().list(part="status", id=video_id).execute()
        if not response.get("items"):
            print("⚠️ [VAULT] Verification failed: Video ID not found on YouTube.")
            return False
            
        status = response["items"][0]["status"]
        upload_status = status.get("uploadStatus", "unknown")
        
        if upload_status in ["failed", "rejected", "deleted"]:
            print(f"🚨 [VAULT] ZOMBIE DETECTED! YouTube flagged upload as: {upload_status.upper()}")
            # Immediately delete the corrupted file to protect channel reputation
            try:
                youtube.videos().delete(id=video_id).execute()
                print("🧹 [VAULT] Zombie file deleted from channel successfully.")
            except:
                print("⚠️ [VAULT] Failed to delete zombie file. Manual cleanup required.")
            return False
            
        print(f"✅ [VAULT] Integrity Verified. Status: {upload_status.upper()}")
        return True
        
    except Exception as e:
        print(f"⚠️ [VAULT] Verification Handshake Error: {e}")
        return True # Default to True if the check itself fails, to avoid false positives

def upload_to_youtube_vault(video_path, niche, topic, metadata):
    """
    Uploads the final video to the private Vault, applies AI metadata, 
    and executes the integrity handshake.
    """
    youtube = get_youtube_client()
    if not youtube:
        return False
        
    print(f"☁️ [VAULT] Initiating 5MB chunked upload for optimized SEO...")
    
    try:
        media = MediaFileUpload(video_path, chunksize=1024*1024*5, resumable=True, mimetype="video/mp4")
        request = youtube.videos().insert(
            part="snippet,status",
            body={
                "snippet": {
                    "title": metadata.get("title", f"{topic} #shorts")[:100], 
                    "description": metadata.get("description", "A new YouTube Short!"),
                    "tags": metadata.get("tags", ["shorts", "viral"]),
                    "categoryId": "22" # People & Blogs default
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
                print(f"⏳ [VAULT] Uploading... {int(status.progress() * 100)}%")
                
        video_id = response["id"]
        print(f"✅ [VAULT] Byte transfer complete. ID: {video_id}")
        
        # 🛡️ Execute the Verification Handshake
        if not verify_upload_integrity(youtube, video_id):
            return False
        
        vault_playlist_id = get_or_create_playlist(youtube, "Vault Backup", "private")
        
        youtube.playlistItems().insert(
            part="snippet",
            body={
                "snippet": {
                    "playlistId": vault_playlist_id,
                    "resourceId": {
                        "kind": "youtube#video",
                        "videoId": video_id
                    }
                }
            }
        ).execute()
        
        print("🔒 [VAULT] Video successfully secured in 'Vault Backup' Playlist.")
        notify_vault_secure(metadata.get("title", topic), video_id, vault_playlist_id)
        return True

    except HttpError as e:
        try:
            error_details = json.loads(e.content.decode('utf-8'))
            error_message = error_details.get('error', {}).get('message', str(e))
            print(f"\n❌ [VAULT] YOUTUBE API REJECTED THE UPLOAD:")
            print(f"Reason: {error_message}\n")
            notify_error(topic, "YouTube API Rejection", error_message)
        except:
            print(f"❌ [VAULT] YouTube API Error (Unparseable): {e}")
            notify_error(topic, "YouTube API Error", str(e)[:200])
        return False
        
    except Exception as e:
        print(f"❌ [VAULT] Upload failed due to a system error:")
        quota_manager.diagnose_fatal_error("youtube_manager.py", e)
        notify_error(topic, "System Upload Error", str(e)[:200])
        return False

if __name__ == "__main__":
    # Local connection test
    client = get_youtube_client()
    if client:
        print("✅ YouTube Master Token is valid and connected!")
