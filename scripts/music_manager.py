# scripts/music_manager.py — Ghost Engine V7.3
"""
Background Music Library Manager & Procedural Ambient Synthesizer.

Key Features:
1. User-Supplied Music First: Automatically detects and prioritizes user-provided
   audio files (*.mp3, *.wav, *.m4a, *.aac, *.ogg) placed in assets/music/{mood}/.
2. Procedural Audio Synthesis Fallback: Pure Python standard library (wave, struct, math).
   If a mood folder is empty, synthesizes a broadcast-quality 44.1kHz stereo ambient pad/drone
   normalized to -24 dBFS with organic LFO breathing and stereo detuning.
3. Zero External API Dependency: Eliminates fragile web scraping and image API calls.
4. Total Fail-Safe: If music is missing or fails, the pipeline safely bypasses background
   music without crashing FFmpeg.
"""
import os
import sys

# Safe UTF-8 console output for Windows CLI environments
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import glob
import math
import struct
import wave
import random
import logging
from typing import Dict, List, Optional
from pathlib import Path

_ROOT_DIR   = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from engine.logger import logger

_MUSIC_ROOT = os.path.join(_ROOT_DIR, "assets", "music")

MOOD_FOLDERS = [
    "cinematic_sad",
    "dark_ambient",
    "dark_phonk",
    "horror_drones",
    "upbeat_curiosity",
]

AUDIO_EXTENSIONS = ("*.mp3", "*.wav", "*.m4a", "*.aac", "*.ogg")
SAMPLE_RATE = 44100


def synthesize_procedural_ambient(folder_path: str, mood: str, duration: float = 65.0) -> Optional[str]:
    """
    Synthesizes a seamless, low-gain ambient harmonic pad/drone loop.
    Completely offline, deterministic, zero external dependencies.
    """
    os.makedirs(folder_path, exist_ok=True)
    out_file = os.path.join(folder_path, "procedural_ambient.wav")

    # Chord frequencies (Hz) tailored to emotional tone
    mood_chords = {
        "cinematic_sad":   [110.0, 130.81, 164.81, 196.0, 246.94],     # Am9 (A2, C3, E3, G3, B3)
        "dark_ambient":    [55.0, 82.41, 110.0, 123.47],               # Deep sub + 5th + octave (A1, E2, A2, B2)
        "dark_phonk":      [43.65, 87.31, 130.81, 174.61],             # F1 sub + F2 + C3 + F3
        "horror_drones":   [65.41, 92.50, 116.54, 155.56],             # C2 + F#2 (tritone) + Bb2 + Eb3
        "upbeat_curiosity": [130.81, 164.81, 196.0, 246.94, 293.66],   # Cmaj9 (C3, E3, G3, B3, D4)
    }
    freqs = mood_chords.get(mood, mood_chords["cinematic_sad"])
    total_samples = int(SAMPLE_RATE * duration)

    try:
        with wave.open(out_file, "wb") as wav:
            wav.setnchannels(2)        # Stereo
            wav.setsampwidth(2)        # 16-bit PCM
            wav.setframerate(SAMPLE_RATE)

            block_size = 8192
            raw_bytes = bytearray()

            for n in range(total_samples):
                t = n / SAMPLE_RATE

                # 3s gentle fade-in, 4s smooth fade-out
                fade_in = min(1.0, t / 3.0)
                fade_out = min(1.0, (duration - t) / 4.0)
                envelope = fade_in * fade_out

                # Slow LFO modulation (0.12 Hz organic breathing effect)
                lfo = 0.85 + 0.15 * math.sin(2 * math.pi * 0.12 * t)

                left_sample = 0.0
                right_sample = 0.0

                for i, f in enumerate(freqs):
                    weight = 1.0 / (i + 1.25)
                    # Left channel: fundamental sine + soft overtone
                    left_sample += weight * (
                        math.sin(2 * math.pi * f * t) +
                        0.25 * math.sin(2 * math.pi * (f * 2) * t)
                    )
                    # Right channel: subtle chorus detune (+0.35 Hz) for stereo width
                    right_sample += weight * (
                        math.sin(2 * math.pi * (f + 0.35) * t) +
                        0.25 * math.sin(2 * math.pi * ((f * 2) + 0.5) * t)
                    )

                # Scale to ~ -24 dBFS (0.06 peak multiplier) so narration stays dominant
                left_val = int(max(-1.0, min(1.0, left_sample * 0.06 * envelope * lfo)) * 32767.0)
                right_val = int(max(-1.0, min(1.0, right_sample * 0.06 * envelope * lfo)) * 32767.0)

                raw_bytes.extend(struct.pack("<hh", left_val, right_val))

                if len(raw_bytes) >= block_size * 4:
                    wav.writeframes(raw_bytes)
                    raw_bytes.clear()

            if raw_bytes:
                wav.writeframes(raw_bytes)

        return out_file
    except Exception as e:
        logger.engine(f"⚠️ [MUSIC] Failed to synthesize procedural track for '{mood}': {e}")
        if os.path.exists(out_file):
            try:
                os.remove(out_file)
            except Exception:
                pass
        return None


