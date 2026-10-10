"""
engine/managers/youtube_manager.py — SEO Director & Collision-Aware YouTube Release Manager (v2.0)
Harvests proven OAuth refresh flow. Checks schedule collisions using 1-unit low-quota queries,
uploads with one-shot publishAt scheduling (zero post-edits), and cleans up video artifacts.
"""

import os
import re
import json
import time
import random
import shutil
import pathlib
import subprocess
import yaml
from datetime import datetime, timezone, timedelta, date
dt = datetime
from typing import Optional, Dict, Any, List

try:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    _GOOGLE_API_AVAILABLE = True
except ImportError:
    Credentials = None
    build = None
    MediaFileUpload = None
    _GOOGLE_API_AVAILABLE = False

from engine.logger import StageTimer, PikaStage, logger
from engine.managers.error_manager import ErrorManager
from engine.models import SpecOutput, ClipsManifest
from scripts.discord_notifier import notify_published


# ─── FFMPEG AVAILABILITY CHECK ────────────────────────────────────────────────
_FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None
if not _FFMPEG_AVAILABLE:
    print("⚠️ [YOUTUBE MANAGER] ffmpeg not found on PATH. Thumbnail extraction will be skipped.", flush=True)


# ─── SEO TITLE GENERATOR ─────────────────────────────────────────────────────

def _load_trend_terms(window_days: int = 1) -> List[str]:
    """
    Reads a cached trends CSV from data/yt_trends.csv (if present).
    CSV format: term,volume,date
    Returns the top 10 unique terms from the last `window_days` days.
    Falls back gracefully to an empty list if the file is missing.
    """
    trend_path = pathlib.Path("data") / "yt_trends.csv"
    if not trend_path.is_file():
        return []
    cutoff = date.today() - timedelta(days=window_days)
    counts: Dict[str, int] = {}
    try:
        with trend_path.open(encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split(",")
                if len(parts) < 3:
                    continue
                term, _, date_str = parts[0], parts[1], parts[2]
                try:
                    if date.fromisoformat(date_str) >= cutoff:
                        counts[term] = counts.get(term, 0) + 1
                except ValueError:
                    continue
    except Exception as e:
        print(f"⚠️ [SEO] Could not read trend data: {e}", flush=True)
        return []
    return [t for t, _ in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:10]]


def generate_seo_title(
    niche: str,
    base_title: str,
    script_text: str,
    cfg: Dict[str, Any]
) -> str:
    """
    Builds a trend-aware, keyword-driven, emoji-randomised title.

    Steps:
    1. Extract meaningful keywords from the script.
    2. Load recent trend terms from the CSV cache.
    3. Find the intersection (max 2 trending keywords).
    4. Apply the channel's style_template from title_settings.
    5. Append a random emoji from the emoji pool.

    Falls back gracefully to `base_title` if anything fails.
    """
    try:
        from engine.managers.pipeline_runner import extract_keywords
        keywords = extract_keywords(script_text, max_keywords=15)
    except Exception:
        keywords = []

    trend_terms = _load_trend_terms(cfg.get("trend_window_days", 1))
    trend_lower = {t.lower() for t in trend_terms}
    hot_terms = [kw for kw in keywords if kw.lower() in trend_lower][:2]

    # Pick an emoji from the pool (different each run for variety)
    emoji_pool: List[str] = cfg.get("emojis", ["👀", "🔴", "⚡️"])
    emoji = random.choice(emoji_pool) if emoji_pool else ""

    # Apply the style template (default: just the base title)
    tmpl: str = cfg.get("style_template", "{title}")
    try:
        title = tmpl.format(title=base_title, niche=niche, emoji=emoji)
    except KeyError:
        title = base_title

    # Append hot trend terms if found
    if hot_terms:
        trend_suffix = " & ".join(hot_terms)
        # Only append if it won't push past YouTube's 100-char title limit
        candidate = f"{title} – {trend_suffix}"
        if len(candidate) <= 100:
            title = candidate

    return title


# ─── FRAME-BASED THUMBNAIL EXTRACTOR ─────────────────────────────────────────

