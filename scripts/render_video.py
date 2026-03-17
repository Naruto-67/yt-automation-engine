# scripts/render_video.py
# Ghost Engine V26.0.0 — Multi-Layer Production & Dynamic Mixing
import os
import subprocess
import json
import random
import time
from engine.logger import logger
from engine.config_manager import config_manager

def get_random_music(music_tag: str) -> str:
    """
    V26: Finds a random track in assets/music/ that matches the AI's music_tag.
    If the folder or tag doesn't exist, it returns None.
    """
    settings = config_manager.get_settings()
    bank_path = settings["paths"]["music_bank"]
    # Look for a subfolder matching the tag (e.g., assets/music/dark_phonk/)
    tag_folder = os.path.join(bank_path, music_tag.lower())
    
    if os.path.exists(tag_folder):
        tracks = [f for f in os.listdir(tag_folder) if f.endswith(('.mp3', '.wav'))]
        if tracks:
            return os.path.join(tag_folder, random.choice(tracks))
    
    # Fallback: Look for any file in the root music_bank that contains the tag in the name
    if os.path.exists(bank_path):
        all_files = [f for f in os.listdir(bank_path) if f.endswith(('.mp3', '.wav'))]
        matching = [f for f in all_files if music_tag.lower() in f.lower()]
        if matching:
            return os.path.join(bank_path, random.choice(matching))
            
    return None

