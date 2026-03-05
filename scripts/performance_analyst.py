import os
import json
from datetime import datetime
from scripts.youtube_manager import get_youtube_client
from scripts.quota_manager import quota_manager
from scripts.discord_notifier import notify_daily_pulse

def run_daily_analysis():
    print("📊 [ANALYST] Running channel performance audit...")
    youtube = get_youtube_client()
    if not youtube: return

    try:
        # 1. Fetch Stats
        data = youtube.channels().list(part="statistics,snippet", mine=True).execute()["items"][0]
        stats = data["statistics"]
        current = {"views": int(stats["viewCount"]), "subs": int(stats["subscriberCount"]), "vids": int(stats["videoCount"])}

        # 2. Compare History
        history_path = os.path.join("memory", "channel_stats_history.json")
        growth = {"views": 0, "subs": 0}
        if os.path.exists(history_path):
            with open(history_path, "r") as f:
                prev = json.load(f).get("last_stats", {})
                growth = {"views": current["views"] - prev.get("views", 0), "subs": current["subs"] - prev.get("subs", 0)}

        # 3. Gemini assessment
        prompt = f"Analyze YouTube growth: +{growth['views']} views, +{growth['subs']} subs today. Blunt 2-sentence strategy fix."
        assessment = quota_manager.generate_text(prompt, task_type="analyst")

        # 4. Token & Quota Health
        is_healthy, health_msg, baby_steps = quota_manager.check_token_health()
        
        pulse_data = {
            "channel": data["snippet"]["title"],
            "current": current, "growth": growth, "assessment": assessment,
            "health": {"is_healthy": is_healthy, "msg": health_msg, "steps": baby_steps}
        }
        
        notify_daily_pulse(pulse_data)
        with open(history_path, "w") as f: json.dump({"last_stats": current}, f, indent=4)
    except Exception as e:
        quota_manager.diagnose_fatal_error("performance_analyst.py", e)
