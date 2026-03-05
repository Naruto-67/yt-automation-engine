import os
import subprocess
import json
import re
from pydub import AudioSegment

def get_style_config(style_name="default"):
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    config_path = os.path.join(root_dir, "style_configs", f"{style_name}.json")
    
    default_style = {
        "FontName": "Montserrat-Bold",
        "FontSize": "24",
        "PrimaryColour": "&H0000FFFF",
        "OutlineColour": "&H00000000",
        "BackColour": "&H40000000",
        "Outline": "2",
        "BorderStyle": "1",
        "Alignment": "5",
        "MarginV": "50"
    }

    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                default_style.update(json.load(f))
        except: pass
    return default_style

def srt_to_ass(srt_path, ass_path, style):
    print("🎨 [RENDERER] Generating High-Impact ASS style...")
    header = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{style['FontName']},{style['FontSize']},{style['PrimaryColour']},&H000000FF,"
        f"{style['OutlineColour']},{style['BackColour']},1,0,0,0,100,100,0,0,{style['BorderStyle']},"
        f"{style['Outline']},1,{style['Alignment']},10,10,{style['MarginV']},1\n\n"
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
                    events.append(f"Dialogue: 0,{convert_time(times[0])},{convert_time(times[1])},Default,,0,0,0,,{text}")

        with open(ass_path, 'w', encoding='utf-8') as f:
            f.write(header + "\n".join(events))
        return True
    except: return False

def render_video(video_path, audio_path, output_path, style_name="default"):
    print("⚙️ [RENDERER] Executing 2-Step Master Render...")
    srt_path = audio_path.replace(".wav", ".srt").replace(".mp3", ".srt")
    ass_path = audio_path.replace(".wav", ".ass").replace(".mp3", ".ass")
    temp_no_subs = "temp_no_subs.mp4"
    
    srt_to_ass(srt_path, ass_path, get_style_config(style_name))

    # Calculate exact duration to clip the video
    try:
        duration_seconds = len(AudioSegment.from_file(audio_path)) / 1000.0
    except: duration_seconds = 60 

    safe_ass = ass_path.replace('\\', '/').replace(':', r'\:')

    # STEP 1: Loop background and merge audio (Fixes the 2-frame freeze bug completely)
    cmd_step_1 = [
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-fflags", "+genpts", # Recalculates timestamps for perfect looping
        "-i", video_path, 
        "-i", audio_path,
        "-map", "0:v:0", "-map", "1:a:0",
        "-t", str(duration_seconds),
        "-vf", "scale=-2:1920,crop=1080:1920,fps=30",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "aac", "-b:a", "192k", "-pix_fmt", "yuv420p",
        "-shortest", temp_no_subs
    ]

    # STEP 2: Burn subtitles onto the perfectly flat, un-looped video
    cmd_step_2 = [
        "ffmpeg", "-y",
        "-i", temp_no_subs,
        "-vf", f"ass='{safe_ass}'",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "copy", # Copy audio untouched
        output_path
    ]

    try:
        print("🎬 [RENDERER] Phase 1: Merging Audio and Video...")
        subprocess.run(cmd_step_1, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        
        print("🔥 [RENDERER] Phase 2: Burning Subtitles...")
        subprocess.run(cmd_step_2, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        
        # Cleanup
        if os.path.exists(temp_no_subs): os.remove(temp_no_subs)
        if os.path.exists(ass_path): os.remove(ass_path)
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ [RENDERER] FFmpeg Error: {e}")
        return False
