"""
engine/managers/youtube_manager.py — SEO Director & Collision-Aware YouTube Release Manager (v2.0)
Harvests proven OAuth refresh flow. Checks schedule collisions using 1-unit low-quota queries,
uploads with one-shot publishAt scheduling (zero post-edits), and cleans up video artifacts.
"""

import os
import json
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from engine.logger import StageTimer, PikaStage, logger
from engine.managers.error_manager import ErrorManager
from engine.models import SpecOutput
from scripts.discord_notifier import notify_published


class YouTubeManager:
    """Manages YouTube OAuth authentication, collision detection, and one-shot scheduled uploads."""

    def __init__(self):
        self.client_id = os.environ.get("YOUTUBE_CLIENT_ID")
        self.client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
        self.refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN")

    def get_client(self):
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

    def calculate_collision_free_publish_time(self, youtube) -> str:
        """
        Determines the optimal peak release window (18:00 UTC).
        Uses a 1-unit query to check scheduled uploads and increments +24 hours if a slot is occupied.
        """
        now = datetime.now(timezone.utc)
        # Target daily peak window: 18:00 UTC
        target_day = now.date()
        # If it's already past 16:00 UTC, schedule for tomorrow
        if now.hour >= 16:
            target_day += timedelta(days=1)

        candidate_time = datetime(target_day.year, target_day.month, target_day.day, 18, 0, 0, tzinfo=timezone.utc)

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

    yt_mgr = YouTubeManager()

    with StageTimer(PikaStage.RELEASE, topic=spec.topic):
        # 1. One-Shot Upload & Collision Scheduling
        result = yt_mgr.upload_one_shot_scheduled_video(
            video_path=video_path,
            title=spec.seo.title,
            description=spec.seo.description,
            tags=spec.seo.tags
        )

        video_id = result.get("video_id")
        publish_time = result.get("publish_at")

        # 2. Notify Discord
        notify_published(
            topic=spec.topic,
            video_id=video_id,
            publish_time=publish_time
        )

        # 3. Clean up heavy video file locally
        try:
            if os.path.exists(video_path):
                os.remove(video_path)
                print(f"🧹 [CLEANUP] Deleted local render '{video_path}' to free disk space.")
        except Exception:
            pass

