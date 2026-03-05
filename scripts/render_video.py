import os
import subprocess
import json
import traceback
import re

def get_style_config(style_name="default"):
    """Returns the 'MrBeast' high-retention default style."""
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    config_path = os.path.join(root_dir, "style_configs", f"{style_name}.json")
    
    default_style = {
        "FontName": "Montserrat-Bold",
        "FontSize": "24",
        "PrimaryColour": "&H0000FFFF",  # Yellow
        "OutlineColour": "&H00000000",  # Black
        "BackColour": "&H40000000",     # Semi-transparent shadow
        "Outline": "2",
        "BorderStyle": "1",
        "Alignment": "5",               # Center
        "MarginV": "40"
    }

    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                custom = json.load(f)
                default_style.update(custom)
        except: pass
    return default_style

def srt_to_ass(srt_path, ass_path, style):
    """Converts SRT to Advanced Substation Alpha (ASS) for professional visual styling."""
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
            ts = ts.replace(',', '.')
            return ts[:-1] 

        events = []
        blocks = content.strip().split('\n\n')
        for block in blocks:
            lines = block.split('\n')
            if len(lines) >= 3:
                times = re.findall(r'(\d+:\d+:\d+,\d+)', lines[1])
                if len(times) == 2:
                    start = convert_time(times[0])
                    end = convert_time(times[1])
                    text = " ".join(lines[2:])
                    events.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")

        with open(ass_path, 'w', encoding='utf-8') as f:
            f.write(header + "\n".join(events))
        return True
    except: return False

def render_video(video_path, audio_path, output_path, style_name="default"):
    """Pure FFmpeg Rendering: BGM Sidechain + SFX + Bouncy Subtitles."""
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    srt_path = audio_path.replace(".wav", ".srt").replace(".mp3", ".srt")
    ass_path = audio_path.replace(".wav", ".ass").replace(".mp3", ".ass")
    
    bgm_path = os.path.join(root_dir, "assets", "audio", "bgm_sigma.mp3")
    sfx_path = os.path.join(root_dir, "assets", "audio", "whoosh.mp3")
    font_path = os.path.join(root_dir, "assets", "fonts", "Montserrat-Bold.ttf")

    if not os.path.exists(video_path) or not os.path.exists(audio_path):
        return False

    style = get_style_config(style_name)
    srt_to_ass(srt_path, ass_path, style)

    safe_ass = ass_path.replace('\\', '/').replace(':', r'\:')
    safe_font = font_path.replace('\\', '/').replace(':', r'\:')

    print("⚙️ [RENDERER] Executing Multi-Track FFmpeg Master Render...")
    
    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", video_path, 
        "-i", audio_path,                      
    ]

    if os.path.exists(bgm_path):
        cmd.extend(["-i", bgm_path])
    else:
        cmd.extend(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"])

    if os.path.exists(sfx_path):
        cmd.extend(["-i", sfx_path])
    else:
        cmd.extend(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"])

    # BGM Ducking Filter Complex
    filter_complex = (
        "[1:a]volume=1.0[voice]; "
        "[2:a]volume=0.10[bgm]; "
        "[3:a]volume=0.40[sfx]; "
        "[voice][bgm][sfx]amix=inputs=3:duration=first:dropout_transition=2[outa]; "
        f"[0:v]ass='{safe_ass}':fontsdir='{os.path.dirname(safe_font)}'[outv]"
    )

    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", "[outv]", "-map", "[outa]",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "21",
        "-c:a", "aac", "-b:a", "192k", "-shortest", output_path
    ])

    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        if os.path.exists(ass_path): os.remove(ass_path)
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ [RENDERER] FFmpeg Error: {e.stderr}")
        return False
