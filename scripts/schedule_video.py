# scripts/schedule_video.py
import os
import json
import time
import yaml
import random
from datetime import datetime, timedelta, timezone
from scripts.youtube_manager import (
    get_authenticated_service, get_or_create_playlist
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

def analyze_power_hours(youtube) -> list:
    if not youtube: return ["15:00", "20:00"]
    try:
        ch_res = youtube.channels().list(part="contentDetails", mine=True).execute()
        uploads_id = ch_res["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        vids = youtube.playlistItems().list(part="snippet", playlistId=uploads_id, maxResults=50).execute()
        vid_ids = [v["snippet"]["resourceId"]["videoId"] for v in vids.get("items", [])]
        if not vid_ids: return ["10:00", "18:00"]
        stats = youtube.videos().list(part="statistics,snippet", id=",".join(vid_ids)).execute()
        hour_map = {}
        for i in stats.get("items", []):
            pub_time = i['snippet']['publishedAt']
            hour = int(pub_time.split('T')[1].split(':')[0])
            views = int(i["statistics"].get("viewCount", 0))
            hour_map[hour] = hour_map.get(hour, 0) + views
        sorted_hours = sorted(hour_map.items(), key=lambda x: x[1], reverse=True)
        power_hours = [f"{h[0]:02d}:00" for h in sorted_hours[:2]]
        if len(power_hours) < 2: power_hours = ["15:00", "21:00"]
        logger.research(f"Analytics Data: Identified Power Hours at {power_hours}")
        return power_hours
    except Exception as e:
        logger.warning(f"Analytics failure: {e}")
        return ["14:00", "19:00"]

def publish_vault_videos():
    if os.environ.get("GHOST_ENGINE_ENABLED", "true").lower() == "false": return
    settings = config_manager.get_settings()
    publish_limit = settings.get("vault", {}).get("publish_per_run", 2)
    published_total = 0
    for channel in config_manager.get_active_channels():
        set_channel_context(channel)
        youtube = None if TEST_MODE else get_authenticated_service(channel.channel_id)
        jobs = db.get_jobs_by_state(channel.channel_id, JobState.VAULTED, limit=publish_limit)
        if not jobs: continue
        peak_times = analyze_power_hours(youtube)
        now = datetime.now(timezone.utc)
        for idx, job in enumerate(jobs):
            vid_id = job.youtube_id
            if not vid_id: continue
            try:
                hr, mn = map(int, peak_times[idx].split(":"))
            except:
                hr, mn = 18, 0
            target_dt = now.replace(hour=hr, minute=mn, second=0, microsecond=0)
            if target_dt <= now + timedelta(minutes=15):
                target_dt += timedelta(days=1)
            publish_time_str = target_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            if not TEST_MODE:
                youtube.videos().update(
                    part="status",
                    body={"id": vid_id, "status": {"privacyStatus": "public", "publishAt": publish_time_str}}
                ).execute()
                quota_manager.consume_points("youtube", 50)
            job.state = JobState.PUBLISHED
            db.upsert_job(job)
            published_total += 1
            notify_published(job.topic, vid_id, target_dt.strftime("%Y-%m-%d %H:%M"))
