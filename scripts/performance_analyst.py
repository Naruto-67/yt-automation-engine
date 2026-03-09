# scripts/performance_analyst.py — Ghost Engine V6.7
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

def load_config_prompts():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    with open(os.path.join(root_dir, "config", "prompts.yaml"), "r") as f:
        return yaml.safe_load(f)

def _apply_time_decay(rules: list, timestamps: dict, prefix: str, decay_days: int = 30) -> tuple:
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
        
    aged  = [rules[i] for i in aged_indices]
    fresh = [r for i, r in enumerate(rules) if i not in aged_indices]
    merged = aged + fresh
    
    new_ts = {}
    old_indices = aged_indices + [i for i in range(len(rules)) if i not in aged_indices]
    for new_i, old_i in enumerate(old_indices):
        new_ts[f"{prefix}_{new_i}"] = timestamps.get(f"{prefix}_{old_i}", now.isoformat())
        
    return merged, new_ts

def _fetch_channel_stats(youtube) -> dict:
    res = youtube.channels().list(part="statistics", mine=True).execute()
    quota_manager.consume_points("youtube", 1)
    stats = res["items"][0]["statistics"]
    return {
        "views": int(stats.get("viewCount", 0)),
        "subs":  int(stats.get("subscriberCount", 0)),
        "videos": int(stats.get("videoCount", 0))
    }

def _fetch_recent_video_stats(youtube, channel_id: str) -> list:
    try:
        uploads_id = youtube.channels().list(part="contentDetails", mine=True).execute()["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        quota_manager.consume_points("youtube", 1)

        # GOD-TIER FIX: Fetch 50 videos instead of 20 to ensure we bypass the 14 private Vault videos
        vids = youtube.playlistItems().list(part="snippet", playlistId=uploads_id, maxResults=50).execute()
        quota_manager.consume_points("youtube", 1)

        vid_ids = [v["snippet"]["resourceId"]["videoId"] for v in vids.get("items", [])]
        if not vid_ids:
            return []

        # GOD-TIER FIX: Add "status" part to strictly check the privacyStatus of the videos
        stats = youtube.videos().list(part="statistics,snippet,status", id=",".join(vid_ids)).execute()
        quota_manager.consume_points("youtube", 1)

        results = []
        for item in stats.get("items", []):
            # Block private/unreleased vault videos from polluting the AI's intelligence with 0 views
            if item.get("status", {}).get("privacyStatus") == "private":
                continue
                
            published = item["snippet"].get("publishedAt", "")
            db.upsert_video_performance(
                channel_id=channel_id, youtube_id=item["id"], title=item["snippet"]["title"],
                views=int(item["statistics"].get("viewCount", 0)), likes=int(item["statistics"].get("likeCount", 0)),
                comments=int(item["statistics"].get("commentCount", 0)), published_at=published
            )
            results.append({
                "title":  item["snippet"]["title"], "views":  int(item["statistics"].get("viewCount", 0)), "published_at": published
            })
        return sorted(results, key=lambda x: x["views"], reverse=True)
    except Exception as e:
        logger.error(f"Failed to fetch video stats: {e}")
        return []

def run_daily_analysis():
    if os.environ.get("GHOST_ENGINE_ENABLED", "true").lower() == "false":
        print("🔴 [KILL SWITCH] Analyst halted.")
        return

    prompts_cfg  = load_config_prompts()
    settings     = config_manager.get_settings()
    decay_days   = settings.get("intelligence", {}).get("rule_decay_days", 30)
    max_rules    = settings.get("intelligence", {}).get("max_rules", 5)

    for channel in config_manager.get_active_channels():
        set_channel_context(channel)
        youtube = get_youtube_client(channel)
        if not youtube:
            continue

        try:
            ch_stats    = _fetch_channel_stats(youtube)
            views       = ch_stats["views"]
            subs        = ch_stats["subs"]
            recent_vids = _fetch_recent_video_stats(youtube, channel.channel_id)

            recent_7d     = db.get_recent_performance(channel.channel_id, days=7)
            growth_7d     = sum(v["views"] for v in recent_7d)

            intel = db.get_channel_intelligence(channel.channel_id)
            ts = intel.get("rule_timestamps", {})

            intel["emphasize"], emp_ts = _apply_time_decay(intel["emphasize"], ts, "emp", decay_days)
            intel["avoid"], avo_ts     = _apply_time_decay(intel["avoid"], ts, "avo", decay_days)
            ts.update(emp_ts)
            ts.update(avo_ts)

            top_videos_str = "\n".join([f"- '{v['title']}' | {v['views']:,} views" for v in recent_vids[:3]]) or "No data yet"

            sys_msg  = prompts_cfg["analyst"]["system_prompt"]
            user_msg = prompts_cfg["analyst"]["user_template"].format(
                views=views, subs=subs, current_strategy=intel["emphasize"][-2:],
                top_videos=top_videos_str, growth_7d=growth_7d
            )

            raw, _ = quota_manager.generate_text(user_msg, task_type="analysis", system_prompt=sys_msg)
            if raw:
                start = raw.find('{')
                end = raw.rfind('}')
                if start != -1 and end != -1 and end > start:
                    try:
                        new_rules = json.loads(raw[start:end+1])
                        now_iso   = datetime.utcnow().isoformat()

                        new_emp = new_rules.get("new_emphasize", "").strip()
                        new_avo = new_rules.get("new_avoid", "").strip()

                        if new_emp:
                            intel["emphasize"].append(new_emp)
                            ts[f"emp_{len(intel['emphasize']) - 1}"] = now_iso
                        if new_avo:
                            intel["avoid"].append(new_avo)
                            ts[f"avo_{len(intel['avoid']) - 1}"] = now_iso

                        for prefix, key in [("emp", "emphasize"), ("avo", "avoid")]:
                            if len(intel[key]) > max_rules:
                                cut_count = len(intel[key]) - max_rules
                                intel[key] = intel[key][-max_rules:]
                                
                                new_ts = {}
                                for i in range(len(intel[key])):
                                    old_key = f"{prefix}_{i + cut_count}"
                                    new_ts[f"{prefix}_{i}"] = ts.get(old_key, now_iso)
                                    
                                ts = {k: v for k, v in ts.items() if not k.startswith(f"{prefix}_")}
                                ts.update(new_ts)

                        intel["rule_timestamps"] = ts

                        if recent_vids:
                            new_tags = new_rules.get("new_tags", [])
                            if new_tags:
                                combined = intel.get("recent_tags", []) + new_tags
                                intel["recent_tags"] = list(dict.fromkeys(combined))[-20:]
                    except Exception as e:
                        logger.error(f"Failed to parse Analyst JSON: {e}")

            db.upsert_channel_intelligence(channel.channel_id, intel)
            notify_daily_pulse(views, subs, growth_7d, intel)
            logger.success(f"Strategy updated for {channel.channel_name}.")

        except Exception as e:
            notify_error("Performance Analyst", type(e).__name__, str(e))
            logger.error(f"Analysis failed for {channel.channel_id}: {e}")

if __name__ == "__main__":
    run_daily_analysis()
