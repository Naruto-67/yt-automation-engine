# scripts/performance_analyst.py
import os
import json
import re
from scripts.youtube_manager import get_youtube_client
from scripts.quota_manager import quota_manager
from scripts.discord_notifier import notify_daily_pulse
from engine.config_manager import config_manager
from engine.logger import logger

def run_daily_analysis():
    """Fetches YouTube analytics and updates the strategic lessons_learned.json."""
    logger.engine("📊 Initiating Performance Audit...")
    
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    lessons_path = os.path.join(root_dir, "assets", "lessons_learned.json")
    
    # Load existing or defaults
    if os.path.exists(lessons_path):
        with open(lessons_path, "r") as f: lessons = json.load(f)
    else:
        lessons = {"emphasize": [], "avoid": [], "recent_tags": [], "preferred_visuals": ["3D Animation"]}

    for channel in config_manager.get_active_channels():
        youtube = get_youtube_client(channel.youtube_refresh_token_env)
        if not youtube: continue

        try:
            # Get Stats
            res = youtube.channels().list(part="statistics,contentDetails", mine=True).execute()
            quota_manager.consume_points("youtube", 1)
            
            stats = res["items"][0]["statistics"]
            views = int(stats.get("viewCount", 0))
            subs = int(stats.get("subscriberCount", 0))
            
            # AI Strategy update (Point 13)
            prompt = f"""
            System Stats: {views} views, {subs} subs. 
            Current Strategy: {lessons['emphasize'][-2:]}
            
            Analyze modern YouTube Shorts retention psychology. 
            Give one NEW specific rule to 'emphasize' and one to 'avoid'.
            Return JSON: {{"new_emphasize": "...", "new_avoid": "..."}}
            """
            
            raw_analysis, _ = quota_manager.generate_text(prompt, task_type="analysis")
            if raw_analysis:
                match = re.search(r'\{.*\}', raw_analysis, re.DOTALL)
                if match:
                    new_rules = json.loads(match.group(0))
                    lessons["emphasize"].append(new_rules["new_emphasize"])
                    lessons["avoid"].append(new_rules["new_avoid"])
                    
                    # Keep lists lean
                    lessons["emphasize"] = lessons["emphasize"][-5:]
                    lessons["avoid"] = lessons["avoid"][-5:]

            # Save updated brain
            with open(lessons_path, "w") as f:
                json.dump(lessons, f, indent=4)
            
            notify_daily_pulse(views, subs, {"emphasize": [lessons["emphasize"][-1]], "avoid": [lessons["avoid"][-1]]})
            logger.success(f"Strategy updated for {channel.channel_name}")

        except Exception as e:
            logger.error(f"Analysis failed for {channel.channel_name}: {e}")

if __name__ == "__main__":
    run_daily_analysis()
