"""
engine/managers/stock_video_manager.py — Pexels & Pixabay Stock Video Sourcing Engine (v2.0)
Replaces all AI image generation. Queries video APIs, filters aspect ratios, and provides CDN URL auto-refresh.
"""

import os
import json
import requests
from typing import Optional, List, Dict, Any
from engine.logger import StageTimer, PikaStage, logger
from engine.managers.error_manager import ErrorManager
from engine.models import SpecOutput, ClipsManifest, ClipItem


class StockVideoManager:
    """Manages searching, ranking, and refreshing stock videos from Pexels and Pixabay."""

    def __init__(self):
        self.pexels_key = os.environ.get("PEXELS_API_KEY")
        self.pixabay_key = os.environ.get("PIXABAY_API_KEY")

    def search_video(self, query: str, orientation: str = "portrait", min_duration: float = 3.0) -> Optional[ClipItem]:
        """
        Searches Pexels first, falling back to Pixabay.
        Returns a ClipItem with download_url and video_id.
        """
        clip = None
        if self.pexels_key:
            try:
                clip = self._search_pexels(query, orientation=orientation, min_duration=min_duration)
            except Exception as e:
                print(f"⚠️ [STOCK] Pexels search failed for '{query}': {e}. Falling back to Pixabay...")

        if not clip and self.pixabay_key:
            try:
                clip = self._search_pixabay(query, orientation=orientation)
            except Exception as e:
                print(f"⚠️ [STOCK] Pixabay search failed for '{query}': {e}")

        # If specific query failed, try abstract motion fallback
        if not clip and query != "satisfying abstract motion 4k":
            print(f"🔄 [STOCK] Retrying query with universal abstract background for: '{query}'")
            return self.search_video("satisfying abstract motion 4k", orientation=orientation, min_duration=min_duration)

        return clip

    def _search_pexels(self, query: str, orientation: str = "portrait", min_duration: float = 3.0) -> Optional[ClipItem]:
        url = "https://api.pexels.com/videos/search"
        headers = {"Authorization": self.pexels_key}
        params = {
            "query": query,
            "orientation": orientation,
            "size": "medium",
            "per_page": 5
        }
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        videos = data.get("videos", [])

        for vid in videos:
            files = vid.get("video_files", [])
            # Find best HD file
            hd_files = [f for f in files if f.get("quality") == "hd" or (f.get("height", 0) >= 1280)]
            chosen = hd_files[0] if hd_files else (files[0] if files else None)

            if chosen and chosen.get("link"):
                return ClipItem(
                    scene_id=0,
                    query=query,
                    video_id=str(vid.get("id")),
                    download_url=chosen["link"],
                    provider="pexels",
                    duration=float(vid.get("duration", 5.0)),
                    width=chosen.get("width", 1080),
                    height=chosen.get("height", 1920)
                )
        return None

    def _search_pixabay(self, query: str, orientation: str = "portrait") -> Optional[ClipItem]:
        url = "https://pixabay.com/api/videos/"
        params = {
            "key": self.pixabay_key,
            "q": query,
            "per_page": 5
        }
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        hits = data.get("hits", [])

        for hit in hits:
            vids = hit.get("videos", {})
            # Prefer large or medium
            target = vids.get("large") or vids.get("medium") or vids.get("small")
            if target and target.get("url"):
                return ClipItem(
                    scene_id=0,
                    query=query,
                    video_id=str(hit.get("id")),
                    download_url=target["url"],
                    provider="pixabay",
                    duration=float(hit.get("duration", 5.0)),
                    width=target.get("width", 1080),
                    height=target.get("height", 1920)
                )
        return None

    def refresh_download_url(self, provider: str, video_id: str) -> Optional[str]:
        """Auto-refreshes signed CDN download link if HTTP 403 occurs."""
        print(f"🔄 [STOCK REFRESH] Refreshing expired CDN link for {provider} ID {video_id}...")
        try:
            if provider == "pexels" and self.pexels_key:
                url = f"https://api.pexels.com/videos/videos/{video_id}"
                headers = {"Authorization": self.pexels_key}
                resp = requests.get(url, headers=headers, timeout=10)
                if resp.status_code == 200:
                    files = resp.json().get("video_files", [])
                    return files[0].get("link") if files else None
            elif provider == "pixabay" and self.pixabay_key:
                url = "https://pixabay.com/api/videos/"
                params = {"key": self.pixabay_key, "id": video_id}
                resp = requests.get(url, params=params, timeout=10)
                if resp.status_code == 200:
                    hits = resp.json().get("hits", [])
                    if hits:
                        vids = hits[0].get("videos", {})
                        target = vids.get("large") or vids.get("medium")
                        return target.get("url") if target else None
        except Exception as e:
            print(f"⚠️ [STOCK REFRESH] Refresh failed: {e}")
        return None


def run_clips_stage() -> None:
    """Executes Stage 2: 🎬 Clip Generation."""
    spec_path = os.path.join("output", "spec.json")
    if not os.path.exists(spec_path):
        raise FileNotFoundError(f"Spec file not found at '{spec_path}'. Run Stage 1 first.")

    with open(spec_path, "r", encoding="utf-8") as f:
        spec = SpecOutput.model_validate_json(f.read())

    orientation = "portrait" if spec.video_type == "short" else "landscape"
    stock_mgr = StockVideoManager()
    manifest_clips = []

    with StageTimer(PikaStage.CLIPS, topic=spec.topic):
        print(f"🎬 [CLIPS] Sourcing stock videos for {len(spec.scenes)} scenes ({orientation})...")

        for scene in spec.scenes:
            query = scene.stock_video_query
            print(f"🔍 [CLIPS] Scene {scene.scene_id}: Querying '{query}'...")
            
            clip = stock_mgr.search_video(query, orientation=orientation, min_duration=scene.duration_seconds)
            if not clip:
                raise RuntimeError(f"Could not find any suitable stock video for query: '{query}'")

            clip.scene_id = scene.scene_id
            manifest_clips.append(clip)
            print(f"✅ [CLIPS] Scene {scene.scene_id}: Selected {clip.provider.upper()} ID {clip.video_id} ({clip.duration:.1f}s)")

        manifest = ClipsManifest(
            topic=spec.topic,
            video_type=spec.video_type,
            clips=manifest_clips
        )

        manifest_path = os.path.join("output", "clips_manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            f.write(manifest.model_dump_json(indent=2))

        print(f"📦 [CLIPS] Saved clips manifest to '{manifest_path}' with {len(manifest_clips)} clips.")

