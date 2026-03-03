import asyncio
import edge_tts
import os
import json

async def generate_audio_async(text, output_file, voice="en-US-ChristopherNeural"):
    """Generates audio and catches EVERY boundary type for metadata."""
    communicate = edge_tts.Communicate(text, voice)
    words_data = []
    
    print(f"Connecting to Edge TTS for: '{text[:20]}...'")
    
    with open(output_file, "wb") as file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                file.write(chunk["data"])
            # Catching Word, Sentence, AND any other boundary type Microsoft might use
            elif "Boundary" in chunk["type"]:
                words_data.append({
                    "text": chunk.get("text", ""),
                    "start": chunk["offset"] / 10000000,
                    "duration": chunk["duration"] / 10000000
                })
                
    # If the list is empty, the editor will fail, so we print a big warning
    if not words_data:
        print("CRITICAL WARNING: No timing data captured from Edge TTS!")
    else:
        print(f"Success! Captured {len(words_data)} word timings.")

    json_path = output_file.replace(".mp3", ".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(words_data, f, indent=4)

def generate_audio(text, output_file, voice="en-US-ChristopherNeural"):
    try:
        asyncio.run(generate_audio_async(text, output_file, voice))
        return os.path.exists(output_file)
    except Exception as e:
        print(f"Audio Engine Error: {e}")
        return False

if __name__ == "__main__":
    # Use a longer sentence to ensure we trigger multiple boundaries
    test_text = "The quick brown fox jumps over the lazy dog to test the subtitle system."
    generate_audio(test_text, "test_audio.mp3")
