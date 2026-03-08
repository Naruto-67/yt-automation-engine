# scripts/performance_analyst.py
import os
import json
import yaml
import re
from scripts.youtube_manager import get_youtube_client
from scripts.quota_manager import quota_manager
from scripts.discord_notifier import notify_daily_pulse
from engine.config_manager import config_manager
from engine.logger import logger
from engine.database import db

def load_config_prompts():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    with open(os.path.join(root_dir, "config", "prompts.yaml"), "r", encoding="utf-8") as f: 
        return yaml.safe_load(f)

def run_daily_analysis():
    logger.engine("📊 Initiating Performance Audit...")
    prompts_cfg = load_config_prompts()

    for channel in config_manager.get_active_channels():
        youtube = get_youtube_client(channel.youtube_refresh_token_env)
        if not youtube: continue

        intel = db.get_channel_intelligence(channel.channel_id)

        try:
            res = youtube.channels().list(part="statistics", mine=True).execute()
            stats = res["items"][0]["statistics"]
            views, subs = int(stats.get("viewCount", 0)), int(stats.get("subscriberCount", 0))
            
            sys_msg = prompts_cfg['analyst']['system_prompt']
            user_msg = prompts_cfg['analyst']['user_template'].format(views=views, subs=subs, current_strategy=intel['emphasize'][-2:])
            
            raw_analysis, _ = quota_manager.generate_text(user_msg, task_type="analysis", system_prompt=sys_msg)
            if raw_analysis:
                match = re.search(r'\{.*\}', raw_analysis, re.DOTALL)
                if match:
                    new_rules = json.loads(match.group(0))
                    intel["emphasize"].append(new_rules.get("new_emphasize", "Maintain pacing"))
                    intel["avoid"].append(new_rules.get("new_avoid", "Dead air"))
                    
                    intel["emphasize"] = intel["emphasize"][-5:]
                    intel["avoid"] = intel["avoid"][-5:]

            db.upsert_channel_intelligence(
                channel.channel_id, intel["emphasize"], intel["avoid"], intel["recent_tags"], intel["preferred_visuals"]
            )
            
            notify_daily_pulse(views, subs, {"emphasize": [intel["emphasize"][-1]], "avoid": [intel["avoid"][-1]]})
            logger.success(f"Strategy updated for {channel.channel_name}")
            
        except Exception as e: 
            logger.error(f"Analysis failed: {e}")

if __name__ == "__main__": 
    run_daily_analysis()
