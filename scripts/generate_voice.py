# scripts/generate_voice.py
# ═══════════════════════════════════════════════════════════════════════════════
# FIX #3 — Groq Orpheus fallback now respects the AI Director's voice choice
#
# BUG: When Kokoro failed and Groq Orpheus took over, it picked a RANDOM Groq
# voice from settings. The AI Director had already chosen a specific Kokoro
# voice to match the episode's psychological tone (e.g., am_adam for horror).
# The random Groq voice destroyed that intentional choice, creating audio
# inconsistency within a channel.
#
# FIX: Added KOKORO_TO_GROQ_MAP — a tone-based mapping from Kokoro voices to
# their closest Groq Orpheus equivalents. When Kokoro fails, the mapped voice
# is passed to Groq so the tonal direction is preserved.
#
#   am_adam   → daniel  (deep, authoritative male)
#   af_bella  → diana   (warm, storytelling female)
#   am_michael→ austin  (fast, punchy male — facts/hacks energy)
#   af_sarah  → hannah  (energetic, bright female — tech/pop-culture)
#
# If the target_voice is not in the map (e.g. a new voice added later),
# falls back to random as before — no hard failure.
# ═══════════════════════════════════════════════════════════════════════════════

import os
import json
import random
import re

if os.environ.get("HF_TOKEN"):
    os.environ["HUGGING_FACE_HUB_TOKEN"] = os.environ.get("HF_TOKEN")

import numpy as np
import soundfile as sf
from pydub import AudioSegment, effects
from scripts.groq_client import groq_client
from scripts.quota_manager import quota_manager
from engine.config_manager import config_manager

_KOKORO_PIPELINE = None
_WHISPER_MODEL   = None

# ── FIX #3: Tone-preserving voice mapping ────────────────────────────────────
# Maps every Kokoro voice to its closest Groq Orpheus equivalent by tone/gender.
KOKORO_TO_GROQ_MAP = {
    "am_adam":    "daniel",   # Deep/Serious male   → daniel  (Groq: deep male)
    "af_bella":   "diana",    # Warm/Storytelling   → diana   (Groq: warm female)
    "am_michael": "austin",   # Fast/Punchy male    → austin  (Groq: fast male)
    "af_sarah":   "hannah",   # Energetic/Bright    → hannah  (Groq: energetic female)
}


def get_kokoro_pipeline():
    global _KOKORO_PIPELINE
    if _KOKORO_PIPELINE is None:
        from kokoro import KPipeline
        _KOKORO_PIPELINE = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M")
    return _KOKORO_PIPELINE


def get_whisper_model():
    global _WHISPER_MODEL
    if _WHISPER_MODEL is None:
        from faster_whisper import WhisperModel
        _WHISPER_MODEL = WhisperModel("tiny.en", device="cpu", compute_type="int8")
    return _WHISPER_MODEL


def format_time(seconds):
    if seconds < 0:
        seconds = 0
    hours   = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs    = int(seconds % 60)
    millis  = int((seconds - int(seconds)) * 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def trim_audio_precision(file_path):
    try:
        audio = AudioSegment.from_file(file_path)
        if len(audio) > 200:
            audio = audio[200:]
        audio         = effects.normalize(audio)
        silence_start = AudioSegment.silent(duration=200, frame_rate=audio.frame_rate).set_channels(audio.channels)
        silence_end   = AudioSegment.silent(duration=500, frame_rate=audio.frame_rate).set_channels(audio.channels)
        final         = silence_start + audio + silence_end
        final.export(file_path, format="wav")
        return True, len(final) / 1000.0
    except Exception:
        return False, 0.0


def sanitize_for_tts(text):
    clean = re.sub(r"[^\w\s.,!?'\"\\-]", "", text)
    return re.sub(r"\s+", " ", clean).strip()


def generate_fallback_srt(text, duration, srt_path):
    try:
        words = [w.strip().upper() for w in text.split() if w.strip()]
        if not words:
            return False
        time_per_word = max(duration / len(words), 0.1)
        srt_lines     = []
        idx           = 1
        for i in range(0, len(words), 3):
            chunk = words[i : i + 3]
            start = i * time_per_word
            end   = min((i + len(chunk)) * time_per_word, duration)
            srt_lines.append(
                f"{idx}\n{format_time(start)} --> {format_time(end)}\n{' '.join(chunk)}\n"
            )
            idx += 1
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(srt_lines))
        return True
    except Exception:
        return False