def extract_thumbnail(video_path: str, strategy: str = "first_frame", custom_path: str = "") -> Optional[str]:
    """
    Extracts a high-impact thumbnail from a rendered video using ffmpeg.

    Strategies:
    - hook_frame / first_frame: grab frame at t=1.2s (captures the bold yellow hook caption + active visual)
    - random_frame: grab a random frame within the first 10 seconds
    - custom_path: return the user-specified image path directly
    """
    if strategy == "custom_path" and custom_path:
        return custom_path if pathlib.Path(custom_path).is_file() else None

    if not shutil.which("ffmpeg"):
        return None

    if strategy in ("hook_frame", "first_frame"):
        t = 1.2
    else:
        t = round(random.uniform(0.5, 10.0), 2)

    out_path = str(pathlib.Path(video_path).with_suffix("")) + "_thumbnail.jpg"
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-nostats", "-loglevel", "error",
             "-ss", str(t), "-i", video_path,
             "-vframes", "1", "-q:v", "2", out_path],
            check=False, capture_output=True
        )
        if result.returncode == 0 and pathlib.Path(out_path).is_file():
            return out_path
    except Exception as e:
        print(f"⚠️ [THUMBNAIL] ffmpeg extraction failed: {e}", flush=True)
    return None


# ─── RANDOMISED UPLOAD SCHEDULER ─────────────────────────────────────────────

def schedule_upload_or_immediate(
    video_path: str,
    metadata: Dict[str, Any],
    upload_cfg: Dict[str, Any],
    yt_mgr: "YouTubeManager"
) -> Dict[str, Any]:
    """
    If `random_schedule` is True in upload_cfg, defers the upload by a random delay
    (within `schedule_window_hours`). Otherwise uploads immediately.

    The deferred path writes a pending-upload JSON file and exits cleanly.
    A separate trigger (e.g. the agent timer) will call `flush_pending_upload()`
    to actually execute the upload — the pipeline does NOT wait, so no 6-hour limit is hit.
    """
    if not upload_cfg.get("random_schedule", False):
        # Immediate upload path (returns result dict)
        return yt_mgr.upload_one_shot_scheduled_video(
            video_path=video_path,
            title=metadata.get("title", ""),
            description=metadata.get("description", ""),
            tags=metadata.get("tags", []),
            category_id=upload_cfg.get("category_id", "24"),
            default_language=upload_cfg.get("default_language", "en-US"),
            default_audio_language=upload_cfg.get("default_audio_language", "en-US"),
            contains_synthetic_media=upload_cfg.get("contains_synthetic_media", False),
            notify_subscribers=upload_cfg.get("notify_subscribers", False),
            public_stats_viewable=upload_cfg.get("public_stats_viewable", False),
            embeddable=upload_cfg.get("embeddable", True),
            license_type=upload_cfg.get("license", "youtube"),
            made_for_kids=upload_cfg.get("made_for_kids", False),
            thumbnail_path=metadata.get("thumbnail")
        )

    # Randomised deferred upload
    max_h = max(1, upload_cfg.get("schedule_window_hours", 4))
    delay_secs = random.randint(300, max_h * 3600)  # at least 5 min delay
    fire_at = dt.now(timezone.utc) + timedelta(seconds=delay_secs)
    fire_at_iso = fire_at.isoformat()

    pending = {
        "video_path": video_path,
        "metadata": metadata,
        "upload_cfg": upload_cfg,
        "fire_at": fire_at_iso,
        "delay_seconds": delay_secs,
    }

    os.makedirs("memory", exist_ok=True)
    pending_path = os.path.join("memory", "pending_upload.json")
    with open(pending_path, "w", encoding="utf-8") as f:
        json.dump(pending, f, indent=2)

    print(
        f"⏰ [UPLOAD] Random schedule enabled. Upload deferred by {delay_secs // 60} min "
        f"(fires at {fire_at_iso}). Saved to '{pending_path}'.",
        flush=True
    )
    return {
        "video_id": "deferred_scheduled",
        "publish_at": fire_at_iso,
        "title": metadata.get("title", "")
    }


