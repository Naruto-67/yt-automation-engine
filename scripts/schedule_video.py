# scripts/schedule_video.py
# ═══════════════════════════════════════════════════════════════════════════════
# FIX #2 — Publisher queries DB by channel_id, not mutable display name
#
# BUG: db.get_jobs_by_state(yt_name, JobState.VAULTED) used the live YouTube
# display name to look up jobs. Jobs are stored using channel_id. If the
# channel name changed on YouTube dashboard between runs, the identity-sync
# updated YAML but the publisher fetched 0 jobs and silently skipped publishing.
#
# FIX: Use channel.channel_id (stable) for all DB queries. The display name
# is only used for watermark text and Discord notifications.
#
# FIX #8 (PARTIAL) — Kill switch also applied here as a Python-level guard.
# The GHA workflow already has `if: vars.GHOST_ENGINE_ENABLED != 'false'` at
# the job level, but this defence-in-depth check ensures the script is safe
# if ever called directly outside of GitHub Actions.
# ═══════════════════════════════════════════════════════════════════════════════

import os
import json
import time
import yaml
import sys
from datetime import datetime, timedelta
from scripts.youtube_manager import get_youtube_client, get_or_create_playlist, get_channel_name
from scripts.quota_manager import quota_manager
from scripts.discord_notifier import notify_summary, notify_error
from engine.database import db
from engine.models import JobState
from engine.config_manager import config_manager


# ── Kill switch (Fix #8 defence-in-depth) ────────────────────────────────────
_ENABLED = os.environ.get("GHOST_ENGINE_ENABLED", "true").strip().lower()
if _ENABLED == "false":
    print("🔴 [KILL SWITCH] GHOST_ENGINE_ENABLED=false. Publisher halted.")
    try:
        notify_summary(False, "**Kill Switch Active** — Publisher halted.")
    except Exception:
        pass
    sys.exit(0)


