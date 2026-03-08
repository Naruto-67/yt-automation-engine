import os
import json
import yaml
import re
from scripts.youtube_manager import get_youtube_client
from scripts.quota_manager import quota_manager
from scripts.discord_notifier import notify_daily_pulse
from engine.config_manager import config_manager
from engine.logger import logger

def load_config_prompts():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    with open(os.path.join(root_dir, "config", "prompts.yaml"), "r", encoding="utf-8") as f: return yaml.safe_load(f)

def run_daily_analysis():
    logger.engine("📊 Initiating Performance Audit...")
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    lessons_path = os.path.join(root_dir, "assets", "lessons_learned.json")
    
    lessons = json.load(open(lessons_path, "r")) if os.path.exists(lessons_path) else {"emphasize": [], "avoid": [], "recent_tags": [], "preferred_visuals": ["3D Animation"]}
    prompts_cfg = load_config_prompts()

    for channel in config_manager.get_active_channels():
        youtube = get_youtube_client(channel.youtube_refresh_token_env)
        if not youtube: continue

        try:
            res = youtube.channels().list(part="statistics", mine=True).execute()
            stats = res["items"][0]["statistics"]
            views, subs = int(stats.get("viewCount", 0)), int(stats.get("subscriberCount", 0))
            
            sys_msg = prompts_cfg['analyst']['system_prompt']
            user_msg = prompts_cfg['analyst']['user_template'].format(views=views, subs=subs, current_strategy=lessons['emphasize'][-2:])
            
            raw_analysis, _ = quota_manager.generate_text(user_msg, task_type="analysis", system_prompt=sys_msg)
            if raw_analysis:
                match = re.search(r'\{.*\}', raw_analysis, re.DOTALL)
                if match:
                    new_rules = json.loads(match.group(0))
                    lessons["emphasize"].append(new_rules["new_emphasize"])
                    lessons["avoid"].append(new_rules["new_avoid"])
                    lessons["emphasize"], lessons["avoid"] = lessons["emphasize"][-5:], lessons["avoid"][-5:]

            with open(lessons_path, "w") as f: json.dump(lessons, f, indent=4)
            notify_daily_pulse(views, subs, {"emphasize": [lessons["emphasize"][-1]], "avoid": [lessons["avoid"][-1]]})
            logger.success(f"Strategy updated for {channel.channel_name}")
        except Exception as e: logger.error(f"Analysis failed: {e}")

if __name__ == "__main__": run_daily_analysis()
