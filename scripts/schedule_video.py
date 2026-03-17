# scripts/schedule_video.py
# Ghost Engine V26.0.0 — Data-Driven Scheduling & Power-Hour Analysis
import os
import json
import time
import yaml
import random
from datetime import datetime, timedelta, timezone
from scripts.youtube_manager import (
    get_youtube_client, get_or_create_playlist
)
from scripts.quota_manager import quota_manager
from scripts.discord_notifier import (
    set_channel_context, notify_published, notify_summary, notify_error
)
from engine.database import db
from engine.models import JobState
from engine.config_manager import config_manager
from engine.logger import logger

TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true"

def load_config_prompts():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    with open(os.path.join(root_dir, "config", "prompts.yaml"), "r") as f:
        return yaml.safe_load(f)

def analyze_power_hours(youtube) -> list:
    """
    V26 Analytics Feature: Analyzes the last 50 videos to find 
    the actual hours where your channel gets the most views.
    """
    if not youtube: return ["15:00", "20:00"]
    
    try:
        # 1. Fetch channel uploads
        ch_res = youtube.channels().list(part="contentDetails", mine=True).execute()
        uploads_id = ch_res["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        
        vids = youtube.playlistItems().list(part="snippet", playlistId=uploads_id, maxResults=50).execute()
        vid_ids = [v["snippet"]["resourceId"]["videoId"] for v in vids.get("items", [])]
        
        if not vid_ids: return ["10:00", "18:00"]

        # 2. Extract performance data
        stats = youtube.videos().list(part="statistics,snippet", id=",".join(vid_ids)).execute()
        
        hour_map = {} # {hour: total_views}
        for i in stats.get("items", []):
            pub_time = i['snippet']['publishedAt'] # e.g. "2026-03-17T15:30:00Z"
            hour = int(pub_time.split('T')[1].split(':')[0])
            views = int(i["statistics"].get("viewCount", 0))
            
            hour_map[hour] = hour_map.get(hour, 0) + views

        # 3. Identify the Top 2 "Power Hours"
        sorted_hours = sorted(hour_map.items(), key=lambda x: x[1], reverse=True)
        power_hours = [f"{h[0]:02d}:00" for h in sorted_hours[:2]]

        if len(power_hours) < 2: power_hours = ["15:00", "21:00"]
        
        logger.research(f"Analytics Data: Identified Power Hours at {power_hours}")
        return power_hours

    except Exception as e:
        logger.warning(f"Analytics failure: {e}. Falling back to default windows.")
        return ["14:00", "19:00"]

def publish_vault_videos():
    """
    Executes the release of vaulted videos during peak engagement windows.
    """
    if os.environ.get("GHOST_ENGINE_ENABLED", "true").lower() == "false":
        logger.info("🔴 [KILL SWITCH] Publisher halted.")
        return

    settings = config_manager.get_settings()
    publish_limit = settings.get("vault", {}).get("publish_per_run", 2)
    
    # 1. Quota Safety Check
    if not quota_manager.can_afford_youtube(publish_limit * 200):
        logger.error("⚠️ [PUBLISHER] Insufficient YT quota for publishing.")
        return

    published_total = 0

    for channel in config_manager.get_active_channels():
        set_channel_context(channel)
        
        youtube = None if TEST_MODE else get_youtube_client(channel)
        if not youtube and not TEST_MODE: continue

        # 2. Retrieve Vaulted Jobs
        jobs = db.get_jobs_by_state(channel.channel_id, JobState.VAULTED, limit=publish_limit)
        if not jobs:
            logger.info(f"Vault empty for {channel.channel_id}.")
            continue

        # 3. Statistical "Power Hour" Selection
        peak_times = analyze_power_hours(youtube)
        now = datetime.utcnow()

        # Build map of existing vault items to delete them after publishing
        vid_to_item = {}
        if not TEST_MODE:
            v_id = get_or_create_playlist(youtube, "Vault Backup")
            v_items = youtube.playlistItems().list(part="snippet", playlistId=v_id, maxResults=50).execute()
            vid_to_item = {i["snippet"]["resourceId"]["videoId"]: i["id"] for i in v_items.get("items", [])}

        for idx, job in enumerate(jobs):
            vid_id = job.youtube_id
            if not vid_id or vid_id == "test_mode_dummy_video_id": continue

            # Calculate target release
            try:
                hr, mn = map(int, peak_times[idx].split(":"))
            except:
                hr, mn = 18, 0

            target_dt = now.replace(hour=hr, minute=mn, second=0, microsecond=0)
            if target_dt <= now + timedelta(minutes=15):
                target_dt += timedelta(days=1)

            publish_time_str = target_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

            if TEST_MODE:
                job.state = JobState.PUBLISHED
                db.upsert_job(job)
                published_total += 1
                notify_published(job.topic, vid_id, target_dt.strftime("%Y-%m-%d %H:%M"))
                continue

            # 4. Official YouTube API Schedule Update
            try:
                youtube.videos().update(
                    part="status",
                    body={
                        "id": vid_id,
                        "status": {
                            "privacyStatus": "private",
                            "publishAt": publish_time_str,
                            "selfDeclaredMadeForKids": False
                        }
                    }
                ).execute()
                quota_manager.consume_points("youtube", 50)

                # Move to public "All Uploads" playlist
                pub_pl = get_or_create_playlist(youtube, "All Uploads | Viral Shorts", "public")
                if pub_pl:
                    youtube.playlistItems().insert(
                        part="snippet",
                        body={"snippet": {"playlistId": pub_pl, "resourceId": {"kind": "youtube#video", "videoId": vid_id}}}
                    ).execute()
                    quota_manager.consume_points("youtube", 50)

                # Remove from Vault Backup playlist
                if vid_id in vid_to_item:
                    youtube.playlistItems().delete(id=vid_to_item[vid_id]).execute()
                    quota_manager.consume_points("youtube", 50)

                job.state = JobState.PUBLISHED
                db.upsert_job(job)
                published_total += 1
                notify_published(job.topic, vid_id, target_dt.strftime("%Y-%m-%d %H:%M"))

            except Exception as e:
                logger.error(f"Publish failed for {vid_id}: {e}")

    if published_total > 0:
        notify_summary(True, f"🚀 Peak-Engagement Schedule set for **{published_total}** videos.")

if __name__ == "__main__":
    publish_vault_videos()
