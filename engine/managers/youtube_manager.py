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
import datetime
import subprocess
from datetime import datetime as dt, timezone, timedelta
from typing import Optional, Dict, Any, List

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

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
    cutoff = datetime.date.today() - datetime.timedelta(days=window_days)
    counts: Dict[str, int] = {}
    try:
        with trend_path.open(encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split(",")
                if len(parts) < 3:
                    continue
                term, _, date_str = parts[0], parts[1], parts[2]
                try:
                    if datetime.date.fromisoformat(date_str) >= cutoff:
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
    Extracts a thumbnail from a rendered video using ffmpeg.

    Strategies:
    - first_frame: grab frame at t=0
    - random_frame: grab a random frame within the first 10 seconds
    - custom_path: return the user-specified image path directly

    Returns the path to the thumbnail image, or None if extraction failed.
    """
    if strategy == "custom_path" and custom_path:
        return custom_path if pathlib.Path(custom_path).is_file() else None

    if not _FFMPEG_AVAILABLE:
        return None

    t = 0.0 if strategy == "first_frame" else round(random.uniform(0.5, 10.0), 2)
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
) -> None:
    """
    If `random_schedule` is True in upload_cfg, defers the upload by a random delay
    (within `schedule_window_hours`). Otherwise uploads immediately.

    The deferred path writes a pending-upload JSON file and exits cleanly.
    A separate trigger (e.g. the agent timer) will call `flush_pending_upload()`
    to actually execute the upload — the pipeline does NOT wait, so no 6-hour limit is hit.
    """
    if not upload_cfg.get("random_schedule", False):
        # Immediate upload path (original behaviour preserved)
        yt_mgr.upload_one_shot_scheduled_video(
            video_path=video_path,
            title=metadata.get("title", ""),
            description=metadata.get("description", ""),
            tags=metadata.get("tags", []),
            category_id=upload_cfg.get("category_id", "27")
        )
        return

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
            category_id=cfg.get("category_id", "27")
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
    def generate_community_post(topic: str, hook: str, script_summary: str = "") -> Dict[str, str]:
        """
        Generates an engaging subscriber discussion question and pinned comment for retention.
        """
        clean_hook = re.sub(r"[^\w\s\?]", "", hook).strip() if hook else topic
        return {
            "pinned_comment": "Which one of these thoughts broke your brain the most? 👇",
            "community_post": f"Quick reality check: {clean_hook}\n\nWhat's your take? Vote below or drop your mind-bending thought! 🧠"
        }

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

    def calculate_collision_free_publish_time(self, youtube) -> str:
        """
        Determines the optimal peak release window (adaptive or 18:00 UTC).
        Uses a 1-unit query to check scheduled uploads and increments +24 hours if a slot is occupied.
        """
        now = datetime.now(timezone.utc)
        peak_hour = self.get_optimal_publish_hour()
        # Target daily peak window: adaptive peak_hour UTC
        target_day = now.date()
        # If it's already past 16:00 UTC, schedule for tomorrow
        if now.hour >= 16:
            target_day += timedelta(days=1)

        candidate_time = datetime(target_day.year, target_day.month, target_day.day, peak_hour, 0, 0, tzinfo=timezone.utc)

        if is_test_mode() or youtube is None:
            return candidate_time.strftime("%Y-%m-%dT%H:%M:%SZ")

        # 1-Unit Low-Quota Schedule Check: Get uploads playlist ID
        try:
            ch_resp = youtube.channels().list(part="contentDetails", mine=True).execute()
            uploads_playlist_id = ch_resp["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

            # Query recent 10 items from uploads playlist (1 unit cost)
            items_resp = youtube.playlistItems().list(
                part="contentDetails",
                playlistId=uploads_playlist_id,
                maxResults=10
            ).execute()

            video_ids = [item["contentDetails"]["videoId"] for item in items_resp.get("items", [])]
            occupied_slots = set()

            if video_ids:
                # Query videos status (1 unit cost)
                vids_resp = youtube.videos().list(part="status", id=",".join(video_ids)).execute()
                for vid in vids_resp.get("items", []):
                    pub_at = vid.get("status", {}).get("publishAt")
                    if pub_at:
                        # Parse date string
                        try:
                            dt = datetime.fromisoformat(pub_at.replace("Z", "+00:00"))
                            occupied_slots.add(dt.strftime("%Y-%m-%d"))
                        except Exception:
                            pass

            # Advance day by day if target slot is occupied
            while candidate_time.strftime("%Y-%m-%d") in occupied_slots:
                print(f"⚠️ [SCHEDULER] Slot {candidate_time.strftime('%Y-%m-%d 18:00 UTC')} is already scheduled. Incrementing +24h...")
                candidate_time += timedelta(days=1)

        except Exception as e:
            print(f"⚠️ [SCHEDULER] Could not check scheduled collisions ({e}). Using default optimal slot.")

        return candidate_time.strftime("%Y-%m-%dT%H:%M:%SZ")

    def upload_one_shot_scheduled_video(
        self,
        video_path: str,
        title: str,
        description: str,
        tags: List[str],
        category_id: str = "27"
    ) -> Dict[str, Any]:
        """
        Executes a single-transaction scheduled upload with full SEO.
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
                "categoryId": category_id
            },
            "status": {
                "privacyStatus": "private",
                "publishAt": publish_at_iso,
                "selfDeclaredMadeForKids": False
            }
        }

        media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True, chunksize=1024 * 1024 * 5)
        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                print(f"📤 [YOUTUBE] Upload Progress: {int(status.progress() * 100)}%")

        video_id = response.get("id")
        print(f"✅ [YOUTUBE] Video uploaded and scheduled! Video ID: {video_id}")

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
    upload_cfg.setdefault("category_id", _cc.get("channel", {}).get("upload_defaults", {}).get("category_id", "27"))

    # Extract thumbnail
    thumb_strategy = upload_cfg.get("thumbnail_strategy", "first_frame")
    thumb_custom = upload_cfg.get("thumbnail_custom_path", "")
    thumbnail_path = extract_thumbnail(video_path, strategy=thumb_strategy, custom_path=thumb_custom)
    if thumbnail_path:
        print(f"🖼️  [THUMBNAIL] Extracted thumbnail: {thumbnail_path}", flush=True)

    yt_mgr = YouTubeManager()

    with StageTimer(PikaStage.RELEASE, topic=spec.topic):
        metadata = {
            "title": spec.seo.title,
            "description": spec.seo.description,
            "tags": spec.seo.tags,
            "thumbnail": thumbnail_path,
        }

        schedule_upload_or_immediate(
            video_path=video_path,
            metadata=metadata,
            upload_cfg=upload_cfg,
            yt_mgr=yt_mgr
        )

        video_id = None
        publish_time = None

        # If immediate upload, notify Discord and clean up
        if not upload_cfg.get("random_schedule", False):
            # (upload already happened inside schedule_upload_or_immediate)
            # Notify Discord
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

