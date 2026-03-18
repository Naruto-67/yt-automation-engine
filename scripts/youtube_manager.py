# scripts/youtube_manager.py
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

TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true"

def get_youtube_client(channel_config):
    if TEST_MODE: return None
    if isinstance(channel_config, dict):
        token_env = channel_config.get("youtube_refresh_token_env")
    else:
        token_env = getattr(channel_config, "youtube_refresh_token_env", "YOUTUBE_REFRESH_TOKEN_MAIN")

    client_id = os.environ.get(token_env.replace("REFRESH_TOKEN", "CLIENT_ID"))
    client_secret = os.environ.get(token_env.replace("REFRESH_TOKEN", "CLIENT_SECRET"))
    refresh_token = os.environ.get(token_env)

    if not all([client_id, client_secret, refresh_token]):
        print(f"⚠️ [YOUTUBE AUTH] Missing credentials for {token_env}.")
        return None

    try:
        creds = Credentials(None, refresh_token=refresh_token, token_uri="https://oauth2.googleapis.com/token", client_id=client_id, client_secret=client_secret)
        return build('youtube', 'v3', credentials=creds, static_discovery=False)
    except Exception as e:
        trace = traceback.format_exc()
        print(f"⚠️ [YOUTUBE AUTH] Token rejected for {token_env}:\n{trace}")
        return None

def get_channel_name(youtube):
    if not youtube: return "Test_Channel"
    try:
        name = youtube.channels().list(part="snippet", mine=True).execute()["items"][0]["snippet"]["title"]
        quota_manager.consume_points("youtube", 1)
        return name
    except: return "GhostEngine_Channel"

def get_or_create_playlist(youtube, title, privacy_status="private"):
    if not youtube: return "test_playlist_id"
    try:
        playlists = []
        request = youtube.playlists().list(part="snippet", mine=True, maxResults=50)
        seen_tokens = set()

        while request is not None:
            response = request.execute()
            quota_manager.consume_points("youtube", 1)
            playlists.extend(response.get("items", []))
            next_token = response.get("nextPageToken")
            if not next_token or next_token in seen_tokens:
                break
            seen_tokens.add(next_token)
            request = youtube.playlists().list_next(request, response)

        for item in playlists:
            if item["snippet"]["title"].lower() == title.lower(): return item["id"]

        new_playlist = youtube.playlists().insert(part="snippet,status", body={"snippet": {"title": title}, "status": {"privacyStatus": privacy_status}}).execute()
        quota_manager.consume_points("youtube", 50)
        return new_playlist["id"]
    except Exception as e:
        print(f"⚠️ Playlist fetch error: {e}")
        return None

def get_actual_vault_count(youtube):
    if not youtube: return 0
    try:
        playlist_id = get_or_create_playlist(youtube, "Vault Backup")
        if not playlist_id: return 0
        response = youtube.playlists().list(part="contentDetails", id=playlist_id).execute()
        quota_manager.consume_points("youtube", 1)
        return response["items"][0]["contentDetails"]["itemCount"]
    except: return 0

def _get_creator_comment(niche):
    niche_lower = niche.lower() if niche else ""
    if any(k in niche_lower for k in ['storytelling', 'moral', 'pixar', 'anime', 'animation', 'fictional', 'story']):
        return "Which part of the story hit you the hardest? 👇 Subscribe for more stories like this. ✨"
    elif any(k in niche_lower for k in ['fact', 'hack', 'science', 'weird', 'educational', 'education']):
        return "Which fact blew your mind the most? Drop it below and subscribe for more! 🧠✨"
    elif any(k in niche_lower for k in ['horror', 'terror', 'eldritch', 'cosmic horror']):
        return "What cosmic horror keeps YOU up at night? Tell us below! 😱 Subscribe for more existential dread."
    elif any(k in niche_lower for k in ['alien', 'extraterrestrial', 'encounter']):
        return "Do you think we're alone in the universe? Reply with your theory and subscribe! 👽🌌"
    elif any(k in niche_lower for k in ['space', 'stellar', 'cosmic', 'galactic', 'planetary', 'nebula', 'pulsar']):
        return "Which corner of the cosmos should we explore next? Comment below and subscribe! 🚀🌠"
    elif any(k in niche_lower for k in ['dream', 'dimensional', 'quantum', 'simulation']):
        return "Does reality feel stranger after this? Share your thoughts and subscribe for more mind-bending content! 🌀"
    elif any(k in niche_lower for k in ['tech', 'ai', 'automation', 'future']):
        return "How long until AI takes over this job entirely? Let me know below and subscribe! 🤖⚡"
    else:
        return "What should we explore next? Drop your idea below and subscribe for more! 🌟"

