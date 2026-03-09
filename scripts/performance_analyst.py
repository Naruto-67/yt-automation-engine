# scripts/performance_analyst.py — Ghost Engine V6
import os
import json
import yaml
import re
from datetime import datetime, timedelta
from scripts.youtube_manager import get_youtube_client
from scripts.quota_manager import quota_manager
from scripts.discord_notifier import (
    set_channel_context, notify_daily_pulse, notify_error
)
from engine.config_manager import config_manager
from engine.database import db
from engine.logger import logger


def load_config_prompts():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    with open(os.path.join(root_dir, "config", "prompts.yaml"), "r") as f:
        return yaml.safe_load(f)


def _apply_time_decay(rules: list, timestamps: dict, decay_days: int = 30) -> list:
    """
    Down-weight old rules by moving them to the end of the list.
    Rules older than decay_days are kept but de-prioritised.
    The AI script generator injects the LAST 3 rules (most recent = highest priority).
    """
    if not timestamps:
        return rules
    now = datetime.utcnow()
    aged_indices = []
    for i, rule in enumerate(rules):
        ts = timestamps.get(str(i))
        if ts:
            try:
                age = (now - datetime.fromisoformat(ts)).days
                if age > decay_days:
                    aged_indices.append(i)
            except Exception:
                pass
    if not aged_indices:
        return rules
    # Move aged rules to front (lowest priority for last-N slicing)
    aged  = [rules[i] for i in aged_indices]
    fresh = [r for i, r in enumerate(rules) if i not in aged_indices]
    return aged + fresh


def _fetch_channel_stats(youtube) -> dict:
    """Fetch channel-level stats. Cost: 1 YT pt."""
    res = youtube.channels().list(part="statistics", mine=True).execute()
    quota_manager.consume_points("youtube", 1)
    stats = res["items"][0]["statistics"]
    return {
        "views": int(stats.get("viewCount", 0)),
        "subs":  int(stats.get("subscriberCount", 0)),
        "videos": int(stats.get("videoCount", 0))
    }


def _fetch_recent_video_stats(youtube, channel_id: str) -> list:
    """
    Fetch view/like/comment stats for recent videos (last 30 days).
    Stores them in the video_performance table for trend analysis.
    Cost: ~3 YT pts.
    """
    try:
        uploads_id = youtube.channels().list(
            part="contentDetails", mine=True
        ).execute()["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        quota_manager.consume_points("youtube", 1)

        vids = youtube.playlistItems().list(
            part="snippet", playlistId=uploads_id, maxResults=20
        ).execute()
        quota_manager.consume_points("youtube", 1)

        vid_ids = [v["snippet"]["resourceId"]["videoId"]
                   for v in vids.get("items", [])]
        if not vid_ids:
            return []

        stats = youtube.videos().list(
            part="statistics,snippet", id=",".join(vid_ids)
        ).execute()
        quota_manager.consume_points("youtube", 1)

        results = []
        for item in stats.get("items", []):
            published = item["snippet"].get("publishedAt", "")
            db.upsert_video_performance(
                channel_id=channel_id,
                youtube_id=item["id"],
                title=item["snippet"]["title"],
                views=int(item["statistics"].get("viewCount", 0)),
                likes=int(item["statistics"].get("likeCount", 0)),
                comments=int(item["statistics"].get("commentCount", 0)),
                published_at=published
            )
            results.append({
                "title":  item["snippet"]["title"],
                "views":  int(item["statistics"].get("viewCount", 0)),
                "published_at": published
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
        # Set Discord context for this channel
        set_channel_context(channel)

        youtube = get_youtube_client(channel)
        if not youtube:
            continue

        try:
            # ── Fetch stats ───────────────────────────────────────────────────
            ch_stats    = _fetch_channel_stats(youtube)
            views       = ch_stats["views"]
            subs        = ch_stats["subs"]
            recent_vids = _fetch_recent_video_stats(youtube, channel.channel_id)

            # Calculate 7-day growth (compare vs DB records)
            recent_30d    = db.get_recent_performance(channel.channel_id, days=30)
            recent_7d     = db.get_recent_performance(channel.channel_id, days=7)
            growth_7d     = sum(v["views"] for v in recent_7d)

            # ── Load current intelligence ─────────────────────────────────────
            intel = db.get_channel_intelligence(channel.channel_id)

            # Apply time-decay to de-prioritise stale rules
            intel["emphasize"] = _apply_time_decay(
                intel["emphasize"], intel.get("rule_timestamps", {}), decay_days
            )
            intel["avoid"] = _apply_time_decay(
                intel["avoid"], intel.get("rule_timestamps", {}), decay_days
            )

            # ── Build context for AI analyst ─────────────────────────────────
            top_videos_str = "\n".join([
                f"- '{v['title']}' | {v['views']:,} views"
                for v in recent_vids[:3]
            ]) or "No data yet"

            sys_msg  = prompts_cfg["analyst"]["system_prompt"]
            user_msg = prompts_cfg["analyst"]["user_template"].format(
                views=views, subs=subs,
                current_strategy=intel["emphasize"][-2:],
                top_videos=top_videos_str,
                growth_7d=growth_7d
            )

            # ── Generate new rules (costs 1 Gemini call) ──────────────────────
            raw, _ = quota_manager.generate_text(
                user_msg, task_type="analysis", system_prompt=sys_msg
            )
            if raw:
                match = re.search(r'\{.*\}', raw, re.DOTALL)
                if match:
                    new_rules = json.loads(match.group(0))

                    now_iso   = datetime.utcnow().isoformat()
                    timestamps = intel.get("rule_timestamps", {})

                    new_emp = new_rules.get("new_emphasize", "").strip()
                    new_avo = new_rules.get("new_avoid", "").strip()

                    if new_emp:
                        intel["emphasize"].append(new_emp)
                        timestamps[str(len(intel["emphasize"]) - 1)] = now_iso

                    if new_avo:
                        intel["avoid"].append(new_avo)
                        timestamps[str(len(intel["avoid"]) - 1)] = now_iso

                    # Cap list size — oldest (front) get removed first
                    intel["emphasize"]    = intel["emphasize"][-max_rules:]
                    intel["avoid"]        = intel["avoid"][-max_rules:]
                    intel["rule_timestamps"] = timestamps

                    # Update tags from recent videos if available
                    if recent_vids:
                        new_tags = new_rules.get("new_tags", [])
                        if new_tags:
                            combined = intel.get("recent_tags", []) + new_tags
                            intel["recent_tags"] = list(dict.fromkeys(combined))[-20:]

            db.upsert_channel_intelligence(channel.channel_id, intel)
            notify_daily_pulse(views, subs, growth_7d, intel)
            logger.success(f"Strategy updated for {channel.channel_name}.")

        except Exception as e:
            notify_error("Performance Analyst", type(e).__name__, str(e))
            logger.error(f"Analysis failed for {channel.channel_id}: {e}")


if __name__ == "__main__":
    run_daily_analysis()
