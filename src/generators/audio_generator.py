import asyncio
import edge_tts
import os

async def generate_audio_async(text, output_file, voice="en-US-ChristopherNeural"):
    """
    Generates TTS audio AND a matching .vtt subtitle file with exact word timings.
    """
    communicate = edge_tts.Communicate(text, voice)
    submaker = edge_tts.SubMaker()
    
    print("Generating audio and subtitle timestamps...")
    
    with open(output_file, "wb") as file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                file.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                # This captures the exact millisecond each word is spoken
                submaker.create_sub((chunk["offset"], chunk["duration"]), chunk["text"])
                
    # Save the subtitle file with the same name as the audio, but .vtt extension
    vtt_path = output_file.replace(".mp3", ".vtt")
    with open(vtt_path, "w", encoding="utf-8") as file:
        file.write(submaker.generate_subs())

def generate_audio(text, output_file, voice="en-US-ChristopherNeural"):
    """Wrapper to run the async audio and subtitle generation."""
    try:
        asyncio.run(generate_audio_async(text, output_file, voice))
        
        vtt_path = output_file.replace(".mp3", ".vtt")
        if os.path.exists(output_file) and os.path.exists(vtt_path):
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