def load_config_prompts():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    with open(os.path.join(root_dir, "config", "prompts.yaml"), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_historical_time_data(youtube):
    try:
        uploads_id = youtube.channels().list(
            part="contentDetails", mine=True
        ).execute()["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

        vids = youtube.playlistItems().list(
            part="snippet", playlistId=uploads_id, maxResults=15
        ).execute()

        vid_ids = [v["snippet"]["resourceId"]["videoId"] for v in vids.get("items", [])]
        if not vid_ids:
            return "No historical data available."

        stats = youtube.videos().list(
            part="statistics,snippet", id=",".join(vid_ids)
        ).execute()

        valid = [
            f"- {i['snippet']['publishedAt']}: {i['statistics'].get('viewCount', '0')} views"
            for i in stats.get("items", [])
            if int(i["statistics"].get("viewCount", "0")) > 0
        ]
        return "📊 DATA:\n" + "\n".join(valid) if valid else "No data with views yet."
    except Exception:
        return "No data."


def get_optimal_publish_times(youtube, prompts_cfg):
    sys_msg  = prompts_cfg["scheduler"]["system_prompt"]
    user_msg = prompts_cfg["scheduler"]["user_template"].format(
        historical_data=get_historical_time_data(youtube)
    )
    response, _ = quota_manager.generate_text(user_msg, task_type="analysis", system_prompt=sys_msg)
    try:
        import re
        match = re.search(
            r"\[.*\]",
            response.replace("```json", "").replace("```", "").strip(),
            re.DOTALL,
        )
        if match:
            return json.loads(match.group(0))
    except Exception:
        pass
    return ["15:00", "23:00"]


def publish_vault_videos():
    if not quota_manager.can_afford_youtube(600):
        print("⚠️ [PUBLISHER] Insufficient YouTube quota. Aborting.")
        return

    prompts_cfg   = load_config_prompts()
    published_total = 0

    for channel in config_manager.get_active_channels():
        youtube = get_youtube_client(channel.youtube_refresh_token_env)
        if not youtube:
            print(f"⚠️ [PUBLISHER] Auth failed for {channel.channel_id}. Skipping.")
            continue

        # ── FIX #2: Always use stable channel_id for DB queries ──────────────
        # Previously used yt_name (the live YouTube display name) which breaks
        # when the name changes between the pipeline run and publisher run.
        jobs = db.get_jobs_by_state(channel.channel_id, JobState.VAULTED, limit=2)
        # ─────────────────────────────────────────────────────────────────────

        if not jobs:
            print(f"ℹ️ [PUBLISHER] No vaulted jobs for {channel.channel_id}.")
            continue

        vault_id = get_or_create_playlist(youtube, "Vault Backup")
        if not vault_id:
            print(f"⚠️ [PUBLISHER] Could not get vault playlist for {channel.channel_id}.")
            continue

        vault_items = youtube.playlistItems().list(
            part="snippet", playlistId=vault_id, maxResults=50
        ).execute()
        vid_to_item = {
            i["snippet"]["resourceId"]["videoId"]: i["id"]
            for i in vault_items.get("items", [])
        }

        ai_times = get_optimal_publish_times(youtube, prompts_cfg)
        now = datetime.utcnow()

        for idx, job in enumerate(jobs):
            vid_id = job.youtube_id
            if not vid_id or vid_id == "test_mode_dummy_id":
                continue

            if not quota_manager.can_afford_youtube(300):
                print("⚠️ [PUBLISHER] Quota low — stopping mid-batch.")
                break

            # Determine scheduled time
            try:
                hr, mn = map(int, ai_times[idx].split(":")) if idx < len(ai_times) else ((15 + idx * 8) % 24, 0)
            except (ValueError, IndexError):
                hr, mn = (15 + idx * 8) % 24, 0

            target_dt = now.replace(hour=hr, minute=mn, second=0, microsecond=0)
            if target_dt <= now + timedelta(minutes=15):
                target_dt += timedelta(days=1)

            try:
                # Schedule video for public release at target_dt
                youtube.videos().update(
                    part="status",
                    body={
                        "id": vid_id,
                        "status": {
                            "privacyStatus":         "private",
                            "publishAt":             target_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                            "selfDeclaredMadeForKids": False,
                        },
                    },
                ).execute()
                quota_manager.consume_points("youtube", 50)

                # Add to public playlist
                pub_pl = get_or_create_playlist(youtube, "All Uploads | Viral Shorts", "public")
                if pub_pl:
                    youtube.playlistItems().insert(
                        part="snippet",
                        body={"snippet": {
                            "playlistId":  pub_pl,
                            "resourceId":  {"kind": "youtube#video", "videoId": vid_id},
                        }},
                    ).execute()
                    quota_manager.consume_points("youtube", 50)

                # Remove from vault playlist
                if vid_id in vid_to_item:
                    youtube.playlistItems().delete(id=vid_to_item[vid_id]).execute()
                    quota_manager.consume_points("youtube", 50)

                # ── FIX #2: Update DB using channel_id ────────────────────
                job.state      = JobState.PUBLISHED
                job.updated_at = datetime.utcnow().isoformat()
                db.upsert_job(job)
                # ──────────────────────────────────────────────────────────

                published_total += 1
                print(f"✅ [PUBLISHER] Scheduled {vid_id} at {target_dt.strftime('%Y-%m-%d %H:%M UTC')}")

            except Exception as e:
                error_str = str(e)
                if "404" in error_str:
                    print(f"⚠️ [PUBLISHER] Video {vid_id} not found on YouTube (deleted?). Marking FAILED.")
                    job.state = JobState.FAILED
                    db.upsert_job(job)
                else:
                    notify_error("Publisher", "Publish Error", error_str)

    if published_total > 0:
        notify_summary(True, f"🚀 Scheduled {published_total} video(s) for public release.")
    else:
        print("ℹ️ [PUBLISHER] No videos published this run.")


if __name__ == "__main__":
    publish_vault_videos()
