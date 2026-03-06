import os
import subprocess
import json
import re
import random
from pydub import AudioSegment

def get_style_config(style_name="default"):
    # 🚨 THE 2026 BRUTALIST RETENTION META
    default_style = {
        "FontName": "Arial",           
        "FontSize": "85",              
        "PrimaryColour": "&H00FFFFFF", 
        "OutlineColour": "&H00000000", 
        "BackColour": "&H00000000",    
        "Outline": "11",               
        "Shadow": "0",                 
        "BorderStyle": "1",            
        "Alignment": "2",              
        "MarginV": "600"               
    }

    if os.path.exists(config_path := os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")), "style_configs", f"{style_name}.json")):
        try:
            with open(config_path, "r") as f: default_style.update(json.load(f))
        except: pass
    return default_style

def time_to_seconds(time_str):
    """Converts SRT timestamp 00:00:00,000 to seconds"""
    h, m, s_ms = time_str.split(':')
    s, ms = s_ms.split(',')
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0

def calculate_dynamic_durations(srt_path, num_images, total_audio_duration):
    """Parses SRT to cut images exactly when the voiceover changes thoughts."""
    print("⏱️ [RENDERER] Syncing visual cuts to voiceover pacing...")
    try:
        with open(srt_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        timestamps = re.findall(r'(\d+:\d+:\d+,\d+) --> (\d+:\d+:\d+,\d+)', content)
        
        if not timestamps or len(timestamps) < num_images:
            return [total_audio_duration / num_images] * num_images
            
        blocks_per_image = len(timestamps) // num_images
        durations = []
        
        for i in range(num_images):
            start_idx = i * blocks_per_image
            end_idx = (i + 1) * blocks_per_image - 1 if i < num_images - 1 else len(timestamps) - 1
            
            start_time = time_to_seconds(timestamps[start_idx][0])
            end_time = time_to_seconds(timestamps[end_idx][1])
            
            if i == 0: start_time = 0.0
            if i == num_images - 1: end_time = total_audio_duration
                
            durations.append(end_time - start_time)
            
        return durations
    except Exception as e:
        print(f"⚠️ [RENDERER] Dynamic sync failed ({e}), using equal splits.")
        return [total_audio_duration / num_images] * num_images

def srt_to_ass(srt_path, ass_path, style):
    print("🎨 [RENDERER] Generating High-Retention Subtitles...")
    header = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{style['FontName']},{style['FontSize']},{style['PrimaryColour']},&H000000FF,"
        f"{style['OutlineColour']},{style['BackColour']},1,0,0,0,100,100,0,0,{style['BorderStyle']},"
        f"{style['Outline']},{style['Shadow']},{style['Alignment']},10,10,{style['MarginV']},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    try:
        with open(srt_path, 'r', encoding='utf-8') as f: content = f.read()
        def convert_time(ts): return ts.replace(',', '.')[:-1] 

        events = []
        blocks = content.strip().split('\n\n')
        for block in blocks:
            lines = block.split('\n')
            if len(lines) >= 3:
                times = re.findall(r'(\d+:\d+:\d+,\d+)', lines[1])
                if len(times) == 2:
                    text = " ".join(lines[2:])
                    text = re.sub(r'<[^>]+>', '', text)
                    events.append(f"Dialogue: 0,{convert_time(times[0])},{convert_time(times[1])},Default,,0,0,0,,{text.upper()}")

        with open(ass_path, 'w', encoding='utf-8') as f:
            f.write(header + "\n".join(events))
        return True
    except: return False

def create_ken_burns_clip(image_path, duration, output_path, index=0, fps=60):
    frames = int(duration * fps)
    
    # 🚨 DYNAMIC ENGAGING ANIMATIONS: Alternates camera movement per scene
    effects = [
        f"zoompan=z='1.0+it/3000':x='iw/2-(iw/zoom)/2':y='ih/2-(ih/zoom)/2':d={frames}:s=1080x1920:fps={fps}", # Zoom Center
        f"zoompan=z='1.0+it/3000':x='0':y='0':d={frames}:s=1080x1920:fps={fps}", # Zoom Top Left
        f"zoompan=z='1.0+it/3000':x='iw-(iw/zoom)':y='ih-(ih/zoom)':d={frames}:s=1080x1920:fps={fps}", # Zoom Bottom Right
        f"zoompan=z='1.0+it/3000':x='iw-(iw/zoom)':y='0':d={frames}:s=1080x1920:fps={fps}", # Zoom Top Right
        f"zoompan=z='1.0+it/3000':x='0':y='ih-(ih/zoom)':d={frames}:s=1080x1920:fps={fps}"  # Zoom Bottom Left
    ]
    
    selected_effect = effects[index % len(effects)]
    
    # 🚨 Adds cinematic color grading to make the AI images "pop" vibrantly
    full_filter = f"{selected_effect},eq=contrast=1.05:saturation=1.15"

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", image_path,
        "-vf", full_filter,
        "-c:v", "libx264", "-t", str(duration),
        "-pix_fmt", "yuv420p", "-preset", "ultrafast", "-crf", "23",
        output_path
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
    return True

def render_video(image_paths, audio_path, output_path, style_name="default"):
    print(f"⚙️ [RENDERER] Executing Cinematic Render Engine (1080p, 60FPS)...")
    srt_path = audio_path.replace(".wav", ".srt")
    ass_path = audio_path.replace(".wav", ".ass")
    temp_concat_file = "concat_list.txt"
    temp_merged_video = "temp_merged_no_subs.mp4"
    
    if not srt_to_ass(srt_path, ass_path, get_style_config(style_name)): return False
    try:
        audio = AudioSegment.from_file(audio_path)
        total_duration = len(audio) / 1000.0 
    except: return False

    # Get perfectly synced durations based on subtitle pacing
    clip_durations = calculate_dynamic_durations(srt_path, len(image_paths), total_duration)

    clip_files = []
    for i, img in enumerate(image_paths):
        clip_out = f"temp_anim_clip_{i}.mp4"
        # Pass the index 'i' so the camera angle changes every scene
        if create_ken_burns_clip(img, clip_durations[i], clip_out, index=i):
            clip_files.append(clip_out)

    with open(temp_concat_file, "w") as f:
        for clip in clip_files: f.write(f"file '{clip}'\n")

    cmd_concat = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", temp_concat_file,
        "-i", audio_path, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest", temp_merged_video
    ]
    subprocess.run(cmd_concat, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)

    safe_ass = ass_path.replace('\\', '/').replace(':', r'\:')
    cmd_burn = [
        "ffmpeg", "-y", "-i", temp_merged_video, "-vf", f"ass='{safe_ass}'",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "copy", output_path
    ]
    subprocess.run(cmd_burn, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)

    for f in clip_files + [temp_concat_file, temp_merged_video, ass_path]:
        if os.path.exists(f): os.remove(f)
    return True
