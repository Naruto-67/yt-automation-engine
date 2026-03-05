import os
import subprocess
import json
import re
from pydub import AudioSegment

def get_style_config(style_name="default"):
    """Returns the high-retention default ASS subtitle style."""
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
        "MarginV": "40"
    }

    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                default_style.update(json.load(f))
        except: pass
    return default_style

def srt_to_ass(srt_path, ass_path, style):
    """Converts standard SRT into customized ASS for FFmpeg burning."""
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
        with open(srt_path, 'r', encoding='utf-8') as f:
            content = f.read()

        def convert_time(ts):
            return ts.replace(',', '.')[:-1] 

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
    """
    Executes the Master Render. 
    Strictly locks duration to prevent the Infinite Loop bug.
    """
    print("⚙️ [RENDERER] Executing Multi-Track FFmpeg Master Render...")
    srt_path = audio_path.replace(".wav", ".srt").replace(".mp3", ".srt")
    ass_path = audio_path.replace(".wav", ".ass").replace(".mp3", ".ass")
    
    style = get_style_config(style_name)
    srt_to_ass(srt_path, ass_path, style)

    # 🚨 THE FIX: Calculate absolute duration of the audio to cap FFmpeg
    try:
        audio_segment = AudioSegment.from_file(audio_path)
        duration_seconds = len(audio_segment) / 1000.0
    except Exception as e:
        print(f"⚠️ [RENDERER] Duration calculation failed: {e}")
        duration_seconds = 60 # Safe default cutoff

    safe_ass = ass_path.replace('\\', '/').replace(':', r'\:')
    
    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1",        # Loop background video
        "-i", video_path, 
        "-i", audio_path,
        "-t", str(duration_seconds), # 🚨 STRICT DURATION CAP (Prevents 3GB infinite file)
        "-vf", f"ass='{safe_ass}'",  # Burn subtitles
        "-c:v", "libx264", 
        "-preset", "ultrafast", 
        "-crf", "23",
        "-c:a", "aac", 
        "-b:a", "192k", 
        "-pix_fmt", "yuv420p",
        output_path
    ]

    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        if os.path.exists(ass_path): os.remove(ass_path)
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ [RENDERER] FFmpeg Error: {e}")
        return False
