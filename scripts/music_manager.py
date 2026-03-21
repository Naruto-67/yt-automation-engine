# scripts/music_manager.py — Ghost Engine V26.0.0
"""
Pixabay Music Library Manager.

Downloads royalty-free background music tracks from Pixabay using the
standard image/video/music API with type=music parameter.

CORRECT ENDPOINT: https://pixabay.com/api/?key=...&type=music&...
WRONG ENDPOINT:   https://pixabay.com/api/music/  ← this does not exist

Pixabay music is completely free: no attribution required, no copyright
claims, safe for commercial use and monetized YouTube videos.

Usage:
    python -m scripts.music_manager          # seed all mood folders
    python -m scripts.music_manager --check  # report current library state only
"""
import os
import sys
import time
import random
import subprocess
import traceback
import requests

from engine.config_manager import config_manager
from engine.logger import logger

_ROOT_DIR   = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_MUSIC_ROOT = os.path.join(_ROOT_DIR, "assets", "music")

# Correct Pixabay API endpoint — same base URL used for images/videos
_PIXABAY_API_BASE = "https://pixabay.com/api/"

# ── Mood → Pixabay search query mapping ───────────────────────────────────────
# Multiple queries per mood — random selection each weekly run for variety.
MOOD_SEARCH_QUERIES = {
    "cinematic_sad": [
        "cinematic sad",
        "melancholic piano",
        "emotional ambient",
    ],
    "dark_ambient": [
        "dark ambient",
        "mystery background",
        "atmospheric drone",
    ],
    "dark_phonk": [
        "dark phonk",
        "dark trap",
        "dark electronic",
    ],
    "horror_drones": [
        "horror ambient",
        "suspense horror",
        "dark suspense",
    ],
    "upbeat_curiosity": [
        "upbeat curious",
        "playful background",
        "light adventure",
    ],
}


def _get_api_key() -> str:
    """Return the Pixabay API key from environment."""
    return os.environ.get("PIXABAY_API_KEY", "")


def _search_pixabay_music(query: str, per_page: int = 8) -> list:
    """
    Search Pixabay for music tracks using type=music parameter.
    Returns list of hit dicts, empty list on any error.

    Key difference from image search: type=music returns audio files
    with a 'audio' field containing the direct download URL.
    """
    api_key = _get_api_key()
    if not api_key:
        return []

    params = {
        "key":        api_key,
        "q":          query,
        "type":       "music",      # ← this is the correct way to search music
        "per_page":   per_page,
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
        logger.error(f"[MUSIC] Pixabay search exception for '{query}':\n{traceback.format_exc()}")
        return []


def _extract_audio_url(hit: dict) -> str:
    """
    Extract the downloadable audio URL from a Pixabay music hit.
    Tries multiple field names defensively.
    """
    for field in ("audio", "audioURL", "audioUrl", "previewURL", "url"):
        val = hit.get(field)
        if val and isinstance(val, str) and val.startswith("http"):
            return val
    return ""


def _download_and_trim(audio_url: str, output_path: str, max_seconds: int = 90) -> bool:
    """
    Download an audio file from URL and trim it to max_seconds using FFmpeg.
    Encodes as 128 kbps MP3.
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
            logger.error(f"[MUSIC] Downloaded file too small: {temp_path}")
            return False

        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i",   temp_path,
                "-t",   str(max_seconds),
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
            logger.error(f"[MUSIC] FFmpeg trim failed:\n{err}")
            return False

        if not os.path.exists(output_path) or os.path.getsize(output_path) < 5000:
            logger.error(f"[MUSIC] Trimmed file too small: {output_path}")
            return False

        size_kb = os.path.getsize(output_path) // 1024
        logger.success(f"[MUSIC] ✅ {os.path.basename(output_path)} ({size_kb} KB)")
        return True

    except subprocess.TimeoutExpired:
        logger.error(f"[MUSIC] FFmpeg timed out for {output_path}")
        return False
    except Exception:
        logger.error(f"[MUSIC] Download/trim exception:\n{traceback.format_exc()}")
        return False
    finally:
        if os.path.exists(temp_path):
            try: os.remove(temp_path)
            except: pass


def download_mood_tracks(folder_name: str, query: str, tracks_needed: int) -> int:
    """
    Search Pixabay for `query` with type=music, download up to `tracks_needed`
    valid tracks into assets/music/{folder_name}/.
    Returns the number of tracks successfully downloaded.
    """
    folder_path = os.path.join(_MUSIC_ROOT, folder_name)
    os.makedirs(folder_path, exist_ok=True)

    hits = _search_pixabay_music(query, per_page=min(tracks_needed * 4, 20))
    if not hits:
        logger.engine(f"[MUSIC] No results for query '{query}'. Skipping {folder_name}.")
        return 0

    random.shuffle(hits)

    downloaded = 0
    for hit in hits:
        if downloaded >= tracks_needed:
            break

        audio_url   = _extract_audio_url(hit)
        track_title = hit.get("title", "unknown")[:50]

        if not audio_url:
            continue

        out_path = os.path.join(folder_path, f"track_{downloaded}.mp3")
        logger.engine(f"[MUSIC] Downloading: '{track_title}' → {folder_name}/track_{downloaded}.mp3")

        success = _download_and_trim(audio_url, out_path, max_seconds=90)
        if success:
            downloaded += 1
        else:
            logger.engine(f"[MUSIC] Skipping '{track_title}' (download/trim failed).")

        time.sleep(1.0)

    return downloaded


def seed_music_library() -> dict:
    """
    Seed all mood folders using Pixabay music API (type=music).
    Randomly picks one search query per folder per run for variety.
    Returns {folder_name: tracks_downloaded}
    """
    api_key = _get_api_key()
    if not api_key:
        logger.engine("[MUSIC] PIXABAY_API_KEY not set. Skipping music library seeding.")
        return {}

    settings      = config_manager.get_settings()
    music_cfg     = settings.get("music", {})
    tracks_needed = int(music_cfg.get("tracks_per_mood", 2))

    logger.engine(f"[MUSIC] Seeding music library — {tracks_needed} track(s) per mood folder...")

    summary = {}
    for folder_name, query_list in MOOD_SEARCH_QUERIES.items():
        query = random.choice(query_list)
        logger.engine(f"[MUSIC] Folder '{folder_name}' — query: '{query}'")

        count = download_mood_tracks(folder_name, query, tracks_needed)
        summary[folder_name] = count

        if count == 0:
            logger.engine(f"[MUSIC] ⚠️ No tracks downloaded for '{folder_name}'.")
        else:
            logger.success(f"[MUSIC] '{folder_name}' → {count} track(s) ready.")

        time.sleep(2)

    return summary


def check_library_state() -> dict:
    """Report current state without downloading anything."""
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
