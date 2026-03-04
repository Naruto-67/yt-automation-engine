import os
import json
import numpy as np
import soundfile as sf
from kokoro import KPipeline
from faster_whisper import WhisperModel

def load_voice_settings():
    """
    Reads historical performance data to dynamically select the best voice and speed.
    This allows the system to auto-adjust pacing based on retention analytics.
    """
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    tracker_path = os.path.join(root_dir, "assets", "lessons_learned.json")
    
    # Default baseline settings for a USA audience
    settings = {
        "voice": "am_adam",  # Default American Male voice
        "speed": 1.1         # Slightly sped up for short-form retention
    }
    
    if os.path.exists(tracker_path):
        try:
            with open(tracker_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "best_voice" in data:
                    settings["voice"] = data["best_voice"]
                if "best_speed" in data:
                    settings["speed"] = data["best_speed"]
        except Exception as e:
            print(f"Warning: Could not read lessons_learned.json: {e}")
            
    return settings

def format_time(seconds):
    """Converts seconds into the standard SRT timestamp format (HH:MM:SS,mmm)."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"

def generate_audio(text, output_base="master_audio"):
    """
    Generates ultra-realistic TTS using Kokoro and creates perfectly 
    synced word-level SRT subtitles using faster-whisper.
    """
    wav_path = f"{output_base}.wav"
    srt_path = f"{output_base}.srt"
    
    settings = load_voice_settings()
    voice_choice = settings["voice"]
    speech_speed = settings["speed"]
    
    print(f"🎙️ Generating voice using Kokoro (Voice: {voice_choice}, Speed: {speech_speed}x)...")
    
    try:
        # 1. GENERATE AUDIO WITH KOKORO
        pipeline = KPipeline(lang_code='a') 
        generator = pipeline(text, voice=voice_choice, speed=speech_speed, split_pattern=r'\n+')
        
        audio_chunks = []
        sample_rate = 24000
        
        for gs, ps, audio in generator:
            if audio is not None:
                audio_chunks.append(audio)
                
        if not audio_chunks:
            print("❌ Kokoro generated empty audio.")
            return False
            
        final_audio = np.concatenate(audio_chunks)
        sf.write(wav_path, final_audio, sample_rate)
        print(f"✅ Audio saved successfully to {wav_path}")
        
        # 2. GENERATE TIMESTAMPS WITH FASTER-WHISPER
        print("⏱️ Generating precise word-level subtitle timestamps...")
        # THE FIX: Upgraded from "tiny.en" to "base.en" for highly accurate spelling
        model = WhisperModel("base.en", device="cpu", compute_type="int8")
        segments, info = model.transcribe(wav_path, word_timestamps=True)
        
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
            
        print(f"✅ SRT Subtitles saved successfully to {srt_path}")
        return True

    except Exception as e:
        print(f"❌ Audio generation failed: {e}")
        return False

if __name__ == "__main__":
    test_text = "This is a test of the fully integrated, self-improving audio system."
    generate_audio(test_text, "test_output")
