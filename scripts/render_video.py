import os
import subprocess
import json
import re
import urllib.request
from pydub import AudioSegment

def download_cinematic_font():
    font_path = "/tmp/Montserrat-Bold.ttf"
    if not os.path.exists(font_path):
        print("📥 [RENDERER] Downloading Cinematic Font...")
        url = "https://github.com/googlefonts/montserrat/raw/main/fonts/ttf/Montserrat-Bold.ttf"
        try:
            urllib.request.urlretrieve(url, font_path)
        except:
            return "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
    return font_path

def get_style_config(style_name="default"):
    return {
        "FontName": "Arial", "FontSize": "75", "PrimaryColour": "&H00FFFFFF", 
        "OutlineColour": "&H00000000", "BackColour": "&H00000000", "Outline": "10", 
        "Shadow": "0", "BorderStyle": "1", "Alignment": "2", "MarginV": "500"               
    }

def time_to_seconds(time_str):
    h, m, s_ms = time_str.split(':')
    s, ms = s_ms.split(',')
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0

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
        for block in content.strip().split('\n\n'):
            lines = block.split('\n')
            if len(lines) >= 3:
                times = re.findall(r'(\d+:\d+:\d+,\d+)', lines[1])
                if len(times) == 2:
                    text = re.sub(r'<[^>]+>', '', " ".join(lines[2:]))
                    events.append(f"Dialogue: 0,{convert_time(times[0])},{convert_time(times[1])},Default,,0,0,0,,{text.upper()}")

        with open(ass_path, 'w', encoding='utf-8') as f: f.write(header + "\n".join(events))
        return True
    except Exception as e:
        print(f"⚠️ [RENDERER] Subtitle generation failed: {e}")
        return False

def create_ken_burns_clip(image_path, duration, output_path, index=0, fps=60):
    frames = int(duration * fps)
    prep_filter = "scale=2160:3840:force_original_aspect_ratio=increase,crop=2160:3840"
    effects = [
        f"zoompan=z='min(zoom+0.0007,1.15)':x='iw/2-(iw/zoom)/2':y='ih/2-(ih/zoom)/2':d={frames}:s=1080x1920:fps={fps}", 
        f"zoompan=z='1.15-0.0007*on':x='iw/2-(iw/zoom)/2':y='ih/2-(ih/zoom)/2':d={frames}:s=1080x1920:fps={fps}",      
        f"zoompan=z='1.15':x='(iw-iw/zoom)*(on/{frames})':y='ih/2-(ih/zoom)/2':d={frames}:s=1080x1920:fps={fps}",     
        f"zoompan=z='1.15':x='(iw-iw/zoom)*(1-(on/{frames}))':y='ih/2-(ih/zoom)/2':d={frames}:s=1080x1920:fps={fps}"  
    ]
    full_filter = f"{prep_filter},{effects[index % len(effects)]},eq=contrast=1.05:saturation=1.15"
    subprocess.run(["ffmpeg", "-y", "-loop", "1", "-i", image_path, "-vf", full_filter, "-c:v", "libx264", "-t", str(duration), "-pix_fmt", "yuv420p", "-preset", "fast", "-crf", "18", output_path], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
    return True

def render_video(image_paths, audio_path, output_path, scene_weights=None, watermark_text="GhostEngine", style_name="default"):
    print(f"⚙️ [RENDERER] Executing Master Render Engine...")
    srt_path, ass_path, temp_concat, temp_merged = audio_path.replace(".wav", ".srt"), audio_path.replace(".wav", ".ass"), "concat_list.txt", "temp_merged_no_subs.mp4"
    
    if not srt_to_ass(srt_path, ass_path, get_style_config(style_name)): return False
    
    try:
        audio = AudioSegment.from_file(audio_path)
        total_dur = min(len(audio) / 1000.0, 59.0)
        if len(audio) / 1000.0 > 59.0:
            audio[:59000].fade_out(1500).export(audio_path, format="wav")
    except: return False

    clip_durs = [w * total_dur for w in scene_weights] if scene_weights else [total_dur / len(image_paths)] * len(image_paths)
    clip_files = []
    
    for i, img in enumerate(image_paths):
        clip_out = f"temp_anim_{i}.mp4"
        if create_ken_burns_clip(img, clip_durs[i], clip_out, index=i): clip_files.append(clip_out)

    with open(temp_concat, "w") as f:
        for c in clip_files: f.write(f"file '{c}'\n")

    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", temp_concat, "-i", audio_path, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", temp_merged], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)

    font_path = download_cinematic_font()
    safe_font = font_path.replace('\\', '/').replace(':', r'\:')
    safe_ass = ass_path.replace('\\', '/').replace(':', r'\:')
    
    watermark_filter = f",drawtext=fontfile='{safe_font}':text='{watermark_text}':fontcolor=0xD3D3D3@0.25:shadowcolor=0x000000@0.25:shadowx=3:shadowy=3:fontsize=60:x=(w-text_w)/2:y=h-250"
    
    subprocess.run(["ffmpeg", "-y", "-i", temp_merged, "-vf", f"ass='{safe_ass}'{watermark_filter}", "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-c:a", "copy", output_path], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)

    for f in clip_files + [temp_concat, temp_merged, ass_path]:
        if os.path.exists(f): os.remove(f)
        
    # 🚨 FIX: The "Zero-Byte Ghost Upload" Shield. Detect FFmpeg soft-failures mathematically.
    if not os.path.exists(output_path): 
        return False, total_dur, 0
        
    file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
    if file_size_mb < 0.5:
        print(f"⚠️ [RENDERER] Critical Failure: Video rendered at {file_size_mb:.2f}MB. Suspected FFmpeg collapse.")
        return False, total_dur, file_size_mb
        
    return True, total_dur, file_size_mb
