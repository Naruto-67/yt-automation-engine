import asyncio
import edge_tts
import os
import json

async def generate_audio_async(text, output_filename, voice="en-US-ChristopherNeural"):
    root_dir     = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
    output_path  = os.path.join(root_dir, output_filename)
    timings_path = output_path.replace(".mp3", "_timings.json")

    communicate = edge_tts.Communicate(text, voice)
    words = []

    with open(output_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                words.append({
                    "text":  chunk["text"],
                    "start": chunk["offset"] / 10_000_000,
                    "end":   (chunk["offset"] + chunk["duration"]) / 10_000_000
                })

    # Group into 3-word chunks
    chunks = []
    for i in range(0, len(words), 3):
        group = words[i:i+3]
        chunks.append({
            "start": group[0]["start"],
            "end":   group[-1]["end"],
            "words": group
        })

    with open(timings_path, "w") as f:
        json.dump(chunks, f, indent=2)

    print(f"✅ Audio:   {output_path}")
    print(f"✅ Timings: {timings_path}  ({len(chunks)} chunks)")
    return True

def generate_audio(text, output_file, voice="en-US-ChristopherNeural"):
    return asyncio.run(generate_audio_async(text, output_file, voice))

if __name__ == "__main__":
    generate_audio(
        "Testing captions. Every word should pop and highlight yellow when spoken. This is the final test.",
        "test_audio.mp3"
    )
