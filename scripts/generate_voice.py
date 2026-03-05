import os
import json
import numpy as np
import soundfile as sf
import subprocess
from pydub import AudioSegment
from pydub.silence import detect_leading_silence
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
        except: pass
    return settings

def format_time(seconds):
    if seconds < 0: seconds = 0
    hours, minutes = int(seconds // 3600), int((seconds % 3600) // 60)
    secs, millis = int(seconds % 60), int((seconds - int(seconds)) * 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"

def trim_audio_precision(file_path):
    try:
        audio = AudioSegment.from_file(file_path)
        start_trim = detect_leading_silence(audio)
        end_trim = detect_leading_silence(audio.reverse())
        trimmed = audio[start_trim:len(audio)-end_trim]
        final = AudioSegment.silent(duration=200) + trimmed + AudioSegment.silent(duration=200)
        final.export(file_path, format="wav")
        return True
    except: return False

def generate_audio(text, output_base="temp_audio"):
    final_wav = f"{output_base}.wav"
    srt_path = f"{output_base}.srt"
    
    success = False
    provider = "Unknown"
    
    print("🎙️ [VOICE] Attempting Primary: Groq Orpheus TTS...")
    if groq_client.generate_audio(text, final_wav):
        success = True
        provider = "Groq Orpheus API"

    if not success:
        print("🎙️ [VOICE] Orpheus failed. Booting Kokoro Local Fallback...")
        try:
            from kokoro import KPipeline
            settings = load_voice_settings()
            pipeline = KPipeline(lang_code='a') 
            gen = pipeline(text, voice=settings['voice'], speed=settings['speed'], split_pattern=r'\n+')
            audio_chunks = [audio for _, _, audio in gen if audio is not None]
            if audio_chunks:
                sf.write(final_wav, np.concatenate(audio_chunks), 24000)
                success = True
                provider = "Kokoro V1 (Local)"
        except: success = False

    if not success: 
        return False, provider
    
    trim_audio_precision(final_wav)

    try:
        print("📝 [VOICE] Transcribing with Faster-Whisper...")
        from faster_whisper import WhisperModel
        model = WhisperModel("tiny.en", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(final_wav, word_timestamps=True)
        
        srt_lines = []
        idx = 1
        for segment in segments:
            for word in segment.words:
                start, end = format_time(word.start), format_time(word.end)
                srt_lines.append(f"{idx}\n{start} --> {end}\n{word.word.strip().upper()}\n")
                idx += 1
                
        with open(srt_path, "w", encoding="utf-8") as f: 
            f.write("\n".join(srt_lines))
    except: pass
    
    return True, provider
