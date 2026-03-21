# scripts/music_manager.py — Ghost Engine V26.0.0
"""
Pixabay Music Library Manager.

Downloads copyright-free background music tracks (CC0 license) from Pixabay
into the assets/music/ folder structure. Runs as part of the weekly audit
pipeline to keep the local library fresh without downloading on every video.

Usage:
    python -m scripts.music_manager          # seed all mood folders
    python -m scripts.music_manager --check  # report current library state only

Pixabay API: https://pixabay.com/api/music/
License: All Pixabay music is CC0 — no attribution required, free commercial use,
         safe for YouTube monetization (no copyright claims).
"""
import os
import sys
import json
import time
import random
import shutil
import subprocess
import traceback
import requests

from engine.config_manager import config_manager
from engine.logger import logger

_ROOT_DIR   = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_MUSIC_ROOT = os.path.join(_ROOT_DIR, "assets", "music")
_PIXABAY_API_BASE = "https://pixabay.com/api/music/"

# ─── Mood → Pixabay search query mapping ─────────────────────────────────────
# Multiple queries per mood to get varied results across seeding runs.
# Pixabay music API accepts: q (keyword), category (optional), per_page (1-200)
MOOD_SEARCH_QUERIES = {
    "cinematic_sad": [
        "cinematic sad piano",
        "melancholic background music",
        "emotional ambient instrumental",
    ],
    "dark_ambient": [
        "dark ambient atmospheric",
        "mystery tension background",
        "dark drone instrumental",
    ],
    "dark_phonk": [
        "dark phonk instrumental",
        "aggressive dark trap beat",
        "dark electronic background",
    ],
    "horror_drones": [
        "horror ambient suspense",
        "scary drone atmosphere",
        "dark suspense instrumental",
    ],
    "upbeat_curiosity": [
        "upbeat discovery adventure",
        "curious playful background",
        "light energetic instrumental",
    ],
}


def _get_api_key() -> str:
    """Return the Pixabay API key from environment."""
    return os.environ.get("PIXABAY_API_KEY", "")


def _search_pixabay_music(query: str, per_page: int = 8) -> list:
    """
    Search Pixabay music API and return a list of hit dicts.
    Returns empty list on any error — caller decides how to handle.
    """
    api_key = _get_api_key()
    if not api_key:
        return []

    params = {
        "key":      api_key,
        "q":        query,
        "per_page": per_page,
        "safesearch": "true",
    }

    try:
        resp = requests.get(_PIXABAY_API_BASE, params=params, timeout=20)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("hits", [])
        else:
            logger.error(f"[MUSIC] Pixabay search failed (HTTP {resp.status_code}): {query}")
            return []
    except Exception:
        logger.error(f"[MUSIC] Pixabay search exception for query '{query}':\n{traceback.format_exc()}")
        return []


def _extract_audio_url(hit: dict) -> str:
    """
    Extract the downloadable audio URL from a Pixabay music hit.
    Tries multiple field names defensively since the API can vary.
    """
    for field in ("audio", "audioUrl", "audioURL", "previewURL", "url"):
        val = hit.get(field)
        if val and isinstance(val, str) and val.startswith("http"):
            return val
    return ""


def _download_and_trim(audio_url: str, output_path: str, max_seconds: int = 90) -> bool:
    """
    Download an audio file from URL and trim it to max_seconds using FFmpeg.
    Encodes as 128 kbps MP3 (~1.4 MB for 90s — safe for GitHub storage).

    Returns True on success, False on any failure.
    """
    temp_path = output_path + ".tmp_raw"

    try:
        resp = requests.get(audio_url, timeout=60, stream=True)
        if resp.status_code != 200:
            logger.error(f"[MUSIC] Download failed (HTTP {resp.status_code}): {audio_url[:80]}")
            return False

        with open(temp_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        if not os.path.exists(temp_path) or os.path.getsize(temp_path) < 1000:
            logger.error(f"[MUSIC] Downloaded file too small or missing: {temp_path}")
            return False

        # Trim to max_seconds and re-encode as 128k MP3
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i",  temp_path,
                "-t",  str(max_seconds),
                "-c:a", "libmp3lame",
                "-b:a", "128k",
                "-ar",  "44100",
                output_path,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=120,
        )

        if result.returncode != 0:
            err = result.stderr.decode("utf-8", errors="replace")[:300]
            logger.error(f"[MUSIC] FFmpeg trim failed for {output_path}:\n{err}")
            return False

        if not os.path.exists(output_path) or os.path.getsize(output_path) < 5000:
            logger.error(f"[MUSIC] Trimmed file too small: {output_path}")
            return False

        size_kb = os.path.getsize(output_path) // 1024
        logger.success(f"[MUSIC] ✅ Downloaded & trimmed: {os.path.basename(output_path)} ({size_kb} KB)")
        return True

    except subprocess.TimeoutExpired:
        logger.error(f"[MUSIC] FFmpeg timed out for {output_path}")
        return False
    except Exception:
        logger.error(f"[MUSIC] Download/trim exception:\n{traceback.format_exc()}")
        return False
    finally:
        # Clean up temp raw file regardless of outcome
        if os.path.exists(temp_path):
            try: os.remove(temp_path)
            except Exception: pass


