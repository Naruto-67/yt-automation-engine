import os
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from scripts.discord_notifier import notify_vault_secure, notify_error

def get_youtube_client():
    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        print("⚠️ YouTube OAuth Credentials missing.")
        return None

    try:
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="[https://oauth2.googleapis.com/token](https://oauth2.googleapis.com/token)",
            client_id=client_id,
            client_secret=client_secret
        )
        return build('youtube', 'v3', credentials=creds)
    except Exception as e:
        print(f"❌ YouTube Authentication Failed: {e}")
        return None

def get_or_create_playlist(youtube, title, privacy_status="private"):
    request = youtube.playlists().list(part="snippet", mine=True, maxResults=50)
    response = request.execute()
    
    for item in response.get("items", []):
        if item["snippet"]["title"].lower() == title.lower():
            return item["id"]
            
    print(f"📁 Creating new playlist: '{title}'")
    request = youtube.playlists().insert(
        part="snippet,status",
        body={
            "snippet": {"title": title},
            "status": {"privacyStatus": privacy_status}
        }
    )
    response = request.execute()
    return response["id"]

def upload_to_youtube_vault(video_path, niche, topic, metadata):
    """
    Uploads the video as Private using the dynamically generated AI SEO metadata.
    """
    youtube = get_youtube_client()
    if not youtube:
        return False
        
    print(f"☁️ Uploading to YouTube Vault with optimized SEO...")
    
    try:
        # 1. UPLOAD THE VIDEO WITH AI METADATA
        media = MediaFileUpload(video_path, chunksize=1024*1024*5, resumable=True, mimetype="video/mp4")
        request = youtube.videos().insert(
            part="snippet,status",
            body={
                "snippet": {
                    "title": metadata["title"][:100],  # Hard cap at 100 chars just to be safe
                    "description": metadata["description"],
                    "tags": metadata["tags"],
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
                print(f"⏳ Uploading... {int(status.progress() * 100)}%")
                
        video_id = response["id"]
        print(f"✅ Video uploaded successfully! ID: {video_id}")
        
        # 2. ADD TO BACKUP PLAYLIST
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
        
        print("✅ Video successfully secured in 'Vault Backup' Playlist.")
        # Ping Discord with the awesome new AI Title
        notify_vault_secure(metadata["title"], video_id, vault_playlist_id)
        return True

    except Exception as e:
        print(f"❌ YouTube Vault upload failed: {e}")
        notify_error(topic, "YouTube Vault Upload", str(e)[:200])
        return False
