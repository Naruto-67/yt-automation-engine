import os
import sys
import random
import time
from src.generators.script_writer import generate_script
from src.generators.audio_generator import generate_audio
from src.generators.video_fetcher import download_pexels_video
from src.assembly.video_editor import assemble_video

def main():
    # THE CONTENT MATRIX
    # Rotates between core pillars and high-viral AI niches
    content_matrix = [
        {
            "niche": "fact",
            "topic": "A bizarre, 100% true, unknown historical event from the USA",
            "bg_query": "mysterious dark background"
        },
        {
            "niche": "brainrot",
            "topic": "Absurd, high-energy internet culture topic designed for maximum USA Gen-Z retention",
            "bg_query": "trippy abstract loop fast"
        },
        {
            "niche": "short story",
            "topic": "A 60-second self-improvement and motivation parable about overcoming laziness",
            "bg_query": "cinematic nature mountain"
        },
        {
            "niche": "psychology trick",
            "topic": "A dark psychology trick to read someone's body language instantly",
            "bg_query": "dark moody city street"
        },
        {
            "niche": "shower thought",
            "topic": "Mind-bending paradoxes and shower thoughts that keep you awake",
            "bg_query": "deep space galaxy"
        },
        {
            "niche": "unsolved mystery",
            "topic": "A creepy, true, unexplained internet or true crime mystery from the USA",
            "bg_query": "creepy foggy forest"
        }
    ]

    # Randomly select one profile for this specific run
    selected = random.choice(content_matrix)
    
    print(f"=== STEP 1: Booting Niche Engine ===")
    print(f"Targeting Niche: {selected['niche'].upper()}")
    print(f"Targeting Topic: {selected['topic']}")
    
    raw_script = generate_script(selected['niche'], selected['topic'])
    if not raw_script:
        print("❌ Failed to generate script.")
        sys.exit(1)
        
    # Clean the script for the TTS (remove the AI's bracketed headers)
    clean_text = raw_script.replace("[HOOK]", "").replace("[BODY]", "").replace("[OUTRO]", "").strip()
    clean_text = " ".join([line.strip() for line in clean_text.split('\n') if line.strip()])
    print(f"Cleaned Script:\n{clean_text}\n")
    
    print("=== STEP 2: Generating Audio & Subtitles ===")
    audio_success = generate_audio(clean_text, "master_audio.mp3")
    if not audio_success:
        print("❌ Failed to generate audio.")
        sys.exit(1)
        
    print(f"=== STEP 3: Fetching Background Video ('{selected['bg_query']}') ===")
    video_success = download_pexels_video(selected['bg_query'], "master_background.mp4")
    if not video_success:
        print("❌ Failed to download video.")
        sys.exit(1)
        
    print("=== STEP 4: Assembling Final Video ===")
    # Adding a timestamp to the output file so two videos a day don't overwrite each other
    run_id = int(time.time())
    final_filename = f"FINAL_SHORT_{selected['niche'].replace(' ', '_')}_{run_id}.mp4"
    
    assembly_success = assemble_video("master_background.mp4", "master_audio.mp3", final_filename)
    if not assembly_success:
        print("❌ Failed to assemble video.")
        sys.exit(1)
        
    print(f"=== 🎉 SUCCESS: Automated Pipeline Complete! ===")
    print(f"Output saved as: {final_filename}")

if __name__ == "__main__":
    main()
