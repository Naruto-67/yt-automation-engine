# scripts/youtube_manager.py — Ghost Engine V6
import os
import shutil
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# Lazy imports to avoid circular dependency
def _quota_manager():
    from scripts.quota_manager import quota_manager
    return quota_manager

def _notify_error(module, etype, msg):
    try:
        from scripts.discord_notifier import notify_error
        notify_error(module, etype, msg)
    except Exception:
        print(f"🚨 [NOTIFY] {module} | {etype}: {msg}")


def get_youtube_client(channel_config):
    """
    Build a YouTube API client for the given channel.

    Accepts either:
      - A ChannelConfig object (preferred — uses per-channel credentials)
      - A string (legacy: env var name for the refresh token — uses shared client creds)

    Per-channel GCP project = separate 10,000pt/day quota per channel.
    """
    from engine.models import ChannelConfig

    if isinstance(channel_config, ChannelConfig):
        client_id     = os.environ.get(channel_config.youtube_client_id_env)
        client_secret = os.environ.get(channel_config.youtube_client_secret_env)
        refresh_token = os.environ.get(channel_config.youtube_refresh_token_env)
        label         = channel_config.channel_id
    else:
        # Legacy string path — uses shared YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET
        client_id     = os.environ.get("YOUTUBE_CLIENT_ID")
        client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
        refresh_token = os.environ.get(str(channel_config))
        label         = str(channel_config)

    if not all([client_id, client_secret, refresh_token]):
        missing = [k for k, v in [
            ("client_id", client_id), ("client_secret", client_secret),
            ("refresh_token", refresh_token)
        ] if not v]
        print(f"⚠️ [YT AUTH] Missing credentials for {label}: {missing}")
        return None

    try:
        creds = Credentials(
            None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret
        )
        return build("youtube", "v3", credentials=creds, static_discovery=False)
    except Exception as e:
        _notify_error("YouTube Auth", "Auth Failure", f"{label}: {e}")
        return None


def get_channel_name(youtube) -> str:
    try:
        res = _quota_manager().consume_youtube_and_call(
            lambda: youtube.channels().list(part="snippet", mine=True).execute(),
            cost=1
        )
        return res["items"][0]["snippet"]["title"]
    except Exception:
        return ""


def get_or_create_playlist(youtube, title: str, privacy: str = "private") -> str:
    try:
        res = _quota_manager().consume_youtube_and_call(
            lambda: youtube.playlists().list(part="snippet", mine=True, maxResults=50).execute(),
            cost=1
        )
        for item in res.get("items", []):
            if item["snippet"]["title"].lower() == title.lower():
                return item["id"]

        new_pl = _quota_manager().consume_youtube_and_call(
            lambda: youtube.playlists().insert(
                part="snippet,status",
                body={
                    "snippet": {"title": title},
                    "status": {"privacyStatus": privacy}
                }
            ).execute(),
            cost=50
        )
        return new_pl["id"]
    except Exception:
        return None


def get_actual_vault_count(youtube) -> int:
    v_id = get_or_create_playlist(youtube, "Vault Backup")
    if not v_id:
        return 0
    try:
        res = _quota_manager().consume_youtube_and_call(
            lambda: youtube.playlists().list(part="contentDetails", id=v_id).execute(),
            cost=1
        )
        return res["items"][0]["contentDetails"]["itemCount"]
    except Exception:
        return 0


def upload_to_youtube_vault(youtube, video_path: str, topic: str,
                             metadata: dict, niche: str):
    """
    Uploads rendered MP4 to YouTube as private, adds to Vault Backup playlist.
    Returns (success: bool, video_id: str | None)
    """
    # Pre-flight: ensure enough disk space (500 MB minimum for upload buffer)
    try:
        if shutil.disk_usage("/").free < (500 * 1024 * 1024):
            print("❌ [UPLOAD] Insufficient disk space for upload buffer.")
            return False, None
    except Exception:
        pass

    qm = _quota_manager()

    # Abort early if we can't afford the upload (1600pts + 50pts playlist)
    if not qm.can_afford_youtube(1650):
        print("❌ [UPLOAD] Quota insufficient for upload. Skipping.")
        return False, None

    try:
        media = MediaFileUpload(
            video_path,
            chunksize=1024 * 1024 * 5,
            resumable=True,
            mimetype="video/mp4"
        )
        request = youtube.videos().insert(
            part="snippet,status",
            body={
                "snippet": {
                    "title":       metadata.get("title", f"{topic} #shorts")[:100],
                    "description": metadata.get("description", "")[:4900],
                    "tags":        metadata.get("tags", ["shorts"])[:15],
                    "categoryId":  "22"
                },
                "status": {
                    "privacyStatus":          "private",
                    "selfDeclaredMadeForKids": False
                }
            },
            media_body=media
        )

        response = None
        while response is None:
            _, response = request.next_chunk()

        video_id = response["id"]
        qm.consume_points("youtube", 1600)

        vault_id = get_or_create_playlist(youtube, "Vault Backup")
        if vault_id:
            youtube.playlistItems().insert(
                part="snippet",
                body={"snippet": {
                    "playlistId": vault_id,
                    "resourceId": {"kind": "youtube#video", "videoId": video_id}
                }}
            ).execute()
            qm.consume_points("youtube", 50)

        print(f"✅ [UPLOAD] Vaulted successfully. Video ID: {video_id}")
        return True, video_id

    except Exception as e:
        qm.diagnose_fatal_error("YouTube Upload", e)
        return False, None
