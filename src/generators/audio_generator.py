import asyncio
import edge_tts
import os

async def generate_audio_async(text, output_file, voice="en-US-ChristopherNeural"):
    """
    Generates TTS audio AND a matching .srt subtitle file with exact word timings.
    """
    communicate = edge_tts.Communicate(text, voice)
    submaker = edge_tts.SubMaker()
    
    print("Generating audio and subtitle timestamps...")
    
    with open(output_file, "wb") as file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                file.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                # Feed the new SubMaker with the word chunks
                submaker.feed(chunk)
                
    # Save the subtitle file with the same name as the audio, but .srt extension
    srt_path = output_file.replace(".mp3", ".srt")
    with open(srt_path, "w", encoding="utf-8") as file:
        file.write(submaker.get_srt())

def generate_audio(text, output_file, voice="en-US-ChristopherNeural"):
    """Wrapper to run the async audio and subtitle generation."""
    try:
        asyncio.run(generate_audio_async(text, output_file, voice))
        
        srt_path = output_file.replace(".mp3", ".srt")
        if os.path.exists(output_file) and os.path.exists(srt_path):
            print(f"Success! Audio and subtitles saved.")
            return True
        else:
            print("Error: Files were not created properly.")
            return False
    except Exception as e:
        print(f"Failed to generate audio/subtitles: {e}")
        return False

if __name__ == "__main__":
    test_text = "System online. We are now generating audio and exact subtitle timestamps at the very same time. This is the foundation of viral retention."
    output_path = "test_audio.mp3"
    generate_audio(test_text, output_path)
