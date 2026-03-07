import os
import json
import sys
import time
import glob
from datetime import datetime
from googleapiclient.errors import HttpError

from scripts.quota_manager import quota_manager
from scripts.discord_notifier import notify_production_success, notify_error, notify_summary, notify_step
from scripts.generate_script import generate_script
from scripts.generate_metadata import generate_seo_metadata
from scripts.logger import log_completed_video

try:
    from scripts.generate_voice import generate_audio
    from scripts.generate_visuals import fetch_scene_images
    from scripts.render_video import render_video
    from scripts.youtube_manager import upload_to_youtube_vault, get_youtube_client, get_channel_name, get_actual_vault_count
except ImportError as e:
    print(f"🚨 [SYSTEM] CRITICAL DEPENDENCY MISSING: {e}")
    sys.exit(1)

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
    tmp_path = path + ".tmp"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(matrix, f, indent=4)
    os.replace(tmp_path, path)

def global_garbage_collector():
    print("🧹 [GC] Initializing Global Garbage Collection...")
    extensions = ["*.wav", "*.srt", "*.ass", "*.jpg", "*.jpeg", "*.JPEG", "*.png", "temp_*", "concat_list.txt"]
    for ext in extensions:
        for file in glob.glob(ext):
            try: os.remove(file)
            except: pass
            
    for file in glob.glob("temp_anim_*.mp4"):
        try: os.remove(file)
        except: pass
        
    for file in glob.glob("temp_merged*.mp4"):
        try: os.remove(file)
        except: pass