def generate_audio(text, output_base="temp_audio", target_voice=None):
    global _KOKORO_PIPELINE
    final_wav      = f"{output_base}.wav"
    srt_path       = f"{output_base}.srt"
    success        = False
    provider       = "Unknown"
    sanitized_text = sanitize_for_tts(text)
    buffered_text  = f", {sanitized_text}"

    # ── Tier 1: Kokoro (local, ultra-realistic) ───────────────────────────────
    print(f"🎙️ [VOICE] AI Director requested voice: {target_voice}...")
    try:
        settings      = config_manager.get_settings()
        kokoro_voices = settings.get("voice_actors", {}).get("kokoro", ["am_adam"])
        chosen_voice  = target_voice if target_voice in kokoro_voices else random.choice(kokoro_voices)
        print(f"🎙️ [VOICE] Executing Kokoro with: {chosen_voice.upper()}")

        pipeline     = get_kokoro_pipeline()
        gen          = pipeline(buffered_text, voice=chosen_voice, speed=1.1, split_pattern=r"\n+")
        audio_chunks = [audio for _, _, audio in gen if audio is not None]

        if audio_chunks:
            sf.write(final_wav, np.concatenate(audio_chunks), 24000)
            success  = True
            provider = f"Kokoro ({chosen_voice})"
    except Exception as e:
        print(f"⚠️ [VOICE] Kokoro failed: {e}")
        _KOKORO_PIPELINE = None

    # ── Tier 2: Groq Orpheus (API fallback) ──────────────────────────────────
    if not success:
        print("🎙️ [VOICE] Kokoro failed. Switching to Groq Orpheus fallback...")

        # ── FIX #3: Map Kokoro voice → closest Groq equivalent ───────────────
        # Instead of picking randomly, look up the tonal equivalent first.
        settings    = config_manager.get_settings()
        groq_voices = settings.get("voice_actors", {}).get("groq", ["autumn"])

        mapped_voice = KOKORO_TO_GROQ_MAP.get(target_voice)          # try the map
        if mapped_voice and mapped_voice in groq_voices:
            groq_voice = mapped_voice
            print(f"🎙️ [VOICE] Tone-mapped {target_voice} → Groq voice: {groq_voice.upper()}")
        else:
            # New/unknown Kokoro voice or map entry not in settings — fall back to random
            groq_voice = random.choice(groq_voices)
            print(f"🎙️ [VOICE] No tone-map for '{target_voice}'. Using random Groq voice: {groq_voice.upper()}")
        # ─────────────────────────────────────────────────────────────────────

        if groq_client.generate_audio(buffered_text, final_wav, voice_override=groq_voice):
            success  = True
            provider = f"Groq Orpheus ({groq_voice})"

    if not success:
        return False, provider, 0.0

    trim_success, duration = trim_audio_precision(final_wav)
    if not trim_success:
        return False, provider, 0.0

    # ── Subtitle generation (Whisper → proportional fallback) ────────────────
    try:
        model             = get_whisper_model()
        segments, _       = model.transcribe(final_wav, word_timestamps=True)
        srt_lines         = []
        idx               = 1
        for segment in segments:
            chunk, chunk_start = [], None
            for word in segment.words:
                if chunk_start is None:
                    chunk_start = word.start
                chunk.append(word.word.strip().upper())
                if len(chunk) >= 3:
                    srt_lines.append(
                        f"{idx}\n{format_time(chunk_start)} --> {format_time(word.end)}\n{' '.join(chunk)}\n"
                    )
                    idx, chunk, chunk_start = idx + 1, [], None
            if chunk:
                srt_lines.append(
                    f"{idx}\n{format_time(chunk_start)} --> {format_time(segment.words[-1].end)}\n{' '.join(chunk)}\n"
                )
                idx += 1
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(srt_lines))
    except Exception:
        if not generate_fallback_srt(sanitized_text, duration, srt_path):
            return False, provider, 0.0

    return True, provider, duration
