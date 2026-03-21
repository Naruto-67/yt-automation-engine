# scripts/music_manager.py — Ghost Engine V7.2
"""
Pixabay Music Library Manager.

Downloads royalty-free background music tracks from Pixabay using the
standard API with type=music parameter.

CORRECT ENDPOINT: https://pixabay.com/api/?key=...&type=music&...
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
_PIXABAY_API_BASE = "https://pixabay.com/api/"

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
    return os.environ.get("PIXABAY_API_KEY", "")


def _search_pixabay_music(query: str, per_page: int = 8) -> list:
    """Search Pixabay for music using type=music parameter."""
    api_key = _get_api_key()
    if not api_key:
        return []

    params = {
        "key":        api_key,
        "q":          query,
        "type":       "music",
        "per_page":   per_page,
        "safesearch": "true",
    }

    try:
        resp = requests.get(_PIXABAY_API_BASE, params=params, timeout=20)
        if resp.status_code == 200:
            data = resp.json()
            hits = data.get("hits", [])
            # Debug: log the field names of the first hit so we know the API structure
            if hits:
                first_keys = list(hits[0].keys())
                logger.engine(f"[MUSIC] API response fields: {first_keys}")
                logger.engine(f"[MUSIC] First hit sample: {hits[0]}")
            return hits
        else:
            logger.error(f"[MUSIC] Pixabay search failed (HTTP {resp.status_code}): {query}")
            return []
    except Exception:
        logger.error(f"[MUSIC] Pixabay search exception:\n{traceback.format_exc()}")
        return []


def _extract_audio_url(hit: dict) -> str:
    """
    Extract the audio URL from a Pixabay music hit.
    Tries all known field name variants.
    """
    # Try all possible field names — we'll log which one works
    candidates = [
        "audio",       # most likely for music type
        "audioURL",
        "audioUrl",
        "audio_url",
        "music",
        "musicURL",
        "download",
        "downloadURL",
        "previewURL",
        "preview",
        "url",
        "pageURL",
    ]
    for field in candidates:
        val = hit.get(field)
        if val and isinstance(val, str) and val.startswith("http"):
            logger.engine(f"[MUSIC] Found audio URL in field '{field}'")
            return val

    # Log all fields so we can see what's actually there
    logger.engine(f"[MUSIC] No audio URL found. Available fields: {list(hit.keys())}")
    return ""


def _extract_title(hit: dict) -> str:
    """Extract track title from hit, trying multiple field names."""
    for field in ("title", "name", "label", "tags"):
        val = hit.get(field)
        if val and isinstance(val, str):
            return val[:50]
    return f"track_{hit.get('id', 'unknown')}"


def _download_and_trim(audio_url: str, output_path: str, max_seconds: int = 90) -> bool:
    """
    Download an audio file from URL and trim to max_seconds using FFmpeg.
    Shows full FFmpeg error output for debugging.
    """
    temp_path = output_path + ".tmp_raw"

    try:
        resp = requests.get(audio_url, timeout=60, stream=True)
        if resp.status_code != 200:
            logger.error(f"[MUSIC] Download failed (HTTP {resp.status_code}): {audio_url[:80]}")
            return False

        content_type = resp.headers.get("content-type", "unknown")
        logger.engine(f"[MUSIC] Downloaded content-type: {content_type}")

        with open(temp_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        file_size = os.path.getsize(temp_path) if os.path.exists(temp_path) else 0
        logger.engine(f"[MUSIC] Downloaded file size: {file_size} bytes")

        if file_size < 1000:
            logger.error(f"[MUSIC] Downloaded file too small ({file_size} bytes)")
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
            # Show FULL FFmpeg error — not truncated — so we can see the real problem
            full_err = result.stderr.decode("utf-8", errors="replace")
            # Find the actual error line (starts with "Error" or is after the config dump)
            err_lines = [l for l in full_err.splitlines() if not l.startswith("  ") and "error" in l.lower()]
            short_err = "\n".join(err_lines[:5]) if err_lines else full_err[-500:]
            logger.error(f"[MUSIC] FFmpeg failed:\n{short_err}")
            return False

        if not os.path.exists(output_path) or os.path.getsize(output_path) < 5000:
            logger.error(f"[MUSIC] Output file too small")
            return False

        size_kb = os.path.getsize(output_path) // 1024
        logger.success(f"[MUSIC] ✅ {os.path.basename(output_path)} ({size_kb} KB)")
        return True

    except subprocess.TimeoutExpired:
        logger.error(f"[MUSIC] FFmpeg timed out")
        return False
    except Exception:
        logger.error(f"[MUSIC] Exception:\n{traceback.format_exc()}")
        return False
    finally:
        if os.path.exists(temp_path):
            try: os.remove(temp_path)
            except: pass


def download_mood_tracks(folder_name: str, query: str, tracks_needed: int) -> int:
    """Download up to tracks_needed tracks into assets/music/{folder_name}/."""
    folder_path = os.path.join(_MUSIC_ROOT, folder_name)
    os.makedirs(folder_path, exist_ok=True)

    hits = _search_pixabay_music(query, per_page=min(tracks_needed * 4, 20))
    if not hits:
        logger.engine(f"[MUSIC] No results for '{query}'. Skipping {folder_name}.")
        return 0

    random.shuffle(hits)

    downloaded = 0
    for hit in hits:
        if downloaded >= tracks_needed:
            break

        audio_url   = _extract_audio_url(hit)
        track_title = _extract_title(hit)

        if not audio_url:
            continue

        out_path = os.path.join(folder_path, f"track_{downloaded}.mp3")
        logger.engine(f"[MUSIC] Downloading: '{track_title}' → {folder_name}/track_{downloaded}.mp3")
        logger.engine(f"[MUSIC] URL: {audio_url[:100]}")

        success = _download_and_trim(audio_url, out_path, max_seconds=90)
        if success:
            downloaded += 1
        else:
            logger.engine(f"[MUSIC] Skipping '{track_title}'.")

        time.sleep(1.0)

    return downloaded


def seed_music_library() -> dict:
    """Seed all mood folders using Pixabay music API."""
    api_key = _get_api_key()
    if not api_key:
        logger.engine("[MUSIC] PIXABAY_API_KEY not set. Skipping.")
        return {}

    settings      = config_manager.get_settings()
    music_cfg     = settings.get("music", {})
    tracks_needed = int(music_cfg.get("tracks_per_mood", 2))

    logger.engine(f"[MUSIC] Seeding — {tracks_needed} track(s) per folder...")

    summary = {}
    for folder_name, query_list in MOOD_SEARCH_QUERIES.items():
        query = random.choice(query_list)
        logger.engine(f"[MUSIC] Folder '{folder_name}' — query: '{query}'")

        count = download_mood_tracks(folder_name, query, tracks_needed)
        summary[folder_name] = count

        if count == 0:
            logger.engine(f"[MUSIC] ⚠️ No tracks for '{folder_name}'.")
        else:
            logger.success(f"[MUSIC] '{folder_name}' → {count} track(s) ready.")

        time.sleep(2)

    return summary


def check_library_state() -> dict:
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
