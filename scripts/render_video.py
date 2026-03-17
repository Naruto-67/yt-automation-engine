# scripts/render_video.py
# Ghost Engine V26.0.0 — Multi-Layer Production & Deep Track Randomization
import os
import random
import subprocess
import time
import requests
import re
from engine.logger import logger
from engine.config_manager import config_manager

def get_random_music(music_tag: str) -> str:
    """
    V26: Finds a random track in assets/music/ that matches the AI's music_tag.
    [cite: 50-51, 115]
    """
    settings = config_manager.get_settings()
    bank_path = settings["paths"]["music_bank"]
    tag_folder = os.path.join(bank_path, music_tag.lower())
    
    if os.path.exists(tag_folder):
        tracks = [f for f in os.listdir(tag_folder) if f.endswith(('.mp3', '.wav'))]
        if tracks:
            return os.path.join(tag_folder, random.choice(tracks))
    
    if os.path.exists(bank_path):
        all_files = [f for f in os.listdir(bank_path) if f.endswith(('.mp3', '.wav'))]
        matching = [f for f in all_files if music_tag.lower() in f.lower()]
        if matching:
            return os.path.join(bank_path, random.choice(matching))
            
    return None

def download_cinematic_font():
    """
    Ensures the Anton-Regular font is available for high-retention captions.
    [cite: 419-423]
    """
    font_path = "/tmp/Anton-Regular.ttf"
    if os.path.exists(font_path) and os.path.getsize(font_path) > 20000:
        return font_path

    mirrors = [
        "https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf",
        "https://fonts.gstatic.com/s/anton/v25/1Ptgg87LROyAm3K.ttf"
    ]
    for url in mirrors:
        try:
            response = requests.get(url, timeout=15)
            if response.status_code == 200:
                with open(font_path, "wb") as f:
                    f.write(response.content)
                return font_path
        except:
            continue
    return "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"

def generate_subtitles_ass(text_segments: list, weights: list, total_duration: float, output_ass: str, style_name: str, glow_color: str):
    """
    Generates V26 Gaussian-glow captions for the 'Human' editing feel.
    [cite: 431-442]
    """
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Glow,Anton,80,&H00000000,&H000000FF,{glow_color},&H00000000,1,0,0,0,100,100,0,0,1,25,0,2,10,10,500,1
Style: {style_name},Anton,80,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,5,0,2,10,10,500,1
"""
    events_header = "\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    
    with open(output_ass, 'w', encoding='utf-8') as f:
        f.write(header + events_header)
        current_time = 0.0
        for i, text in enumerate(text_segments):
            dur = weights[i] * total_duration
            start = time.strftime('%H:%M:%S.%S', time.gmtime(current_time))[:-1]
            end = time.strftime('%H:%M:%S.%S', time.gmtime(current_time + dur))[:-1]
            clean_text = text.replace('\n', ' ').strip().upper()
            f.write(f"Dialogue: 0,{start},{end},Glow,,0,0,0,,{{\\blur15}}{clean_text}\n")
            f.write(f"Dialogue: 1,{start},{end},{style_name},,0,0,0,,{clean_text}\n")
            current_time += dur

def render_video(image_paths, audio_path, output_path, scene_weights, watermark_text="Ghost Engine", glow_color="&H0000D700", mood="NEUTRAL", music_tag="upbeat_curiosity", caption_style="PUNCHY_YELLOW"):
    """
    V26 Master Renderer with Deep Track Randomization.
    [cite: 119-122, 446-455]
    """
    start_time = time.time()
    settings = config_manager.get_settings()
    
    # 1. Get total video duration
    try:
        probe = subprocess.check_output([
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1', audio_path
        ]).decode('utf-8').strip()
        total_duration = float(probe)
    except Exception as e:
        logger.error(f"FFprobe failed on voiceover: {e}")
        return False, 0, 0

    # 2. Deep Track Logic: Random Music Offset [cite: 119-122]
    music_file = get_random_music(music_tag)
    music_start_offset = 0
    if music_file:
        try:
            m_probe = subprocess.check_output([
                'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1', music_file
            ]).decode('utf-8').strip()
            music_total_len = float(m_probe)
            
            if music_total_len > (total_duration + 5):
                # Pick a random start point, leaving a 5s buffer at the end
                max_start = int(music_total_len - total_duration - 5)
                music_start_offset = random.randint(0, max_start)
                logger.render(f"🎵 Deep Track Sync: Starting '{music_tag}' at {music_start_offset}s")
        except:
            music_start_offset = 0

    # 3. Prepare Subtitles and Watermark [cite: 453]
    temp_ass = f"temp_subs_{int(start_time)}.ass"
    # Fallback segments if not provided
    segments = ["..."] * len(image_paths) 
    generate_subtitles_ass(segments, scene_weights, total_duration, temp_ass, caption_style, glow_color)
    
    font_path = download_cinematic_font()
    safe_font = font_path.replace("\\", "/").replace(":", r"\:")
    
    # 4. Construct FFmpeg Filter Complex
    inputs_count = len(image_paths)
    v_inputs = "".join([f"[{i}:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920[v{i}];" for i in range(inputs_count)])
    v_concat = "".join([f"[v{i}]" for i in range(inputs_count)]) + f"concat=n={inputs_count}:v=1:a=0[v_base];"
    
    # Centralized Watermark [cite: 453]
    v_final = f"[v_base]ass='{temp_ass}',drawtext=fontfile='{safe_font}':text='{watermark_text.upper()}':fontcolor=white@0.3:fontsize=50:x=(w-text_w)/2:y=h*0.28[vout]"
    
    # Audio Mixing with Random Offset and Fade [cite: 51, 119-122]
    voice_idx = inputs_count
    music_vol = settings["audio"]["music_volume"]
    if music_file:
        music_idx = inputs_count + 1
        a_final = f"[{voice_idx}:a]volume=1.0[avoice];[{music_idx}:a]volume={music_vol},afade=t=in:st=0:d=2[amusic];[avoice][amusic]amix=inputs=2:duration=first[aout]"
    else:
        a_final = f"[{voice_idx}:a]volume=1.0[aout]"

    # 5. Execute Final Command
    final_cmd = ['ffmpeg', '-y']
    for i, img in enumerate(image_paths):
        final_cmd.extend(['-loop', '1', '-t', str(scene_weights[i] * total_duration), '-i', img])
    
    final_cmd.extend(['-i', audio_path])
    if music_file:
        final_cmd.extend(['-ss', str(music_start_offset), '-stream_loop', '-1', '-i', music_file])

    final_cmd.extend([
        '-filter_complex', v_inputs + v_concat + v_final + ";" + a_final,
        '-map', '[vout]', '-map', '[aout]',
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '22',
        '-c:a', 'aac', '-b:a', '192k',
        '-t', str(total_duration),
        output_path
    ])

    try:
        subprocess.run(final_cmd, check=True, capture_output=True)
        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        return True, total_duration, size_mb
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg Error: {e.stderr.decode()}")
        return False, 0, 0
    finally:
        if os.path.exists(temp_ass): os.remove(temp_ass)
