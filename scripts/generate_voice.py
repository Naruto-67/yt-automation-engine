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

# Import the Nervous System and Quota Manager
from scripts.groq_client import groq_client
from scripts.retry import quota_manager

def load_voice_settings():
    """Reads historical performance data to dynamically select voice speed."""
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
    """Converts seconds into standard SRT timestamp (HH:MM:SS,mmm)."""
    if seconds < 0: seconds = 0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"

# ==========================================
# ✂️ SILENCE STRIPPER (Loophole 5 Fix)
# ==========================================
def trim_audio_precision(file_path):
    """
    Uses pydub to remove micro-silence gaps (0.1s - 0.3s) added by TTS engines.
    This ensures word-sync remains perfect across long scripts.
    """
    print("✂️ [VOICE] Stripping micro-silence padding...")
    try:
        audio = AudioSegment.from_file(file_path)
        
        # Trim leading silence
        start_trim = detect_leading_silence(audio)
        # Trim trailing silence (by reversing)
        end_trim = detect_leading_silence(audio.reverse())
        
        duration = len(audio)
        trimmed_audio = audio[start_trim:duration-end_trim]
        
        # Add a fixed 0.3s 'Safety Buffer' at the very start to prevent player clipping
        silence_buffer = AudioSegment.silent(duration=300)
        final_audio = silence_buffer + trimmed_audio
        
        final_audio.export(file_path, format="wav")
        return True
    except Exception as e:
        print(f"⚠️ [VOICE] Precision trimming failed: {e}")
        return False

# ==========================================
# 🏥 SRT SANITY FILTER (Loophole 3 Fix)
# ==========================================
def apply_srt_sanity_filter(words):
    """
    Scans Whisper timestamps. Heals null durations, negative times, 
    and overlapping words to prevent FFmpeg rendering hangs.
    """
    sanitized = []
    for i, w in enumerate(words):
        start = max(0, w.start)
        end = max(start + 0.05, w.end) # Enforce minimum 50ms duration
        
        # If this isn't the first word, ensure no overlap with previous
        if i > 0:
            prev_end = sanitized[i-1]['end']
            if start < prev_end:
                start = prev_end + 0.01 # Slide forward by 10ms
                end = max(start + 0.05, end)
        
        sanitized.append({'start': start, 'end': end, 'word': w.word.strip()})
    return sanitized

# ==========================================
# 🎙️ GENERATION ENGINES
# ==========================================
def generate_kokoro_local(text, output_path):
    """Failsafe local TTS generation using GitHub CPU."""
    settings = load_voice_settings()
    print(f"🛡️ [KOKORO] Booting local failsafe (Voice: {settings['voice']})...")
    try:
        pipeline = KPipeline(lang_code='a') 
        generator = pipeline(text, voice=settings['voice'], speed=settings['speed'], split_pattern=r'\n+')
        audio_chunks = [audio for _, _, audio in generator if audio is not None]
        
        if not audio_chunks: return False
        raw_audio = np.concatenate(audio_chunks)
        sf.write(output_path, raw_audio, 24000)
        return True
    except Exception as e:
        print(f"❌ [KOKORO] Local crash: {e}")
        return False

def generate_audio(text, output_base="master_audio"):
    """
    The Audio Pipeline: 
    1. Groq Orpheus -> 2. Kokoro Fallback -> 3. Pydub Trim -> 4. Whisper SRT -> 5. Sanity Filter.
    """
    temp_mp3 = f"{output_base}.mp3"
    final_wav = f"{output_base}.wav"
    srt_path = f"{output_base}.srt"
    
    # --- PHASE 1: GENERATE RAW AUDIO ---
    success = False
    if groq_client.generate_audio(text, temp_mp3):
        # Convert MP3 to WAV for Pydub/Whisper compatibility
        subprocess.run(["ffmpeg", "-y", "-i", temp_mp3, final_wav], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.path.exists(temp_mp3): os.remove(temp_mp3)
        success = True
    else:
        print("🔄 [VOICE] Orpheus Offline. Triggering Kokoro...")
        success = generate_kokoro_local(text, final_wav)

    if not success or not os.path.exists(final_wav):
        print("🚨 [VOICE] Total Audio Failure.")
        return False

    # --- PHASE 2: PRECISION TRIMMING ---
    trim_audio_precision(final_wav)

    # --- PHASE 3: SUBTITLES & SANITY ---
    print("⏱️ [WHISPER] Transcribing word-level timestamps...")
    try:
        model = WhisperModel("base.en", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(final_wav, word_timestamps=True)
        
        all_words = []
        for segment in segments:
            if segment.words:
                all_words.extend(segment.words)
        
        # Apply the Loophole 3 Sanity Filter
        clean_words = apply_srt_sanity_filter(all_words)
        
        srt_lines = []
        for idx, w in enumerate(clean_words, 1):
            srt_lines.append(f"{idx}")
            srt_lines.append(f"{format_time(w['start'])} --> {format_time(w['end'])}")
            srt_lines.append(w['word'])
            srt_lines.append("")
            
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(srt_lines))
            
        print(f"✅ [VOICE] Master audio and sanitized SRT locked.")
        return True

    except Exception as e:
        print(f"❌ [VOICE] Subtitle Phase Crash: {e}")
        quota_manager.diagnose_fatal_error("generate_voice.py", e)
        return False

if __name__ == "__main__":
    generate_audio("Testing the Ghost Engine precision audio sync.")
