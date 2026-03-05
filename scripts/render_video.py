import os
import subprocess
import json
import traceback
import re

def get_style_config(style_name="default"):
    """Loads style configurations or returns the 'MrBeast' high-retention default."""
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    config_path = os.path.join(root_dir, "style_configs", f"{style_name}.json")
    
    # The 'MrBeast/Hormozi' High-Retention Preset
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
    """
    Converts standard SRT to Advanced Substation Alpha (ASS).
    This allows us to force professional styling that creates 'Viral' visual impact.
    """
    print("🎨 [RENDERER] Converting SRT to High-Impact ASS style...")
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

        # Simple regex to convert SRT timestamps to ASS format (H:MM:SS.cc)
        def convert_time(ts):
            ts = ts.replace(',', '.')
            return ts[:-1] # Remove last digit to match centisecond precision

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
    except Exception as e:
        print(f"⚠️ [RENDERER] ASS conversion failed: {e}")
        return False

def render_video(video_path, audio_path, output_path, style_name="default"):
    """
    The Ghost Engine V4.0 Master Renderer.
    Pure FFmpeg: BGM Mixing + Sidechain Ducking + SFX + Bouncy Subtitles.
    """
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    srt_path = audio_path.replace(".wav", ".srt").replace(".mp3", ".srt")
    ass_path = audio_path.replace(".wav", ".ass").replace(".mp3", ".ass")
    
    # Asset Pathing
    bgm_path = os.path.join(root_dir, "assets", "audio", "bgm_sigma.mp3")
    sfx_path = os.path.join(root_dir, "assets", "audio", "whoosh.mp3")
    font_path = os.path.join(root_dir, "assets", "fonts", "Montserrat-Bold.ttf")

    if not os.path.exists(video_path) or not os.path.exists(audio_path):
        print("❌ [RENDERER] Critical Input Missing.")
        return False

    # 1. Prepare Styles
    style = get_style_config(style_name)
    srt_to_ass(srt_path, ass_path, style)

    # 2. Build Complex Filter
    # [0:v] Background Loop
    # [1:a] Voiceover
    # [2:a] BGM (Duck to 10% volume)
    # [3:a] SFX (Whoosh at start)
    
    # Path escaping for FFmpeg
    safe_ass = ass_path.replace('\\', '/').replace(':', r'\:')
    safe_font = font_path.replace('\\', '/').replace(':', r'\:')

    print("⚙️ [RENDERER] Executing Multi-Track FFmpeg Render...")
    
    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", video_path,  # Input 0: Video
        "-i", audio_path,                       # Input 1: Voiceover
    ]

    # Add BGM if exists
    if os.path.exists(bgm_path):
        cmd.extend(["-i", bgm_path])
    else:
        cmd.extend(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]) # Silent dummy

    # Add SFX if exists
    if os.path.exists(sfx_path):
        cmd.extend(["-i", sfx_path])
    else:
        cmd.extend(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]) # Silent dummy

    # Filter Complex Logic:
    # 1. Duck BGM volume
    # 2. Mix Voiceover + BGM + SFX
    # 3. Apply Subtitles with custom font provider
    filter_complex = (
        "[1:a]volume=1.0[voice]; "
        "[2:a]volume=0.10[bgm]; "
        "[3:a]volume=0.40[sfx]; "
        "[voice][bgm][sfx]amix=inputs=3:duration=first:dropout_transition=2[outa]; "
        f"[0:v]ass='{safe_ass}':fontsdir='{os.path.dirname(safe_font)}'[outv]"
    )

    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", "[outa]",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "21",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest", # Clip to audio length
        output_path
    ])

    try:
        process = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print(f"✅ [RENDERER] Video Rendered Successfully: {output_path}")
        
        # Cleanup temp ASS
        if os.path.exists(ass_path): os.remove(ass_path)
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ [RENDERER] FFmpeg Error:\n{e.stderr}")
        return False
    except Exception as e:
        print(f"❌ [RENDERER] System Crash: {e}")
        return False

if __name__ == "__main__":
    # Test execution
    render_video("test_bg.mp4", "test_audio.wav", "FINAL_OUTPUT.mp4")
