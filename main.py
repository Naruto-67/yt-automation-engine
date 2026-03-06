import os
import json
import sys
import random
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
    from scripts.youtube_manager import upload_to_youtube_vault, get_youtube_client, get_channel_name
except ImportError as e:
    print(f"🚨 [SYSTEM] CRITICAL DEPENDENCY MISSING: {e}")
    sys.exit(1)

TEST_MODE = True 

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

def enforce_weekly_targets(matrix):
    unprocessed_stories = sum(1 for item in matrix if not item.get('processed', False) and 'stor' in item.get('niche', '').lower())
    unprocessed_facts = sum(1 for item in matrix if not item.get('processed', False) and 'fact' in item.get('niche', '').lower())
    
    fact_subs = ["Horror", "Historical", "Space", "Psychological", "Deep Ocean", "Bizarre"]
    
    added_new = False
    while unprocessed_stories < 2:
        matrix.append({"niche": "Short Stories", "topic": "A mysterious and eerie urban legend", "processed": False})
        unprocessed_stories += 1
        added_new = True
        
    while unprocessed_facts < 4:
        sub = random.choice(fact_subs)
        matrix.append({"niche": f"{sub} Facts", "topic": f"Mind-blowing and unknown {sub} facts", "processed": False})
        unprocessed_facts += 1
        added_new = True
        
    if added_new: save_matrix(matrix)
    return matrix

def get_vault_status(matrix):
    vaulted = [t for t in matrix if t.get("processed", False) and not t.get("published", False)]
    return len(vaulted)

def run_production_cycle():
    print("🚀 [ENGINE] Ignition. Analyzing Vault Status...")
    try:
        matrix = load_matrix()
        matrix = enforce_weekly_targets(matrix)

        vault_count = get_vault_status(matrix)
        print(f"🏦 [VAULT] Current Backlog: {vault_count}/14 videos.")
        target_batch = 4 if vault_count < 14 else 2

        unprocessed = [t for t in matrix if not t.get("processed", False)]
        batch_size = target_batch if not TEST_MODE else 1 
        batch = unprocessed[:batch_size]

        if not batch:
            print("✅ [ENGINE] All topics complete.")
            return

        # 🚨 DYNAMIC WATERMARK: Fetching Channel Name (No "@" symbol)
        youtube_client = get_youtube_client()
        channel_name = get_channel_name(youtube_client) if youtube_client else "GhostEngine"
        print(f"🏷️ [BRANDING] Secured Channel Name for Watermark: {channel_name}")

        success_count = 0
        for item in batch:
            topic = item['topic']
            niche = item['niche']
            print(f"\n🎬 [PROCESSING] {niche.upper()}: {topic}")
            
            audio_base = f"temp_audio_{success_count}"
            final_video = f"final_output_{success_count}.mp4"

            try:
                script_text, image_prompts, pexels_queries, scene_weights, script_prov = generate_script(niche, topic)
                if not script_text: raise Exception("Script generation failed.")
                
                # 🚨 RATE LIMIT GUARD
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
                    image_paths, 
                    f"{audio_base}.wav", 
                    final_video, 
                    scene_weights=scene_weights, 
                    watermark_text=channel_name # Passed dynamically here
                )
                if not render_success:
                    raise Exception("Render failed.")

                if not TEST_MODE:
                    upload_success = upload_to_youtube_vault(final_video, niche, topic, metadata)
                    if upload_success:
                        item['processed'] = True
                        item['vaulted_date'] = datetime.utcnow().isoformat()
                        item['published'] = False
                        success_count += 1
                else:
                    print(f"🛑 [TEST MODE] Skipped YT Upload & Auto-Comment. Vaulting '{topic}' virtually.")
                    item['processed'] = True
                    item['vaulted_date'] = datetime.utcnow().isoformat()
                    item['published'] = False
                    success_count += 1
                
                notify_production_success(
                    niche=niche,
                    topic=topic,
                    script=script_text,
                    script_ai=script_prov,
                    seo_ai=seo_prov,
                    voice_ai=voice_prov,
                    visual_ai=visual_prov,
                    metadata=metadata,
                    duration=video_duration,
                    size=video_size,
                    status="Successful (Test Mode)" if TEST_MODE else "Vaulted & Commented"
                )
                
                if not TEST_MODE:
                    for f in [f"{audio_base}.wav", f"{audio_base}.srt", final_video] + image_paths:
                        if os.path.exists(f): os.remove(f)

            except Exception as e:
                print(f"🚨 [CRASH] Topic '{topic}' failed: {e}")
                from scripts.quota_manager import quota_manager
                quota_manager.diagnose_fatal_error("main.py", e)
                notify_error("Production Pipeline", type(e).__name__, str(e))
                continue

        save_matrix(matrix)
        print(f"🏁 [FINISH] {success_count} videos sent to Vault.")
        
    except Exception as fatal_e:
        print(f"🚨 [FATAL SYSTEM CRASH]: {fatal_e}")
        notify_error("System Core (main.py)", "Fatal Exception", str(fatal_e))

if __name__ == "__main__":
    run_production_cycle()
