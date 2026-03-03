import asyncio
import edge_tts
import os
import json

def format_ass_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"

async def generate_audio_async(text, output_filename, voice="en-US-ChristopherNeural"):
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
    output_path = os.path.join(root_dir, output_filename)
    timings_path = output_path.replace(".mp3", "_timings.json")

    communicate = edge_tts.Communicate(text, voice)
    words = []

    with open(output_path, "wb") as file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                file.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                words.append({
                    "text": chunk["text"],
                    "start": chunk["offset"] / 10000000,
                    "end": (chunk["offset"] + chunk["duration"]) / 10000000
                })

    # Group into 3-word caption chunks
    chunks = []
    for i in range(0, len(words), 3):
        group = words[i:i+3]
        chunks.append({
            "start": group[0]["start"],
            "end": group[-1]["end"],
            "words": group
        })

    # Save timings as JSON — this is what video_editor.py reads
    with open(timings_path, "w", encoding="utf-8") as f:
        json.dump(chunks, f, indent=2)

    print(f"Audio saved to: {output_path}")
    print(f"Timings saved to: {timings_path}")
    return True

def generate_audio(text, output_file, voice="en-US-ChristopherNeural"):
    return asyncio.run(generate_audio_async(text, output_file, voice))

if __name__ == "__main__":
    generate_audio("Testing the universal path system for perfect captions.", "test_audio.mp3")
