import os
import sys
import time
import json
import random
import traceback
import subprocess

# Ghost Engine Core Imports
from scripts.quota_manager import quota_manager
from scripts.generate_script import generate_script
from scripts.generate_voice import generate_audio
from scripts.generate_visuals import fetch_background
from scripts.render_video import render_video
from scripts.generate_metadata import generate_seo_metadata
from scripts.logger import log_completed_video, is_script_duplicate
from scripts.youtube_manager import upload_to_youtube_vault, get_youtube_client, get_or_create_playlist
from scripts.discord_notifier import notify_error, notify_summary

def get_vault_count(youtube):
    """Calculates the current volume of the private Vault."""
    try:
        vault_id = get_or_create_playlist(youtube, "Vault Backup", "private")
        request = youtube.playlistItems().list(part="contentDetails", playlistId=vault_id, maxResults=50)
        response = request.execute()
        return len(response.get("items", []))
    except:
        return 14 # Default to full if API fails

def main():
    print(f"🚀 GHOST ENGINE V4.0 - MISSION START")
    
    youtube = get_youtube_client()
    if not youtube:
        sys.exit(1)

    # 1. Health Handshake
    is_healthy, msg, baby_steps = quota_manager.check_token_health()
    remaining_points = quota_manager.get_available_youtube_quota()

    if remaining_points < 1650:
        notify_summary(False, "YouTube Quota Depleted. Standing down.")
        sys.exit(0)

    # 2. Production Deficit Check (The 14-Vault Equilibrium)
    vault_count = get_vault_count(youtube)
    videos_to_build = quota_manager.get_production_deficit(vault_count)

    if videos_to_build <= 0:
        print("✅ [HEART] Vault at 100% Capacity (14/14). No build required.")
        notify_summary(True, "Equilibrium Maintained. Vault is full.")
        sys.exit(0)

    # 3. Execution Loop
    content_matrix_path = os.path.join("memory", "content_matrix.json")
    with open(content_matrix_path, "r") as f:
        content_matrix = json.load(f)

    successful_builds = 0

    for i in range(1, videos_to_build + 1):
        try:
            selected = random.choice(content_matrix)
            print(f"\n🎬 [BATCH {i}/{videos_to_build}] Producing: {selected['topic']}")

            raw_script, hook = generate_script(selected['niche'], selected['topic'])
            if is_script_duplicate(hook): continue

            run_id = int(time.time())
            audio_base = f"temp_audio_{run_id}"
            bg_video = f"temp_bg_{run_id}.mp4"
            final_video = f"GHOST_FINAL_{run_id}.mp4"

            # Production Pipeline
            if not generate_audio(raw_script, output_base=audio_base): raise Exception("Audio Crash")
            if not fetch_background(selected['bg_query'], output_filename=bg_video): raise Exception("Visual Crash")
            if not render_video(bg_video, f"{audio_base}.wav", final_video): raise Exception("Render Crash")

            metadata = generate_seo_metadata(selected['niche'], raw_script)
            
            if upload_to_youtube_vault(final_video, selected['niche'], selected['topic'], metadata):
                log_completed_video(selected['niche'], hook, final_video)
                successful_builds += 1
                
                # Immediate Cleanup to prevent Disk-Space Guard trigger
                for f in [bg_video, final_video, f"{audio_base}.wav", f"{audio_base}.srt", f"{audio_base}.ass"]:
                    if os.path.exists(f): os.remove(f)
            else:
                raise Exception("Vault Rejection")

        except Exception as e:
            quota_manager.diagnose_fatal_error(f"main.py (Build {i})", e)
            continue

    # 4. Reporting
    final_msg = f"Vault Equilibrium: {vault_count + successful_builds}/14.\n{msg}\n{baby_steps}"
    notify_summary(successful_builds > 0, final_msg)

if __name__ == "__main__":
    main()