def flush_pending_upload() -> bool:
    """
    Called by the agent timer trigger. Reads memory/pending_upload.json,
    checks if the scheduled time has arrived, and executes the upload.
    Returns True if an upload was executed, False otherwise.
    """
    pending_path = os.path.join("memory", "pending_upload.json")
    if not os.path.exists(pending_path):
        return False

    try:
        with open(pending_path, "r", encoding="utf-8") as f:
            pending = json.load(f)
    except Exception as e:
        print(f"⚠️ [UPLOAD] Could not read pending upload file: {e}", flush=True)
        return False

    fire_at = dt.fromisoformat(pending["fire_at"])
    if dt.now(timezone.utc) < fire_at:
        remaining = int((fire_at - dt.now(timezone.utc)).total_seconds())
        print(f"⏳ [UPLOAD] Not yet time. {remaining // 60} min remaining.", flush=True)
        return False

    meta = pending.get("metadata", {})
    cfg = pending.get("upload_cfg", {})
    yt_mgr = YouTubeManager()
    try:
        yt_mgr.upload_one_shot_scheduled_video(
            video_path=pending["video_path"],
            title=meta.get("title", ""),
            description=meta.get("description", ""),
            tags=meta.get("tags", []),
            category_id=cfg.get("category_id", "24"),
            default_language=cfg.get("default_language", "en-US"),
            default_audio_language=cfg.get("default_audio_language", "en-US"),
            contains_synthetic_media=cfg.get("contains_synthetic_media", False),
            notify_subscribers=cfg.get("notify_subscribers", False),
            public_stats_viewable=cfg.get("public_stats_viewable", False),
            embeddable=cfg.get("embeddable", True),
            license_type=cfg.get("license", "youtube"),
            made_for_kids=cfg.get("made_for_kids", False),
            thumbnail_path=meta.get("thumbnail")
        )
        os.remove(pending_path)
        print("✅ [UPLOAD] Pending upload executed and cleared.", flush=True)
        return True
    except Exception as e:
        print(f"❌ [UPLOAD] Upload failed: {e}", flush=True)
        return False




def is_test_mode() -> bool:
    """Returns True if TEST_MODE is active via environment variable."""
    return os.environ.get("TEST_MODE", "false").lower() == "true"


