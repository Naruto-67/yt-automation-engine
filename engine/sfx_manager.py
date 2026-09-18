"""
engine/sfx_manager.py — Contextual Sound Effects (SFX) Audio Layer

Manages and generates audio stems for YouTube Shorts transitions,
dramatic beats, and pattern interrupts.

Key Features:
1. Zero External Asset Dependency: Pure Python deterministic wave synthesis
   using `wave`, `struct`, and `math` (standard library). Automatically
   synthesizes broadcast-quality PCM WAV stems (whoosh, sub-drop, tick, riser)
   if external audio assets are missing.
2. FFmpeg Filtergraph Integration: Generates precise `adelay`, `volume`, and
   `amix` filter chains to inject transitional whooshes and bass drops at
   exact scene change timestamps without clipping narration.
3. Pattern Interrupt Support: Pairs a whoosh/swell with the initial 0-3s hook
   to maximize scroll-stopping retention.
"""

import os
import sys
import math
import wave
import struct
import random
import logging
from typing import List, Dict, Tuple, Optional
from pathlib import Path

logger = logging.getLogger("yt_engine.sfx_manager")

SAMPLE_RATE = 44100


class SFXManager:
    """Manages audio sound effects with procedural synthesis fallbacks."""

    def __init__(self, sfx_dir: Optional[str] = None):
        if sfx_dir is None:
            root = Path(__file__).resolve().parent.parent
            self.sfx_dir = root / "assets" / "audio" / "sfx"
        else:
            self.sfx_dir = Path(sfx_dir)

        self.sfx_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_default_stems()

    def _write_wav(self, path: Path, samples: List[float], channels: int = 1):
        """Writes floating point audio samples (-1.0 to 1.0) to a 16-bit PCM WAV."""
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(channels)
            wav.setsampwidth(2)  # 16-bit
            wav.setframerate(SAMPLE_RATE)
            
            raw_data = bytearray()
            for s in samples:
                # Clamp between -1.0 and 1.0
                clamped = max(-1.0, min(1.0, s))
                val = int(clamped * 32767.0)
                raw_data.extend(struct.pack("<h", val))
                if channels == 2:
                    raw_data.extend(struct.pack("<h", val))
                    
            wav.writeframes(raw_data)

    def synthesize_whoosh(self, output_path: Path, duration: float = 0.45):
        """Synthesizes an airy cinematic transitional whoosh."""
        total_samples = int(SAMPLE_RATE * duration)
        samples = []
        
        # Whoosh created with frequency-modulated sweeping noise + soft sine base
        rng = random.Random(42)  # Deterministic seed
        for n in range(total_samples):
            t = n / SAMPLE_RATE
            progress = t / duration  # 0.0 -> 1.0
            
            # Envelope: rises sharply to 0.45 then decays
            if progress < 0.45:
                env = math.sin((progress / 0.45) * (math.pi / 2))
            else:
                env = math.cos(((progress - 0.45) / 0.55) * (math.pi / 2))
            env = max(0.0, env) ** 1.8

            # Modulated center frequency (200Hz -> 1800Hz -> 300Hz)
            center_freq = 200.0 + 1600.0 * math.sin(progress * math.pi)
            carrier = math.sin(2.0 * math.pi * center_freq * t)
            
            # Filtered noise component
            noise = (rng.random() * 2.0 - 1.0)
            sample_val = (carrier * 0.35 + noise * 0.65) * env * 0.75
            samples.append(sample_val)

        self._write_wav(output_path, samples, channels=2)

    def synthesize_sub_drop(self, output_path: Path, duration: float = 0.85):
        """Synthesizes a deep 808-style cinematic sub-drop impact."""
        total_samples = int(SAMPLE_RATE * duration)
        samples = []
        
        # Sub drop sweeping from 85Hz down to 28Hz with exponential decay
        start_freq = 85.0
        end_freq = 28.0
        
        phase = 0.0
        for n in range(total_samples):
            t = n / SAMPLE_RATE
            progress = t / duration
            
            # Instantaneous frequency sweeping down
            freq = start_freq * math.exp(-2.2 * progress) + end_freq * (1.0 - progress)
            phase += 2.0 * math.pi * freq * (1.0 / SAMPLE_RATE)
            
            # Exponential decay envelope with punchy attack
            attack = min(1.0, t / 0.015)  # 15ms punchy attack
            decay = math.exp(-3.5 * progress)
            env = attack * decay
            
            # Slight harmonic saturation for warmth
            raw_sine = math.sin(phase)
            saturated = math.tanh(raw_sine * 1.4) * 0.8
            samples.append(saturated * env * 0.85)

        self._write_wav(output_path, samples, channels=2)

    def synthesize_tick(self, output_path: Path, duration: float = 0.06):
        """Synthesizes a high-frequency rhythmic tension tick."""
        total_samples = int(SAMPLE_RATE * duration)
        samples = []
        
        for n in range(total_samples):
            t = n / SAMPLE_RATE
            progress = t / duration
            env = math.exp(-35.0 * progress)
            # 2.4 kHz woodblock click
            val = math.sin(2.0 * math.pi * 2400.0 * t) * env * 0.6
            samples.append(val)

        self._write_wav(output_path, samples, channels=2)

    def synthesize_riser(self, output_path: Path, duration: float = 1.2):
        """Synthesizes a rising tension swell."""
        total_samples = int(SAMPLE_RATE * duration)
        samples = []
        
        rng = random.Random(99)
        phase = 0.0
        for n in range(total_samples):
            t = n / SAMPLE_RATE
            progress = t / duration
            
            # Pitch rises from 110Hz to 650Hz
            freq = 110.0 + 540.0 * (progress ** 2)
            phase += 2.0 * math.pi * freq * (1.0 / SAMPLE_RATE)
            
            # Exponential swell envelope
            env = progress ** 2.2
            
            # Tone + shimmery noise
            tone = math.sin(phase)
            shimmer = (rng.random() * 2.0 - 1.0) * 0.25
            samples.append((tone * 0.75 + shimmer) * env * 0.7)

        self._write_wav(output_path, samples, channels=2)

    def _ensure_default_stems(self):
        """Generates any missing default procedural stems."""
        stems = {
            "whoosh.wav": self.synthesize_whoosh,
            "sub_drop.wav": self.synthesize_sub_drop,
            "tick.wav": self.synthesize_tick,
            "riser.wav": self.synthesize_riser,
        }
        for filename, synth_func in stems.items():
            path = self.sfx_dir / filename
            if not path.exists() or path.stat().st_size < 1000:
                try:
                    synth_func(path)
                    logger.info(f"Synthesized procedural audio stem: {filename}")
                except Exception as e:
                    logger.warning(f"Could not synthesize {filename}: {e}")

    def get_stem_path(self, stem_name: str) -> Optional[str]:
        """Returns the absolute path to a named SFX stem."""
        clean_name = stem_name if stem_name.endswith(".wav") else f"{stem_name}.wav"
        target = self.sfx_dir / clean_name
        if target.exists():
            return str(target)
        
        # Try auto-generating if recognized
        generators = {
            "whoosh.wav": self.synthesize_whoosh,
            "sub_drop.wav": self.synthesize_sub_drop,
            "tick.wav": self.synthesize_tick,
            "riser.wav": self.synthesize_riser,
        }
        if clean_name in generators:
            generators[clean_name](target)
            return str(target)
            
        return None

    def build_sfx_filtergraph_chain(
        self,
        transition_timestamps: List[float],
        base_input_index: int,
        stem_type: str = "whoosh",
        volume: float = 0.22
    ) -> Tuple[List[str], str, str]:
        """
        Builds FFmpeg filtergraph segments to mix sound effects at specific timestamps.
        
        Args:
            transition_timestamps: List of seconds where SFX should trigger.
            base_input_index: The input index in FFmpeg args for this SFX audio file.
            stem_type: Name of stem ('whoosh', 'sub_drop', etc.)
            volume: Relative volume level (default 0.22 for subtle non-masking level).
            
        Returns:
            Tuple of:
            - inputs: Additional FFmpeg CLI inputs
            - filter_chunk: Complex filter string with adelay and amix
            - output_pad: The resulting audio pad name (e.g. '[sfx_mix]')
        """
        stem_path = self.get_stem_path(stem_type)
        if not stem_path or not transition_timestamps:
            return [], "", ""

        # Filter out transitions too close to the very end
        valid_ts = [ts for ts in transition_timestamps if ts >= 0.0]
        if not valid_ts:
            return [], "", ""

        inputs = ["-i", stem_path]
        
        # If single timestamp
        if len(valid_ts) == 1:
            delay_ms = int(valid_ts[0] * 1000)
            chunk = (
                f"[{base_input_index}:a]volume={volume},"
                f"adelay={delay_ms}|{delay_ms}[sfx_mix]"
            )
            return inputs, chunk, "[sfx_mix]"

        # Multiple timestamps: split stem, delay each, and amix together
        split_count = len(valid_ts)
        split_pads = [f"[sfx_s{i}]" for i in range(split_count)]
        delayed_pads = [f"[sfx_d{i}]" for i in range(split_count)]
        
        filter_lines = [
            f"[{base_input_index}:a]volume={volume},asplit={split_count}{''.join(split_pads)}"
        ]
        
        for i, ts in enumerate(valid_ts):
            delay_ms = max(0, int(ts * 1000))
            filter_lines.append(
                f"{split_pads[i]}adelay={delay_ms}|{delay_ms}{delayed_pads[i]}"
            )
            
        amix_line = f"{''.join(delayed_pads)}amix=inputs={split_count}:dropout_transition=2:normalize=0[sfx_mix]"
        filter_lines.append(amix_line)
        
        return inputs, ";".join(filter_lines), "[sfx_mix]"


# Singleton instance
sfx_manager = SFXManager()

