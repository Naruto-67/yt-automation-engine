import os
import json
import sys
import time
from datetime import datetime

from scripts.quota_manager import quota_manager
from scripts.discord_notifier import notify_production_success, notify_error
from scripts.generate_script import generate_script
from scripts.generate_metadata import generate_seo_metadata

try:
    from scripts.generate_voice import generate_audio
    from scripts.generate_visuals import fetch_scene_images
    from scripts.render_video import render_video
    from scripts.youtube_manager import upload_to_youtube_vault, get_youtube_client, get_channel_name, get_actual_vault_count
except ImportError as e:
    print(f"🚨 [SYSTEM] CRITICAL DEPENDENCY MISSING: {e}")
    sys.exit(1)

# 🚨 ENGINE IS LIVE. 
TEST_MODE = False 

def load_matrix():
    path = os.path.join(os.path.dirname(__file__), "memory", "content_matrix.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except: return []
    return []

def save_matrix(matrix):
    path = os.path.join(os.path.dirname(__file__), "memory", "content_matrix.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(matrix, f, indent=4)

def run_production_cycle():
    # 🚨 SECURITY CHECK: Monitor Token Age
    quota_manager.check_and_update_refresh_token()

    print("🚀 [ENGINE] Ignition. Analyzing Live YouTube Vault Status...")
    try:
        youtube_client = get_youtube_client()
        if not youtube_client:
            raise Exception("YouTube Client failed to initialize. Check OAuth tokens.")

        vault_count = get_actual_vault_count(youtube_client)
        print(f"🏦 [VAULT] Verified YouTube Playlist Backlog: {vault_count}/14 videos.")
        
        if vault_count >= 14:
            print("🛑 [ENGINE] Vault is fully stocked. Shutting down to conserve APIs.")
            return

        matrix = load_matrix()
        unprocessed = [t for t in matrix if not t.get("processed", False)]
        
        if not unprocessed:
            print("⚠️ [ENGINE] Content Matrix is empty! Triggering Emergency Research Cycle...")
            from scripts.dynamic_researcher import run_dynamic_research
            run_dynamic_research()
            matrix = load_matrix()
            unprocessed = [t for t in matrix if not t.get("processed", False)]
            if not unprocessed:
                raise Exception("Emergency Research failed to populate matrix.")

        videos_needed = 14 - vault_count
        batch_size = min(videos_needed, 4) if not TEST_MODE else 1
        batch = unprocessed[:batch_size]

        channel_name = get_channel_name(youtube_client).replace("@", "")
        print(f"🏷️ [BRANDING] Secured Watermark: {channel_name}")

        success_count = 0
        for item in batch:
            topic = item['topic']
            niche = item['niche']
            print(f"\n🎬 [PROCESSING] {niche.upper()}: {topic}")
            
            # 🚨 QUOTA CHECK: Ensures we don't hit the 24-hr ban
            if not quota_manager.can_afford_youtube(1600):
                print("🛑 [QUOTA GUARDIAN] YouTube Quota limit reached (10k). Halting production to prevent API ban.")
                break

            audio_base = f"temp_audio_{success_count}"
            final_video = f"final_output_{success_count}.mp4"

            try:
                script_text, image_prompts, pexels_queries, scene_weights, script_prov = generate_script(niche, topic)
                if not script_text: raise Exception("Script generation failed.")
                
                print("⏳ [ENGINE] Pacing pipeline (10s) to prevent API rate limits...")
                time.sleep(10)

                metadata, seo_prov = generate_seo_metadata(niche, script_text)
                time.sleep(10)

                voice_success, voice_prov = generate_audio(script_text, output_base=audio_base)
                if not voice_success: raise Exception("Voice generation failed.")
                time.sleep(10)

                image_paths, visual_prov = fetch_scene_images(image_prompts, pexels_queries, base_filename=f"temp_scene_{success_count}")
                if len(image_paths) == 0: raise Exception("Visual generation failed.")
                time.sleep(10)

                render_success, video_duration, video_size = render_video(
                    image_paths, f"{audio_base}.wav", final_video, 
                    scene_weights=scene_weights, watermark_text=channel_name 
                )
                if not render_success: raise Exception("Render failed.")

                if not TEST_MODE:
                    upload_success, video_id = upload_to_youtube_vault(final_video, topic, metadata)
                    if upload_success:
                        item['processed'] = True
                        item['vaulted_date'] = datetime.utcnow().isoformat()
                        item['published'] = False
                        item['youtube_id'] = video_id 
                        success_count += 1
                else:
                    print(f"🛑 [TEST MODE] Skipped YT Upload (Saved 1600 Quota). Vaulting '{topic}' virtually.")
                    item['processed'] = True
                    item['vaulted_date'] = datetime.utcnow().isoformat()
                    item['published'] = False
                    success_count += 1
                
                notify_production_success(
                    niche=niche, topic=topic, script=script_text, script_ai=script_prov,
                    seo_ai=seo_prov, voice_ai=voice_prov, visual_ai=visual_prov,
                    metadata=metadata, duration=video_duration, size=video_size,
                    status="Successful (Test Mode)" if TEST_MODE else "Vaulted & Commented"
                )
                
                if not TEST_MODE:
                    for f in [f"{audio_base}.wav", f"{audio_base}.srt", final_video] + image_paths:
                        if os.path.exists(f): os.remove(f)

            except Exception as e:
                print(f"🚨 [CRASH] Topic '{topic}' failed.")
                quota_manager.diagnose_fatal_error("main.py", e)
                continue

        save_matrix(matrix)
        print(f"🏁 [FINISH] {success_count} videos sent to Vault.")
        
    except Exception as fatal_e:
        quota_manager.diagnose_fatal_error("System Core (main.py)", fatal_e)

if __name__ == "__main__":
    run_production_cycle()
