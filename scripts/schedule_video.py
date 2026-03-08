import os
import json
import time
import yaml
from datetime import datetime, timedelta
from scripts.youtube_manager import get_youtube_client, get_or_create_playlist, get_channel_name
from scripts.quota_manager import quota_manager
from scripts.discord_notifier import notify_summary, notify_error
from engine.database import db
from engine.models import JobState
from engine.config_manager import config_manager

def load_config_prompts():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    with open(os.path.join(root_dir, "config", "prompts.yaml"), "r", encoding="utf-8") as f: return yaml.safe_load(f)

def get_historical_time_data(youtube):
    try:
        uploads_id = youtube.channels().list(part="contentDetails", mine=True).execute()["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        vids = youtube.playlistItems().list(part="snippet", playlistId=uploads_id, maxResults=15).execute()
        vid_ids = [v["snippet"]["resourceId"]["videoId"] for v in vids.get("items", [])]
        if not vid_ids: return "No data."
        stats = youtube.videos().list(part="statistics,snippet", id=",".join(vid_ids)).execute()
        valid = [f"- {i['snippet']['publishedAt']}: {i['statistics'].get('viewCount', '0')} views" for i in stats.get("items", []) if int(i['statistics'].get('viewCount', '0')) > 0]
        return "📊 DATA:\n" + "\n".join(valid) if valid else "No data."
    except: return "No data."

def get_optimal_publish_times(youtube, prompts_cfg):
    sys_msg = prompts_cfg['scheduler']['system_prompt']
    user_msg = prompts_cfg['scheduler']['user_template'].format(historical_data=get_historical_time_data(youtube))
    
    response, _ = quota_manager.generate_text(user_msg, task_type="analysis", system_prompt=sys_msg)
    try:
        import re
        match = re.search(r'\[.*\]', response.replace("```json", "").replace("```", "").strip(), re.DOTALL)
        if match: return json.loads(match.group(0))
    except: pass
    return ["15:00", "23:00"]

def publish_vault_videos():
    if not quota_manager.can_afford_youtube(600): return
    prompts_cfg = load_config_prompts()
    published_total = 0

    for channel in config_manager.get_active_channels():
        youtube = get_youtube_client(channel.youtube_refresh_token_env)
        if not youtube: continue

        yt_name = get_channel_name(youtube).replace("@", "") if os.environ.get("TEST_MODE", "False") == "False" else channel.channel_name
        jobs = db.get_jobs_by_state(yt_name, JobState.VAULTED, limit=2)
        if not jobs: continue

        vault_id = get_or_create_playlist(youtube, "Vault Backup")
        if not vault_id: continue

        vault_items = youtube.playlistItems().list(part="snippet", playlistId=vault_id, maxResults=50).execute()
        vid_to_item = {i["snippet"]["resourceId"]["videoId"]: i["id"] for i in vault_items.get("items", [])}
        
        ai_times = get_optimal_publish_times(youtube, prompts_cfg)
        now = datetime.utcnow()

        for idx, job in enumerate(jobs):
            vid_id = job.youtube_id
            if not vid_id or vid_id == "test_mode_dummy_id": continue

            hr, mn = map(int, ai_times[idx].split(':')) if idx < len(ai_times) else ((15 + idx * 8) % 24, 0)
            target_dt = now.replace(hour=hr, minute=mn, second=0, microsecond=0)
            if target_dt <= now + timedelta(minutes=15): target_dt += timedelta(days=1)

            try:
                youtube.videos().update(part="status", body={"id": vid_id, "status": {"privacyStatus": "private", "publishAt": target_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "selfDeclaredMadeForKids": False}}).execute()
                
                # Assign to public playlist
                pub_pl = get_or_create_playlist(youtube, "All Uploads | Viral Shorts", "public")
                if pub_pl: youtube.playlistItems().insert(part="snippet", body={"snippet": {"playlistId": pub_pl, "resourceId": {"kind": "youtube#video", "videoId": vid_id}}}).execute()

                # Clean from Vault
                if vid_id in vid_to_item: youtube.playlistItems().delete(id=vid_to_item[vid_id]).execute()

                job.state = JobState.PUBLISHED
                job.updated_at = datetime.utcnow().isoformat()
                db.upsert_job(job)
                published_total += 1
            except Exception as e:
                if "404" in str(e):
                    job.state = JobState.FAILED
                    db.upsert_job(job)

    if published_total > 0: notify_summary(True, f"🚀 Scheduled {published_total} videos.")

if __name__ == "__main__": publish_vault_videos()