def download_mood_tracks(folder_name: str, query: str, tracks_needed: int) -> int:
    """
    Search Pixabay for `query`, download up to `tracks_needed` valid tracks
    into assets/music/{folder_name}/.

    Track filenames: track_0.mp3, track_1.mp3 (overwrites existing on refresh).
    Returns the number of tracks successfully downloaded.
    """
    folder_path = os.path.join(_MUSIC_ROOT, folder_name)
    os.makedirs(folder_path, exist_ok=True)

    hits = _search_pixabay_music(query, per_page=min(tracks_needed * 4, 20))
    if not hits:
        logger.engine(f"[MUSIC] No results for query '{query}'. Skipping {folder_name}.")
        return 0

    # Shuffle hits so repeated runs get variety
    random.shuffle(hits)

    downloaded = 0
    for hit in hits:
        if downloaded >= tracks_needed:
            break

        audio_url = _extract_audio_url(hit)
        if not audio_url:
            continue

        track_title = hit.get("title", "unknown")[:50]
        out_path    = os.path.join(folder_path, f"track_{downloaded}.mp3")

        logger.engine(f"[MUSIC] Downloading: '{track_title}' → {folder_name}/track_{downloaded}.mp3")
        success = _download_and_trim(audio_url, out_path, max_seconds=90)
        if success:
            downloaded += 1
        else:
            logger.engine(f"[MUSIC] Skipping '{track_title}' (download/trim failed).")

        # Polite pause between Pixabay requests
        time.sleep(1.5)

    return downloaded


def seed_music_library() -> dict:
    """
    Seed all mood folders in assets/music/ using Pixabay music API.
    Uses one randomly chosen search query per folder to get variety on each run.
    Skips any folder where tracks_per_mood = 0.

    Returns a summary dict: {folder_name: tracks_downloaded}
    """
    api_key = _get_api_key()
    if not api_key:
        logger.engine("[MUSIC] PIXABAY_API_KEY not set. Skipping music library seeding.")
        return {}

    settings     = config_manager.get_settings()
    music_cfg    = settings.get("music", {})
    tracks_needed = int(music_cfg.get("tracks_per_mood", 2))

    logger.engine(f"[MUSIC] Seeding music library — {tracks_needed} track(s) per mood folder...")

    summary = {}
    for folder_name, query_list in MOOD_SEARCH_QUERIES.items():
        # Randomly pick one query from the list — different results each weekly run
        query = random.choice(query_list)
        logger.engine(f"[MUSIC] Folder '{folder_name}' — query: '{query}'")

        count = download_mood_tracks(folder_name, query, tracks_needed)
        summary[folder_name] = count

        if count == 0:
            logger.engine(f"[MUSIC] ⚠️ No tracks downloaded for '{folder_name}'.")
        else:
            logger.success(f"[MUSIC] '{folder_name}' → {count} track(s) ready.")

        # Pause between folders to respect API rate limits
        time.sleep(2)

    return summary


def check_library_state() -> dict:
    """
    Report the current state of the music library without downloading anything.
    Returns {folder_name: [list of .mp3 filenames]}
    """
    state = {}
    for folder_name in MOOD_SEARCH_QUERIES:
        folder_path = os.path.join(_MUSIC_ROOT, folder_name)
        if os.path.isdir(folder_path):
            mp3s = [f for f in os.listdir(folder_path) if f.endswith(".mp3")]
            state[folder_name] = mp3s
        else:
            state[folder_name] = []
    return state


def print_library_report():
    """Print a human-readable report of the current music library state."""
    state = check_library_state()
    print("\n🎵 Music Library State:")
    print("─" * 40)
    total = 0
    for folder, tracks in state.items():
        status = f"{len(tracks)} track(s)" if tracks else "⚠️  EMPTY"
        print(f"  {folder:<22} → {status}")
        total += len(tracks)
    print("─" * 40)
    print(f"  Total tracks cached: {total}")
    print()


if __name__ == "__main__":
    if "--check" in sys.argv:
        print_library_report()
    else:
        print_library_report()
        logger.engine("[MUSIC] Starting Pixabay music library seeding...")
        result = seed_music_library()
        print("\n📦 Seeding complete:")
        for folder, count in result.items():
            print(f"  {folder}: {count} track(s) downloaded")
