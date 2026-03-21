# scripts/generate_voice.py
import os
import re
import random
import traceback

if os.environ.get("HF_TOKEN"):
    os.environ["HUGGING_FACE_HUB_TOKEN"] = os.environ["HF_TOKEN"]

_KOKORO_PIPELINE = None
_WHISPER_MODEL   = None


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


def format_time(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    h  = int(seconds // 3600)
    m  = int((seconds % 3600) // 60)
    s  = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def trim_audio_precision(file_path: str):
    """
    Intelligently trim leading silence from TTS audio.

    Strategy:
      1. Detect leading silence using pydub's detect_leading_silence()
         at -38 dBFS (was -45). Less aggressive — won't clip soft-onset
         phonemes like 'th', 'sh', 's', or breathy vowels.
      2. Only trim if meaningful silence exists, leaving a 100ms breath room
         before voice onset (was 30ms). This prevents the first phoneme from
         ever being cut — even when Kokoro has a near-silent onset.
      3. Trim capped at 400ms — never over-trim.
      4. Prepend 300ms silence at start (was 150ms) — gives the viewer a
         natural moment to read the scene before narration begins.
         Data from test videos: 150ms felt abrupt. 300ms feels professional.
      5. Append 500ms silence at end — natural tail for the last word.
      6. Normalize volume.

    Why -38 dBFS (not -45):
      Kokoro sometimes generates words starting with very soft onset
      (quiet 's', 'th', breathy vowels). At -45 dBFS the silence detector
      treats these as silence and clips them. At -38 dBFS we only trim
      genuine empty silence, never the start of a word.
    """
    from pydub import AudioSegment, effects, silence as pydub_silence
    try:
        audio = AudioSegment.from_file(file_path)

        # Detect leading silence — use -38 dBFS to avoid clipping soft phoneme onsets
        leading_silence_ms = pydub_silence.detect_leading_silence(
            audio, silence_threshold=-38.0
        )

        # Leave 100ms breath room before voice onset so no syllable gets clipped.
        # Cap trim at 400ms — if Kokoro generated >500ms silence, trim up to 400ms of it.
        breath_room_ms = 100
        trim_ms = max(0, min(leading_silence_ms - breath_room_ms, 400))
        if trim_ms > 0:
            audio = audio[trim_ms:]
            print(f"✂️  [VOICE] Trimmed {trim_ms}ms of leading silence (detected {leading_silence_ms}ms).")
        else:
            print(f"✂️  [VOICE] No trim needed (leading silence: {leading_silence_ms}ms).")

        audio = effects.normalize(audio)

        # 300ms lead silence: professional breathing room before first word
        # 500ms tail silence: natural decay after last word before video ends
        sil_start = AudioSegment.silent(duration=300, frame_rate=audio.frame_rate).set_channels(audio.channels)
        sil_end   = AudioSegment.silent(duration=500, frame_rate=audio.frame_rate).set_channels(audio.channels)

        final = sil_start + audio + sil_end
        final.export(file_path, format="wav")
        return True, len(final) / 1000.0

    except Exception as e:
        trace = traceback.format_exc()
        print(f"⚠️ [VOICE] Audio trim failed:\n{trace}")
        return False, 0.0


# ── Acronyms that TTS handles correctly and should NOT be title-cased ─────────
_KNOWN_ACRONYMS = {
    "DNA", "RNA", "NASA", "FBI", "CIA", "BBC", "CNN", "NFL", "NBA", "UFC",
    "USA", "UK", "EU", "UN", "WHO", "HIV", "AIDS", "ADHD", "PTSD",
    "CEO", "CFO", "CTO", "HR", "PR", "TV", "PC", "GPU", "CPU", "RAM",
    "DIY", "VIP", "ATM", "PIN", "PDF", "HTML", "CSS", "API", "URL",
    "STEM", "IQ", "GPA", "IRS", "DMV",
}

# Stage directions: ALL-CAPS label followed by colon — e.g. "INTENSE CLOSE-UP:", "CUT TO:"
# These are visual cues for the editor/viewer, never meant to be spoken aloud.
_STAGE_DIR_RE  = re.compile(r"(?<![.!?])\b[A-Z][A-Z\s\-]{2,}:\s*")
_ALLCAPS_RE    = re.compile(r"\b([A-Z]{2,})\b")


def _fix_caps_word(m: re.Match) -> str:
    word = m.group(1)
    if word in _KNOWN_ACRONYMS:
        return word          # NASA, DNA etc — TTS reads these fine as-is
    if len(word) <= 2:
        return word          # AI, OK, TV, US — leave short ones alone
    return word.title()      # CRICKET→Cricket, TICK→Tick, HERO→Hero


def sanitize_for_tts(text: str) -> str:
    # 1. Strip stage directions ("INTENSE CLOSE-UP:", "WIDE SHOT:", "CUT TO:")
    #    These are screenplay conventions — not words to be spoken.
    text = _STAGE_DIR_RE.sub("", text)
    # 2. Title-case remaining ALL-CAPS emphasis words so TTS reads them as
    #    whole words instead of spelling each letter (T-I-C-K → "Tick").
    text = _ALLCAPS_RE.sub(_fix_caps_word, text)
    # 3. Strip characters TTS engines choke on, collapse whitespace.
    clean = re.sub(r"[^\w\s.,!?'\"−]", "", text)
    return re.sub(r"\s+", " ", clean).strip()


def generate_fallback_srt(text: str, duration: float, srt_path: str) -> bool:
    """
    Generate a fallback SRT from word-count timing.
    Used by Groq Orpheus path (Whisper not available for Groq output).
    Accounts for the 300ms lead silence so caption timing aligns with audio.
    """
    try:
        words = [w.strip().upper() for w in text.split() if w.strip()]
        if not words:
            return False

        # The audio has 300ms lead silence. Start captions at 0.3s.
        # Duration excludes the lead/tail silence for timing calculation.
        voice_duration = duration - 0.8   # subtract 300ms lead + 500ms tail
        voice_duration = max(voice_duration, len(words) * 0.1)

        time_per_word = voice_duration / len(words)
        lead_offset   = 0.3   # match the 300ms lead silence

        lines = []
        for i in range(0, len(words), 3):
            chunk  = words[i:i + 3]
            start  = lead_offset + i * time_per_word
            end    = lead_offset + min((i + len(chunk)) * time_per_word, voice_duration)
            lines.append(
                f"{i // 3 + 1}\n{format_time(start)} --> {format_time(end)}\n"
                f"{' '.join(chunk)}\n"
            )
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return True
    except Exception:
        return False


def _get_kokoro_to_groq_map() -> dict:
    from engine.config_manager import config_manager
    settings = config_manager.get_settings()
    return settings.get("voice_actors", {}).get("kokoro_to_groq_map", {
        "am_adam":    "daniel",
        "af_bella":   "diana",
        "am_michael": "austin",
        "af_sarah":   "hannah",
    })


# ── Emotion injection: Kokoro (punctuation-based preprocessing) ───────────────
# Kokoro-82M has no native emotion tags — we shape emotion through rhythm,
# punctuation cadence, and sentence structure that guide prosody naturally.

def _inject_kokoro_emotion(text: str, mood: str) -> str:
    """
    Reshape script text with punctuation cues that guide Kokoro's prosody.
    Does NOT add any content — only adjusts rhythm and pause signals.
    Returns the modified text string.
    """
    if mood == "neutral":
        return text

    elif mood == "wonder":
        sentences = re.split(r'(?<=[.!?])\s+', text)
        result = []
        for i, s in enumerate(sentences):
            s = s.strip()
            if not s:
                continue
            if 0 < i < len(sentences) - 1 and s.endswith('.'):
                s = s[:-1] + '...'
            result.append(s)
        return ' '.join(result)

    elif mood == "excitement":
        sentences = re.split(r'(?<=[.!?])\s+', text)
        result = []
        for s in sentences:
            s = s.strip()
            if not s:
                continue
            word_count = len(s.split())
            if word_count > 10 and s.endswith('.'):
                s = s[:-1] + '!'
            result.append(s)
        return ' '.join(result)

    elif mood == "horror":
        processed = re.sub(r'\s+(and|but|because|however|yet)\s+', r', \1 ', text)
        sentences = re.split(r'(?<=[.!?])\s+', processed)
        result = []
        for i, s in enumerate(sentences):
            s = s.strip()
            if not s:
                continue
            if s.endswith('.') and i < len(sentences) - 1:
                s = s[:-1] + '...'
            result.append(s)
        return ' '.join(result)

    elif mood == "warm":
        sentences = re.split(r'(?<=[.!?])\s+', text)
        result = []
        for s in sentences:
            s = s.strip()
            if not s:
                continue
            words = s.split()
            if len(words) > 12 and ',' not in s[-30:]:
                pivot = len(words) - 3
                s = ' '.join(words[:pivot]) + ', ' + ' '.join(words[pivot:])
            result.append(s)
        return ' '.join(result)

    return text


# ── Emotion injection: Orpheus (native tag-based) ─────────────────────────────

def _inject_orpheus_emotion(text: str, mood: str) -> str:
    """
    Insert Orpheus-native emotion tags at strategic positions in the text.
    Tags: <sigh>, <laugh>, <whisper>...</whisper>, [pause]
    """
    sentences = re.split(r'(?<=[.!?])\s+', text)

    if mood == "neutral":
        return text

    elif mood == "wonder":
        if len(sentences) > 2:
            sentences[-1] = "[pause] " + sentences[-1]
        return ' '.join(sentences)

    elif mood == "excitement":
        return text

    elif mood == "horror":
        result = []
        for i, s in enumerate(sentences):
            s = s.strip()
            if not s:
                continue
            if i == 0:
                s = "<sigh> " + s
            if i == len(sentences) - 1 and len(sentences) > 1:
                s = "[pause] " + s
            result.append(s)
        return ' '.join(result)

    elif mood == "warm":
        if len(sentences) > 2:
            idx = len(sentences) - 2
            sentences[idx] = sentences[idx].rstrip('.') + '. <sigh>'
        return ' '.join(sentences)

    return text


def generate_audio(text: str, output_base: str = "temp_audio",
                   target_voice: str = None, mood: str = "neutral"):
    """
    Synthesize TTS audio for the given script text.

    Parameters
    ----------
    text         : script text
    output_base  : file path base (without extension) — .wav and .srt written here
    target_voice : Kokoro voice name (e.g. "am_adam")
    mood         : emotional register — controls emotion injection preprocessing

    Returns
    -------
    tuple: (success: bool, provider: str, duration: float)
    """
    from scripts.groq_client import groq_client

    clean_text = sanitize_for_tts(text)
    wav_path   = f"{output_base}.wav"
    srt_path   = f"{output_base}.srt"
    duration   = 0.0

    from engine.config_manager import config_manager
    settings     = config_manager.get_settings()
    kokoro_voice = target_voice or "am_adam"
    tts_speed    = settings.get("tts", {}).get("kokoro_speed_multiplier", 1.1)
    valid_kokoro = settings.get("voice_actors", {}).get("kokoro", ["am_adam"])

    if kokoro_voice not in valid_kokoro:
        kokoro_voice = "am_adam"

    # ── Primary: Kokoro TTS with emotion preprocessing ────────────────────────
    try:
        import numpy as np
        import soundfile as sf

        kokoro_text  = _inject_kokoro_emotion(clean_text, mood)
        pipeline     = get_kokoro_pipeline()
        audio_chunks = []

        for _, _, audio in pipeline(kokoro_text, voice=kokoro_voice, speed=tts_speed):
            if audio is not None:
                audio_chunks.append(audio)

        if audio_chunks:
            full_audio = np.concatenate(audio_chunks)
            sf.write(wav_path, full_audio, 24000)
            ok, duration = trim_audio_precision(wav_path)
            if ok and duration > 0:
                try:
                    print("📝 [VOICE] Transcribing and Chunking Captions (Max 3 words)...")
                    whisper = get_whisper_model()
                    segments, _ = whisper.transcribe(wav_path, language="en", word_timestamps=True)

                    srt_lines = []
                    idx = 1
                    for segment in segments:
                        chunk       = []
                        chunk_start = None
                        for word in (segment.words or []):
                            if chunk_start is None:
                                chunk_start = word.start
                            chunk.append(word.word.strip().upper())

                            if len(chunk) >= 3:
                                end = word.end
                                srt_lines.append(
                                    f"{idx}\n{format_time(chunk_start)} --> {format_time(end)}\n"
                                    f"{' '.join(chunk)}\n"
                                )
                                idx         += 1
                                chunk        = []
                                chunk_start  = None

                        if chunk:
                            srt_lines.append(
                                f"{idx}\n{format_time(chunk_start)} --> {format_time(segment.words[-1].end)}\n"
                                f"{' '.join(chunk)}\n"
                            )
                            idx += 1

                    if srt_lines:
                        with open(srt_path, "w", encoding="utf-8") as f:
                            f.write("\n".join(srt_lines))
                    else:
                        generate_fallback_srt(clean_text, duration, srt_path)

                except Exception as e:
                    trace = traceback.format_exc()
                    print(f"⚠️ [VOICE] Whisper failed:\n{trace}")
                    generate_fallback_srt(clean_text, duration, srt_path)

                print(f"✅ [TTS] Kokoro — {duration:.1f}s | Voice: {kokoro_voice} | Mood: {mood}")
                return True, "Kokoro", duration

    except Exception as e:
        trace = traceback.format_exc()
        print(f"⚠️ [TTS] Kokoro failed:\n{trace}")

    # ── Fallback: Groq Orpheus TTS with native emotion tags ───────────────────
    try:
        voice_map     = _get_kokoro_to_groq_map()
        groq_voice    = voice_map.get(target_voice) if target_voice else None
        orpheus_text  = _inject_orpheus_emotion(clean_text, mood)

        ok = groq_client.generate_audio(orpheus_text, wav_path, voice_override=groq_voice)
        if ok:
            _, duration = trim_audio_precision(wav_path)
            generate_fallback_srt(clean_text, duration, srt_path)
            used_voice = groq_voice or "random"
            print(f"✅ [TTS] Groq Orpheus — {duration:.1f}s | Voice: {used_voice} | Mood: {mood}")
            return True, "Groq Orpheus", duration

    except Exception as e:
        trace = traceback.format_exc()
        print(f"⚠️ [TTS] Groq Orpheus failed:\n{trace}")

    return False, "All TTS Providers Failed", 0.0
