# scripts/render_video.py
import os
import shutil
import subprocess
import json
import re
import requests
import traceback
from pydub import AudioSegment
from engine.config_manager import config_manager


MIN_RENDER_DISK_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB

def _check_disk_space(required_bytes: int = MIN_RENDER_DISK_BYTES) -> bool:
    try:
        free = shutil.disk_usage("/").free
        if free < required_bytes:
            required_gb = required_bytes / (1024 ** 3)
            free_gb     = free / (1024 ** 3)
            print(
                f"❌ [RENDERER] Insufficient disk space. "
                f"Required: {required_gb:.1f}GB | Available: {free_gb:.2f}GB. "
                f"Aborting render to prevent FFmpeg silent failure."
            )
            return False
        return True
    except Exception as e:
        print(f"⚠️ [RENDERER] Disk check failed ({e}). Proceeding with caution.")
        return True


# ── FIX 1: Download Anton (heavy condensed = Impact equivalent) ──────────────
def download_cinematic_font():
    """Download Anton-Regular.ttf — the viral Shorts caption font (Impact-class)."""
    font_path = "/tmp/Anton-Regular.ttf"
    if os.path.exists(font_path) and os.path.getsize(font_path) > 20000:
        return font_path
    mirrors = [
        "https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf",
        "https://fonts.gstatic.com/s/anton/v25/1Ptgg87LROyAm3K.ttf",
        "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/anton/Anton-Regular.ttf",
    ]
    for url in mirrors:
        try:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            with open(font_path, "wb") as f:
                f.write(response.content)
            if os.path.getsize(font_path) > 20000:
                print(f"✅ [RENDERER] Anton font downloaded from {url}")
                return font_path
        except Exception:
            pass
    # Final fallback — Liberation Sans Bold (better than nothing)
    return "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"


# ── Glow color safety map ────────────────────────────────────────────────────
# ASS format: &HAABBGGRR  (alpha, blue, green, red)
# If LLM returns a legacy subtitle_color accidentally, remap to a proper glow.
_LEGACY_TO_GLOW = {
    "&H00FFFFFF": "&H0000D700",   # white text → green glow
    "&H0000FFFF": "&H00FFD700",   # yellow text → cyan glow
}

def _resolve_glow_color(raw_color: str) -> str:
    """Ensure the value is a valid ASS glow color, not a text color."""
    if not raw_color or not raw_color.startswith("&H"):
        return "&H0000D700"   # default: green
    return _LEGACY_TO_GLOW.get(raw_color, raw_color)


def get_style_config():
    """Return the base style dict from settings.yaml. Text color is always white."""
    settings   = config_manager.get_settings()
    base_style = settings.get("subtitle_style", {
        "FontName": "Anton", "FontSize": "90", "PrimaryColour": "&H00FFFFFF",
        "OutlineColour": "&H00000000", "Outline": "5",
        "Shadow": "0", "BorderStyle": "1", "Alignment": "2", "MarginV": "500",
    })
    # SAFETY: always force white text — never let LLM color bleed into text layer
    base_style["PrimaryColour"] = "&H00FFFFFF"
    return base_style


def time_to_seconds(time_str):
    h, m, s_ms = time_str.split(":")
    s, ms      = s_ms.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


# ── FIX 2: Dual-layer ASS with colored glow ──────────────────────────────────
def srt_to_ass(srt_path, ass_path, style, glow_color="&H0000D700"):
    """
    Convert SRT → ASS with a two-layer caption system matching manual Topato style:
      Layer 0 (Glow):    transparent text, thick colored outline, Gaussian blur  → outer glow
      Layer 1 (Default): white text, thin black outline, sharp                   → readable text
    """
    font      = style.get("FontName", "Anton")
    size      = style.get("FontSize", "90")
    alignment = style.get("Alignment", "2")
    margin_v  = style.get("MarginV", "500")
    safe_glow = _resolve_glow_color(glow_color)

    header = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, "
        "Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        # Glow layer: transparent primary, glow color outline, thick (28px), blurred
        f"Style: Glow,{font},{size},&H00000000,&H000000FF,"
        f"{safe_glow},&H00000000,1,0,0,0,100,100,0,0,1,28,0,{alignment},10,10,{margin_v},1\n"
        # Text layer: white primary, black outline, sharp (5px)
        f"Style: Default,{font},{size},&H00FFFFFF,&H000000FF,"
        f"&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,5,0,{alignment},10,10,{margin_v},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    try:
        with open(srt_path, "r", encoding="utf-8") as f:
            content = f.read()

        def convert_time(ts):
            return ts.replace(",", ".")[:-1]

        events = []
        for block in content.strip().split("\n\n"):
            lines = block.split("\n")
            if len(lines) >= 3 and "-->" in lines[1]:
                times = re.findall(r"(\d+:\d+:\d+,\d+)", lines[1])
                if len(times) == 2:
                    text = re.sub(r"<[^>]+>", "", " ".join(lines[2:]))
                    text = text.replace("\n", " ").replace("\r", " ").strip().upper()
                    t0, t1 = convert_time(times[0]), convert_time(times[1])
                    # Layer 0: blurred glow halo
                    events.append(f"Dialogue: 0,{t0},{t1},Glow,,0,0,0,,{{\\blur15}}{text}")
                    # Layer 1: sharp white text on top
                    events.append(f"Dialogue: 1,{t0},{t1},Default,,0,0,0,,{text}")

        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(header + "\n".join(events))
        print(f"🎨 [RENDERER] ASS subtitles built — glow color: {safe_glow}")
        return True
    except Exception as e:
        trace = traceback.format_exc()
        print(f"⚠️ [RENDERER] SRT to ASS conversion failed:\n{trace}")
        return False


