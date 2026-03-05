import os
import json
import traceback
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from scripts.discord_notifier import notify_upload, notify_warning, notify_error
from scripts.retry import quota_manager

def get_youtube_client():
    """Authenticates and returns the YouTube API client."""
    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        print("⚠️ [PUBLISHER] YouTube OAuth Credentials missing.")
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
        print(f"❌ [PUBLISHER] YouTube Authentication Failed: {e}")
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
    print(f"📁 [PUBLISHER] Creating new {privacy_status.upper()} playlist: '{title}'")
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

def publish_vault_videos():
    """
    The Dual-Release Publisher Engine.
    Pulls up to 2 videos from the Vault, schedules them for USA peak times,
    and moves them to dynamic public playlists.
    """
    youtube = get_youtube_client()
    if not youtube:
        return

    print("🔍 [PUBLISHER] Scanning YouTube Vault for pending videos...")
    vault_playlist_id = get_playlist_id(youtube, "Vault Backup")
    
    if not vault_playlist_id:
        print("⚠️ [PUBLISHER] 'Vault Backup' playlist not found. Is the vault empty?")
        notify_error("Publisher Bot", "Vault Check", "Vault Backup playlist does not exist.")
        return

    try:
        # 1. GET THE OLDEST VIDEOS IN THE VAULT
        playlist_items = youtube.playlistItems().list(
            part="snippet",
            playlistId=vault_playlist_id,
            maxResults=10 # Fetch a batch, but we only process 2
        ).execute()

        items = playlist_items.get("items", [])
        if not items:
            print("⚠️ [PUBLISHER] The Vault is completely empty! No videos to publish.")
            notify_warning("Publisher Bot", "Vault Empty", 1, 1)
            return

        # Restrict to a maximum of 2 videos to match daily production
        videos_to_process = items[:2]
        print(f"🎯 [PUBLISHER] Found {len(items)} videos. Locking targets: {len(videos_to_process)}.")

        published_count = 0

        for index, target_item in enumerate(videos_to_process):
            video_id = target_item["snippet"]["resourceId"]["videoId"]
            playlist_item_id = target_item["id"]
            video_title = target_item["snippet"]["title"]

            print(f"\n==================================================")
            print(f"🚀 SCHEDULING VIDEO {index + 1}: '{video_title}'")
            print(f"==================================================")

            # 2. FETCH EXISTING METADATA
            video_response = youtube.videos().list(part="snippet,status", id=video_id).execute()

            if not video_response.get("items"):
                print(f"❌ [PUBLISHER] Could not fetch video details for ID: {video_id}. Skipping.")
                continue

            video_data = video_response["items"][0]
            snippet = video_data["snippet"]
            
            # AI Metadata Scanner routed video to niche
            target_playlist_name = determine_niche_playlist(snippet)
            
            # 3. SCHEDULE THE VIDEO (Staggered Releases)
            # Video 1: +4 hours (Peak 1), Video 2: +10 hours (Peak 2)
            offset_hours = 4 if index == 0 else 10
            publish_time = (datetime.utcnow() + timedelta(hours=offset_hours))
            
            # YouTube API requires precise ISO formatting with trailing 'Z'
            iso_publish_time = publish_time.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            
            print(f"⏰ [PUBLISHER] Scheduling to go live at: {publish_time.strftime('%Y-%m-%d %H:%M UTC')}")

            youtube.videos().update(
                part="snippet,status",
                body={
                    "id": video_id,
                    "snippet": snippet,  # Preserve the AI SEO exactly as generated
                    "status": {
                        "privacyStatus": "private", # Must remain private until publishAt hits
                        "publishAt": iso_publish_time,
                        "selfDeclaredMadeForKids": False
                    }
                }
            ).execute()
            
            # 4. MOVE VIDEO TO THE DYNAMIC PUBLIC PLAYLIST
            print(f"🚚 [PUBLISHER] Moving out of Vault into '{target_playlist_name}'...")
            try:
                # Remove from Vault
                youtube.playlistItems().delete(id=playlist_item_id).execute()
            except Exception as e:
                print(f"⚠️ [PUBLISHER] Could not delete from vault playlist (Maybe already deleted): {e}")
            
            public_playlist_id = get_playlist_id(youtube, target_playlist_name)
            if not public_playlist_id:
                public_playlist_id = create_playlist(youtube, target_playlist_name, "public")
                
            # Add to Public Niche Playlist
            youtube.playlistItems().insert(
                part="snippet",
                body={
                    "snippet": {
                        "playlistId": public_playlist_id,
                        "resourceId": {"kind": "youtube#video", "videoId": video_id}
                    }
                }
            ).execute()

            published_count += 1
            readable_time = publish_time.strftime("%B %d at %H:%M UTC")
            notify_upload(video_title, f"{readable_time} (Playlist: {target_playlist_name})")
            
            print(f"✅ [PUBLISHER] Video {index + 1} successfully locked and loaded.")

        print(f"\n🎉 [PUBLISHER] Daily deployment complete. Scheduled {published_count} videos.")

    except HttpError as e:
        error_details = json.loads(e.content.decode('utf-8'))
        error_message = error_details.get('error', {}).get('message', str(e))
        print(f"\n❌ [PUBLISHER] YOUTUBE API ERROR: {error_message}")
        notify_error("Publisher API", "YouTube Publisher", error_message)
    except Exception as e:
        print("❌ [PUBLISHER] System Error:")
        quota_manager.diagnose_fatal_error("schedule_video.py", e)
        notify_error("Publisher Bot", "System Error", str(e)[:200])

if __name__ == "__main__":
    publish_vault_videos()
