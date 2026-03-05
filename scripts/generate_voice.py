import os
import json
import numpy as np
import soundfile as sf
import traceback
import subprocess
import asyncio
import edge_tts
from pydub import AudioSegment
from pydub.silence import detect_leading_silence
from kokoro import KPipeline
from faster_whisper import WhisperModel
from scripts.quota_manager import quota_manager

def load_voice_settings():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    tracker_path = os.path.join(root_dir, "assets", "lessons_learned.json")
    settings = {"voice": "af_heart", "speed": 1.1}
    if os.path.exists(tracker_path):
        try:
            with open(tracker_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "best_voice" in data: settings["voice"] = data["best_voice"]
                if "best_speed" in data: settings["speed"] = data["best_speed"]
        except Exception: pass
    return settings

def format_time(seconds):
    if seconds < 0: seconds = 0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"

def trim_audio_precision(file_path):
    try:
        audio = AudioSegment.from_file(file_path)
        start_trim = detect_leading_silence(audio)
        end_trim = detect_leading_silence(audio.reverse())
        duration = len(audio)
        trimmed_audio = audio[start_trim:duration-end_trim]
        # Add 300ms buffer for better pacing
        final_audio = AudioSegment.silent(duration=200) + trimmed_audio + AudioSegment.silent(duration=200)
        final_audio.export(file_path, format="wav")
        return True
    except Exception as e:
        print(f"⚠️ [VOICE] Precision trimming failed: {e}")
        return False

def generate_kokoro_local(text, output_path):
    settings = load_voice_settings()
    print(f"🎙️ [VOICE] Synthesizing with Kokoro V1 (Voice: {settings['voice']})...")
    try:
        pipeline = KPipeline(lang_code='a') 
        generator = pipeline(text, voice=settings['voice'], speed=settings['speed'], split_pattern=r'\n+')
        audio_chunks = [audio for _, _, audio in generator if audio is not None]
        if not audio_chunks: return False
        raw_audio = np.concatenate(audio_chunks)
        sf.write(output_path, raw_audio, 24000)
        return True
    except Exception as e:
        print(f"⚠️ [VOICE] Kokoro local failed: {e}")
        return False

def generate_edge_fallback(text, output_path):
    print("🎙️ [VOICE] Engaging Edge-TTS Fallback...")
    try:
        async def _run():
            communicate = edge_tts.Communicate(text, "en-US-ChristopherNeural", rate="+10%")
            await communicate.save(output_path)
        asyncio.run(_run())
        return True
    except Exception as e:
        print(f"❌ [VOICE] Edge-TTS failed: {e}")
        return False

def generate_audio(text, output_base="temp_audio"):
    final_wav = f"{output_base}.wav"
    srt_path = f"{output_base}.srt"
    
    # Bypass Groq Orpheus due to terms-acceptance requirement
    success = generate_kokoro_local(text, final_wav)
    if not success:
        success = generate_edge_fallback(text, final_wav)

    if not success: return False
    
    trim_audio_precision(final_wav)

    try:
        print("📝 [VOICE] Transcribing for word-level captions...")
        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(final_wav, word_timestamps=True)
        
        srt_lines = []
        idx = 1
        for segment in segments:
            for word in segment.words:
                start = format_time(word.start)
                end = format_time(word.end)
                srt_lines.append(f"{idx}\n{start} --> {end}\n{word.word.strip().upper()}\n")
                idx += 1
                
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(srt_lines))
        return True
    except Exception as e:
        print(f"⚠️ [VOICE] Whisper SRT generation failed: {e}")
        # Return True anyway as the audio exists, render_video will handle missing SRT
        return True
