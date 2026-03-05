import os
import json
import numpy as np
import soundfile as sf
import traceback
import subprocess
from kokoro import KPipeline
from faster_whisper import WhisperModel

# Import the newly built Groq API Client
from scripts.groq_client import groq_client

def load_voice_settings():
    """Reads historical performance data to dynamically select the best voice and speed."""
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    tracker_path = os.path.join(root_dir, "assets", "lessons_learned.json")
    settings = {"voice": "am_adam", "speed": 1.1}
    
    if os.path.exists(tracker_path):
        try:
            with open(tracker_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "best_voice" in data: settings["voice"] = data["best_voice"]
                if "best_speed" in data: settings["speed"] = data["best_speed"]
        except Exception as e:
            print(f"⚠️ Warning: Could not read lessons_learned.json: {e}")
    return settings

def format_time(seconds):
    """Converts seconds into the standard SRT timestamp format (HH:MM:SS,mmm)."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"

def generate_kokoro_audio(text, output_path):
    """The ultimate local failsafe. Uses GitHub Actions CPU."""
    settings = load_voice_settings()
    voice_choice = settings["voice"]
    speech_speed = settings["speed"]
    
    print(f"🛡️ [KOKORO] Generating locally (Voice: {voice_choice}, Speed: {speech_speed}x)...")
    try:
        pipeline = KPipeline(lang_code='a') 
        generator = pipeline(text, voice=voice_choice, speed=speech_speed, split_pattern=r'\n+')
        audio_chunks = []
        sample_rate = 24000
        
        for gs, ps, audio in generator:
            if audio is not None:
                audio_chunks.append(audio)
                
        if not audio_chunks:
            print("❌ [KOKORO] Generated empty audio.")
            return False
            
        raw_audio = np.concatenate(audio_chunks)
        
        # The 0.3s silence buffer to prevent video clipping at the very start
        silence_duration = 0.3 
        silence_array = np.zeros(int(sample_rate * silence_duration), dtype=np.float32)
        final_audio = np.concatenate([silence_array, raw_audio])
        
        sf.write(output_path, final_audio, sample_rate)
        print(f"✅ [KOKORO] Audio saved successfully to {output_path}")
        return True
    except Exception as e:
        print(f"❌ [KOKORO] Local generation failed:")
        traceback.print_exc()
        return False

def generate_audio(text, output_base="master_audio"):
    """
    Manages the API flow: Groq Orpheus Primary -> Kokoro Fallback -> Whisper SRT.
    Maintains .wav output for backward compatibility with main.py.
    """
    groq_audio_path = f"{output_base}.mp3"
    wav_audio_path = f"{output_base}.wav"
    srt_path = f"{output_base}.srt"
    
    final_audio_path = None

    # STEP 1: Try Groq Orpheus API (Fast, Free, Zero CPU)
    if groq_client.generate_audio(text, groq_audio_path):
        print("🔄 [VOICE ROUTER] Converting Groq MP3 to WAV for pipeline compatibility...")
        try:
            # Silently convert the mp3 to wav so render_video.py doesn't crash
            subprocess.run(["ffmpeg", "-y", "-i", groq_audio_path, wav_audio_path], 
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            final_audio_path = wav_audio_path
            os.remove(groq_audio_path) # Clean up the temp mp3
            print("✅ [VOICE ROUTER] Conversion successful.")
        except Exception as e:
            print(f"⚠️ [VOICE ROUTER] FFmpeg conversion failed: {e}. Falling back to Kokoro.")
            if generate_kokoro_audio(text, wav_audio_path):
                final_audio_path = wav_audio_path
    
    # STEP 2: Seamless Local Fallback
    else:
        print("🔄 [VOICE ROUTER] Groq TTS failed or rate-limited. Booting Local Failsafe...")
        if generate_kokoro_audio(text, wav_audio_path):
            final_audio_path = wav_audio_path
            
    if not final_audio_path:
        print("🚨 FATAL: Both Groq TTS and Kokoro TTS failed. Cannot proceed.")
        return False

    # STEP 3: Generate Subtitles via Faster-Whisper
    print("⏱️ [WHISPER] Generating precise word-level subtitle timestamps...")
    try:
        model = WhisperModel("base.en", device="cpu", compute_type="int8")
        segments, info = model.transcribe(final_audio_path, word_timestamps=True)
        
        srt_content = []
        subtitle_index = 1
        for segment in segments:
            for word in segment.words:
                start_time = format_time(word.start)
                end_time = format_time(word.end)
                
                srt_content.append(str(subtitle_index))
                srt_content.append(f"{start_time} --> {end_time}")
                srt_content.append(word.word.strip())
                srt_content.append("")
                subtitle_index += 1
                
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(srt_content))
            
        print(f"✅ [WHISPER] SRT Subtitles saved successfully to {srt_path}")
        return True

    except Exception as e:
        print(f"❌ [WHISPER] Subtitle generation failed: {e}")
        from scripts.retry import quota_manager
        quota_manager.diagnose_fatal_error("generate_voice.py", e)
        return False

if __name__ == "__main__":
    test_text = "This is a test of the Ghost Engine audio system. Orpheus and Kokoro are online."
    generate_audio(test_text, "test_output")
