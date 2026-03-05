import os
import json
import numpy as np
import soundfile as sf
import subprocess
import asyncio
import edge_tts
from pydub import AudioSegment
from pydub.silence import detect_leading_silence
from kokoro import KPipeline
from faster_whisper import WhisperModel
from scripts.groq_client import groq_client
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
    except Exception: return False

def generate_audio(text, output_base="temp_audio"):
    final_wav = f"{output_base}.wav"
    temp_mp3 = f"{output_base}.mp3"
    srt_path = f"{output_base}.srt"
    
    success = False
    
    # 1. Groq Orpheus
    print("🎙️ [VOICE] Attempting Primary: Groq Orpheus...")
    if groq_client.generate_audio(text, temp_mp3):
        try:
            subprocess.run(["ffmpeg", "-y", "-i", temp_mp3, final_wav], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            if os.path.exists(temp_mp3): os.remove(temp_mp3)
            success = True
        except: success = False

    # 2. Kokoro Local
    if not success:
        print("🎙️ [VOICE] Attempting Fallback: Kokoro V1...")
        setts = load_voice_settings()
        try:
            pipeline = KPipeline(lang_code='a') 
            gen = pipeline(text, voice=setts['voice'], speed=setts['speed'])
            audio_chunks = [audio for _, _, audio in gen if audio is not None]
            if audio_chunks:
                sf.write(final_wav, np.concatenate(audio_chunks), 24000)
                success = True
        except: success = False

    # 3. Edge-TTS
    if not success:
        print("🎙️ [VOICE] Attempting Failsafe: Edge-TTS...")
        try:
            async def _edge():
                c = edge_tts.Communicate(text, "en-US-ChristopherNeural", rate="+10%")
                await c.save(final_wav)
            asyncio.run(_edge())
            success = True
        except: success = False

    if not success: return False
    
    trim_audio_precision(final_wav)

    try:
        print("📝 [VOICE] Transcribing...")
        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(final_wav, word_timestamps=True)
        srt_lines = []
        idx = 1
        for s in segments:
            for w in s.words:
                srt_lines.append(f"{idx}\n{format_time(w.start)} --> {format_time(w.end)}\n{w.word.strip().upper()}\n")
                idx += 1
        with open(srt_path, "w", encoding="utf-8") as f: f.write("\n".join(srt_lines))
        return True
    except: return True