def run_production_cycle():
    notify_summary(True, "☀️ **System Wake**\nGhost Engine is spinning up the daily production cycle.")
    quota_manager.check_and_update_refresh_token()
    
    # 🚨 FIX: Absolute SIGKILL Defense. Deletes massive partial video renders from the previous day immediately upon boot to save GitHub Actions Storage Space.
    global_garbage_collector()

    print("🚀 [ENGINE] Ignition. Analyzing Live YouTube Vault Status...")
    try:
        youtube_client = get_youtube_client()
        if not youtube_client and not TEST_MODE:
            raise Exception("YouTube Client failed to initialize. Check OAuth tokens.")

        vault_count = get_actual_vault_count(youtube_client) if not TEST_MODE else 5
        print(f"🏦 [VAULT] Verified YouTube Playlist Backlog: {vault_count}/14 videos.")
        
        if vault_count >= 14:
            print("🛑 [ENGINE] Vault is fully stocked. Shutting down to conserve APIs.")
            notify_summary(True, "🌙 **System Sleep**\nVault is completely full. Shutting down to conserve API quotas.")
            return

        matrix = load_matrix()
        unprocessed = [t for t in matrix if not t.get("processed", False) and not t.get("failed_flag", False)]
        
        if len(unprocessed) < 4:
            print(f"⚠️ [ENGINE] Queue low ({len(unprocessed)} left). Triggering Emergency Research Cycle...")
            from scripts.dynamic_researcher import run_dynamic_research
            run_dynamic_research()
            matrix = load_matrix()
            unprocessed = [t for t in matrix if not t.get("processed", False) and not t.get("failed_flag", False)]
            if not unprocessed:
                raise Exception("Emergency Research failed to populate matrix.")

        videos_needed = 14 - vault_count
        batch_size = min(videos_needed, 2) if TEST_MODE else min(videos_needed, 4)
        batch = unprocessed[:batch_size]

        channel_name = get_channel_name(youtube_client).replace("@", "") if not TEST_MODE else "GhostEngine_Test"
        print(f"🏷️ [BRANDING] Secured Watermark: {channel_name}")
        print(f"🎯 [TARGET] Processing {batch_size} videos for this run.")

        success_count = 0
        
        for item in batch:
            topic = item['topic']
            niche = item['niche']
            
            is_fact_based = any(k in niche.lower() for k in ['fact', 'hack', 'trend', 'brainrot'])
            min_audio = 10.0 if is_fact_based else 22.0
            
            max_item_attempts = 3
            item_success = False
            
            for attempt in range(1, max_item_attempts + 1):
                print(f"\n🎬 [PROCESSING] {niche.upper()}: {topic} (Attempt {attempt}/{max_item_attempts})")
                notify_step(topic, f"Ignition (Attempt {attempt}/{max_item_attempts})", f"Niche: **{niche.upper()}**", 0x3498db) 
                
                if not TEST_MODE and not quota_manager.can_afford_youtube(1700):
                    print("🛑 [QUOTA GUARDIAN] YouTube Quota limit reached (10k). Halting production to prevent API ban.")
                    notify_step(topic, "Quota Guardian", "YouTube Quota limit reached (10k). Halting.", 0xe74c3c)
                    return 

                global_garbage_collector()

                audio_base = f"temp_audio_{success_count}"
                final_video = f"final_output_{success_count}.mp4"
                image_paths = []

                try:
                    valid_script = False
                    for script_attempt in range(3):
                        print(f"   -> [SCRIPT] Generation Phase (Attempt {script_attempt + 1}/3)...")
                        notify_step(topic, f"Drafting Script (Try {script_attempt + 1}/3)", "Asking AI for narrative constraints...", 0x95a5a6)
                        
                        script_text, image_prompts, pexels_queries, scene_weights, script_prov = generate_script(niche, topic)
                        
                        if not script_text: 
                            notify_step(topic, "Script Rejected", "AI returned invalid JSON/Length. Retrying...", 0xf1c40f)
                            time.sleep(2)
                            continue
                            
                        print(f"   -> [VOICE] Testing audio length for Kokoro pacing...")
                        notify_step(topic, "Testing Voice Pacing", f"Generating audio via {script_prov}...", 0x3498db)
                        
                        voice_success, voice_prov, audio_duration = generate_audio(script_text, output_base=audio_base)
                        
                        if not voice_success: 
                            notify_step(topic, "Voice Generator Crashed", "Kokoro/Groq failed to return audio.", 0xe74c3c)
                            raise ValueError("Voice generation crashed entirely.")
                            
                        print(f"   -> [TIMING] Audio clocked at {audio_duration:.1f} seconds.")
                        
                        if audio_duration > 59.0:
                            print(f"   ⚠️ [REJECTED] Audio is too long ({audio_duration:.1f}s). Regenerating...")
                            notify_step(topic, "Validation Rejected", f"Audio is too long ({audio_duration:.1f}s). Max is 59s. Regenerating...", 0xf1c40f)
                            continue 
                            
                        if audio_duration < min_audio:
                            print(f"   ⚠️ [REJECTED] Audio is too short for this niche type ({audio_duration:.1f}s < {min_audio}s). Regenerating...")
                            notify_step(topic, "Validation Rejected", f"Audio is too short ({audio_duration:.1f}s). Min is {min_audio}s. Regenerating...", 0xf1c40f)
                            continue

                        print(f"   ✅ [TIMING] Perfect duration for {niche.upper()} ({audio_duration:.1f}s).")
                        notify_step(topic, "Validation Passed", f"Perfect duration achieved: **{audio_duration:.1f}s**.", 0x2ecc71)
                        valid_script = True
                        break 
                        
                    if not valid_script:
                        raise ValueError("Failed to generate a script with proper audio timing after 3 attempts.")

                    print(f"   -> [METADATA] Generating SEO payload...")
                    notify_step(topic, "Generating SEO", "Creating YouTube optimized metadata...", 0x3498db)
                    time.sleep(5)
                    metadata, seo_prov = generate_seo_metadata(niche, script_text)
                    print(f"      Title: {metadata.get('title')}")

                    print(f"   -> [VISUALS] Sourcing {len(image_prompts)} scenes...")
                    notify_step(topic, "Sourcing Visuals", f"Fetching {len(image_prompts)} scenes from Cloudflare/HF/Pexels...", 0x3498db)
                    time.sleep(5)
                    image_paths, visual_prov = fetch_scene_images(image_prompts, pexels_queries, base_filename=f"temp_scene_{success_count}")
                    
                    if len(image_paths) < len(image_prompts): 
                        raise ValueError(f"Visual Desync: Only generated {len(image_paths)}/{len(image_prompts)} images. Aborting.")
                    time.sleep(10)

                    print(f"   -> [RENDER] Compiling Video...")
                    notify_step(topic, "Rendering Video", "Combining Audio, Visuals, and Subtitles via Master Engine...", 0x9b59b6)
                    render_success, video_duration, video_size = render_video(
                        image_paths, f"{audio_base}.wav", final_video, 
                        scene_weights=scene_weights, watermark_text=channel_name 
                    )
                    if not render_success: raise ValueError("Render failed or output file is corrupted/zero-bytes.")

                    if not TEST_MODE:
                        upload_success, video_id = upload_to_youtube_vault(final_video, topic, metadata)
                        if upload_success:
                            item['processed'] = True
                            item['vaulted_date'] = datetime.utcnow().isoformat()
                            item['published'] = False
                            item['youtube_id'] = video_id 
                            success_count += 1
                            log_completed_video(niche, topic, final_video)
                            item_success = True
                        else:
                            raise ConnectionError("YouTube Upload API Rejected the Payload after successful render.")
                    else:
                        print(f"🛑 [TEST MODE] Skipped YT Upload. Vaulting '{topic}' virtually.")
                        item['processed'] = True
                        item['vaulted_date'] = datetime.utcnow().isoformat()
                        item['published'] = False
                        success_count += 1
                        item_success = True
                    
                    notify_production_success(
                        niche=niche, topic=topic, script=script_text, script_ai=script_prov,
                        seo_ai=seo_prov, voice_ai=voice_prov, visual_ai=visual_prov,
                        metadata=metadata, duration=video_duration, size=video_size,
                        status="Successful (Test Mode)" if TEST_MODE else "Vaulted & Commented"
                    )
                    break

                except Exception as e:
                    if isinstance(e, HttpError) and e.resp.status == 403 and b"quota" in e.content.lower():
                        print(f"🛑 [FATAL] Hard YouTube Quota Reached. System is freezing to protect the queue.")
                        notify_step(topic, "Quota Freeze", "Hard YouTube Quota reached mid-upload. Freezing process.", 0xe74c3c)
                        save_matrix(matrix)
                        sys.exit(0)
                        
                    if isinstance(e, ConnectionError):
                        notify_step(topic, "Upload Blocked", "Video rendered safely, but YT refused upload. Retrying tomorrow.", 0xe74c3c)
                        print(f"⚠️ [NETWORK] {e}")
                        break 

                    error_msg = str(e)
                    print(f"🚨 [CRASH] Topic '{topic}' failed: {error_msg}")
                    notify_step(topic, "Exception Caught", error_msg[:300], 0xe74c3c)
                    
                    is_api_error = not isinstance(e, ValueError)
                    
                    if is_api_error:
                        quota_manager.diagnose_fatal_error("main.py", e)
                        
                    if attempt < max_item_attempts:
                        if is_api_error:
                            cooldown = 60 * attempt
                            notify_step(topic, "API Cooldown", f"Enforcing {cooldown}s progressive cooldown before retry...", 0xe67e22)
                            time.sleep(cooldown)
                        else:
                            notify_step(topic, "Logic Retry", "Retrying immediately without cooldown...", 0xe67e22)
                    else:
                        print(f"💀 [SAFETY PROTOCOL] Topic failed 3 times. Permanently quarantined.")
                        notify_step(topic, "Quarantined", "Topic failed 3 times. Permanently removing from queue.", 0x000000)
                        item['processed'] = True
                        item['failed_flag'] = True
                
                finally:
                    if not TEST_MODE:
                        global_garbage_collector()
            
            save_matrix(matrix)

        print(f"🏁 [FINISH] {success_count} videos sent to Vault.")
        notify_summary(True, f"🌙 **System Sleep**\nProduction cycle complete. Successfully processed {success_count} videos.")
        
    except Exception as fatal_e:
        quota_manager.diagnose_fatal_error("System Core (main.py)", fatal_e)

if __name__ == "__main__":
    run_production_cycle()
