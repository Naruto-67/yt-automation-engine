import asyncio
import edge_tts
import os
import json

async def generate_audio_async(text, output_file, voice="en-US-ChristopherNeural"):
    communicate = edge_tts.Communicate(text, voice)
    words_data = []
    
    print("Generating audio and word-level metadata...")
    
    with open(output_file, "wb") as file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                file.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                # Convert 100-nanosecond ticks to seconds
                words_data.append({
                    "text": chunk["text"],
                    "start": chunk["offset"] / 10000000,
                    "duration": chunk["duration"] / 10000000
                })
                
    # Save word data to JSON for the video editor to read
    json_path = output_file.replace(".mp3", ".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(words_data, f, indent=4)

def generate_audio(text, output_file, voice="en-US-ChristopherNeural"):
    try:
        asyncio.run(generate_audio_async(text, output_file, voice))
        return os.path.exists(output_file)
    except Exception as e:
        print(f"Audio Error: {e}")
        return False

if __name__ == "__main__":
    generate_audio("Testing the dynamic line highlight system.", "test_audio.mp3")
