# scripts/performance_analyst.py — Ghost Engine V20.0
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
from engine.models import JobState

TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true"


def _print_growth_diagnosis(channel_name: str, subs: int, analytics: dict, growth_7d: int):
    """
    Print a plain-English weekly growth diagnosis to the GitHub Actions log.
    No API calls — uses already-fetched data. Helps spot problems at a glance.
    """
    print(f"\n📋 [DIAGNOSIS] {channel_name} weekly growth report:")

    # Phase
    if subs < 500:
        print(f"   📍 Phase: LAUNCH ({subs} subs) — focus on variety and finding winning pillars")
    elif subs < 1000:
        print(f"   📍 Phase: GROWTH ({subs} subs) — double down on proven content categories")
    else:
        print(f"   📍 Phase: MONETIZATION ({subs} subs) — optimise for RPM and retention")

    # 7-day trend — distinguish API failure from real zero views
    if analytics.get("_api_unavailable"):
        print("   ⚠️  7-day views: unavailable — YouTube Analytics API not enabled in GCP project.")
        print("       Action required: enable at https://console.developers.google.com/apis/api/youtubeanalytics.googleapis.com/overview")
    elif analytics.get("_api_bad_request"):
        print("   ⚠️  7-day views: unavailable — Analytics API returned a bad request (check metric names in performance_analyst.py).")
    elif growth_7d == 0:
        print("   ⚠️  7-day views: 0 — no recent views, or videos are not public yet")
    elif growth_7d < 500:
        print(f"   🔴 7-day views: {growth_7d:,} — very low. Check if videos are public and indexed.")
    elif growth_7d < 5000:
        print(f"   🟡 7-day views: {growth_7d:,} — growing but slowly. Prioritise hook quality.")
    else:
        print(f"   🟢 7-day views: {growth_7d:,} — strong growth.")

    # Retention — only show if real analytics data is present (not error sentinels)
    real_analytics = {k: v for k, v in analytics.items() if not k.startswith("_api_")}
    if real_analytics:
        avg_view_pct = real_analytics.get("avg_view_pct", 0)
        subs_gained = real_analytics.get("subscribers_gained", 0)
        
        if avg_view_pct < 40:
            print(f"   🔴 Retention: {avg_view_pct:.1f}% — CRITICAL. Hook or pacing is broken.")
        elif avg_view_pct < 70:
            print(f"   🟡 Retention: {avg_view_pct:.1f}% — acceptable. Add more open loops mid-video.")
        else:
            print(f"   🟢 Retention: {avg_view_pct:.1f}% — excellent.")
            
        if subs_gained > 0:
            print(f"   📈 Subs Gained (28d): {subs_gained}")
    elif not analytics.get("_api_unavailable") and not analytics.get("_api_bad_request"):
        print("   ℹ️  Analytics data not available yet (need at least 1 public video).")
    print()



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

        vids = youtube.playlistItems().list(part="snippet", playlistId=uploads_id, maxResults=50).execute()
        quota_manager.consume_points("youtube", 1)

        vid_ids = [v["snippet"]["resourceId"]["videoId"] for v in vids.get("items", [])]
        if not vid_ids:
            return []

        stats = youtube.videos().list(part="statistics,snippet,status", id=",".join(vid_ids)).execute()
        quota_manager.consume_points("youtube", 1)

        results = []
        for item in stats.get("items", []):
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


