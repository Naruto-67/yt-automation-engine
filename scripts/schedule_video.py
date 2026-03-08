import os
import json
import time
from datetime import datetime, timedelta
from scripts.youtube_manager import get_youtube_client, get_or_create_playlist
from scripts.quota_manager import quota_manager
from scripts.discord_notifier import notify_summary, notify_error


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


def _save_matrix(matrix, matrix_path):
    """Atomic matrix write — shared helper used after each video publish."""
    tmp_path = matrix_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(matrix, f, indent=4)
    os.replace(tmp_path, matrix_path)


def publish_vault_videos():
    if not quota_manager.can_afford_youtube(600):
        print("🛑 [QUOTA GUARDIAN] YouTube Quota too low to safely publish. Aborting to prevent API ban.")
        return

    youtube = get_youtube_client()
    if not youtube: return

    matrix_path = os.path.join(os.path.dirname(__file__), "..", "memory", "content_matrix.json")
    matrix = []

    try:
        if os.path.exists(matrix_path):
            try:
                with open(matrix_path, "r") as f: matrix = json.load(f)
            except Exception as e:
                print(f"⚠️ [PUBLISHER] Matrix JSON load failed. Falling back to empty array: {e}")
                matrix = []

        vault_id = get_or_create_playlist(youtube, "Vault Backup")
        if not vault_id:
            print("⚠️ [PUBLISHER] Failed to find or create the Vault Backup playlist. Halting publisher to protect metadata.")
            return

        items = youtube.playlistItems().list(part="snippet", playlistId=vault_id, maxResults=2).execute().get("items", [])
        quota_manager.consume_points("youtube", 1)

        if len(items) == 0:
            print("⚠️ [PUBLISHER] No videos found in the vault.")
            return

        ai_times = get_optimal_publish_times(youtube)
        now = datetime.utcnow()

        # 🚨 FLAW FIX: Playlist ID cache.
        # Previously get_or_create_playlist() was called 3× per video with NO caching.
        # Each call does a full paginated fetch of ALL playlists (1+ quota points each).
        # For 2 videos that's 6+ wasted quota points fetching the same three playlists.
        # Fix: resolve all playlist IDs once upfront, reuse the IDs in the loop.
        print("📋 [PUBLISHER] Pre-resolving playlist IDs...")
        playlist_cache = {}

        def get_cached_playlist(name, privacy="public"):
            if name not in playlist_cache:
                playlist_cache[name] = get_or_create_playlist(youtube, name, privacy)
            return playlist_cache[name]

        # Pre-warm vault (already fetched above) + both content playlists
        playlist_cache["Vault Backup"] = vault_id
        get_cached_playlist("All Uploads | Viral Shorts", "public")
        get_cached_playlist("Mind-Blowing Facts", "public")
        get_cached_playlist("Immersive AI Stories", "public")

        published_count = 0
        published_times = []

        for idx, item in enumerate(items):
            vid_id = item["snippet"]["resourceId"]["videoId"]

            try:
                is_fact_based = False
                for m_item in matrix:
                    if m_item.get("youtube_id") == vid_id:
                        is_fact_based = any(k in m_item.get('niche', '').lower() for k in ['fact', 'hack', 'trend', 'brainrot'])
                        break

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

                # Use cached playlist IDs — no redundant API calls
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

                try:
                    youtube.playlistItems().delete(id=item["id"]).execute()
                    quota_manager.consume_points("youtube", 50)
                    time.sleep(3)
                except Exception as del_err:
                    print(f"⚠️ [PUBLISHER] Failed to remove video {vid_id} from Vault Playlist: {del_err}")

                # Mark published in matrix
                for m_item in matrix:
                    if m_item.get("youtube_id") == vid_id:
                        m_item['published'] = True
                        m_item['published_date'] = datetime.utcnow().isoformat()

                published_count += 1
                published_times.append(target_time_str)

                # 🚨 FLAW FIX: Write matrix to disk IMMEDIATELY after each successful publish.
                # Previously the matrix was written ONCE at the very end of the function.
                # If the runner was killed mid-loop (quota freeze, timeout, network drop),
                # any videos that HAD been published never got their published=True flag saved.
                # On the next publisher run, those videos would be fetched again, hit 404 on
                # the vault (since they were already removed), and trigger ghost cleanup.
                # Fix: atomic write after every video — partial success is always persisted.
                _save_matrix(matrix, matrix_path)
                print(f"   💾 [PUBLISHER] Matrix state persisted after video {vid_id}.")

            except Exception as vid_e:
                print(f"⚠️ [PUBLISHER] Failed to publish video {vid_id}: {vid_e}.")
                notify_error("Publisher", "Publishing Error", f"Video {vid_id} failed: {vid_e}")

                if "404" in str(vid_e) or "not found" in str(vid_e).lower():
                    print(f"🗑️ [PUBLISHER] 404 Detected. Removing ghost video {vid_id} from memory.")
                    matrix = [m for m in matrix if m.get("youtube_id") != vid_id]
                    _save_matrix(matrix, matrix_path)
                continue

        # Final write for any trailing state changes (no-op if already written per-video above)
        _save_matrix(matrix, matrix_path)

        if published_count > 0:
            times_str = ", ".join(published_times)
            notify_summary(True, f"🚀 **Publisher Online**\nSuccessfully scheduled {published_count} videos for {times_str} UTC. Routed to Mega-Playlists.")
        else:
            notify_summary(False, f"⚠️ **Publisher Alert**\nAttempted to publish videos, but encountered 404 Ghosts or Quota blocks. Matrix cleaned and queue preserved.")

    except Exception as e:
        quota_manager.diagnose_fatal_error("schedule_video.py", e)


if __name__ == "__main__":
    publish_vault_videos()
