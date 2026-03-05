import os
import json
import time
from datetime import datetime
from scripts.youtube_manager import get_youtube_client
from scripts.retry import quota_manager
from scripts.discord_notifier import notify_daily_pulse

def run_daily_analysis():
    """
    The Channel Manager. 
    Fetches stats, calculates growth, gets Gemini's assessment, 
    and checks the Token Health alarm.
    """
    print("📊 [ANALYST] Initiating Daily Performance Pulse...")
    youtube = get_youtube_client()
    if not youtube:
        print("❌ [ANALYST] Failed to connect to YouTube for stats.")
        return

    try:
        # 1. Fetch Real-Time Channel Stats
        request = youtube.channels().list(
            part="statistics,snippet",
            mine=True
        )
        response = request.execute()
        
        if not response.get("items"):
            print("⚠️ [ANALYST] No channel data found.")
            return

        item = response["items"][0]
        stats = item["statistics"]
        channel_name = item["snippet"]["title"]
        
        current_data = {
            "views": int(stats["viewCount"]),
            "subs": int(stats["subscriberCount"]),
            "videos": int(stats["videoCount"]),
            "timestamp": datetime.utcnow().isoformat()
        }

        # 2. Calculate Growth (Historical Comparison)
        history_path = os.path.join("memory", "channel_stats_history.json")
        growth = {"views": 0, "subs": 0}
        
        if os.path.exists(history_path):
            with open(history_path, "r") as f:
                history = json.load(f)
                prev = history.get("last_stats", {})
                if prev:
                    growth["views"] = current_data["views"] - prev.get("views", 0)
                    growth["subs"] = current_data["subs"] - prev.get("subs", 0)

        # 3. Get Gemini Strategy Assessment
        prompt = f"""
        Analyze these YouTube stats for the channel '{channel_name}':
        - Total Views: {current_data['views']} (+{growth['views']} today)
        - Total Subs: {current_data['subs']} (+{growth['subs']} today)
        - Total Videos: {current_data['videos']}
        
        Provide a blunt, 2-sentence assessment of the channel's growth and what to focus on next.
        """
        ai_take = quota_manager.generate_text(prompt, task_type="analyst") or "Assessment unavailable."

        # 4. Check System Health (Token Birthday)
        is_healthy, health_msg, baby_steps = quota_manager.check_token_health()
        
        # 5. Pack data for Discord
        pulse_data = {
            "channel_name": channel_name,
            "views": current_data["views"],
            "views_growth": growth["views"],
            "subs": current_data["subs"],
            "subs_growth": growth["subs"],
            "videos": current_data["videos"],
            "ai_take": ai_take,
            "health_report": {
                "is_healthy": is_healthy,
                "msg": health_msg,
                "baby_steps": baby_steps
            }
        }

        # 6. Send to Discord
        notify_daily_pulse(pulse_data)

        # 7. Update History for tomorrow
        with open(history_path, "w") as f:
            json.dump({"last_stats": current_data}, f, indent=4)
            
        print("✅ [ANALYST] Daily Pulse transmitted successfully.")

    except Exception as e:
        print(f"❌ [ANALYST] Analysis failed: {e}")
        quota_manager.diagnose_fatal_error("performance_analyst.py", e)

if __name__ == "__main__":
    run_daily_analysis()
