# scripts/youtube_manager.py — Ghost Engine V9.0
import os
import shutil
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

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
    from engine.models import ChannelConfig

    if isinstance(channel_config, ChannelConfig):
        client_id     = os.environ.get(channel_config.youtube_client_id_env)
        client_secret = os.environ.get(channel_config.youtube_client_secret_env)
        refresh_token = os.environ.get(channel_config.youtube_refresh_token_env)
        label         = channel_config.channel_id
    else:
        client_id     = os.environ.get("YOUTUBE_CLIENT_ID")
        client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
        refresh_token = os.environ.get(str(channel_config))
        label         = str(channel_config)

    if not all([client_id, client_secret, refresh_token]):
        missing = [k for k, v in [
            ("client_id", client_id),
            ("client_secret", client_secret),
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
        client = build("youtube", "v3", credentials=creds, static_discovery=False)
        
        # GOD-TIER FIX: Pre-flight active validation ping. 
        # Fails fast if token is revoked or quota is already busted, 
        # saving thousands of AI quota points from being wasted on a doomed render.
        try:
            _quota_manager().consume_youtube_and_call(
                lambda: client.channels().list(part="id", mine=True).execute(),
                cost=1
            )
        except Exception as ping_err:
            err_str = str(ping_err).lower()
            if "quota" in err_str or "403" in err_str:
                _notify_error("YouTube Validation", "Quota Exceeded", f"Channel {label} hit 403 Quota limit during validation ping.")
            else:
                _notify_error("YouTube Validation", "Auth Revoked/Expired", f"Channel {label} token invalid: {ping_err}")
            return None
            
        return client

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

def get_actual_vault_count(youtube) -> int:
    v_id = get_or_create_playlist(youtube, "Vault Backup")
    if not v_id: return 0
    try:
        res = _quota_manager().consume_youtube_and_call(
            lambda: youtube.playlistItems().list(part="id", playlistId=v_id, maxResults=50).execute(),
            cost=1
        )
        return len(res.get("items", []))
    except Exception:
        return 0

def get_or_create_playlist(youtube, title: str, privacy: str = "private"):
    try:
        res = _quota_manager().consume_youtube_and_call(
            lambda: youtube.playlists().list(part="snippet", mine=True, maxResults=50).execute(),
            cost=1
        )
        for item in res.get("items", []):
            if item["snippet"]["title"].lower() == title.lower():
                return item["id"]

        create_res = youtube.playlists().insert(
            part="snippet,status",
            body={
                "snippet": {"title": title},
                "status": {"privacyStatus": privacy}
            }
        ).execute()
        _quota_manager().consume_points("youtube", 50)
        return create_res["id"]
    except Exception as e:
        print(f"⚠️ [PLAYLIST] Could not get/create '{title}': {e}")
        return None

def upload_to_youtube_vault(youtube, video_path: str, topic: str, metadata: dict, niche: str):
    try:
        if not os.path.exists(video_path):
            print(f"❌ [UPLOAD] File not found: {video_path}")
            return False, "File not found on disk"

        free_bytes = shutil.disk_usage("/").free
        if free_bytes < (500 * 1024 * 1024):
            print("❌ [UPLOAD] Insufficient disk space for upload buffer.")
            return False, "Insufficient disk space"
    except Exception:
        pass

    qm = _quota_manager()
    
    if not qm.can_afford_youtube(1650):
        print("❌ [UPLOAD] Quota insufficient for upload. Skipping.")
        return False, "403 Quota Exceeded (Internal Engine Estimate)"

    try:
        media = MediaFileUpload(
            video_path, chunksize=1024 * 1024 * 5, resumable=True, mimetype="video/mp4"
        )

        request = youtube.videos().insert(
            part="snippet,status",
            body={
                "snippet": {
                    "title": metadata.get("title", f"{topic} #shorts")[:100],
                    "description": metadata.get("description", "")[:4900],
                    "tags": metadata.get("tags", ["shorts"])[:15],
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
            _, response = request.next_chunk()

        video_id = response["id"]
        qm.consume_points("youtube", 1600)

        try:
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
        except Exception as pl_error:
            print(f"⚠️ [UPLOAD] Playlist insertion failed, but video was successfully uploaded: {pl_error}")

        print(f"✅ [UPLOAD] Vaulted successfully. Video ID: {video_id}")
        return True, video_id

    except Exception as e:
        qm.diagnose_fatal_error("YouTube Upload", e)
        return False, str(e)
