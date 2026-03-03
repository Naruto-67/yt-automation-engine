import asyncio
import edge_tts
import os

def format_time(ticks):
    """Converts Edge-TTS 100-nanosecond ticks to SRT timestamp format."""
    ms = int(ticks / 10000)
    s, ms = divmod(ms, 1000)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

async def generate_audio_async(text, output_file, voice="en-US-ChristopherNeural"):
    communicate = edge_tts.Communicate(text, voice)
    words = []
    
    print("Generating audio and 1-word rapid timestamps...")
    
    with open(output_file, "wb") as file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                file.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                # We grab every single word individually
                words.append({
                    "text": chunk["text"],
                    "offset": chunk["offset"],
                    "duration": chunk["duration"]
                })
                
    # Build a custom SRT file forcing exactly ONE word per screen flash
    srt_path = output_file.replace(".mp3", ".srt")
    with open(srt_path, "w", encoding="utf-8") as f:
        for i, w in enumerate(words):
            start = format_time(w["offset"])
            end = format_time(w["offset"] + w["duration"])
            # Format: Index \n Start --> End \n Word \n\n
            f.write(f"{i+1}\n{start} --> {end}\n{w['text']}\n\n")

def generate_audio(text, output_file, voice="en-US-ChristopherNeural"):
    try:
        asyncio.run(generate_audio_async(text, output_file, voice))
        srt_path = output_file.replace(".mp3", ".srt")
        if os.path.exists(output_file) and os.path.exists(srt_path):
            print(f"Success! Audio and rapid-fire subtitles saved.")
            return True
        else:
            return False
    except Exception as e:
        print(f"Failed to generate audio/subtitles: {e}")
        return False

if __name__ == "__main__":
    test_text = "System online. This is a test of the fast paced one word caption engine."
    output_path = "test_audio.mp3"
    generate_audio(test_text, output_path)