class YouTubeManager:
    """Manages YouTube OAuth authentication, collision detection, and one-shot scheduled uploads."""

    def __init__(self):
        self.client_id = os.environ.get("YOUTUBE_CLIENT_ID")
        self.client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
        self.refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN")

    def get_client(self):
        if is_test_mode():
            return None

        if not _GOOGLE_API_AVAILABLE:
            raise ImportError("Google API client is not installed. Install google-api-python-client and google-auth-oauthlib.")

        if not all([self.client_id, self.client_secret, self.refresh_token]):
            raise ValueError("Missing YouTube credentials in environment variables.")

        creds = Credentials(
            None,
            refresh_token=self.refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self.client_id,
            client_secret=self.client_secret
        )
        return build('youtube', 'v3', credentials=creds, static_discovery=False)

    @staticmethod
    def get_optimal_publish_hour() -> int:
        """
        Reads learned peak view velocity release hour from memory/channel_performance.json.
        Defaults to 18 (18:00 UTC) if no data has been collected yet.
        """
        perf_path = os.path.join("memory", "channel_performance.json")
        if os.path.exists(perf_path):
            try:
                with open(perf_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                hour = data.get("best_publish_hour")
                if isinstance(hour, int) and 0 <= hour <= 23:
                    return hour
            except Exception:
                pass
        return 18

    @staticmethod
    def generate_community_post(topic: str, hook: str, script_summary: str = "") -> Dict[str, Any]:
        """
        Generates an engaging subscriber discussion question, pinned comment, and Community Tab poll.
        """
        clean_hook = re.sub(r"[^\w\s\?]", "", hook).strip() if hook else topic
        clean_topic = topic.strip()

        # Dynamic, debative pinned comment that sparks comments & watch-time replay
        if hook:
            pinned_comment = f'"{hook}" — Did this one break your brain, or do you have a wilder perspective? Drop your thoughts below! 👇'
        else:
            pinned_comment = f"Which realization in this video broke your brain the most? Drop your perspective below! 👇"

        community_post = f"Quick reality check: {clean_hook}\n\nWhat's your take? Vote below or drop your mind-bending thought! 🧠"

        community_poll = {
            "question": f"Reality Check: {clean_topic} — Which realization broke your brain the most?",
            "options": [
                "My perspective is completely broken 🤯",
                "Already knew this one, drop a harder thought 👀",
                "Need 5 minutes to process this existence glitch 💀",
                "I have a wilder thought (check my comment) 👇"
            ],
            "channel_handle": "@metopato"
        }

        return {
            "pinned_comment": pinned_comment,
            "community_post": community_post,
            "community_poll": community_poll
        }

    def post_creator_comment(self, video_id: str, comment_text: str, youtube=None) -> Optional[str]:
        """
        Inserts a top-level creator comment on the uploaded video using YouTube Data API v3.
        Note: The official YouTube Data API does not expose a parameter to 'pin' a comment;
        pinning requires a creator tap in YouTube Studio UI, but inserting places it as top-level.
        """
        if is_test_mode():
            print(f"🧪 [TEST MODE] Bypassing YouTube API comment insert for {video_id}: '{comment_text[:50]}...'")
            return "test_comment_id"

        if not video_id or video_id == "deferred_scheduled":
            return None

        client = youtube or self.get_client()
        try:
            body = {
                "snippet": {
                    "videoId": video_id,
                    "topLevelComment": {
                        "snippet": {
                            "textOriginal": comment_text
                        }
                    }
                }
            }
            resp = client.commentThreads().insert(part="snippet", body=body).execute()
            comment_id = resp.get("id")
            print(f"💬 [YOUTUBE] Successfully posted creator engagement comment on video {video_id} (Comment ID: {comment_id})", flush=True)
            return comment_id
        except Exception as e:
            print(f"⚠️ [YOUTUBE] Could not post creator comment on video {video_id}: {e}", flush=True)
            return None

    def sync_channel_performance(self, youtube=None) -> Dict[str, Any]:
        """
        Queries recent published videos to track audience view velocity and engagement.
        Updates memory/channel_performance.json with learned peak hours and top topics.
        """
        perf_path = os.path.join("memory", "channel_performance.json")
        os.makedirs("memory", exist_ok=True)
        default_data = {
            "last_sync": datetime.now(timezone.utc).isoformat(),
            "best_publish_hour": 18,
            "top_topic": "shower thoughts and perceptual paradoxes",
            "videos_tracked": 0
        }

        if is_test_mode() or youtube is None:
            with open(perf_path, "w", encoding="utf-8") as f:
                json.dump(default_data, f, indent=2)
            return default_data

        try:
            ch_resp = youtube.channels().list(part="contentDetails", mine=True).execute()
            uploads_playlist_id = ch_resp["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
            items_resp = youtube.playlistItems().list(
                part="contentDetails,snippet",
                playlistId=uploads_playlist_id,
                maxResults=15
            ).execute()

            video_ids = [item["contentDetails"]["videoId"] for item in items_resp.get("items", [])]
            if not video_ids:
                return default_data

            vids_resp = youtube.videos().list(part="statistics,snippet", id=",".join(video_ids)).execute()
            items = vids_resp.get("items", [])

            best_hour = 18
            max_views = -1
            top_topic = "perceptual paradoxes"

            for v in items:
                stats = v.get("statistics", {})
                snippet = v.get("snippet", {})
                views = int(stats.get("viewCount", 0))
                pub_time = snippet.get("publishedAt", "")
                if pub_time and views > max_views:
                    max_views = views
                    top_topic = snippet.get("title", "")
                    try:
                        dt = datetime.fromisoformat(pub_time.replace("Z", "+00:00"))
                        best_hour = dt.hour
                    except Exception:
                        pass

            result = {
                "last_sync": datetime.now(timezone.utc).isoformat(),
                "best_publish_hour": best_hour,
                "top_topic": top_topic,
                "videos_tracked": len(items)
            }
            with open(perf_path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2)
            print(f"📊 [CHANNEL LEARNING] Synced {len(items)} videos. Peak hour: {best_hour}:00 UTC. Top topic: '{top_topic[:40]}...'", flush=True)
            return result
        except Exception as e:
            print(f"⚠️ [CHANNEL LEARNING] Performance sync skipped: {e}", flush=True)
            return default_data

    def calculate_collision_free_publish_time(self, youtube=None) -> str:
        """
        Determines the next optimal, collision-free scheduled publish time in the future.
        Features:
        1. Checks all currently scheduled videos on YouTube and identifies the last scheduled time.
        2. Enforces anti-cannibalization spacing (min_spacing_hours, e.g. 6.0h).
        3. Supports daily shorts volume strategy (shorts_per_day: 1, 2, 3, or 4).
        4. Researches own channel + competitor channels (@BrainBlud, etc.) + viral niche benchmarks.
        5. Uses negative minute jitter (e.g. -5 to -18 mins before the hour) to prime YouTube's CDN
           and recommendation index before peak viewer activity strikes.
        """
        now = datetime.now(timezone.utc)

        # 1. Load configuration from channel_config.yaml
        cfg = {}
        try:
            with open("config/channel_config.yaml", "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
        except Exception:
            pass

        upload_cfg = cfg.get("upload_settings", {})
        shorts_per_day = max(1, int(upload_cfg.get("shorts_per_day", 1)))
        min_spacing_hours = float(upload_cfg.get("min_spacing_hours", 6.0))
        use_negative_jitter = bool(upload_cfg.get("use_negative_jitter", True))
        jitter_min = int(upload_cfg.get("jitter_minutes_min", 5))
        jitter_max = int(upload_cfg.get("jitter_minutes_max", 18))
        target_windows = upload_cfg.get("target_peak_windows_utc", [18, 22, 14, 1])

        # 2. Gather cross-channel niche timing intelligence
        from engine.managers.competitor_spy import CompetitorSpy
        timing_intel = CompetitorSpy.get_niche_timing_intel(
            youtube=youtube if not is_test_mode() else None,
            default_slots=target_windows
        )
        ranked_hours = timing_intel.get("ranked_hours", target_windows)

        # Select primary hours based on shorts_per_day
        selected_peak_hours = []
        for h in ranked_hours:
            if not selected_peak_hours:
                selected_peak_hours.append(h)
            else:
                if all(min((h - sh) % 24, (sh - h) % 24) >= min(4, int(min_spacing_hours - 1)) for sh in selected_peak_hours):
                    selected_peak_hours.append(h)
            if len(selected_peak_hours) >= max(shorts_per_day, 4):
                break
        if not selected_peak_hours:
            selected_peak_hours = target_windows

        # 3. Query existing scheduled videos on YouTube
        scheduled_dts = []
        if not is_test_mode() and youtube is not None:
            try:
                ch_resp = youtube.channels().list(part="contentDetails", mine=True).execute()
                uploads_playlist_id = ch_resp["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
                items_resp = youtube.playlistItems().list(
                    part="contentDetails",
                    playlistId=uploads_playlist_id,
                    maxResults=15
                ).execute()
                video_ids = [item["contentDetails"]["videoId"] for item in items_resp.get("items", [])]
                if video_ids:
                    vids_resp = youtube.videos().list(part="status", id=",".join(video_ids)).execute()
                    for vid in vids_resp.get("items", []):
                        pub_at = vid.get("status", {}).get("publishAt")
                        if pub_at:
                            try:
                                p_dt = datetime.fromisoformat(pub_at.replace("Z", "+00:00"))
                                if p_dt > now:
                                    scheduled_dts.append(p_dt)
                            except Exception:
                                pass
            except Exception as e:
                print(f"⚠️ [SCHEDULER] Could not fetch current upload schedule: {e}", flush=True)

        # 4. Determine earliest allowed schedule reference point
        min_future_buffer = now + timedelta(minutes=45)

        if scheduled_dts:
            last_scheduled_dt = max(scheduled_dts)
            earliest_allowed = max(min_future_buffer, last_scheduled_dt + timedelta(hours=min_spacing_hours))
            print(
                f"🗓️  [SCHEDULER] Found {len(scheduled_dts)} queued video(s). "
                f"Last scheduled: {last_scheduled_dt.strftime('%Y-%m-%d %H:%M UTC')}. "
                f"Next slot must be after: {earliest_allowed.strftime('%Y-%m-%d %H:%M UTC')} "
                f"(anti-cannibalization buffer: {min_spacing_hours}h).",
                flush=True
            )
        else:
            earliest_allowed = min_future_buffer
            print(f"🗓️  [SCHEDULER] No pending scheduled videos. Earliest allowed slot: {earliest_allowed.strftime('%Y-%m-%d %H:%M UTC')}.", flush=True)

        # 5. Scan forward from earliest_allowed for the optimal peak slot
        candidate_date = earliest_allowed.date()
        chosen_time = None

        for _ in range(30):
            daily_candidates = []
            for peak_hour in selected_peak_hours:
                if use_negative_jitter:
                    jitter_mins = random.randint(jitter_min, jitter_max)
                    dt_candidate = datetime(
                        candidate_date.year, candidate_date.month, candidate_date.day,
                        peak_hour, 0, 0, tzinfo=timezone.utc
                    ) - timedelta(minutes=jitter_mins)
                else:
                    jitter_mins = random.randint(10, 45)
                    dt_candidate = datetime(
                        candidate_date.year, candidate_date.month, candidate_date.day,
                        peak_hour, jitter_mins, 0, tzinfo=timezone.utc
                    )

                if dt_candidate >= earliest_allowed:
                    is_clear = True
                    for s_dt in scheduled_dts:
                        gap_h = abs((dt_candidate - s_dt).total_seconds()) / 3600.0
                        if gap_h < min_spacing_hours:
                            is_clear = False
                            break
                    if is_clear:
                        daily_candidates.append((dt_candidate, peak_hour, jitter_mins))

            if daily_candidates:
                daily_candidates.sort(key=lambda x: x[0])
                chosen_dt, peak_h, jit_m = daily_candidates[0]
                chosen_time = chosen_dt
                jit_str = f"-{jit_m}m CDN prime jitter" if use_negative_jitter else f"+{jit_m}m jitter"
                print(
                    f"🎯 [SCHEDULER] Optimal slot selected: {chosen_dt.strftime('%Y-%m-%d %H:%M UTC')} "
                    f"(Target peak: {peak_h:02d}:00 UTC with {jit_str}, cadence: {shorts_per_day} short(s)/day).",
                    flush=True
                )
                break

            candidate_date += timedelta(days=1)

        if chosen_time is None:
            chosen_time = earliest_allowed + timedelta(hours=min_spacing_hours)

        return chosen_time.strftime("%Y-%m-%dT%H:%M:%SZ")

    def upload_one_shot_scheduled_video(
        self,
        video_path: str,
        title: str,
        description: str,
        tags: List[str],
        category_id: str = "24",
        default_language: str = "en-US",
        default_audio_language: str = "en-US",
        contains_synthetic_media: bool = False,
        notify_subscribers: bool = False,
        public_stats_viewable: bool = False,
        embeddable: bool = True,
        license_type: str = "youtube",
        made_for_kids: bool = False,
        thumbnail_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Executes a single-transaction scheduled upload with full SEO and rich channel metadata.
        Explicitly never updates or touches the video post-upload.
        """
        if is_test_mode():
            publish_at_iso = self.calculate_collision_free_publish_time(None)
            print(f"🧪 [TEST MODE] Bypassing YouTube API upload. Simulated publishAt: {publish_at_iso}")
            return {
                "video_id": "test_mode_dummy_video_id",
                "publish_at": publish_at_iso,
                "title": title
            }

        youtube = self.get_client()
        publish_at_iso = self.calculate_collision_free_publish_time(youtube)

        print(f"📦 [YOUTUBE] Uploading video with publishAt: {publish_at_iso}...")

        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": str(category_id),
                "defaultLanguage": default_language,
                "defaultAudioLanguage": default_audio_language,
            },
            "status": {
                "privacyStatus": "private",
                "publishAt": publish_at_iso,
                "selfDeclaredMadeForKids": made_for_kids,
                "embeddable": embeddable,
                "publicStatsViewable": public_stats_viewable,
                "license": license_type
            }
        }
        if contains_synthetic_media is not None:
            body["status"]["containsSyntheticMedia"] = bool(contains_synthetic_media)

        media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True, chunksize=1024 * 1024 * 5)
        try:
            request = youtube.videos().insert(
                part="snippet,status",
                body=body,
                media_body=media,
                notifySubscribers=bool(notify_subscribers)
            )
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    print(f"📤 [YOUTUBE] Upload Progress: {int(status.progress() * 100)}%")
        except Exception as e:
            # Fallback if containsSyntheticMedia is rejected by older API schemas
            if "containsSyntheticMedia" in str(e) and "containsSyntheticMedia" in body.get("status", {}):
                print("⚠️ [YOUTUBE] Retrying upload without containsSyntheticMedia field...", flush=True)
                body["status"].pop("containsSyntheticMedia", None)
                request = youtube.videos().insert(
                    part="snippet,status",
                    body=body,
                    media_body=media,
                    notifySubscribers=bool(notify_subscribers)
                )
                response = None
                while response is None:
                    status, response = request.next_chunk()
                    if status:
                        print(f"📤 [YOUTUBE] Upload Progress: {int(status.progress() * 100)}%")
            else:
                raise e

        video_id = response.get("id")
        print(f"✅ [YOUTUBE] Video uploaded and scheduled! Video ID: {video_id}")

        # Upload custom thumbnail if available
        if thumbnail_path and os.path.exists(thumbnail_path):
            try:
                print(f"🖼️ [THUMBNAIL] Uploading custom thumbnail from '{thumbnail_path}' for video {video_id}...", flush=True)
                thumb_media = MediaFileUpload(thumbnail_path, mimetype="image/jpeg")
                youtube.thumbnails().set(videoId=video_id, media_body=thumb_media).execute()
                print(f"✅ [THUMBNAIL] Custom thumbnail uploaded successfully for {video_id}!", flush=True)
            except Exception as ex:
                print(f"⚠️ [THUMBNAIL] Custom thumbnail upload notice: {ex}. (YouTube default frame retained).", flush=True)

        return {
            "video_id": video_id,
            "publish_at": publish_at_iso,
            "title": title
        }


def run_release_stage() -> None:
    """Executes Stage 4: 📦 YouTube Release."""
    spec_path = os.path.join("output", "spec.json")
    with open(spec_path, "r", encoding="utf-8") as f:
        spec = SpecOutput.model_validate_json(f.read())

    video_path = os.path.join("output", "final_render.mp4")
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Final render not found at '{video_path}'. Run Stage 3 first.")

    # Load upload settings from channel_config.yaml
    import yaml as _yaml
    with open("config/channel_config.yaml", "r", encoding="utf-8") as _f:
        _cc = _yaml.safe_load(_f) or {}
    upload_cfg = _cc.get("upload_settings", {})
    defaults = _cc.get("channel", {}).get("upload_defaults", {})
    for k, v in defaults.items():
        upload_cfg.setdefault(k, v)

    is_short = (spec.video_type == "short")

    # Resolve notification setting per video type (disabled for Shorts, enabled for Long form)
    notify_subs = upload_cfg.get(
        "notify_subscribers_shorts" if is_short else "notify_subscribers_long",
        upload_cfg.get("notify_subscribers", not is_short)
    )

    # Resolve like count viewability per video type (hidden on Shorts to avoid low-like count bias)
    public_stats = upload_cfg.get(
        "public_stats_viewable_shorts" if is_short else "public_stats_viewable_long",
        upload_cfg.get("public_stats_viewable", not is_short)
    )

    upload_cfg["notify_subscribers"] = notify_subs
    upload_cfg["public_stats_viewable"] = public_stats
    upload_cfg["category_id"] = upload_cfg.get("category_id", "24")
    upload_cfg["default_language"] = upload_cfg.get("default_language", "en-US")
    upload_cfg["default_audio_language"] = upload_cfg.get("default_audio_language", "en-US")

    # Locate or extract thumbnail
    thumb_strategy = upload_cfg.get("thumbnail_strategy", "hook_frame")
    thumb_custom = upload_cfg.get("thumbnail_custom_path", "")
    thumbnail_path = extract_thumbnail(video_path, strategy=thumb_strategy, custom_path=thumb_custom)
    if not thumbnail_path or not os.path.exists(thumbnail_path):
        candidate = str(pathlib.Path(video_path).with_suffix("")) + "_thumbnail.jpg"
        if os.path.exists(candidate):
            thumbnail_path = candidate
        elif os.path.exists("output/thumbnail.jpg"):
            thumbnail_path = "output/thumbnail.jpg"

    if thumbnail_path and os.path.exists(thumbnail_path):
        print(f"🖼️  [THUMBNAIL] Found thumbnail for release: {thumbnail_path}", flush=True)

    # Merge evergreen brand tags with spec topic tags
    brand_tags = _cc.get("brand_tags", [])
    merged_tags = []
    seen_tags = set()
    for t in list(spec.seo.tags) + list(brand_tags):
        t_clean = t.strip()
        t_lower = t_clean.lower()
        if t_clean and t_lower not in seen_tags:
            seen_tags.add(t_lower)
            merged_tags.append(t_clean)

    # Cap total tags string to 490 characters (YouTube allows 500 max)
    final_tags = []
    char_count = 0
    for t in merged_tags:
        if char_count + len(t) + 1 <= 490:
            final_tags.append(t)
            char_count += len(t) + 1

    yt_mgr = YouTubeManager()

    with StageTimer(PikaStage.RELEASE, topic=spec.topic):
        metadata = {
            "title": spec.seo.title,
            "description": spec.seo.description,
            "tags": final_tags,
            "thumbnail": thumbnail_path,
        }

        upload_res = schedule_upload_or_immediate(
            video_path=video_path,
            metadata=metadata,
            upload_cfg=upload_cfg,
            yt_mgr=yt_mgr
        )

        video_id = upload_res.get("video_id") if isinstance(upload_res, dict) else None
        publish_time = upload_res.get("publish_at") if isinstance(upload_res, dict) else None

        # Auto-post creator engagement comment and save community poll artifact
        if video_id and video_id != "deferred_scheduled":
            comm_engagement = getattr(spec, "community_engagement", None)
            if not comm_engagement:
                hook_txt = spec.scenes[0].spoken_text if spec.scenes else spec.topic
                comm_engagement = YouTubeManager.generate_community_post(spec.topic, hook_txt)

            pinned_txt = comm_engagement.get("pinned_comment") if isinstance(comm_engagement, dict) else None
            if pinned_txt:
                yt_mgr.post_creator_comment(video_id=video_id, comment_text=pinned_txt)

            # Persist community engagement package for 1-click posting
            comm_payload = {
                "video_id": video_id,
                "video_title": spec.seo.title,
                "pinned_comment": pinned_txt,
                "community_post": comm_engagement.get("community_post") if isinstance(comm_engagement, dict) else "",
                "community_poll": comm_engagement.get("community_poll") if isinstance(comm_engagement, dict) else None,
                "published_at": publish_time or datetime.now(timezone.utc).isoformat()
            }
            try:
                os.makedirs("output", exist_ok=True)
                with open(os.path.join("output", "community_post.json"), "w", encoding="utf-8") as pf:
                    json.dump(comm_payload, pf, indent=2)
                print("📦 [COMMUNITY] Saved release Community Post & Poll in 'output/community_post.json'", flush=True)
            except Exception:
                pass

        # If immediate upload, notify Discord and clean up
        if not upload_cfg.get("random_schedule", False):
            notify_published(
                topic=spec.topic,
                video_id=video_id or "unknown",
                publish_time=publish_time or "scheduled"
            )

        # 3. Clean up heavy video file locally
        try:
            if os.path.exists(video_path):
                os.remove(video_path)
                print(f"🧹 [CLEANUP] Deleted local render '{video_path}' to free disk space.")
        except Exception:
            pass