def create_ken_burns_clip(image_path, duration, output_path, index=0, fps=30):
    frames      = int(duration * fps)
    prep_filter = "scale=2160:3840:force_original_aspect_ratio=increase,crop=2160:3840"
    effects     = [
        f"zoompan=z='min(zoom+0.0007,1.15)':x='iw/2-(iw/zoom)/2':y='ih/2-(ih/zoom)/2':d={frames}:s=1080x1920:fps={fps}",
        f"zoompan=z='1.15-0.0007*on':x='iw/2-(iw/zoom)/2':y='ih/2-(ih/zoom)/2':d={frames}:s=1080x1920:fps={fps}",
        f"zoompan=z='1.15':x='(iw-iw/zoom)*(on/{frames})':y='ih/2-(ih/zoom)/2':d={frames}:s=1080x1920:fps={fps}",
        f"zoompan=z='1.15':x='(iw-iw/zoom)*(1-(on/{frames}))':y='ih/2-(ih/zoom)/2':d={frames}:s=1080x1920:fps={fps}",
    ]
    full_filter = f"{prep_filter},{effects[index % len(effects)]},eq=contrast=1.05:saturation=1.15"
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-loop", "1", "-i", image_path, "-vf", full_filter,
             "-c:v", "libx264", "-t", str(duration), "-pix_fmt", "yuv420p",
             "-preset", "fast", "-crf", "18", output_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, timeout=600,
        )
        return True
    except Exception as e:
        trace = traceback.format_exc()
        print(f"⚠️ [RENDERER] Ken Burns generation failed:\n{trace}")
        return False


# ── FIX 3: Renamed subtitle_color → glow_color in signature ─────────────────
def render_video(image_paths, audio_path, output_path,
                 scene_weights=None, watermark_text="Topato", glow_color=None):
    print("⚙️ [RENDERER] Executing Master Render Engine...")

    if not _check_disk_space():
        return False, 0.0, 0

    srt_path    = audio_path.replace(".wav", ".srt")
    ass_path    = audio_path.replace(".wav", ".ass")
    temp_concat = "concat_list.txt"
    temp_merged = "temp_merged_no_subs.mp4"

    resolved_glow = _resolve_glow_color(glow_color)
    if not srt_to_ass(srt_path, ass_path, get_style_config(), glow_color=resolved_glow):
        return False, 0.0, 0

    try:
        audio     = AudioSegment.from_file(audio_path)
        total_dur = min(len(audio) / 1000.0, 59.0)
        if len(audio) / 1000.0 > 59.0:
            print(f"⚠️ [RENDERER] Audio exceeds 59s ({len(audio)/1000.0}s). Applying cinematic fade-out.")
            audio[:59000].fade_out(1500).export(audio_path, format="wav")
    except Exception as e:
        trace = traceback.format_exc()
        print(f"⚠️ [RENDERER] Audio processing failed:\n{trace}")
        return False, 0.0, 0

    clip_durs = (
        [w * total_dur for w in scene_weights]
        if scene_weights
        else [total_dur / len(image_paths)] * len(image_paths)
    )
    if clip_durs:
        clip_durs[-1] += 0.6

    clip_files = []
    for i, img in enumerate(image_paths):
        clip_out = f"temp_anim_{i}.mp4"
        if create_ken_burns_clip(img, clip_durs[i], clip_out, index=i):
            clip_files.append(clip_out)

    if not clip_files:
        return False, total_dur, 0

    with open(temp_concat, "w") as f:
        for c in clip_files:
            f.write(f"file '{c}'\n")

    try:
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", temp_concat,
             "-i", audio_path, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
             "-shortest", temp_merged],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, timeout=600,
        )
    except Exception as e:
        trace = traceback.format_exc()
        print(f"⚠️ [RENDERER] Concat phase failed:\n{trace}")
        return False, total_dur, 0

    font_path = download_cinematic_font()
    safe_font = font_path.replace("\\", "/").replace(":", r"\:")
    safe_ass  = ass_path.replace("\\", "/").replace(":", r"\:")

    # ── FIX 4: Watermark — ALL CAPS, top-center at ~28% height, no shadow ────
    safe_watermark = re.sub(r"[^a-zA-Z0-9\s]", "", watermark_text).strip().upper() or "TOPATO"
    watermark_filter = (
        f",drawtext=fontfile='{safe_font}':text='{safe_watermark}':"
        f"fontcolor=0xC8C8C8@0.35:"
        f"fontsize=55:x=(w-text_w)/2:y=h*0.28"
    )

    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", temp_merged, "-vf",
             f"ass='{safe_ass}'{watermark_filter}",
             "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-c:a", "copy", output_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, timeout=600,
        )
    except Exception as e:
        trace = traceback.format_exc()
        print(f"⚠️ [RENDERER] Final subtitle overlay failed:\n{trace}")
        return False, total_dur, 0

    if not os.path.exists(output_path):
        return False, total_dur, 0

    file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
    if file_size_mb < 0.5:
        return False, total_dur, file_size_mb

    return True, total_dur, file_size_mb
