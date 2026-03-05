import os
import json
import numpy as np
import soundfile as sf
import traceback
import subprocess
from pydub import AudioSegment
from pydub.silence import detect_leading_silence
from kokoro import KPipeline
from faster_whisper import WhisperModel

# Corrected Import
from scripts.groq_client import groq_client
from scripts.quota_manager import quota_manager

def load_voice_settings():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    tracker_path = os.path.join(root_dir, "assets", "lessons_learned.json")
    settings = {"voice": "am_adam", "speed": 1.1}
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
        silence_buffer = AudioSegment.silent(duration=300)
        final_audio = silence_buffer + trimmed_audio
        final_audio.export(file_path, format="wav")
        return True
    except Exception as e:
        print(f"⚠️ [VOICE] Precision trimming failed: {e}")
        return False

def apply_srt_sanity_filter(words):
    sanitized = []
    for i, w in enumerate(words):
        start = max(0, w.start)
        end = max(start + 0.05, w.end)
        if i > 0:
            prev_end = sanitized[i-1]['end']
            if start < prev_end:
                start = prev_end + 0.01
                end = max(start + 0.05, end)
        sanitized.append({'start': start, 'end': end, 'word': w.word.strip()})
    return sanitized

def generate_kokoro_local(text, output_path):
    settings = load_voice_settings()
    try:
        pipeline = KPipeline(lang_code='a') 
        generator = pipeline(text, voice=settings['voice'], speed=settings['speed'], split_pattern=r'\n+')
        audio_chunks = [audio for _, _, audio in generator if audio is not None]
        if not audio_chunks: return False
        raw_audio = np.concatenate(audio_chunks)
        sf.write(output_path, raw_audio, 24000)
        return True
    except Exception: return False

def generate_audio(text, output_base="master_audio"):
    temp_mp3 = f"{output_base}.mp3"
    final_wav = f"{output_base}.wav"
    srt_path = f"{output_base}.srt"
    
    if groq_client.generate_audio(text, temp_mp3):
        subprocess.run(["ffmpeg", "-y", "-i", temp_mp3, final_wav], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.path.exists(temp_mp3): os.remove(temp_mp3)
        success = True
    else:
        success = generate_kokoro_local(text, final_wav)

    if not success: return False
    trim_audio_precision(final_wav)

    try:
        model = WhisperModel("base.en", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(final_wav, word_timestamps=True)
        all_words = []
        for segment in segments:
            if segment.words: all_words.extend(segment.words)
        clean_words = apply_srt_sanity_filter(all_words)
        srt_lines = []
        for idx, w in enumerate(clean_words, 1):
            srt_lines.append(f"{idx}\n{format_time(w['start'])} --> {format_time(w['end'])}\n{w['word']}\n")
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(srt_lines))
        return True
    except Exception as e:
        quota_manager.diagnose_fatal_error("generate_voice.py", e)
        return False
