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
    # 🚨 LEGACY RESTORE: Biological Padding & Normalization
    from pydub import AudioSegment, effects
    try:
        audio = AudioSegment.from_file(file_path)
        if len(audio) > 200:
            audio = audio[200:]
        
        audio = effects.normalize(audio)
        
        # Exact 200ms start pad, 500ms end pad to prevent abrupt cutoffs
        sil_start = AudioSegment.silent(duration=200, frame_rate=audio.frame_rate).set_channels(audio.channels)
        sil_end   = AudioSegment.silent(duration=500, frame_rate=audio.frame_rate).set_channels(audio.channels)
        
        final = sil_start + audio + sil_end
        final.export(file_path, format="wav")
        return True, len(final) / 1000.0
    except Exception as e:
        trace = traceback.format_exc()
        print(f"⚠️ [VOICE] Audio trim failed:\n{trace}")
        return False, 0.0

def sanitize_for_tts(text: str) -> str:
    clean = re.sub(r"[^\w\s.,!?'\"−]", "", text)
    return re.sub(r"\s+", " ", clean).strip()

def generate_fallback_srt(text: str, duration: float, srt_path: str) -> bool:
    try:
        words        = [w.strip().upper() for w in text.split() if w.strip()]
        if not words:
            return False
        time_per_word = max(duration / len(words), 0.1)
        lines         = []
        for i in range(0, len(words), 3):
            chunk  = words[i:i+3]
            start  = i * time_per_word
            end    = min((i + len(chunk)) * time_per_word, duration)
            lines.append(
                f"{i//3 + 1}\n{format_time(start)} --> {format_time(end)}\n"
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

def generate_audio(text: str, output_base: str = "temp_audio", target_voice: str = None):
    from scripts.groq_client import groq_client

    clean_text  = sanitize_for_tts(text)
    wav_path    = f"{output_base}.wav"
    srt_path    = f"{output_base}.srt"
    duration    = 0.0

    from engine.config_manager import config_manager
    settings     = config_manager.get_settings()
    kokoro_voice = target_voice or "am_adam"
    tts_speed    = settings.get("tts", {}).get("kokoro_speed_multiplier", 1.1)
    valid_kokoro = settings.get("voice_actors", {}).get("kokoro", ["am_adam"])

    if kokoro_voice not in valid_kokoro:
        kokoro_voice = "am_adam"

    try:
        import numpy as np
        import soundfile as sf

        pipeline   = get_kokoro_pipeline()
        audio_chunks = []

        for _, _, audio in pipeline(clean_text, voice=kokoro_voice, speed=tts_speed):
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
                    
                    # 🚨 LEGACY RESTORE: Exact 3-Word Chunking logic
                    srt_lines = []
                    idx = 1
                    for segment in segments:
                        chunk = []
                        chunk_start = None
                        for word in (segment.words or []):
                            if chunk_start is None:
                                chunk_start = word.start
                            chunk.append(word.word.strip().upper())
                            
                            if len(chunk) >= 3:
                                end = word.end
                                srt_lines.append(f"{idx}\n{format_time(chunk_start)} --> {format_time(end)}\n{' '.join(chunk)}\n")
                                idx += 1
                                chunk = []
                                chunk_start = None
                                
                        if chunk:
                            srt_lines.append(f"{idx}\n{format_time(chunk_start)} --> {format_time(segment.words[-1].end)}\n{' '.join(chunk)}\n")
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

                print(f"✅ [TTS] Kokoro — {duration:.1f}s | Voice: {kokoro_voice}")
                return True, "Kokoro", duration

    except Exception as e:
        trace = traceback.format_exc()
        print(f"⚠️ [TTS] Kokoro failed:\n{trace}")

    try:
        voice_map     = _get_kokoro_to_groq_map()
        groq_voice    = voice_map.get(target_voice) if target_voice else None
        groq_override = groq_voice

        ok = groq_client.generate_audio(clean_text, wav_path, voice_override=groq_override)
        if ok:
            _, duration = trim_audio_precision(wav_path)
            generate_fallback_srt(clean_text, duration, srt_path)
            used_voice  = groq_override or "random"
            print(f"✅ [TTS] Groq Orpheus — {duration:.1f}s | Voice: {used_voice}")
            return True, "Groq Orpheus", duration

    except Exception as e:
        trace = traceback.format_exc()
        print(f"⚠️ [TTS] Groq Orpheus failed:\n{trace}")

    return False, "All TTS Providers Failed", 0.0
