# scripts/schedule_video.py — Ghost Engine V20.0
import os
import json
import time
import yaml
from datetime import datetime, timedelta
from scripts.youtube_manager import (
    get_youtube_client, get_or_create_playlist, get_channel_name
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

def get_historical_time_data(youtube) -> str:
    if not youtube:
        return "No data."
    try:
        uploads_id = youtube.channels().list(
            part="contentDetails", mine=True
        ).execute()["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        quota_manager.consume_points("youtube", 1)

        vids = youtube.playlistItems().list(
            part="snippet", playlistId=uploads_id, maxResults=50
        ).execute()
        quota_manager.consume_points("youtube", 1)

        vid_ids = [v["snippet"]["resourceId"]["videoId"]
                   for v in vids.get("items", [])]
        if not vid_ids:
            return "No data."

        stats = youtube.videos().list(
            part="statistics,snippet,status", id=",".join(vid_ids)
        ).execute()
        quota_manager.consume_points("youtube", 1)

        rows = []
        for i in stats.get("items", []):
            if i.get("status", {}).get("privacyStatus") == "private":
                continue
            if int(i["statistics"].get("viewCount", "0")) > 0:
                rows.append(f"- {i['snippet']['publishedAt']}: {i['statistics'].get('viewCount', '0')} views")
                
        return "📊 DATA:\n" + "\n".join(rows[:15]) if rows else "No data."
    except Exception:
        return "No data."

def get_optimal_publish_times(youtube, prompts_cfg) -> list:
    sys_msg  = prompts_cfg["scheduler"]["system_prompt"]
    user_msg = prompts_cfg["scheduler"]["user_template"].format(
        historical_data=get_historical_time_data(youtube)
    )
    response, _ = quota_manager.generate_text(user_msg, task_type="analysis",
                                               system_prompt=sys_msg)
    try:
        if response:
            start = response.find('[')
            end = response.rfind(']')
            if start != -1 and end != -1 and end > start:
                times = json.loads(response[start:end+1])
                if isinstance(times, list) and len(times) >= 1:
                    return times[:2]
    except Exception:
        pass
    return ["15:00", "23:00"]

def publish_vault_videos():
    if os.environ.get("GHOST_ENGINE_ENABLED", "true").lower() == "false":
        print("🔴 [KILL SWITCH] Publisher halted.")
        return

    settings      = config_manager.get_settings()
    publish_limit = settings.get("vault", {}).get("publish_per_run", 2)
    publish_cost  = publish_limit * 150  
    
    if not quota_manager.can_afford_youtube(publish_cost + 10):
        print("⚠️ [PUBLISHER] Insufficient YT quota for publishing. Skipping.")
        return

    prompts_cfg    = load_config_prompts()
    published_total = 0

    for channel in config_manager.get_active_channels():
        set_channel_context(channel)
        
        youtube = None if TEST_MODE else get_youtube_client(channel)
        if not youtube and not TEST_MODE:
            continue

        jobs = db.get_jobs_by_state(channel.channel_id, JobState.VAULTED, limit=publish_limit)
        if not jobs:
            logger.engine(f"No vaulted videos for {channel.channel_id}.")
            continue

        if TEST_MODE:
            vid_to_item = {}
        else:
            vault_id = get_or_create_playlist(youtube, "Vault Backup")
            if not vault_id:
                continue

            vault_items = youtube.playlistItems().list(
                part="snippet", playlistId=vault_id, maxResults=50
            ).execute()
            quota_manager.consume_points("youtube", 1)
            vid_to_item = {
                i["snippet"]["resourceId"]["videoId"]: i["id"]
                for i in vault_items.get("items", [])
            }

        ai_times = get_optimal_publish_times(youtube, prompts_cfg)
        now      = datetime.utcnow()

        for idx, job in enumerate(jobs):
            vid_id = job.youtube_id

            if not vid_id or vid_id in ["test_mode_dummy_id", "test_mode_dummy_video_id"]:
                if not TEST_MODE:
                    logger.error(f"Job {job.id} has no valid youtube_id. Marking FAILED.")
                    job.state = JobState.FAILED
                    db.upsert_job(job)
                    continue

            try:
                hr, mn = map(int, ai_times[idx].split(":"))
            except (IndexError, ValueError):
                hr, mn = (15 + idx * 8) % 24, 0

            target_dt = now.replace(hour=hr, minute=mn, second=0, microsecond=0)
            
            if target_dt <= now + timedelta(minutes=30):
                target_dt += timedelta(days=1)
            publish_time_str = target_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

            if TEST_MODE:
                job.state      = JobState.PUBLISHED
                job.updated_at = datetime.utcnow().isoformat()
                db.upsert_job(job)
                published_total += 1
                notify_published(job.topic, vid_id or "test_mode_dummy", target_dt.strftime("%Y-%m-%d %H:%M"))
                continue

            if not quota_manager.can_afford_youtube(150):
                logger.error("YT quota insufficient for publish. Stopping.")
                break

            try:
                youtube.videos().update(
                    part="status",
                    body={
                        "id":     vid_id,
                        "status": {
                            "privacyStatus":            "private",
                            "publishAt":                publish_time_str,
                            "selfDeclaredMadeForKids":  False
                        }
                    }
                ).execute()
                quota_manager.consume_points("youtube", 50)

                pub_pl = get_or_create_playlist(youtube, "All Uploads | Viral Shorts", "public")
                if pub_pl:
                    youtube.playlistItems().insert(
                        part="snippet",
                        body={"snippet": {
                            "playlistId": pub_pl,
                            "resourceId": {"kind": "youtube#video", "videoId": vid_id}
                        }}
                    ).execute()
                    quota_manager.consume_points("youtube", 50)

                if vid_id in vid_to_item:
                    youtube.playlistItems().delete(id=vid_to_item[vid_id]).execute()
                    quota_manager.consume_points("youtube", 50)

                job.state      = JobState.PUBLISHED
                job.updated_at = datetime.utcnow().isoformat()
                db.upsert_job(job)
                published_total += 1

                notify_published(job.topic, vid_id, target_dt.strftime("%Y-%m-%d %H:%M"))

            except Exception as e:
                err_str = str(e)
                if "404" in err_str:
                    logger.error(f"Video {vid_id} not found on YouTube (404). Marking FAILED.")
                    job.state = JobState.FAILED
                    db.upsert_job(job)
                else:
                    notify_error("Publisher", "PublishError", err_str)
        time.sleep(2)

    if published_total > 0:
        notify_summary(True, f"🚀 Scheduled **{published_total}** video(s) for release.")
    else:
        notify_summary(True, "└ No videos published this run — vault may be empty.")

if __name__ == "__main__":
    publish_vault_videos()
