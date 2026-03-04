import os
import sys
import random
import time
import re
from scripts.generate_script import generate_script
from scripts.generate_voice import generate_audio
from scripts.fetch_background import fetch_background
from scripts.render_video import render_video
from scripts.logger import is_script_duplicate, log_completed_video  # <--- Added Logger

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
        },
        {
            "niche": "psychology trick",
            "topic": "A dark psychology trick to read someone's body language instantly",
            "bg_query": "dark moody city street",
            "style": "default"
        },
        {
            "niche": "unsolved mystery",
            "topic": "A creepy, true, unexplained internet or true crime mystery from the USA",
            "bg_query": "creepy foggy forest",
            "style": "default"
        }
    ]

    selected = random.choice(content_matrix)
    
    print(f"==================================================")
    print(f"🚀 INITIALIZING YOUTUBE AUTOMATION ENGINE")
    print(f"==================================================")
    print(f"🎯 Target Niche: {selected['niche'].upper()}")
    print(f"📝 Target Topic: {selected['topic']}")
    print(f"🎨 Target Style: {selected['style']}")
    print(f"--------------------------------------------------")
    
    # --- STEP 1: SCRIPT GENERATION (WITH MEMORY LOOP) ---
    print("\n[STEP 1/4] Booting Self-Improving AI Writer...")
    max_retries = 3
    clean_text = ""
    script_hook = ""
    
    for attempt in range(max_retries):
        raw_script = generate_script(selected['niche'], selected['topic'])
        if not raw_script:
            print("❌ Critical Failure: Script generation aborted.")
            sys.exit(1)
            
        # Sanitize text
        temp_text = re.sub(r'\[.*?\]', '', raw_script)
        temp_text = re.sub(r'\(.*?\)', '', temp_text)
        
        pronunciation_map = {
            r"\b911\b": "nine one one",
            r"\b100%\b": "one hundred percent",
            r"\bUSA\b": "U S A"
        }
        for pattern, replacement in pronunciation_map.items():
            temp_text = re.sub(pattern, replacement, temp_text, flags=re.IGNORECASE)
            
        temp_text = temp_text.replace("*", "").replace("_", "").replace('"', "").replace("#", "")
        temp_text = " ".join([line.strip() for line in temp_text.split('\n') if line.strip()])
        
        # Extract the first 10 words to use as a unique fingerprint/hook for the logger
        words = temp_text.split()
        script_hook = " ".join(words[:10])
        
        # Check the Google Sheet Vault
        if is_script_duplicate(script_hook):
            print(f"⚠️ Attempt {attempt+1}/{max_retries}: AI generated a duplicate topic. Retrying...")
            continue # Try again!
        else:
            clean_text = temp_text
            break # It's unique! Break the loop.
            
    if not clean_text:
        print("❌ Critical Failure: AI could not generate a unique script after 3 tries.")
        sys.exit(1)

    print(f"✅ Unique Script Locked:\n{clean_text}\n")
    
    # --- STEP 2: VOICE & SUBTITLES ---
    print("[STEP 2/4] Booting Kokoro TTS & Faster-Whisper...")
    audio_base_name = "master_audio"
    audio_success = generate_audio(clean_text, output_base=audio_base_name)
    if not audio_success:
        print("❌ Critical Failure: Audio generation aborted.")
        sys.exit(1)
        
    # --- STEP 3: BACKGROUND VISUALS ---
    print(f"\n[STEP 3/4] Fetching Background ('{selected['bg_query']}') via APIs/Fallbacks...")
    video_filename = "master_background.mp4"
    video_success = fetch_background(selected['bg_query'], output_filename=video_filename)
    if not video_success:
        print("❌ Critical Failure: Visual generation aborted.")
        sys.exit(1)
        
    # --- STEP 4: FINAL ASSEMBLY ---
    print("\n[STEP 4/4] Sending to FFmpeg Render Engine...")
    run_id = int(time.time())
    final_filename = f"FINAL_SHORT_{selected['niche'].replace(' ', '_')}_{run_id}.mp4"
    
    assembly_success = render_video(
        video_path=video_filename, 
        audio_path=f"{audio_base_name}.wav", 
        output_path=final_filename,
        style_name=selected['style']
    )
    
    if not assembly_success:
        print("❌ Critical Failure: Video assembly aborted.")
        sys.exit(1)
        
    # --- STEP 5: LOG TO BRAIN ---
    print("\n[STEP 5/5] Logging success to Google Sheets Memory...")
    log_completed_video(selected['niche'], script_hook, final_filename)
        
    print(f"\n==================================================")
    print(f"🎉 FACTORY RUN COMPLETE")
    print(f"📦 Output File: {final_filename}")
    print(f"==================================================")

    if "GITHUB_ENV" in os.environ:
        with open(os.environ["GITHUB_ENV"], "a") as env_file:
            env_file.write(f"FINAL_VIDEO_NAME={final_filename}\n")

if __name__ == "__main__":
    main()
