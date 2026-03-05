import os
import sys
import random
import time
import re
import json
import traceback
import subprocess

from scripts.generate_script import generate_script
from scripts.generate_voice import generate_audio
from scripts.fetch_background import fetch_background
from scripts.render_video import render_video
from scripts.generate_metadata import generate_seo_metadata
from scripts.logger import is_script_duplicate, log_completed_video
from scripts.youtube_manager import upload_to_youtube_vault
from scripts.discord_notifier import notify_render, notify_warning, notify_error, notify_summary
from scripts.retry import quota_manager  # Importing the AI Doctor & Master Guard

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
                    print(f"🧠 [MATRIX] Loaded {len(data)} trending topics.")
                    return data
        except Exception as e:
            print(f"⚠️ [MATRIX] Failed to read matrix: {e}")
            
    return default_matrix

def get_video_duration(filepath):
    """Replaces MoviePy. Uses FFprobe to get video duration without using RAM."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", filepath],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        return int(float(result.stdout.strip()))
    except Exception as e:
        print(f"⚠️ [FFPROBE] Could not read duration: {e}")
        return 60  # Safe fallback

def main():
    print(f"==================================================")
    print(f"🚀 INITIALIZING GHOST ENGINE V3.0 (2026 ARCHITECTURE)")
    print(f"==================================================")
    
    content_matrix = load_content_matrix()
    
    # The 2-Shorts-Per-Run Engine
    VIDEOS_TO_GENERATE = 2
    successful_videos = 0

    for run_index in range(1, VIDEOS_TO_GENERATE + 1):
        try:
            selected = random.choice(content_matrix)
            print(f"\n==================================================")
            print(f"🎬 STARTING PRODUCTION: VIDEO {run_index}/{VIDEOS_TO_GENERATE}")
            print(f"🎯 Niche: {selected['niche'].upper()} | Topic: {selected['topic']}")
            print(f"==================================================")
            
            # --- STEP 1: SCRIPT GENERATION ---
            print("\n[STEP 1/6] Booting AI Writer (Groq/Gemini)...")
            max_retries = 3
            clean_text, script_hook = "", ""
            
            for attempt in range(max_retries):
                # Unpacking the new tuple return from the upgraded generate_script
                raw_text, raw_hook = generate_script(selected['niche'], selected['topic'])
                
                if not raw_text:
                    notify_warning(selected['topic'], "Script Gen", attempt+1, max_retries)
                    continue
                    
                # Extra layer of pronunciation safety
                temp_text = raw_text
                pronunciation_map = {r"\b911\b": "nine one one", r"\b100%\b": "one hundred percent", r"\bUSA\b": "U S A"}
                for pattern, replacement in pronunciation_map.items():
                    temp_text = re.sub(pattern, replacement, temp_text, flags=re.IGNORECASE)
                    
                temp_text = temp_text.replace("*", "").replace("_", "").replace('"', "")
                
                if is_script_duplicate(raw_hook):
                    notify_warning(selected['topic'], "Script Gen (Duplicate Detected)", attempt+1, max_retries)
                    continue 
                else:
                    clean_text = temp_text
                    script_hook = raw_hook
                    break 
                    
            if not clean_text:
                print(f"⏭️ Skipping {selected['topic']} due to script failures/duplicates.")
                continue

            print(f"✅ Unique Script Locked:\n{clean_text[:100]}...\n")
            
            # --- DYNAMIC FILENAMES (Prevents overwriting in loop) ---
            audio_base_name = f"temp_audio_{run_index}"
            bg_filename = f"temp_bg_{run_index}.mp4"
            run_id = int(time.time())
            final_filename = f"FINAL_SHORT_{selected['niche'].replace(' ', '_')}_{run_id}.mp4"

            # --- STEP 2: VOICE & SUBTITLES ---
            print("[STEP 2/6] Booting Voice Engine (Orpheus/Kokoro)...")
            if not generate_audio(clean_text, output_base=audio_base_name):
                raise Exception("Voice Generation completely failed across all fallbacks.")
                
            # --- STEP 3: BACKGROUND VISUALS ---
            print(f"\n[STEP 3/6] Booting Visual Engine (Pollinations/FFmpeg/Pexels)...")
            if not fetch_background(selected['bg_query'], output_filename=bg_filename):
                raise Exception("Visual Generation completely failed across all fallbacks.")
                
            # --- STEP 4: FINAL ASSEMBLY ---
            print("\n[STEP 4/6] Sending to FFmpeg Assembly Engine...")
            # Note: generate_audio always outputs a .wav file even if Groq was used
            if not render_video(bg_filename, f"{audio_base_name}.wav", final_filename, selected.get('style', 'default')):
                raise Exception("FFmpeg Rendering crashed.")
                
            file_size_mb = os.path.getsize(final_filename) / (1024 * 1024)
            duration_sec = get_video_duration(final_filename)
            
            notify_render(selected['niche'], selected['topic'], clean_text, file_size_mb, duration_sec)

            # --- STEP 5: AI SEO GENERATOR ---
            print("\n[STEP 5/6] Generating Viral SEO Metadata...")
            seo_metadata = generate_seo_metadata(selected['niche'], clean_text)
                
            # --- STEP 6: LOG & YOUTUBE VAULT ---
            print("\n[STEP 6/6] Securing Data: Logging and Vaulting in YouTube...")
            log_completed_video(selected['niche'], script_hook, final_filename)
            
            vault_success = upload_to_youtube_vault(final_filename, selected['niche'], selected['topic'], seo_metadata)
            
            if vault_success:
                successful_videos += 1
                print(f"🎉 VIDEO {run_index} COMPLETELY SECURED.")
            else:
                notify_error(selected['topic'], "Vault Upload", "Video rendered, but YouTube rejected the upload.")

            # Append to GitHub ENV for artifact uploading if needed
            if "GITHUB_ENV" in os.environ:
                with open(os.environ["GITHUB_ENV"], "a") as env_file:
                    env_file.write(f"FINAL_VIDEO_NAME_{run_index}={final_filename}\n")

            # Clean up temporary files to save disk space
            for temp_file in [f"{audio_base_name}.wav", f"{audio_base_name}.srt", bg_filename]:
                if os.path.exists(temp_file): os.remove(temp_file)

        except Exception as e:
            # 🏥 THE AI DOCTOR CATCHES THE CRASH 
            # If ANY step in the loop above catastrophically fails, it won't crash the script.
            # It sends the error to Discord and tries to build the next video.
            print(f"\n❌ [CRITICAL] Video {run_index} failed catastrophically.")
            quota_manager.diagnose_fatal_error(f"main.py (Run {run_index})", e)
            continue # Skip to the next video

    # --- FINAL REPORT ---
    if successful_videos == VIDEOS_TO_GENERATE:
        notify_summary(True, f"✅ Daily Pipeline Complete. {successful_videos}/{VIDEOS_TO_GENERATE} Videos Vaulted.")
    elif successful_videos > 0:
        notify_summary(True, f"⚠️ Partial Pipeline Complete. {successful_videos}/{VIDEOS_TO_GENERATE} Videos Vaulted. Check AI Doctor logs.")
    else:
        notify_summary(False, "❌ Pipeline Failed. 0 Videos Vaulted. Check AI Doctor logs immediately.")
        sys.exit(1)

if __name__ == "__main__":
    main()
