import os
import re
import requests
import time

# Kokoro V1 is the master, edge-tts is the backup
def generate_voiceover(text, topic_name):
    """
    Generates audio narration. 
    Checks for Kokoro installation, falls back to Edge-TTS.
    """
    safe_name = re.sub(r'[^a-z0-9]', '_', topic_name.lower())
    output_path = f"temp_voice_{safe_name}.wav"
    
    print(f"🎙️ [VOICE] Generating narration for: {topic_name}")
    
    try:
        # Step 1: Attempt Kokoro (Local High-End AI)
        # Note: This requires 'kokoro' and 'soundfile' in requirements.txt
        try:
            from kokoro import KPipeline
            import soundfile as sf
            
            pipeline = KPipeline(lang_code='a') 
            generator = pipeline(text, voice='af_heart', speed=1.1, split_pattern=r'\n+')
            
            # Collect all audio segments
            import numpy as np
            all_audio = []
            for i, (gs, ps, audio) in enumerate(generator):
                all_audio.append(audio)
            
            if all_audio:
                combined = np.concatenate(all_audio)
                sf.write(output_path, combined, 24000)
                return output_path
        except Exception as e:
            print(f"⚠️ [VOICE] Kokoro unavailable or failed: {e}. Switching to Fallback.")

        # Step 2: Fallback to Edge-TTS (No API Key Required)
        import edge_tts
        import asyncio

        async def amain():
            communicate = edge_tts.Communicate(text, "en-US-ChristopherNeural", rate="+10%")
            await communicate.save(output_path.replace(".wav", ".mp3"))
            return output_path.replace(".wav", ".mp3")

        return asyncio.run(amain())

    except Exception as e:
        print(f"❌ [VOICE] Voice engine total failure: {e}")
        return None
