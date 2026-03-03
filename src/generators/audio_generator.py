import asyncio
import edge_tts
import os

async def generate_audio_async(text, output_file, voice="en-US-ChristopherNeural"):
    """
    Generates TTS audio using Microsoft Edge TTS.
    'en-US-ChristopherNeural' is a deep, engaging male voice perfect for Shorts.
    Other good options: 'en-US-EricNeural', 'en-GB-RyanNeural', 'en-US-AriaNeural'
    """
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_file)

def generate_audio(text, output_file, voice="en-US-ChristopherNeural"):
    """Wrapper to run the async audio generation."""
    try:
        # Run the async function synchronously
        asyncio.run(generate_audio_async(text, output_file, voice))
        
        if os.path.exists(output_file):
            print(f"Success! Audio saved to {output_file}")
            return True
        else:
            print("Error: Audio file was not created.")
            return False
    except Exception as e:
        print(f"Failed to generate audio: {e}")
        return False

if __name__ == "__main__":
    # Test script to make sure the voice engine is working
    test_text = "System online. This is a test of the automated voice engine. The pipeline is running perfectly, and we are ready to dominate the algorithm."
    output_path = "test_audio.mp3"
    
    print("Booting up Edge TTS...")
    generate_audio(test_text, output_path)
