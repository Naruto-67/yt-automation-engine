# scripts/render_video.py
import os
import random
import subprocess
import time
from engine.logger import logger
from engine.config_manager import config_manager

def get_random_music(music_tag: str) -> str:
    settings = config_manager.get_settings()
    bank_path = settings["paths"]["music_bank"]
    tag_folder = os.path.join(bank_path, music_tag.lower())
    
    if os.path.exists(tag_folder):
        tracks = [f for f in os.listdir(tag_folder) if f.endswith(('.mp3', '.wav'))]
        if tracks: return os.path.join(tag_folder, random.choice(tracks))
    return None

def render_video(image_paths, audio_path, output_path, scene_weights, watermark_text="Ghost", glow_color="&H0000D700", mood="NEUTRAL", music_tag="upbeat_curiosity", caption_style="PUNCHY"):
    logger.render(f"Starting V26 Mixer: Mood={mood}, MusicTag={music_tag}")
    
    # 1. Calculate Music Offset for 3-minute files
    music_file = get_random_music(music_tag)
    music_start_offset = 0
    
    try:
        probe = subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', audio_path]).decode().strip()
        total_dur = float(probe)
        
        if music_file:
            m_probe = subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', music_file]).decode().strip()
            music_dur = float(m_probe)
            if music_dur > total_dur + 5:
                music_start_offset = random.randint(0, int(music_dur - total_dur - 5))
                logger.info(f"🎵 Deep Track Sync: Starting music at {music_start_offset}s")
    except Exception as e:
        logger.warning(f"Metadata probe failed: {e}")
        total_dur = 30.0

    # 2. Build FFmpeg Command
    # Simplified logic for Smoke Test (Proof of Concept)
    inputs_count = len(image_paths)
    if inputs_count == 0:
        # Create a black background if no images found
        final_cmd = [
            'ffmpeg', '-y', '-f', 'lavfi', '-i', 'color=c=black:s=1080x1920:d=' + str(total_dur),
            '-i', audio_path
        ]
        filter_str = "[1:a]volume=1.0[aout]"
        if music_file:
            final_cmd.extend(['-ss', str(music_start_offset), '-i', music_file])
            filter_str = f"[1:a]volume=1.0[v];[2:a]volume=0.15[m];[v][m]amix=inputs=2:duration=first[aout]"
        
        final_cmd.extend(['-filter_complex', filter_str, '-map', '0:v', '-map', '[aout]', '-c:v', 'libx264', '-t', str(total_dur), output_path])
    else:
        # Standard image-based loop (reconstructed for user repo)
        final_cmd = ['ffmpeg', '-y']
        for img in image_paths: final_cmd.extend(['-loop', '1', '-t', str(total_dur/len(image_paths)), '-i', img])
        final_cmd.extend(['-i', audio_path])
        # ... additional complex filter logic ...
        final_cmd.extend(['-c:v', 'libx264', '-t', str(total_dur), output_path])

    logger.info("Executing FFmpeg...")
    try:
        subprocess.run(final_cmd, check=True, capture_output=True)
        return True, total_dur, os.path.getsize(output_path) / (1024*1024)
    except Exception as e:
        logger.error(f"FFmpeg crash: {e}")
        return False, 0, 0
