import os
import json
import sys
from datetime import datetime

from scripts.quota_manager import quota_manager
from scripts.discord_notifier import notify_summary, notify_error, notify_warning
from scripts.generate_script import generate_script
from scripts.generate_metadata import generate_seo_metadata

try:
    from scripts.generate_voice import generate_audio
    from scripts.generate_visuals import fetch_scene_images
    from scripts.render_video import render_video
    from scripts.youtube_manager import upload_to_youtube_vault
except ImportError as e:
    print(f"🚨 [SYSTEM] CRITICAL DEPENDENCY MISSING: {e}")
    sys.exit(1)

TEST_MODE = True  # Skips YouTube Upload safely

def load_matrix():
    path = os.path.join(os.path.dirname(__file__), "memory", "content_matrix.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_matrix(matrix):
    path = os.path.join(os.path.dirname(__file__), "memory", "content_matrix.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(matrix, f, indent=4)

def run_production_cycle():
    print("🚀 [ENGINE] Ignition. Analyzing Vault Status...")
    matrix = load_matrix()
    if not matrix: return

    unprocessed = [t for t in matrix if not t.get("processed", False)]
    batch = unprocessed[:1]

    if not batch:
        print("✅ [ENGINE] All topics complete.")
        return

    for item in batch:
        topic = item['topic']
        niche = item['niche']
        print(f"\n🎬 [PROCESSING] {niche.upper()}: {topic}")
        
        audio_base = f"temp_audio_0"
        final_video = f"final_output_0.mp4"

        try:
            # SCRIPT
            script_text, hook, image_prompts, script_prov = generate_script(niche, topic)
            if not script_text: raise Exception("Script generation failed.")

            # SEO
            metadata, seo_prov = generate_seo_metadata(niche, script_text)

            # VOICE
            voice_success, voice_prov = generate_audio(script_text, output_base=audio_base)
            if not voice_success: raise Exception("Voice generation failed.")

            # VISUALS
            image_paths, visual_prov = fetch_scene_images(image_prompts, base_filename="temp_scene_0")
            if len(image_paths) == 0: raise Exception("Visual generation failed.")

            # RENDER
            if not render_video(image_paths, f"{audio_base}.wav", final_video):
                raise Exception("Render failed.")

            # VAULT & PING
            print(f"🛑 [TEST MODE] Skipped YT Upload. Vaulting '{topic}' virtually.")
            item['processed'] = True
            
            summary_msg = (
                f"**Topic:** {topic}\n"
                f"**Script AI:** {script_prov}\n"
                f"**SEO AI:** {seo_prov}\n"
                f"**Voice AI:** {voice_prov}\n"
                f"**Visual AI:** {visual_prov}\n"
                f"*Status:* Vaulted (Test Mode)"
            )
            notify_summary(True, summary_msg)
            
            # CLEANUP
            for f in [f"{audio_base}.wav", f"{audio_base}.srt", final_video] + image_paths:
                if os.path.exists(f): os.remove(f)

        except Exception as e:
            print(f"🚨 [CRASH] Topic '{topic}' failed: {e}")
            quota_manager.diagnose_fatal_error("main.py", e)
            continue

    save_matrix(matrix)
    print(f"🏁 [FINISH] Production Complete.")

if __name__ == "__main__":
    run_production_cycle()
