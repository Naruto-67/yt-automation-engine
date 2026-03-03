import asyncio
import edge_tts
import os

async def generate_audio_async(text, output_file, voice="en-US-ChristopherNeural"):
    communicate = edge_tts.Communicate(text, voice)
    submaker = edge_tts.SubMaker()
    
    with open(output_file, "wb") as file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                file.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                submaker.feed(chunk)
                
    srt_path = output_file.replace(".mp3", ".srt")
    with open(srt_path, "w", encoding="utf-8") as file:
        file.write(submaker.get_srt())
    return True

def generate_audio(text, output_file, voice="en-US-ChristopherNeural"):
    return asyncio.run(generate_audio_async(text, output_file, voice))

if __name__ == "__main__":
    generate_audio("This is the stable, simple captioning system.", "test_audio.mp3")