def _fetch_analytics_metrics(channel_id: str) -> dict:
    """
    Fetch core engagement metrics from YouTube Analytics API v2.

    Metrics returned:
      views, watch_minutes, avg_view_duration, avg_view_pct,
      subscribers_gained, subscribers_lost

    CTR / Impressions NOTE:
      CTR is NOT available via the YouTube Analytics API v2 for channel owners.
      It requires the YouTube Reporting API v1 (channel_reach_basic_a1 report),
      which generates async daily CSV files that must be downloaded and parsed.
      This is a meaningful addition once channels have >1000 subs / consistent
      traffic — implement then via a separate `_fetch_ctr_from_reporting_api()`.

    Special sentinel keys:
      _api_unavailable: True  → 403 / API not enabled — do NOT diagnose as "no views"
      _api_bad_request: True  → 400 (wrong metric/param) — log and skip entirely
    """
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        from engine.config_manager import config_manager

        channels = config_manager.get_active_channels()
        ch_cfg   = next((c for c in channels if c.channel_id == channel_id), None)
        if not ch_cfg:
            return {}

        token_env     = ch_cfg.youtube_refresh_token_env
        client_id     = os.environ.get(token_env.replace("REFRESH_TOKEN", "CLIENT_ID"), "")
        client_secret = os.environ.get(token_env.replace("REFRESH_TOKEN", "CLIENT_SECRET"), "")
        refresh_token = os.environ.get(token_env, "")

        if not all([client_id, client_secret, refresh_token]):
            return {}

        creds = Credentials(
            None, refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id, client_secret=client_secret
        )
        analytics = build("youtubeAnalytics", "v2", credentials=creds, static_discovery=False)

        end_date   = datetime.utcnow().strftime("%Y-%m-%d")
        start_date = (datetime.utcnow() - timedelta(days=28)).strftime("%Y-%m-%d")

        # Core engagement metrics — all valid in Analytics API v2 for channel owners.
        # Do NOT add CTR here: it only exists in Reporting API v1 (async CSV jobs).
        resp = analytics.reports().query(
            ids="channel==MINE",
            startDate=start_date,
            endDate=end_date,
            metrics="views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,subscribersGained,subscribersLost",
            dimensions="",
        ).execute()

        rows = resp.get("rows", [])
        if not rows:
            return {}

        row = rows[0]
        return {
            "views":              int(row[0])   if len(row) > 0 else 0,
            "watch_minutes":      float(row[1]) if len(row) > 1 else 0,
            "avg_view_duration":  float(row[2]) if len(row) > 2 else 0,
            "avg_view_pct":       float(row[3]) if len(row) > 3 else 0,
            "subscribers_gained": int(row[4])   if len(row) > 4 else 0,
            "subscribers_lost":   int(row[5])   if len(row) > 5 else 0,
        }

    except Exception as e:
        err_str = str(e)
        if "403" in err_str or "disabled" in err_str.lower():
            logger.error(
                f"Analytics metrics fetch failed — YouTube Analytics API not enabled "
                f"in GCP project. Enable it at: "
                f"https://console.developers.google.com/apis/api/youtubeanalytics.googleapis.com/overview "
                f"| Error: {e}"
            )
            return {"_api_unavailable": True}
        elif "400" in err_str or "unknown identifier" in err_str.lower():
            logger.error(f"Analytics metrics fetch failed — bad API request: {e}")
            return {"_api_bad_request": True}
        logger.error(f"Analytics metrics fetch failed (non-fatal): {e}")
        return {}





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
        
        youtube = None if TEST_MODE else get_youtube_client(channel)
        if not youtube and not TEST_MODE:
            continue

        try:
            if TEST_MODE:
                ch_stats    = {"views": 15000, "subs": 1200, "videos": 45}
                recent_vids = [{"title": "Test Video Performance", "views": 5000, "published_at": datetime.utcnow().isoformat()}]
                analytics   = {}
            else:
                ch_stats    = _fetch_channel_stats(youtube)
                recent_vids = _fetch_recent_video_stats(youtube, channel.channel_id)
                analytics   = _fetch_analytics_metrics(channel.channel_id)

            views   = ch_stats["views"]
            subs    = ch_stats["subs"]

            # ── Analytics metrics (28-day) ────────────────────────────────────
            avg_view_pct     = analytics.get("avg_view_pct", 0.0)
            avg_view_sec     = analytics.get("avg_view_duration", 0.0)
            watch_minutes    = analytics.get("watch_minutes", 0.0)
            subs_gained      = analytics.get("subscribers_gained", 0)
            subs_lost        = analytics.get("subscribers_lost", 0)

            # Log analytics so they're visible in Actions output
            if analytics:
                print(
                    f"📊 [ANALYTICS] {channel.channel_name} (28d): "
                    f"Retention={avg_view_pct:.1f}% | AvgDuration={avg_view_sec:.1f}s | "
                    f"WatchTime={watch_minutes:,.0f}min | Subs={subs_gained}-{subs_lost}"
                )

            recent_7d  = db.get_recent_performance(channel.channel_id, days=7)
            growth_7d  = sum(v["views"] for v in recent_7d)

            intel = db.get_channel_intelligence(channel.channel_id)
            ts = intel.get("rule_timestamps", {})

            intel["emphasize"], emp_ts = _apply_time_decay(intel["emphasize"], ts, "emp", decay_days)
            intel["avoid"], avo_ts     = _apply_time_decay(intel["avoid"], ts, "avo", decay_days)
            ts.update(emp_ts)
            ts.update(avo_ts)

            top_videos_str = "\n".join([f"- '{v['title']}' | {v['views']:,} views" for v in recent_vids[:3]]) or "No data yet"

            # ── Build analytics context block for the analyst prompt ──────────
            analytics_block = ""
            real_analytics = {k: v for k, v in analytics.items() if not k.startswith("_api_")}
            if real_analytics:
                retention_diagnosis = (
                    "🔴 LOW (<40%) — pacing too slow or hook weak, viewers leaving early." if avg_view_pct < 40 else
                    "🟡 AVERAGE (40–70%) — decent but improve script structure."            if avg_view_pct < 70 else
                    "🟢 STRONG (>70%) — viewers watching most of the video."
                )
                net_subs = subs_gained - subs_lost
                subs_diagnosis = "Growing" if net_subs > 0 else ("Shrinking" if net_subs < 0 else "Flat")

                analytics_block = (
                    f"\n\n📊 ANALYTICS (last 28 days):\n"
                    f"- Average retention: {avg_view_pct:.1f}% → {retention_diagnosis}\n"
                    f"- Avg view duration: {avg_view_sec:.1f}s\n"
                    f"- Total watch time: {watch_minutes:,.0f} minutes\n"
                    f"- Subscribers: +{subs_gained} / -{subs_lost} (Net: {net_subs} - {subs_diagnosis})\n"
                    f"\nBased on these metrics, your new_emphasize and new_avoid rules MUST address "
                    f"the specific weaknesses above. If retention is low, focus on pacing and open loops."
                )

            sys_msg  = prompts_cfg["analyst"]["system_prompt"]
            user_msg = prompts_cfg["analyst"]["user_template"].format(
                views=views, subs=subs, current_strategy=intel["emphasize"][-2:],
                top_videos=top_videos_str, growth_7d=growth_7d,
                analytics_block=analytics_block
            )


            raw, _ = quota_manager.generate_text(user_msg, task_type="strategy", system_prompt=sys_msg)
            if raw:
                start = raw.find('{')
                end = raw.rfind('}')
                if start != -1 and end != -1 and end > start:
                    try:
                        new_rules = json.loads(raw[start:end+1])
                        now_iso   = datetime.utcnow().isoformat()

                        new_emp_raw = new_rules.get("new_emphasize", "")
                        if isinstance(new_emp_raw, list):
                            new_emp_raw = new_emp_raw[0] if new_emp_raw else ""
                        new_emp = str(new_emp_raw).strip() if new_emp_raw else ""

                        new_avo_raw = new_rules.get("new_avoid", "")
                        if isinstance(new_avo_raw, list):
                            new_avo_raw = new_avo_raw[0] if new_avo_raw else ""
                        new_avo = str(new_avo_raw).strip() if new_avo_raw else ""

                        if new_emp and new_emp not in ["[]", "{}", "['']", "[\"\"]", "None", "null"]:
                            intel["emphasize"].append(new_emp)
                            ts[f"emp_{len(intel['emphasize']) - 1}"] = now_iso
                            
                        if new_avo and new_avo not in ["[]", "{}", "['']", "[\"\"]", "None", "null"]:
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

                        new_tags_raw = new_rules.get("new_tags", [])
                        if isinstance(new_tags_raw, str):
                            new_tags = [t.strip() for t in new_tags_raw.split(",") if t.strip()]
                        elif isinstance(new_tags_raw, list):
                            new_tags = [str(t).strip() for t in new_tags_raw if str(t).strip()]
                        else:
                            new_tags = []

                        if new_tags:
                            combined = intel.get("recent_tags", []) + new_tags
                            intel["recent_tags"] = list(dict.fromkeys(combined))[-20:]
                    except Exception as e:
                        logger.error(f"Failed to parse Analyst JSON: {e}")

            # ── Persist sub count for growth phase detection ─────────────────
            # Stored inside rule_timestamps under a reserved key so no new
            # DB column is needed. The researcher reads this to pick strategy.
            ts = intel.get("rule_timestamps", {})
            ts["__sub_count__"]    = subs
            ts["__last_analyzed__"] = datetime.utcnow().isoformat()
            intel["rule_timestamps"] = ts

            # ── Update pillar performance stats ──────────────────────────────
            # Read pillar from each recent video's job metadata and tally views.
            # Stored in title_templates (repurposed) as a JSON dict.
            # Format: {"psychology": {"videos": 5, "total_views": 48000}}
            try:
                pillar_perf = intel.get("title_templates", {})
                if not isinstance(pillar_perf, dict):
                    pillar_perf = {}

                recent_jobs = db.get_jobs_by_state(
                    channel.channel_id, JobState.VAULTED, limit=50
                )
                for job in recent_jobs:
                    if not job.metadata:
                        continue
                    try:
                        jmeta  = json.loads(job.metadata)
                        pillar = jmeta.get("pillar", "")
                        if not pillar:
                            continue
                        # Look up views for this video from performance table
                        perf_rows = db.get_recent_performance(channel.channel_id, days=90)
                        job_views = next((r["views"] for r in perf_rows if job.topic and job.topic.lower() in r.get("title", "").lower()), 0)
                        if pillar not in pillar_perf:
                            pillar_perf[pillar] = {"videos": 0, "total_views": 0}
                        pillar_perf[pillar]["videos"]      += 1
                        pillar_perf[pillar]["total_views"] += job_views
                    except Exception:
                        continue

                intel["title_templates"] = pillar_perf  # repurposed field
                if pillar_perf:
                    top_pillar = max(pillar_perf, key=lambda k: pillar_perf[k].get("total_views", 0))
                    print(f"🏛️  [ANALYST] Top pillar: {top_pillar} "
                          f"({pillar_perf[top_pillar]['total_views']:,} views from "
                          f"{pillar_perf[top_pillar]['videos']} videos)")
            except Exception as e:
                logger.error(f"Pillar performance update failed (non-fatal): {e}")

            # ── Growth diagnosis ──────────────────────────────────────────────
            _print_growth_diagnosis(channel.channel_name, subs, analytics, growth_7d)

            db.upsert_channel_intelligence(channel.channel_id, intel)
            notify_daily_pulse(views, subs, growth_7d, intel, analytics)
            logger.success(f"Strategy updated for {channel.channel_name}.")

        except Exception as e:
            notify_error("Performance Analyst", type(e).__name__, str(e))
            logger.error(f"Analysis failed for {channel.channel_id}: {e}")

if __name__ == "__main__":
    run_daily_analysis()
