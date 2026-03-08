# scripts/schedule_video.py
import os
import json
import time
from datetime import datetime, timedelta
from scripts.youtube_manager import get_youtube_client, get_or_create_playlist, get_channel_name
from scripts.quota_manager import quota_manager
from scripts.discord_notifier import notify_summary, notify_error
from engine.database import db
from engine.models import JobState
from engine.config_manager import config_manager


def get_historical_time_data(youtube):
    try:
        uploads_id = youtube.channels().list(part="contentDetails", mine=True).execute()["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        quota_manager.consume_points("youtube", 1)

        vids = youtube.playlistItems().list(part="snippet", playlistId=uploads_id, maxResults=15).execute()
        quota_manager.consume_points("youtube", 1)

        vid_ids = [v["snippet"]["resourceId"]["videoId"] for v in vids.get("items", [])]
        if not vid_ids: return "No historical data yet."

        stats_response = youtube.videos().list(part="statistics,snippet", id=",".join(vid_ids)).execute()
        quota_manager.consume_points("youtube", 1)

        valid_history = []
        for item in stats_response.get("items", []):
            views = int(item["statistics"].get("viewCount", "0"))
            if views > 0:
                pub_time = item["snippet"]["publishedAt"]
                valid_history.append(f"- Posted at: {pub_time} (UTC) | Views: {views}")

        if not valid_history:
            return "No public historical data available yet."

        return "📊 HISTORICAL PUBLISH TIMES VS. VIEWS:\n" + "\n".join(valid_history)
    except Exception as e:
        return "No historical data available."


def get_optimal_publish_times(youtube):
    print("🧠 [PUBLISHER] Asking Data Scientist for optimal retention times...")
    historical_data = get_historical_time_data(youtube)

    prompt = f"""
    You are an Elite YouTube Data Scientist. Your goal is to determine the two absolute best times to publish YouTube Shorts today to maximize the initial algorithmic feed spike.
    TARGET AUDIENCE: Primarily United States (US), but rely on the actual data below if a clear trend exists.

    {historical_data}

    INSTRUCTIONS:
    1. Cross-reference the historical upload times with their view counts.
    2. Identify which time windows generate the highest viewership.
    3. If there is no clear trend or data is missing, default to optimal US peak algorithmic times for Shorts.
    4. Output EXACTLY TWO times in UTC format (HH:MM).

    Return ONLY a valid JSON array of two time strings. Do not use markdown or explain your reasoning.
    Example: ["14:30", "22:00"]
    """

    response, _ = quota_manager.generate_text(prompt, task_type="analysis")
    try:
        import re
        match = re.search(r'\[.*\]', response.replace("```json", "").replace("```", "").strip(), re.DOTALL)
        if match: return json.loads(match.group(0))
    except: pass
    return ["15:00", "23:00"]


def publish_vault_videos():
    if not quota_manager.can_afford_youtube(600):
        print("🛑 [QUOTA GUARDIAN] YouTube Quota too low to safely publish. Aborting to prevent API ban.")
        return

    channels = config_manager.get_active_channels()
    published_total = 0

    for channel in channels:
        print(f"🚀 [PUBLISHER] Initiating publish cycle for {channel.channel_name}...")
        youtube = get_youtube_client(channel.youtube_refresh_token_env)
        if not youtube:
            continue

        # Map channel name strictly to match what the Orchestrator saves in the DB
        yt_channel_display_name = get_channel_name(youtube).replace("@", "") if os.environ.get("TEST_MODE", "False") == "False" else channel.channel_name

        jobs = db.get_jobs_by_state(yt_channel_display_name, JobState.VAULTED, limit=2)
        
        if not jobs:
            print(f"⚠️ [PUBLISHER] No vaulted jobs found in database for {channel.channel_name}.")
            continue

        vault_id = get_or_create_playlist(youtube, "Vault Backup")
        if not vault_id:
            print(f"⚠️ [PUBLISHER] Failed to retrieve Vault Backup playlist for {channel.channel_name}.")
            continue

        # Fetch items from YouTube Vault to map videoId to playlistItemId for deletion
        vault_items_req = youtube.playlistItems().list(part="snippet", playlistId=vault_id, maxResults=50).execute()
        quota_manager.consume_points("youtube", 1)
        
        vid_to_playlist_item = {}
        for item in vault_items_req.get("items", []):
            v_id = item["snippet"]["resourceId"]["videoId"]
            vid_to_playlist_item[v_id] = item["id"]

        ai_times = get_optimal_publish_times(youtube)
        now = datetime.utcnow()

        playlist_cache = {"Vault Backup": vault_id}
        def get_cached_playlist(name, privacy="public"):
            if name not in playlist_cache:
                playlist_cache[name] = get_or_create_playlist(youtube, name, privacy)
            return playlist_cache[name]

        # Pre-warm primary playlist
        get_cached_playlist("All Uploads | Viral Shorts", "public")

        for idx, job in enumerate(jobs):
            vid_id = job.youtube_id
            if not vid_id or vid_id == "test_mode_dummy_id":
                print(f"⚠️ [PUBLISHER] Skipping Job {job.id} - Invalid or Test Video ID.")
                continue

            is_fact_based = any(k in job.niche.lower() for k in ['fact', 'hack', 'trend', 'brainrot'])
            primary_playlist_name = "All Uploads | Viral Shorts"
            secondary_playlist_name = "Mind-Blowing Facts" if is_fact_based else "Immersive AI Stories"

            target_time_str = ai_times[idx] if idx < len(ai_times) else "15:00"
            try:
                hr_str, mn_str = target_time_str.split(':')
                hr = int(hr_str) % 24
                mn = int(mn_str) % 60
            except:
                hr, mn = (15 + (idx * 8)) % 24, 0

            target_dt = now.replace(hour=hr, minute=mn, second=0, microsecond=0)
            if target_dt <= now + timedelta(minutes=15):
                target_dt += timedelta(days=1)
            pub_time = target_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

            try:
                youtube.videos().update(
                    part="status",
                    body={
                        "id": vid_id,
                        "status": {
                            "privacyStatus": "private",
                            "publishAt": pub_time,
                            "selfDeclaredMadeForKids": False
                        }
                    }
                ).execute()
                quota_manager.consume_points("youtube", 50)
                time.sleep(5)

                primary_playlist_id = get_cached_playlist(primary_playlist_name, "public")
                if primary_playlist_id:
                    youtube.playlistItems().insert(part="snippet", body={"snippet": {"playlistId": primary_playlist_id, "resourceId": {"kind": "youtube#video", "videoId": vid_id}}}).execute()
                    quota_manager.consume_points("youtube", 50)
                    time.sleep(3)

                secondary_playlist_id = get_cached_playlist(secondary_playlist_name, "public")
                if secondary_playlist_id:
                    youtube.playlistItems().insert(part="snippet", body={"snippet": {"playlistId": secondary_playlist_id, "resourceId": {"kind": "youtube#video", "videoId": vid_id}}}).execute()
                    quota_manager.consume_points("youtube", 50)
                    time.sleep(3)

                playlist_item_id = vid_to_playlist_item.get(vid_id)
                if playlist_item_id:
                    try:
                        youtube.playlistItems().delete(id=playlist_item_id).execute()
                        quota_manager.consume_points("youtube", 50)
                        time.sleep(3)
                    except Exception as del_err:
                        print(f"⚠️ [PUBLISHER] Failed to remove {vid_id} from Vault Playlist: {del_err}")

                # Update SQLite State to PUBLISHED
                job.state = JobState.PUBLISHED
                job.updated_at = datetime.utcnow().isoformat()
                db.upsert_job(job)
                published_total += 1
                
                print(f"   ✅ Scheduled Video {vid_id} for {target_time_str} UTC.")

            except Exception as vid_e:
                print(f"⚠️ [PUBLISHER] Failed to publish video {vid_id}: {vid_e}.")
                notify_error("Publisher", "Publishing Error", f"Video {vid_id} failed: {vid_e}")
                
                if "404" in str(vid_e) or "not found" in str(vid_e).lower():
                    print(f"🗑️ [PUBLISHER] 404 Detected. Flagging ghost video {vid_id} as FAILED in DB.")
                    job.state = JobState.FAILED
                    job.updated_at = datetime.utcnow().isoformat()
                    db.upsert_job(job)

    if published_total > 0:
        notify_summary(True, f"🚀 **Publisher Online**\nSuccessfully scheduled {published_total} videos across channels. Routed to Mega-Playlists.")
    else:
        notify_summary(False, "⚠️ **Publisher Alert**\nAttempted to publish videos, but found no valid vaulted jobs or encountered an error.")

if __name__ == "__main__":
    publish_vault_videos()
