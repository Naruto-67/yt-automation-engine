import os
import json
import random
import warnings
import re

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
if os.environ.get("HF_TOKEN"):
    os.environ["HUGGING_FACE_HUB_TOKEN"] = os.environ.get("HF_TOKEN")

import numpy as np
import soundfile as sf
from pydub import AudioSegment, effects
from scripts.groq_client import groq_client
from scripts.quota_manager import quota_manager

_KOKORO_PIPELINE = None
_WHISPER_MODEL = None

def get_kokoro_pipeline():
    global _KOKORO_PIPELINE
    if _KOKORO_PIPELINE is None:
        from kokoro import KPipeline
        _KOKORO_PIPELINE = KPipeline(lang_code='a')
    return _KOKORO_PIPELINE

def get_whisper_model():
    global _WHISPER_MODEL
    if _WHISPER_MODEL is None:
        from faster_whisper import WhisperModel
        _WHISPER_MODEL = WhisperModel("tiny.en", device="cpu", compute_type="int8")
    return _WHISPER_MODEL

def format_time(seconds):
    if seconds < 0: seconds = 0
    hours, minutes = int(seconds // 3600), int((seconds % 3600) // 60)
    secs, millis = int(seconds % 60), int((seconds - int(seconds)) * 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"

def trim_audio_precision(file_path):
    try:
        audio = AudioSegment.from_file(file_path)
        if len(audio) > 200:
            audio = audio[200:]
            
        audio = effects.normalize(audio)
        
        silence_start = AudioSegment.silent(duration=200, frame_rate=audio.frame_rate).set_channels(audio.channels)
        silence_end = AudioSegment.silent(duration=500, frame_rate=audio.frame_rate).set_channels(audio.channels)
        
        final = silence_start + audio + silence_end
        final.export(file_path, format="wav")
        return True, len(final) / 1000.0
    except Exception as e: 
        print(f"⚠️ Audio trim failed: {e}")
        return False, 0.0

def sanitize_for_tts(text):
    clean_text = re.sub(r'[^\w\s.,!?\'"-]', '', text)
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
    return clean_text

def generate_audio(text, output_base="temp_audio"):
    global _KOKORO_PIPELINE
    final_wav = f"{output_base}.wav"
    srt_path = f"{output_base}.srt"
    
    success = False
    provider = "Unknown"
    
    sanitized_text = sanitize_for_tts(text)
    buffered_text = f", {sanitized_text}" 
    
    print("🎙️ [VOICE] Attempting Primary: Kokoro (Ultra-Realistic Human)...")
    try:
        kokoro_voices = ['am_adam', 'af_bella', 'am_michael', 'af_sarah']
        chosen_voice = random.choice(kokoro_voices)
        print(f"🎙️ [VOICE] Selected actor: {chosen_voice.upper()}")
        
        pipeline = get_kokoro_pipeline() 
        gen = pipeline(buffered_text, voice=chosen_voice, speed=1.1, split_pattern=r'\n+')
        audio_chunks = [audio for _, _, audio in gen if audio is not None]
        if audio_chunks:
            sf.write(final_wav, np.concatenate(audio_chunks), 24000)
            success = True
            provider = f"Kokoro ({chosen_voice})"
    except Exception as e: 
        print(f"⚠️ Kokoro failed (resetting pipeline state): {e}")
        _KOKORO_PIPELINE = None 
        success = False

    if not success:
        print("🎙️ [VOICE] Kokoro failed. Booting Groq Fallback...")
        if groq_client.generate_audio(buffered_text, final_wav):
            success = True
            provider = "Groq Orpheus API"

    if not success: 
        return False, provider, 0.0
    
    trim_success, duration = trim_audio_precision(final_wav)
    if not trim_success:
        return False, provider, 0.0

    try:
        print("📝 [VOICE] Transcribing and Chunking Captions (Max 3 words)...")
        model = get_whisper_model()
        segments, _ = model.transcribe(final_wav, word_timestamps=True)
        
        srt_lines = []
        idx = 1
        for segment in segments:
            chunk = []
            chunk_start = None
            for word in segment.words:
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
                
        with open(srt_path, "w", encoding="utf-8") as f: 
            f.write("\n".join(srt_lines))
    except Exception as e: 
        print(f"⚠️ Transcription error: {e}")
        return False, provider, 0.0
    
    return True, provider, duration