def post_creator_comment(youtube, video_id, text):
    if not youtube: return True
    try:
        youtube.commentThreads().insert(part="snippet", body={"snippet": {"videoId": video_id, "topLevelComment": {"snippet": {"textOriginal": text}}}}).execute()
        return True
    except: return False

def upload_to_youtube_vault(youtube, video_path, topic, metadata, niche="", channel_config=None):
    if not youtube: return True, "test_mode_dummy_video_id"
    if shutil.disk_usage("/").free < (500 * 1024 * 1024): return False, None

    # Resolve per-channel monetization metadata — fall back to safe defaults if not provided
    category_id = "22"
    language    = "en"
    if channel_config is not None:
        category_id = getattr(channel_config, "category_id", "22")
        language    = getattr(channel_config, "language",    "en")

    try:
        media = MediaFileUpload(video_path, chunksize=1024*1024*5, resumable=True, mimetype="video/mp4")

        safe_title = (metadata.get("title") or f"{topic} #shorts")[:100]
        safe_desc = metadata.get("description") or ""
        raw_tags = metadata.get("tags") or ["shorts"]

        safe_tags = []
        char_count = 0
        for tag in raw_tags:
            clean_tag = str(tag).replace("<", "").replace(">", "").strip()[:30]
            if char_count + len(clean_tag) < 400 and len(safe_tags) < 15:
                safe_tags.append(clean_tag)
                char_count += len(clean_tag)

        if not safe_tags: safe_tags = ["shorts"]

        request = youtube.videos().insert(
            part="snippet,status",
            body={
                "snippet": {
                    "title":                safe_title,
                    "description":          safe_desc,
                    "tags":                 safe_tags,
                    "categoryId":           category_id,       # per-channel, not hardcoded
                    "defaultLanguage":      language,          # enables correct ad targeting
                    "defaultAudioLanguage": language,
                },
                "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False}
            },
            media_body=media
        )

        response = None
        error_count = 0

        while response is None:
            try:
                status, response = request.next_chunk()
                error_count = 0
            except Exception as net_err:
                if isinstance(net_err, HttpError) and net_err.resp.status == 403 and b"quota" in net_err.content.lower():
                    raise net_err
                error_count += 1
                print(f"⚠️ [VAULT] Network drop during chunk upload (Attempt {error_count}/5): {net_err}")
                if error_count >= 5:
                    raise net_err
                time.sleep(5)

        video_id = response["id"]
        quota_manager.consume_points("youtube", 1600)

        try:
            vault_playlist_id = get_or_create_playlist(youtube, "Vault Backup")
            if vault_playlist_id:
                youtube.playlistItems().insert(part="snippet", body={"snippet": {"playlistId": vault_playlist_id, "resourceId": {"kind": "youtube#video", "videoId": video_id}}}).execute()
                quota_manager.consume_points("youtube", 50)
        except Exception as playlist_err:
            trace = traceback.format_exc()
            print(f"⚠️ [VAULT] Video uploaded, but playlist assignment failed:\n{trace}")
            vault_playlist_id = "Failed to Assign"

        comment_text = _get_creator_comment(niche)
        if post_creator_comment(youtube, video_id, comment_text):
            quota_manager.consume_points("youtube", 50)

        notify_vault_secure(safe_title, video_id, vault_playlist_id)
        return True, video_id

    except Exception as e:
        if isinstance(e, HttpError) and e.resp.status == 403 and b"quota" in e.content.lower():
            raise e
        quota_manager.diagnose_fatal_error("youtube_manager.py", e)
        return False, None
