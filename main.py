import os
import json
import traceback
import sys

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

# ==========================================
# 🛑 TEST MODE TOGGLE
# ==========================================
TEST_MODE = True  # Set to False to enable YouTube Uploads and File Cleanup

def load_matrix():
    root_dir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(root_dir, "memory", "content_matrix.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_matrix(matrix):
    root_dir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(root_dir, "memory", "content_matrix.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(matrix, f, indent=4)

def run_production_cycle():
    print("🚀 [ENGINE] Ignition. Starting Batch Production...")
    if TEST_MODE:
        print("🛑 [TEST MODE] Uploads Disabled. Cleanup Disabled. Artifacts will be preserved.")
        
    matrix = load_matrix()
    if not matrix:
        print("❌ [ENGINE] Content Matrix is empty. Run Weekly Research first.")
        return

    unprocessed = [t for t in matrix if not t.get("processed", False)]
    batch_size = 1 if TEST_MODE else 4
    batch = unprocessed[:batch_size]

    if not batch:
        print("✅ [ENGINE] All topics complete.")
        return

    success_count = 0
    
    for item in batch:
        topic = item['topic']
        niche = item['niche']
        
        print(f"\n🎬 [PROCESSING] {niche.upper()}: {topic}")
        
        audio_base = f"temp_audio_{success_count}"
        final_video = f"final_output_{success_count}.mp4"

        try:
            script_text, hook, image_prompts = generate_script(niche, topic)
            if not script_text or len(image_prompts) == 0:
                raise Exception("Script or Image Prompts returned empty.")

            metadata = generate_seo_metadata(niche, script_text)

            voice_success, provider = generate_audio(script_text, output_base=audio_base)
            if not voice_success:
                raise Exception("Voice/SRT generation failed.")
            print(f"✅ [VOICE] Audio secured via {provider}")

            image_paths = fetch_scene_images(image_prompts, base_filename=f"temp_scene_{success_count}")
            if len(image_paths) == 0:
                raise Exception("All visual generation engines failed.")
            print(f"✅ [VISUALS] Secured {len(image_paths)} scene images.")

            render_success = render_video(image_paths, f"{audio_base}.wav", final_video)
            if not render_success:
                raise Exception("FFmpeg Master Render failed.")

            if not TEST_MODE:
                upload_success = upload_to_youtube_vault(final_video, niche, topic, metadata)
                if upload_success:
                    item['processed'] = True
                    success_count += 1
                    print(f"✅ [SUCCESS] {topic} vaulted.")
            else:
                print(f"🛑 [TEST MODE] Skipping YouTube Upload for '{topic}'. Marking as successful for test.")
                item['processed'] = True
                success_count += 1
            
            if not TEST_MODE:
                print("🧹 [CLEANUP] Removing temporary files...")
                for f in [f"{audio_base}.wav", f"{audio_base}.srt", f"{audio_base}.mp3", final_video] + image_paths:
                    if os.path.exists(f): os.remove(f)
            else:
                print("🛑 [TEST MODE] Cleanup skipped. Artifacts preserved for inspection.")

        except Exception as e:
            print(f"🚨 [CRASH] Topic '{topic}' failed: {e}")
            quota_manager.diagnose_fatal_error("main.py", e)
            continue

    save_matrix(matrix)
    if success_count > 0:
        msg = f"Production Complete. {success_count} videos processed."
        print(f"🏁 [FINISH] {msg}")
    else:
        print("⚠️ [FINISH] Production batch yielded 0 results.")

if __name__ == "__main__":
    run_production_cycle()
