import os
import sys
import random
import time
import re
from scripts.generate_script import generate_script
from scripts.generate_voice import generate_audio
from scripts.fetch_background import fetch_background
from scripts.render_video import render_video
from scripts.logger import is_script_duplicate, log_completed_video
from scripts.drive_manager import manage_drive_backup
from scripts.discord_notifier import notify_render, notify_warning, notify_error, notify_summary
from moviepy import VideoFileClip

def main():
    content_matrix = [
        {
            "niche": "fact",
            "topic": "A bizarre, 100% true, unknown historical event from the USA",
            "bg_query": "mysterious dark background",
            "style": "default"
        },
        {
            "niche": "brainrot",
            "topic": "Absurd, high-energy internet culture topic designed for maximum Gen-Z retention",
            "bg_query": "trippy abstract loop fast",
            "style": "default"
        },
        {
            "niche": "short story",
            "topic": "A 60-second self-improvement and motivation parable about overcoming laziness",
            "bg_query": "cinematic nature mountain",
            "style": "default"
        }
    ]

    selected = random.choice(content_matrix)
    print(f"==================================================")
    print(f"🚀 INITIALIZING YOUTUBE AUTOMATION ENGINE")
    print(f"🎯 Target Niche: {selected['niche'].upper()}")
    print(f"==================================================")
    
    # --- STEP 1: SCRIPT GENERATION ---
    print("\n[STEP 1/5] Booting Self-Improving AI Writer...")
    max_retries = 3
    clean_text, script_hook = "", ""
    
    for attempt in range(max_retries):
        raw_script = generate_script(selected['niche'], selected['topic'])
        if not raw_script:
            sys.exit(1)
            
        temp_text = re.sub(r'\[.*?\]', '', raw_script)
        temp_text = re.sub(r'\(.*?\)', '', temp_text)
        
        pronunciation_map = {r"\b911\b": "nine one one", r"\b100%\b": "one hundred percent", r"\bUSA\b": "U S A"}
        for pattern, replacement in pronunciation_map.items():
            temp_text = re.sub(pattern, replacement, temp_text, flags=re.IGNORECASE)
            
        temp_text = temp_text.replace("*", "").replace("_", "").replace('"', "").replace("#", "")
        temp_text = " ".join([line.strip() for line in temp_text.split('\n') if line.strip()])
        
        words = temp_text.split()
        script_hook = " ".join(words[:10])
        
        if is_script_duplicate(script_hook):
            notify_warning(selected['topic'], "Script Generation (Duplicate)", attempt+1, max_retries)
            continue 
        else:
            clean_text = temp_text
            break 
            
    if not clean_text:
        notify_error(selected['topic'], "Script Generation", "Job Aborted")
        sys.exit(1)

    # --- STEP 2: VOICE & SUBTITLES ---
    print("[STEP 2/5] Booting Kokoro TTS & Faster-Whisper...")
    audio_base_name = "master_audio"
    if not generate_audio(clean_text, output_base=audio_base_name):
        sys.exit(1)
        
    # --- STEP 3: BACKGROUND VISUALS ---
    print(f"\n[STEP 3/5] Fetching Background ('{selected['bg_query']}') via APIs/Fallbacks...")
    video_filename = "master_background.mp4"
    if not fetch_background(selected['bg_query'], output_filename=video_filename):
        notify_error(selected['topic'], "Pexels Download", "Local Assets Vault")
        
    # --- STEP 4: FINAL ASSEMBLY ---
    print("\n[STEP 4/5] Sending to FFmpeg Render Engine...")
    run_id = int(time.time())
    final_filename = f"FINAL_SHORT_{selected['niche'].replace(' ', '_')}_{run_id}.mp4"
    
    if not render_video(video_filename, f"{audio_base_name}.wav", final_filename, selected['style']):
        sys.exit(1)
        
    # CALCULATE PRECISE STATS FOR DISCORD
    file_size_mb = os.path.getsize(final_filename) / (1024 * 1024)
    clip = VideoFileClip(final_filename)
    duration_sec = int(clip.duration)
    clip.close()
    
    # 📢 DISCORD PING: Render Complete
    notify_render(selected['topic'], file_size_mb, duration_sec)
        
    # --- STEP 5: LOG & BACKUP ---
    print("\n[STEP 5/5] Securing Data: Logging and Vaulting...")
    log_completed_video(selected['niche'], script_hook, final_filename)
    manage_drive_backup(final_filename, selected['topic'])
    
    notify_summary(f"1 Video Rendered | Backed up to Vault")

    if "GITHUB_ENV" in os.environ:
        with open(os.environ["GITHUB_ENV"], "a") as env_file:
            env_file.write(f"FINAL_VIDEO_NAME={final_filename}\n")

if __name__ == "__main__":
    main()
