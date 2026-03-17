# scripts/performance_analyst.py
# Ghost Engine V26.0.0 — Performance Intelligence & Strategy Evolution
import os
import json
import yaml
import re
from datetime import datetime, timedelta
from scripts.youtube_manager import get_youtube_client
from scripts.quota_manager import quota_manager
from scripts.discord_notifier import set_channel_context, notify_daily_pulse, notify_error
from engine.config_manager import config_manager
from engine.database import db
from engine.logger import logger

TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true"

def load_config_prompts():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    with open(os.path.join(root_dir, "config", "prompts.yaml"), "r") as f:
        return yaml.safe_load(f)

def _apply_time_decay(rules: list, timestamps: dict, prefix: str, decay_days: int = 30) -> tuple:
    """
    V26 Logic: Automatically ages out old strategy rules to keep the engine fresh. [cite: 376-379]
    """
    if not timestamps or not rules:
        return rules, timestamps
    now = datetime.utcnow()
    aged_indices = []
    
    for i, rule in enumerate(rules):
        ts = timestamps.get(f"{prefix}_{i}")
        if ts:
            try:
                if (now - datetime.fromisoformat(ts)).days > decay_days:
                    aged_indices.append(i)
            except Exception:
                pass
                
    if not aged_indices:
        new_ts = {f"{prefix}_{i}": timestamps.get(f"{prefix}_{i}", now.isoformat()) for i in range(len(rules))}
        return rules, new_ts
        
    # Move aged rules to the front (to be pruned first) and keep fresh ones at the end
    aged  = [rules[i] for i in aged_indices]
    fresh = [r for i, r in enumerate(rules) if i not in aged_indices]
    merged = aged + fresh
    
    new_ts = {}
    old_indices = aged_indices + [i for i in range(len(rules)) if i not in aged_indices]
    for new_i, old_i in enumerate(old_indices):
        new_ts[f"{prefix}_{new_i}"] = timestamps.get(f"{prefix}_{old_i}", now.isoformat())
        
    return merged, new_ts

def _fetch_channel_stats(youtube) -> dict:
    """Retrieves high-level channel growth metrics. [cite: 379]"""
    res = youtube.channels().list(part="statistics", mine=True).execute()
    quota_manager.consume_points("youtube", 1)
    stats = res["items"][0]["statistics"]
    return {
        "views": int(stats.get("viewCount", 0)),
        "subs":  int(stats.get("subscriberCount", 0)),
        "videos": int(stats.get("videoCount", 0))
    }

def _fetch_recent_video_stats(youtube, channel_id: str) -> list:
    """Analyzes recent video performance to identify success patterns. [cite: 380-383]"""
    try:
        uploads_id = youtube.channels().list(part="contentDetails", mine=True).execute()["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        quota_manager.consume_points("youtube", 1)

        vids = youtube.playlistItems().list(part="snippet", playlistId=uploads_id, maxResults=50).execute()
        quota_manager.consume_points("youtube", 1)

        vid_ids = [v["snippet"]["resourceId"]["videoId"] for v in vids.get("items", [])]
        if not vid_ids: return []

        stats = youtube.videos().list(part="statistics,snippet,status", id=",".join(vid_ids)).execute()
        quota_manager.consume_points("youtube", 1)

        results = []
        for item in stats.get("items", []):
            if item.get("status", {}).get("privacyStatus") == "private": continue
            
            published = item["snippet"].get("publishedAt", "")
            results.append({
                "title": item["snippet"]["title"], 
                "views": int(item["statistics"].get("viewCount", 0)), 
                "published_at": published
            })
        return sorted(results, key=lambda x: x["views"], reverse=True)
    except Exception as e:
        logger.error(f"Failed to fetch video stats: {e}")
        return []

def run_daily_analysis():
    """V26 Master Analyst: Updates strategy based on real-world data. [cite: 384-403]"""
    prompts_cfg  = load_config_prompts()
    settings     = config_manager.get_settings()
    decay_days   = settings.get("intelligence", {}).get("rule_decay_days", 30)
    max_rules    = settings.get("intelligence", {}).get("max_rules", 5)

    for channel in config_manager.get_active_channels():
        set_channel_context(channel)
        
        youtube = None if TEST_MODE else get_youtube_client(channel)
        if not youtube and not TEST_MODE: continue

        try:
            if TEST_MODE:
                ch_stats = {"views": 15000, "subs": 1200, "videos": 45}
                recent_vids = [{"title": "Test Performance", "views": 5000, "published_at": datetime.utcnow().isoformat()}]
            else:
                ch_stats    = _fetch_channel_stats(youtube)
                recent_vids = _fetch_recent_video_stats(youtube, channel.channel_id)

            views, subs = ch_stats["views"], ch_stats["subs"]
            growth_7d = sum(v["views"] for v in recent_vids[:7]) # Simplified 7D calculation

            intel = db.get_channel_intelligence(channel.channel_id)
            ts = intel.get("rule_timestamps", {})

            # Apply V26 Time Decay logic to keep strategies relevant [cite: 387-388]
            intel["emphasize"], emp_ts = _apply_time_decay(intel["emphasize"], ts, "emp", decay_days)
            intel["avoid"], avo_ts     = _apply_time_decay(intel["avoid"], ts, "avo", decay_days)
            ts.update(emp_ts); ts.update(avo_ts)

            top_videos_str = "\n".join([f"- '{v['title']}' | {v['views']:,} views" for v in recent_vids[:3]])

            # AI Strategy Update
            sys_msg  = prompts_cfg["analyst"]["system_prompt"]
            user_msg = prompts_cfg["analyst"]["user_template"].format(
                views=views, subs=subs, current_strategy=intel["emphasize"][-2:],
                top_videos=top_videos_str, growth_7d=growth_7d
            )

            raw, _ = quota_manager.generate_text(user_msg, task_type="strategy", system_prompt=sys_msg)
            if raw:
                start, end = raw.find('{'), raw.rfind('}')
                if start != -1 and end != -1:
                    new_rules = json.loads(raw[start:end+1])
                    now_iso   = datetime.utcnow().isoformat()

                    # Extract new rules [cite: 391-395]
                    for key, prefix in [("new_emphasize", "emphasize"), ("new_avoid", "avoid")]:
                        rule_val = new_rules.get(key)
                        if rule_val and str(rule_val) not in ["None", "null", "[]"]:
                            intel[prefix].append(str(rule_val))
                            ts[f"{prefix[:3]}_{len(intel[prefix]) - 1}"] = now_iso

                    # Prune old rules if they exceed the max limit [cite: 396-399]
                    for prefix in ["emp", "avo"]:
                        key = "emphasize" if prefix == "emp" else "avoid"
                        if len(intel[key]) > max_rules:
                            intel[key] = intel[key][-max_rules:]

            intel["rule_timestamps"] = ts
            db.upsert_channel_intelligence(channel.channel_id, intel)
            notify_daily_pulse(views, subs, growth_7d, intel)
            logger.success(f"Strategy updated for {channel.channel_name}.")

        except Exception as e:
            notify_error("Performance Analyst", type(e).__name__, str(e))
            logger.error(f"Analysis failed for {channel.channel_id}: {e}")

if __name__ == "__main__":
    run_daily_analysis()