def generate_subtitles_ass(text_segments: list, weights: list, total_duration: float, output_ass: str, style_name: str = "PUNCHY_YELLOW", glow_color: str = "&H0000D700"):
    """
    V26: Generates a .ass subtitle file with dynamic styles and glow effects.
    """
    # ASS Header with V26 Style Definitions
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: {style_name},Anton,80,&H00FFFFFF,&H000000FF,&H00000000,{glow_color},1,0,0,0,100,100,0,0,1,3,10,5,50,50,960,1
"""
    
    events_header = "\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    
    with open(output_ass, 'w', encoding='utf-8') as f:
        f.write(header)
        f.write(events_header)
        
        current_time = 0.0
        for i, text in enumerate(text_segments):
            duration = weights[i] * total_duration
            start_str = time.strftime('%H:%M:%S.%S', time.gmtime(current_time))[:-1]
            end_str = time.strftime('%H:%M:%S.%S', time.gmtime(current_time + duration))[:-1]
            
            # Escape text for ASS
            clean_text = text.replace('\n', ' ').strip()
            f.write(f"Dialogue: 0,{start_str},{end_str},{style_name},,0,0,0,,{clean_text}\n")
            current_time += duration

def render_video(image_paths, audio_path, output_path, scene_weights, watermark_text="Ghost Engine", glow_color="&H0000D700", mood="NEUTRAL", music_tag="upbeat_curiosity", caption_style="PUNCHY_YELLOW"):
    """
    V26 Full Multi-Layer Renderer.
    Layers: 1. Images, 2. Subtitles, 3. Watermark, 4. Voiceover, 5. Background Music.
    """
    start_time = time.time()
    settings = config_manager.get_settings()
    
    # 1. Get total duration from audio
    try:
        probe = subprocess.check_output([
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1', audio_path
        ]).decode('utf-8').strip()
        total_duration = float(probe)
    except Exception as e:
        logger.error(f"FFprobe failed: {e}")
        return False, 0, 0

    # 2. Prepare Subtitles
    # We split the script into sentences for the subtitles based on weights
    # Since script_data isn't passed directly, we use the image_paths count to split
    temp_ass = f"temp_subs_{int(start_time)}.ass"
    # Note: In a production run, you'd pass the actual text segments. 
    # For this implementation, we assume scene_weights corresponds to scenes.
    # In job_runner, we'll ensure this syncs.
    
    # 3. Choose Music and Watermark Position
    music_file = get_random_music(music_tag)
    watermark_pos = random.choice(settings["visuals"]["watermark"]["positions"])
    
    pos_map = {
        "top_right":    "x=main_w-text_w-50:y=50",
        "bottom_right": "x=main_w-text_w-50:y=main_h-text_h-50",
        "top_left":     "x=50:y=50",
        "bottom_left":  "x=50:y=main_h-text_h-50"
    }
    drawtext_pos = pos_map.get(watermark_pos, "x=50:y=50")

    # 4. Construct Complex Filter
    # Filter 1: Create video from images
    # Filter 2: Mix Audio (Voice + Music)
    music_vol = settings["audio"]["music_volume"]
    
    cmd = [
        'ffmpeg', '-y',
        '-loop', '1', '-i', image_paths[0], # Placeholder for concatenation logic
    ]
    
    # Add all images (simplified concat for this block, full engine uses filter_complex concat)
    filter_parts = []
    for i, img in enumerate(image_paths):
        cmd.extend(['-loop', '1', '-t', str(scene_weights[i] * total_duration), '-i', img])
        filter_parts.append(f"[{i+1}:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920[v{i}];")
    
    concat_filter = "".join([f"[v{i}]" for i in range(len(image_paths))])
    concat_filter += f"concat=n={len(image_paths)}:v=1:a=0[v_base];"
    
    # Subtitles and Watermark
    visual_filter = concat_filter + (
        f"[v_base]ass={temp_ass},"
        f"drawtext=text='{watermark_text}':fontfile=assets/fonts/Anton-Regular.ttf:"
        f"fontsize={settings['visuals']['watermark']['font_size']}:fontcolor=white@0.3:"
        f"{drawtext_pos}[v_final]"
    )

    # Audio Mixing logic
    audio_inputs = ['-i', audio_path]
    if music_file:
        audio_inputs.extend(['-stream_loop', '-1', '-i', music_file])
        audio_filter = f"[0:a]volume=1.0[a_voice];[1:a]volume={music_vol},afade=t=in:st=0:d=2[a_music];[a_voice][a_music]amix=inputs=2:duration=first[a_final]"
    else:
        audio_filter = "[0:a]volume=1.0[a_final]"

    final_cmd = [
        'ffmpeg', '-y'
    ]
    # Add image inputs
    for i, img in enumerate(image_paths):
        final_cmd.extend(['-loop', '1', '-t', str(scene_weights[i] * total_duration), '-i', img])
    
    # Add audio inputs
    final_cmd.extend(['-i', audio_path])
    if music_file:
        final_cmd.extend(['-stream_loop', '-1', '-i', music_file])

    # Build the filter_complex
    inputs_count = len(image_paths)
    v_inputs = "".join([f"[{i}:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920[v{i}];" for i in range(inputs_count)])
    v_concat = "".join([f"[v{i}]" for i in range(inputs_count)]) + f"concat=n={inputs_count}:v=1:a=0[v_base];"
    
    # Handle Subtitles and Watermark in the filter
    # FFmpeg requires escaping the path for the ass filter
    escaped_ass = temp_ass.replace(":", "\\:").replace("\\", "/")
    
    v_final = f"[v_base]ass='{escaped_ass}',drawtext=text='{watermark_text}':fontfile=assets/fonts/Anton-Regular.ttf:fontsize=45:fontcolor=white@0.3:{drawtext_pos}[vout]"
    
    # Audio Mixing
    voice_idx = inputs_count
    if music_file:
        music_idx = inputs_count + 1
        a_final = f"[{voice_idx}:a]volume=1.0[avoice];[{music_idx}:a]volume={music_vol},afade=t=in:st=0:d=2[amusic];[avoice][amusic]amix=inputs=2:duration=first[aout]"
    else:
        a_final = f"[{voice_idx}:a]volume=1.0[aout]"

    final_cmd.extend([
        '-filter_complex', v_inputs + v_concat + v_final + ";" + a_final,
        '-map', '[vout]', '-map', '[aout]',
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '22',
        '-c:a', 'aac', '-b:a', '192k',
        '-t', str(total_duration),
        output_path
    ])

    try:
        # Before running, create dummy ASS if text segments are missing (fallback)
        if not os.path.exists(temp_ass):
            generate_subtitles_ass(["..."] * len(image_paths), scene_weights, total_duration, temp_ass, caption_style, glow_color)
            
        subprocess.run(final_cmd, check=True, capture_output=True)
        
        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        return True, total_duration, size_mb
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg Error: {e.stderr.decode()}")
        return False, 0, 0
    finally:
        # Cleanup
        if os.path.exists(temp_ass):
            os.remove(temp_ass)
