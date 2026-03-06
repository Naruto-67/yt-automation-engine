import os
import json
import sys
from datetime import datetime

from scripts.quota_manager import quota_manager
from scripts.discord_notifier import notify_production_success, notify_error
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

def get_vault_status(matrix):
    vaulted = [t for t in matrix if t.get("processed", False) and not t.get("published", False)]
    return len(vaulted)

def run_production_cycle():
    print("🚀 [ENGINE] Ignition. Analyzing Vault Status...")
    try:
        matrix = load_matrix()
        if not matrix: return

        vault_count = get_vault_status(matrix)
        print(f"🏦 [VAULT] Current Backlog: {vault_count}/14 videos.")
        target_batch = 4 if vault_count < 14 else 2

        unprocessed = [t for t in matrix if not t.get("processed", False)]
        batch_size = target_batch if not TEST_MODE else 1 
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
                # SCRIPT
                script_text, hook, image_prompts, script_prov = generate_script(niche, topic)
                if not script_text: raise Exception("Script generation failed.")

                # SEO
                metadata, seo_prov = generate_seo_metadata(niche, script_text)

                # VOICE
                voice_success, voice_prov = generate_audio(script_text, output_base=audio_base)
                if not voice_success: raise Exception("Voice generation failed.")

                # VISUALS
                image_paths, visual_prov = fetch_scene_images(image_prompts, base_filename=f"temp_scene_{success_count}")
                if len(image_paths) == 0: raise Exception("Visual generation failed.")

                # RENDER
                if not render_video(image_paths, f"{audio_base}.wav", final_video):
                    raise Exception("Render failed.")

                # VAULT
                if not TEST_MODE:
                    upload_success = upload_to_youtube_vault(final_video, niche, topic, metadata)
                    if upload_success:
                        item['processed'] = True
                        item['vaulted_date'] = datetime.utcnow().isoformat()
                        item['published'] = False
                        success_count += 1
                else:
                    print(f"🛑 [TEST MODE] Skipped YT Upload. Vaulting '{topic}' virtually.")
                    item['processed'] = True
                    item['vaulted_date'] = datetime.utcnow().isoformat()
                    item['published'] = False
                    success_count += 1
                
                # 🚨 THE NEW DISCORD PING
                notify_production_success(
                    niche=niche,
                    topic=topic,
                    script=script_text,
                    script_ai=script_prov,
                    seo_ai=seo_prov,
                    voice_ai=voice_prov,
                    visual_ai=visual_prov,
                    metadata=metadata,
                    status="Successful (Test Mode)"
                )
                
                # CLEANUP
                if not TEST_MODE:
                    for f in [f"{audio_base}.wav", f"{audio_base}.srt", final_video] + image_paths:
                        if os.path.exists(f): os.remove(f)

            except Exception as e:
                print(f"🚨 [CRASH] Topic '{topic}' failed: {e}")
                quota_manager.diagnose_fatal_error("main.py", e)
                # Global Error Ping to Discord
                notify_error("Production Pipeline", type(e).__name__, str(e))
                continue

        save_matrix(matrix)
        print(f"🏁 [FINISH] {success_count} videos sent to Vault.")
        
    except Exception as fatal_e:
        print(f"🚨 [FATAL SYSTEM CRASH]: {fatal_e}")
        notify_error("System Core (main.py)", "Fatal Exception", str(fatal_e))

if __name__ == "__main__":
    run_production_cycle()
