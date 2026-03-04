import os
import sys
import random
import time
import re  # <--- Added for advanced text filtering
from scripts.generate_script import generate_script
from scripts.generate_voice import generate_audio
from scripts.fetch_background import fetch_background
from scripts.render_video import render_video

def main():
    # THE DYNAMIC CONTENT MATRIX
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
    
    # --- STEP 1: SCRIPT GENERATION ---
    print("\n[STEP 1/4] Booting Self-Improving AI Writer...")
    raw_script = generate_script(selected['niche'], selected['topic'])
    if not raw_script:
        print("❌ Critical Failure: Script generation aborted.")
        sys.exit(1)
        
    # --- TEXT SANITIZATION & PRONUNCIATION LOGIC ---
    # 1. Erase Stage Directions: Delete anything inside [brackets] or (parentheses) completely.
    clean_text = re.sub(r'\[.*?\]', '', raw_script)
    clean_text = re.sub(r'\(.*?\)', '', clean_text)
    
    # 2. Pronunciation Dictionary: Map tricky numbers and symbols to exact words.
    # \b ensures it only replaces the exact word (e.g., won't turn 1911 into 1nine one one)
    pronunciation_map = {
        r"\b911\b": "nine one one",
        r"\b100%\b": "one hundred percent",
        r"\bUSA\b": "U S A"
    }
    
    for pattern, replacement in pronunciation_map.items():
        clean_text = re.sub(pattern, replacement, clean_text, flags=re.IGNORECASE)
        
    # 3. Clean up rogue punctuation (leave periods, commas, and ellipses for natural TTS pauses)
    clean_text = clean_text.replace("*", "").replace("_", "").replace('"', "").replace("#", "")
    clean_text = " ".join([line.strip() for line in clean_text.split('\n') if line.strip()])
    
    print(f"✅ Script Locked and Sanitized:\n{clean_text}\n")
    
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
        
    print(f"\n==================================================")
    print(f"🎉 FACTORY RUN COMPLETE")
    print(f"📦 Output File: {final_filename}")
    print(f"==================================================")

    if "GITHUB_ENV" in os.environ:
        with open(os.environ["GITHUB_ENV"], "a") as env_file:
            env_file.write(f"FINAL_VIDEO_NAME={final_filename}\n")

if __name__ == "__main__":
    main()
