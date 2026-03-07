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

def publish_vault_videos():
    if not quota_manager.can_afford_youtube(600):
        print("🛑 [QUOTA GUARDIAN] YouTube Quota too low to safely publish. Aborting to prevent API ban.")
        return

    youtube = get_youtube_client()
    if not youtube: return
    
    try:
        matrix_path = os.path.join(os.path.dirname(__file__), "..", "memory", "content_matrix.json")
        matrix = []
        
        # 🚨 FIX: Safe fallback if matrix corrupted during IO operations
        if os.path.exists(matrix_path):
            try:
                with open(matrix_path, "r") as f: matrix = json.load(f)
            except Exception as e:
                print(f"⚠️ [PUBLISHER] Matrix JSON load failed. Falling back to empty array: {e}")
                matrix = []

        vault_id = get_or_create_playlist(youtube, "Vault Backup")
        items = youtube.playlistItems().list(part="snippet", playlistId=vault_id, maxResults=2).execute().get("items", [])
        quota_manager.consume_points("youtube", 1) 
        
        if len(items) < 2:
            print("⚠️ [PUBLISHER] Not enough videos in the vault to execute dual-release.")
            return

        ai_times = get_optimal_publish_times(youtube)
        now = datetime.utcnow()

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
                
                primary_playlist_id = get_or_create_playlist(youtube, primary_playlist_name, "public")
                if primary_playlist_id:
                    youtube.playlistItems().insert(part="snippet", body={"snippet": {"playlistId": primary_playlist_id, "resourceId": {"kind": "youtube#video", "videoId": vid_id}}}).execute()
                    quota_manager.consume_points("youtube", 50) 
                    time.sleep(3)
                
                secondary_playlist_id = get_or_create_playlist(youtube, secondary_playlist_name, "public")
                if secondary_playlist_id:
                    youtube.playlistItems().insert(part="snippet", body={"snippet": {"playlistId": secondary_playlist_id, "resourceId": {"kind": "youtube#video", "videoId": vid_id}}}).execute()
                    quota_manager.consume_points("youtube", 50) 
                    time.sleep(3)
                
                youtube.playlistItems().delete(id=item["id"]).execute()
                quota_manager.consume_points("youtube", 50) 
                time.sleep(3)
                
                for m_item in matrix:
                    if m_item.get("youtube_id") == vid_id:
                        m_item['published'] = True
                        m_item['published_date'] = datetime.utcnow().isoformat()
                        
            except Exception as vid_e:
                print(f"⚠️ [PUBLISHER] Failed to publish video {vid_id}: {vid_e}.")
                notify_error("Publisher", "Publishing Error", f"Video {vid_id} failed: {vid_e}")
                
                if "404" in str(vid_e) or "not found" in str(vid_e).lower():
                    print(f"🗑️ [PUBLISHER] 404 Detected. Removing ghost video {vid_id} from memory.")
                    matrix = [m for m in matrix if m.get("youtube_id") != vid_id]
                continue

            tmp_path = matrix_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(matrix, f, indent=4)
            os.replace(tmp_path, matrix_path)
            
        notify_summary(True, f"🚀 **Publisher Online**\nScheduled 2 videos for {ai_times[0]} and {ai_times[1]} UTC. Routed to Mega-Playlists.")
    except Exception as e:
        quota_manager.diagnose_fatal_error("schedule_video.py", e)

if __name__ == "__main__":
    publish_vault_videos()
