import os
import json
import traceback
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from scripts.discord_notifier import notify_upload, notify_warning, notify_error

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
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret
        )
        return build('youtube', 'v3', credentials=creds)
    except Exception as e:
        print(f"❌ YouTube Authentication Failed: {e}")
        return None

def get_playlist_id(youtube, title):
    """Finds a playlist by name. Returns None if it doesn't exist."""
    request = youtube.playlists().list(part="snippet", mine=True, maxResults=50)
    response = request.execute()
    for item in response.get("items", []):
        if item["snippet"]["title"].lower() == title.lower():
            return item["id"]
    return None

def create_playlist(youtube, title, privacy_status="public"):
    """Creates a new playlist and returns the ID."""
    print(f"📁 Creating new {privacy_status.upper()} playlist: '{title}'")
    request = youtube.playlists().insert(
        part="snippet,status",
        body={
            "snippet": {"title": title},
            "status": {"privacyStatus": privacy_status}
        }
    )
    response = request.execute()
    return response["id"]

def determine_niche_playlist(snippet):
    """
    Scans the AI-generated metadata (Title, Desc, Tags) to intelligently 
    route the video to the correct public niche playlist.
    """
    tags = snippet.get("tags", [])
    text_blob = (snippet.get("title", "") + " " + snippet.get("description", "") + " " + " ".join(tags)).lower()
    
    if "brainrot" in text_blob or "gen z" in text_blob or "trippy" in text_blob:
        return "Brainrot Shorts"
    elif "fact" in text_blob or "history" in text_blob or "bizarre" in text_blob:
        return "Fact Shorts"
    elif "story" in text_blob or "parable" in text_blob or "tale" in text_blob:
        return "Short Stories"
    else:
        return "Viral Shorts" # Safe fallback playlist

def publish_oldest_vault_video():
    youtube = get_youtube_client()
    if not youtube:
        return

    print("🔍 Scanning YouTube Vault for the oldest private video...")
    
    vault_playlist_id = get_playlist_id(youtube, "Vault Backup")
    if not vault_playlist_id:
        print("⚠️ 'Vault Backup' playlist not found. Is the vault empty?")
        notify_error("Publisher Bot", "Vault Check", "Vault Backup playlist does not exist.")
        return

    try:
        # 1. GET THE OLDEST VIDEO IN THE VAULT
        playlist_items = youtube.playlistItems().list(
            part="snippet",
            playlistId=vault_playlist_id,
            maxResults=50
        ).execute()

        items = playlist_items.get("items", [])
        if not items:
            print("⚠️ The Vault is completely empty! No videos to publish.")
            notify_warning("Publisher Bot", "Vault Empty", 1, 1)
            return

        # Grab the first item (oldest added)
        target_item = items[0]
        video_id = target_item["snippet"]["resourceId"]["videoId"]
        playlist_item_id = target_item["id"]
        video_title = target_item["snippet"]["title"]

        print(f"🎯 Target Locked: '{video_title}' (ID: {video_id})")

        # 2. FETCH EXISTING METADATA
        video_response = youtube.videos().list(
            part="snippet,status",
            id=video_id
        ).execute()

        if not video_response.get("items"):
            print("❌ Could not fetch video details.")
            return

        video_data = video_response["items"][0]
        snippet = video_data["snippet"]
        
        # Determine the dynamic target playlist based on SEO data
        target_playlist_name = determine_niche_playlist(snippet)
        print(f"🧠 AI Metadata Scanner routed video to niche: {target_playlist_name}")
        
        # 3. SCHEDULE THE VIDEO (For 12 hours from right now)
        publish_time = (datetime.utcnow() + timedelta(hours=12))
        iso_publish_time = publish_time.isoformat() + "Z"
        
        print(f"⏰ Scheduling video to go live at: {iso_publish_time}")

        youtube.videos().update(
            part="snippet,status",
            body={
                "id": video_id,
                "snippet": snippet,  # Preserve the AI SEO
                "status": {
                    "privacyStatus": "private", # Must remain private until the schedule hits
                    "publishAt": iso_publish_time,
                    "selfDeclaredMadeForKids": False
                }
            }
        ).execute()
        
        print("✅ Video successfully scheduled!")

        # 4. MOVE VIDEO TO THE DYNAMIC PUBLIC PLAYLIST
        print(f"🚚 Moving video out of Vault and into '{target_playlist_name}'...")
        youtube.playlistItems().delete(id=playlist_item_id).execute()
        
        public_playlist_id = get_playlist_id(youtube, target_playlist_name)
        if not public_playlist_id:
            # Automatically create the niche playlist as PUBLIC if it doesn't exist
            public_playlist_id = create_playlist(youtube, target_playlist_name, "public")
            
        youtube.playlistItems().insert(
            part="snippet",
            body={
                "snippet": {
                    "playlistId": public_playlist_id,
                    "resourceId": {
                        "kind": "youtube#video",
                        "videoId": video_id
                    }
                }
            }
        ).execute()

        print("✅ Pipeline Complete. Pinging Discord...")
        
        readable_time = publish_time.strftime("%B %d, %Y at %H:%M UTC")
        notify_upload(video_title, f"{readable_time} (Playlist: {target_playlist_name})")

    except HttpError as e:
        error_details = json.loads(e.content.decode('utf-8'))
        error_message = error_details.get('error', {}).get('message', str(e))
        print(f"\n❌ YOUTUBE API ERROR: {error_message}")
        notify_error(video_title, "YouTube Publisher", error_message)
    except Exception as e:
        print("❌ System Error:")
        traceback.print_exc()
        notify_error("Publisher Bot", "System Error", str(e)[:200])

if __name__ == "__main__":
    publish_oldest_vault_video()
