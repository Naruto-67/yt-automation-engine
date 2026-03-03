import asyncio
import edge_tts
import os

async def generate_audio_async(text, output_filename, voice="en-US-ChristopherNeural"):
    root_dir    = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
    output_path = os.path.join(root_dir, output_filename)

    communicate = edge_tts.Communicate(text, voice)

    with open(output_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])

    size_kb = os.path.getsize(output_path) / 1024
    print(f"✅ Audio saved: {output_path} ({size_kb:.1f} KB)")
    return output_path

def generate_audio(text, output_file, voice="en-US-ChristopherNeural"):
    return asyncio.run(generate_audio_async(text, output_file, voice))

if __name__ == "__main__":
    generate_audio(
        "Testing captions. Every word should pop and highlight yellow when spoken.",
        "test_audio.mp3"
    )