def get_mood_tracks(folder_name: str) -> List[str]:
    """Return all valid audio files present in assets/music/{folder_name}/."""
    folder_path = os.path.join(_MUSIC_ROOT, folder_name)
    if not os.path.isdir(folder_path):
        return []

    tracks = []
    for ext in AUDIO_EXTENSIONS:
        tracks.extend(glob.glob(os.path.join(folder_path, ext)))

    # Filter out empty or corrupt files (< 4 KB)
    return [t for t in tracks if os.path.isfile(t) and os.path.getsize(t) > 4096]


def seed_music_library(force_synth: bool = False) -> Dict[str, int]:
    """
    Ensure all mood folders have background music.
    1. If user has already placed music files (*.mp3, *.wav, etc.), preserves them.
    2. If a folder is empty (or force_synth=True), synthesizes a procedural fallback.
    3. Never crashes or blocks the pipeline if anything fails.
    """
    logger.engine("[MUSIC] Auditing background music library...")
    summary: Dict[str, int] = {}

    for folder_name in MOOD_FOLDERS:
        folder_path = os.path.join(_MUSIC_ROOT, folder_name)
        os.makedirs(folder_path, exist_ok=True)

        existing_tracks = get_mood_tracks(folder_name)

        if existing_tracks and not force_synth:
            summary[folder_name] = len(existing_tracks)
            logger.engine(f"[MUSIC] '{folder_name}' has {len(existing_tracks)} user track(s). Preserved.")
            continue

        # If empty, synthesize procedural fallback
        try:
            logger.engine(f"[MUSIC] Synthesizing procedural fallback for '{folder_name}'...")
            track_path = synthesize_procedural_ambient(folder_path, folder_name, duration=65.0)
            if track_path and os.path.isfile(track_path) and os.path.getsize(track_path) > 10000:
                size_kb = os.path.getsize(track_path) // 1024
                logger.success(f"[MUSIC] ✅ {folder_name}/procedural_ambient.wav ({size_kb} KB ready)")
                summary[folder_name] = 1
            else:
                logger.engine(f"[MUSIC] ℹ️ Bypassed fallback for '{folder_name}'.")
                summary[folder_name] = 0
        except Exception as e:
            logger.engine(f"[MUSIC] ℹ️ Synthesis bypassed for '{folder_name}': {e}")
            summary[folder_name] = 0

    return summary


def check_library_state() -> Dict[str, List[str]]:
    """Inspect current music library state across all mood folders."""
    state = {}
    for folder_name in MOOD_FOLDERS:
        state[folder_name] = [os.path.basename(t) for t in get_mood_tracks(folder_name)]
    return state


def print_library_report():
    """Print human-readable summary of background music assets."""
    state = check_library_state()
    print("\n🎵 Background Music Library State:")
    print("─" * 45)
    total = 0
    for folder, tracks in state.items():
        if tracks:
            track_list = ", ".join(tracks[:2]) + (f" (+{len(tracks)-2} more)" if len(tracks) > 2 else "")
            print(f"  {folder:<20} → {len(tracks)} track(s) [{track_list}]")
            total += len(tracks)
        else:
            print(f"  {folder:<20} → ⚠️  EMPTY (procedural fallback will engage)")
    print("─" * 45)
    print(f"  Total active tracks: {total}\n")


if __name__ == "__main__":
    if "--check" in sys.argv:
        print_library_report()
    elif "--synth-all" in sys.argv:
        print("[MUSIC] Forcing procedural synthesis for all mood folders...")
        seed_music_library(force_synth=True)
        print_library_report()
    else:
        print_library_report()
        res = seed_music_library()
        print("\n📦 Library check complete.")
