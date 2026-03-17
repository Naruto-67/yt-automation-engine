# smoke_test_v26.py
# Ghost Engine V26.0.0 — Pre-Flight Validation Script
import os
import json
from engine.logger import logger
from engine.config_manager import config_manager
from scripts.generate_script import generate_script
from scripts.generate_voice import generate_audio
from scripts.render_video import render_video

def run_v26_smoke_test():
    logger.engine("🧪 Initializing Ghost Engine V26 Smoke Test...")
    
    # 1. Test LLM & Directorial Logic
    logger.research("Testing V26 Script Generation & Personality Alignment...")
    try:
        topic = "The hidden silence of deep space"
        # Testing AnimeRise Gothic Narrator personality [cite: 12, 13, 262]
        script_text, prompts, pexels, weights, prov, meta = generate_script(
            niche="Space Mystery", 
            topic=topic, 
            personality="Gothic Narrator"
        )
        logger.success(f"Script Generated via {prov}. Mood: {meta['mood']}")
    except Exception as e:
        logger.error(f"Script Generation Failed: {e}")
        return

    # 2. Test TTS Prosody
    logger.generation("Testing V26 Punctuation-Based Prosody (Kokoro/Groq)...")
    audio_base = "test_smoke_audio"
    try:
        # We inject a test string with V26 ellipses for breath-pause testing [cite: 19, 25, 331]
        test_text = "Space is not empty... it is waiting. For us... to notice."
        success, voice_prov, duration = generate_audio(
            test_text, 
            output_base=audio_base, 
            target_voice="am_adam"
        )
        if success:
            logger.success(f"Audio Synthesized ({duration:.1f}s) via {voice_prov}")
        else:
            logger.error("TTS Production Failed.")
            return
    except Exception as e:
        logger.error(f"TTS Error: {e}")
        return

    # 3. Test FFmpeg Multi-Layer Mixer
    logger.render("Testing V26 FFmpeg Mixer (Subtitles, Glow, Music)...")
    output_vid = "v26_smoke_test_output.mp4"
    try:
        # Generate a dummy black image for rendering if none exists
        from PIL import Image
        dummy_img = "test_smoke_img.jpg"
        Image.new('RGB', (1080, 1920), color=(20, 20, 20)).save(dummy_img)

        # Test the renderer with V26 dynamic parameters [cite: 121, 122, 446]
        success, total_dur, size_mb = render_video(
            image_paths=[dummy_img],
            audio_path=f"{audio_base}.wav",
            output_path=output_vid,
            scene_weights=[1.0],
            watermark_text="V26_SMOKE_TEST",
            glow_color=meta.get("glow_color", "&H0000D700"),
            mood=meta.get("mood"),
            music_tag=meta.get("music_tag"),
            caption_style=meta.get("caption_style")
        )

        if success:
            logger.success(f"V26 Render Successful: {output_vid} ({size_mb:.1f}MB)")
            logger.success("✅ SYSTEM READY FOR PRODUCTION.")
        else:
            logger.error("FFmpeg Render Layer Failed.")

    except Exception as e:
        logger.error(f"Rendering Error: {e}")
    finally:
        # Cleanup test artifacts [cite: 153, 154]
        for f in [f"{audio_base}.wav", f"{audio_base}.srt", f"{audio_base}.ass", "test_smoke_img.jpg"]:
            if os.path.exists(f): os.remove(f)

if __name__ == "__main__":
    run_v26_smoke_test()
