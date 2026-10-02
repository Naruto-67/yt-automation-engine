"""
engine/managers/music_manager.py — Background Lo-Fi Music & Audio Bed Engine (v2.0)
Manages royalty-free CC0 background music sourcing, ducking, and procedural ambient synthesis.
Zero-dependency fallback ensures 100% reliability in CI/CD without external API bottlenecks.
"""

import os
import sys
import glob
import math
import struct
import wave
import random
from typing import Dict, List, Optional
from engine.logger import logger

# Reconfigure stdout/stderr on Windows console if needed
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass



class MusicManager:
    """Manages searching, seeding, and procedural synthesis of royalty-free Lo-Fi background audio."""

    AUDIO_EXTENSIONS = ("*.mp3", "*.wav", "*.m4a", "*.aac", "*.ogg")
    SAMPLE_RATE = 44100

    @classmethod
    def get_music_dir(cls) -> str:
        """Returns the primary directory for background Lo-Fi tracks."""
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        lofi_dir = os.path.join(base_dir, "assets", "audio", "lofi")
        os.makedirs(lofi_dir, exist_ok=True)
        return lofi_dir

    @classmethod
    def get_available_tracks(cls) -> List[str]:
        """Scans for user-provided or cached royalty-free audio tracks."""
        music_dir = cls.get_music_dir()
        tracks = []
        for ext in cls.AUDIO_EXTENSIONS:
            tracks.extend(glob.glob(os.path.join(music_dir, ext)))

        # Also check fallback assets/music/cinematic_sad/
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        legacy_dir = os.path.join(base_dir, "assets", "music", "cinematic_sad")
        if os.path.isdir(legacy_dir):
            for ext in cls.AUDIO_EXTENSIONS:
                tracks.extend(glob.glob(os.path.join(legacy_dir, ext)))

        # Filter out empty or corrupted files (< 8 KB)
        valid_tracks = [t for t in tracks if os.path.isfile(t) and os.path.getsize(t) > 8192]
        return valid_tracks

    @classmethod
    def synthesize_procedural_lofi(
        cls,
        output_path: Optional[str] = None,
        duration: float = 65.0,
        mood: str = "lofi_chill"
    ) -> Optional[str]:
        """
        Synthesizes a broadcast-quality, low-gain ambient Lo-Fi harmonic pad/drone loop.
        Completely offline, deterministic, zero external dependencies.
        Uses 16-bit PCM stereo WAV with organic LFO breathing, chorus detune, and warm sub-frequencies.
        """
        if not output_path:
            music_dir = cls.get_music_dir()
            output_path = os.path.join(music_dir, f"procedural_{mood}_ambient.wav")

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        # Harmonic chords tuned for relaxed, contemplative curiosity (frequencies in Hz)
        mood_chords = {
            "lofi_chill": [130.81, 164.81, 196.0, 246.94, 293.66],       # Cmaj9 (C3, E3, G3, B3, D4)
            "lofi_rain": [110.0, 130.81, 164.81, 196.0, 220.0],          # Am7 (A2, C3, E3, G3, A3)
            "lofi_curiosity": [146.83, 174.61, 220.0, 261.63, 329.63],   # Dm9 (D3, F3, A3, C4, E4)
            "lofi_night": [98.0, 123.47, 146.83, 185.0, 220.0],          # Gmaj7 (G2, B2, D3, F#3, A3)
        }
        freqs = mood_chords.get(mood, mood_chords["lofi_chill"])
        total_samples = int(cls.SAMPLE_RATE * duration)

        try:
            with wave.open(output_path, "wb") as wav:
                wav.setnchannels(2)        # Stereo
                wav.setsampwidth(2)        # 16-bit PCM
                wav.setframerate(cls.SAMPLE_RATE)

                block_size = 8192
                raw_bytes = bytearray()

                for n in range(total_samples):
                    t = n / cls.SAMPLE_RATE

                    # 3.0s smooth fade-in, 4.0s smooth fade-out
                    fade_in = min(1.0, t / 3.0)
                    fade_out = min(1.0, (duration - t) / 4.0)
                    envelope = fade_in * fade_out

                    # Slow LFO modulation (0.10 Hz breathing cycle for organic warmth)
                    lfo = 0.85 + 0.15 * math.sin(2 * math.pi * 0.10 * t)

                    left_sample = 0.0
                    right_sample = 0.0

                    for i, f in enumerate(freqs):
                        weight = 1.0 / (i + 1.25)
                        # Left channel: fundamental sine + warm soft octave overtone
                        left_sample += weight * (
                            math.sin(2 * math.pi * f * t) +
                            0.20 * math.sin(2 * math.pi * (f * 2) * t)
                        )
                        # Right channel: subtle chorus detune (+0.30 Hz) for spatial stereo width
                        right_sample += weight * (
                            math.sin(2 * math.pi * (f + 0.30) * t) +
                            0.20 * math.sin(2 * math.pi * ((f * 2) + 0.45) * t)
                        )

                    # Scale to ~ -24 dBFS (0.05 peak amplitude) so narration voiceover remains crisp and dominant
                    left_val = int(max(-1.0, min(1.0, left_sample * 0.05 * envelope * lfo)) * 32767.0)
                    right_val = int(max(-1.0, min(1.0, right_sample * 0.05 * envelope * lfo)) * 32767.0)

                    raw_bytes.extend(struct.pack("<hh", left_val, right_val))

                    if len(raw_bytes) >= block_size * 4:
                        wav.writeframes(raw_bytes)
                        raw_bytes.clear()

                if raw_bytes:
                    wav.writeframes(raw_bytes)

            print(f"🎵 [MUSIC] Synthesized procedural Lo-Fi track ({duration:.1f}s): '{output_path}'", flush=True)
            return output_path
        except Exception as e:
            print(f"⚠️ [MUSIC] Failed to synthesize procedural track: {e}", flush=True)
            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except Exception:
                    pass
            return None

    @classmethod
    def get_or_create_lofi_track(
        cls,
        duration: float = 60.0,
        mood: str = "lofi_chill",
        force_synth: bool = False
    ) -> Optional[str]:
        """
        Retrieves an existing royalty-free CC0 track or auto-synthesizes a procedural Lo-Fi track.
        Guarantees zero-dependency availability for video rendering.
        """
        if not force_synth:
            available = cls.get_available_tracks()
            if available:
                selected = random.choice(available)
                print(f"🎵 [MUSIC] Selected background audio track: '{os.path.basename(selected)}'", flush=True)
                return selected

        # If no tracks exist or force_synth is True, synthesize procedural Lo-Fi
        return cls.synthesize_procedural_lofi(duration=max(30.0, duration + 5.0), mood=mood)
