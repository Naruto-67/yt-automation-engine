import os
import sys
import random
import time
import re
import json
from scripts.generate_script import generate_script
from scripts.generate_voice import generate_audio
from scripts.fetch_background import fetch_background
from scripts.render_video import render_video
from scripts.generate_metadata import generate_seo_metadata
from scripts.logger import is_script_duplicate, log_completed_video
from scripts.youtube_manager import upload_to_youtube_vault
from scripts.discord_notifier import notify_render, notify_warning, notify_error, notify_summary
from moviepy import VideoFileClip

def load_content_matrix():
    """Reads the AI-generated topic matrix. Falls back to default if empty."""
    root_dir = os.path.dirname(os.path.abspath(__file__))
    matrix_path = os.path.join(root_dir, "memory", "content_matrix.json")
    
    default_matrix = [
        {"niche": "fact", "topic": "Bizarre USA history", "bg_query": "mysterious dark", "style": "default"},
        {"niche": "brainrot", "topic": "Gen Z memes", "bg_query": "trippy abstract", "style": "default"}
    ]
    
    if os.path.exists(matrix_path):
        try:
            with open(matrix_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data:
                    print(f"🧠 Matrix Loaded: {len(data)} trending topics ready.")
                    return data
        except Exception as e:
            print(f"⚠️ Failed to read matrix: {e}")
            
    return default_matrix

def main():
    # --- LOAD DYNAMIC TOPICS ---
    content_matrix = load_content_matrix()
    selected = random.choice(content_matrix)
    
    print(f"==================================================")
    print(f"🚀 INITIALIZING YOUTUBE AUTOMATION ENGINE V2.0")
    print(f"🎯 Target Niche: {selected['niche'].upper()}")
    print(f"📝 Target Topic: {selected['topic']}")
    print(f"==================================================")
    
    # --- STEP 1: SCRIPT GENERATION ---
    print("\n[STEP 1/6] Booting Self-Improving AI Writer...")
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
            notify_warning(selected['topic'], "Script Gen (Duplicate Detected)", attempt+1, max_retries)
            continue 
        else:
            clean_text = temp_text
            break 
            
    if not clean_text:
        notify_error(selected['topic'], "Script Generation", "Job Aborted - Too many duplicates")
        sys.exit(1)

    print(f"✅ Unique Script Locked:\n{clean_text[:100]}...\n")
    
    # --- STEP 2: VOICE & SUBTITLES ---
    print("[STEP 2/6] Booting Kokoro TTS & Faster-Whisper...")
    audio_base_name = "master_audio"
    if not generate_audio(clean_text, output_base=audio_base_name):
        notify_error(selected['topic'], "Audio Generation", "Job Aborted")
        sys.exit(1)
        
    # --- STEP 3: BACKGROUND VISUALS ---
    print(f"\n[STEP 3/6] Fetching Background via APIs/Fallbacks...")
    video_filename = "master_background.mp4"
    if not fetch_background(selected['bg_query'], output_filename=video_filename):
        notify_error(selected['topic'], "Pexels Download", "Fell back to Local Assets")
        
    # --- STEP 4: FINAL ASSEMBLY ---
    print("\n[STEP 4/6] Sending to FFmpeg Render Engine...")
    run_id = int(time.time())
    final_filename = f"FINAL_SHORT_{selected['niche'].replace(' ', '_')}_{run_id}.mp4"
    
    if not render_video(video_filename, f"{audio_base_name}.wav", final_filename, selected['style']):
        notify_error(selected['topic'], "FFmpeg Render", "Job Aborted")
        sys.exit(1)
        
    file_size_mb = os.path.getsize(final_filename) / (1024 * 1024)
    clip = VideoFileClip(final_filename)
    duration_sec = int(clip.duration)
    clip.close()
    
    notify_render(selected['niche'], selected['topic'], clean_text, file_size_mb, duration_sec)

    # --- STEP 5: AI SEO GENERATOR ---
    print("\n[STEP 5/6] Generating Viral SEO Metadata...")
    seo_metadata = generate_seo_metadata(selected['niche'], clean_text)
        
    # --- STEP 6: LOG & YOUTUBE VAULT ---
    print("\n[STEP 6/6] Securing Data: Logging and Vaulting in YouTube...")
    log_completed_video(selected['niche'], script_hook, final_filename)
    
    vault_success = upload_to_youtube_vault(final_filename, selected['niche'], selected['topic'], seo_metadata)
    
    if vault_success:
        notify_summary(True, f"✅ Video Rendered & Vaulted.\n└ Niche: {selected['niche']}\n└ Topic: {selected['topic']}")
    else:
        notify_summary(False, "⚠️ Video rendered, but Vault Upload FAILED.")

    if "GITHUB_ENV" in os.environ:
        with open(os.environ["GITHUB_ENV"], "a") as env_file:
            env_file.write(f"FINAL_VIDEO_NAME={final_filename}\n")

if __name__ == "__main__":
    main()
