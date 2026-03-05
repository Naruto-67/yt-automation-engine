import os
import sys
import time
import json
import random
import traceback
import subprocess

# Ghost Engine Pillar Imports
from scripts.quota_manager import quota_manager
from scripts.generate_script import generate_script
from scripts.generate_voice import generate_audio
from scripts.generate_visuals import fetch_background
from scripts.render_video import render_video
from scripts.generate_metadata import generate_seo_metadata
from scripts.logger import log_completed_video, is_script_duplicate
from scripts.youtube_manager import upload_to_youtube_vault, get_youtube_client, get_or_create_playlist
from scripts.discord_notifier import notify_render, notify_error, notify_summary

def get_vault_count(youtube):
    """Counts current videos in the private Vault Backup playlist."""
    try:
        vault_id = get_or_create_playlist(youtube, "Vault Backup", "private")
        request = youtube.playlistItems().list(
            part="contentDetails",
            playlistId=vault_id,
            maxResults=50
        )
        response = request.execute()
        return len(response.get("items", []))
    except Exception as e:
        print(f"⚠️ [HEART] Could not fetch vault count: {e}")
        return 14 # Assume full to avoid infinite production loops if API is down

def main():
    print(f"==================================================")
    print(f"🚀 GHOST ENGINE V4.0 - MISSION START")
    print(f"==================================================")

    # --- PHASE 0: PRE-FLIGHT DIAGNOSTICS ---
    youtube = get_youtube_client()
    if not youtube:
        print("🚨 [HEART] Critical: YouTube Client failed to initialize.")
        sys.exit(1)

    # 1. Check Token Health (The 5-Month Alarm)
    is_healthy, msg, baby_steps = quota_manager.check_token_health()
    if not is_healthy:
        print(f"📢 [HEART] Token Warning Issued: {msg}")
        # We will let the script continue, but the warning is logged to the final summary

    # 2. Check YouTube Quota Points (10k Limit)
    remaining_points = quota_manager.get_available_youtube_quota()
    if remaining_points < 1650:
        print(f"🛑 [HEART] Insufficient YouTube Quota ({remaining_points} pts). Aborting to prevent 403 ban.")
        notify_summary(False, "YouTube Quota Exhausted. Production halted.")
        sys.exit(0)

    # 3. Assess Production Deficit (The 14-Vault Equilibrium)
    vault_count = get_vault_count(youtube)
    videos_to_build = quota_manager.get_production_deficit(vault_count)

    if videos_to_build <= 0:
        print("✅ [HEART] Vault is saturated (14/14). Standing down.")
        notify_summary(True, "Vault Full. No production needed today.")
        sys.exit(0)

    # --- PHASE 1: DYNAMIC PRODUCTION LOOP ---
    content_matrix_path = os.path.join("memory", "content_matrix.json")
    if not os.path.exists(content_matrix_path):
        print("🚨 [HEART] No content matrix found. Run weekly research first.")
        sys.exit(1)

    with open(content_matrix_path, "r") as f:
        content_matrix = json.load(f)

    successful_builds = 0

    for i in range(1, videos_to_build + 1):
        try:
            selected = random.choice(content_matrix)
            print(f"\n🎬 [RUN {i}/{videos_to_build}] Targeting: {selected['topic']}")

            # --- STEP 1: SCRIPT ---
            raw_script, hook = generate_script(selected['niche'], selected['topic'])
            if not raw_script or is_script_duplicate(hook):
                print(f"⏭️ [HEART] Duplicate hook or script failure. Skipping...")
                continue

            # --- DYNAMIC FILENAMES ---
            run_id = int(time.time())
            audio_base = f"temp_audio_{run_id}"
            bg_video = f"temp_bg_{run_id}.mp4"
            final_video = f"GHOST_FINAL_{run_id}.mp4"

            # --- STEP 2: VOICE (Orpheus/Kokoro + Pydub Trim) ---
            if not generate_audio(raw_script, output_base=audio_base):
                raise Exception("Audio engine failed.")

            # --- STEP 3: VISUALS (Imagen 4.0 + Ken Burns) ---
            if not fetch_background(selected['bg_query'], output_filename=bg_video):
                raise Exception("Visual engine failed.")

            # --- STEP 4: RENDER (BGM + Ducking + SFX + Bouncy ASS Subs) ---
            if not render_video(bg_video, f"{audio_base}.wav", final_video, selected.get('style', 'default')):
                raise Exception("FFmpeg rendering failed.")

            # --- STEP 5: SEO & VAULT ---
            metadata = generate_seo_metadata(selected['niche'], raw_script)
            
            # This triggers the Zombie Handshake and deducts 1600 points from QuotaManager
            if upload_to_youtube_vault(final_video, selected['niche'], selected['topic'], metadata):
                log_completed_video(selected['niche'], hook, final_video)
                successful_builds += 1
                
                # Update local quota points
                quota_manager.consume_points("youtube", 1600)
                
                # --- STEP 6: AGGRESSIVE CLEANUP (Loophole 1 Fix) ---
                print("🧹 [HEART] Cleaning up binary artifacts...")
                for f in [bg_video, final_video, f"{audio_base}.wav", f"{audio_base}.srt", f"{audio_base}.ass"]:
                    if os.path.exists(f): os.remove(f)
            else:
                raise Exception("YouTube Vault rejected the upload.")

        except Exception as e:
            # 🏥 THE AI DOCTOR LOGS THE CRASH
            quota_manager.diagnose_fatal_error(f"main.py (Build {i})", e)
            print(f"⚠️ [HEART] Build {i} failed. Attempting next in queue...")
            continue

    # --- PHASE 2: FINAL REPORTING ---
    final_msg = f"Vault Status: {vault_count + successful_builds}/14. Produced {successful_builds} videos."
    if not is_healthy:
        final_msg += f"\n\n{msg}\n{baby_steps}"

    notify_summary(successful_builds > 0, final_msg)
    print(f"\n✅ [HEART] Mission Complete. {successful_builds} secured.")

if __name__ == "__main__":
    main()
