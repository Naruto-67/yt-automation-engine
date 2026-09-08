# scripts/render_video.py
import os
import glob
import shutil
import subprocess
import json
import re
import random
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


def download_cinematic_font():
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
                print(f"✅ [RENDERER] Anton font downloaded.")
                return font_path
        except Exception:
            pass

    print("⚠️ [RENDERER] Anton font download failed. Using Liberation Sans Bold fallback.")
    return "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"


# ── Glow color safety map ─────────────────────────────────────────────────────
_LEGACY_COLOR_REMAP = {
    "&H00FFFFFF": "&H0000D700",  # old "white text" → green glow
    "&H0000FFFF": "&H00FFD700",  # old "yellow text" → cyan glow
    "&H000000FF": "&H000015FF",  # old "red text"    → red glow
    "&H00FF0000": "&H00FF8040",  # old "blue text"   → blue glow
}

_VALID_GLOW_COLORS = {
    "&H0000D700",  # Green  — nature, animals, science facts
    "&H00FFD700",  # Cyan   — technology, space, futurism
    "&H000015FF",  # Red    — horror, danger, dark revelations
    "&H00FF8040",  # Blue   — mystery, ocean, sci-fi
}


def _resolve_glow_color(raw_color: str) -> str:
    if not raw_color or not isinstance(raw_color, str):
        return "&H0000D700"
    remapped = _LEGACY_COLOR_REMAP.get(raw_color, raw_color)
    return remapped if remapped in _VALID_GLOW_COLORS else "&H0000D700"


# ── Mood-specific visual color grades ─────────────────────────────────────────
_MOOD_COLOR_GRADE = {
    "neutral": (
        "eq=contrast=1.06:saturation=1.18:brightness=0.01"
    ),
    "wonder": (
        "eq=contrast=1.08:saturation=1.15:brightness=0.02,"
        "colorbalance=bs=-0.06:gs=-0.02:rs=0.02"
    ),
    "excitement": (
        "eq=contrast=1.12:saturation=1.38:brightness=0.02"
    ),
    "horror": (
        "eq=contrast=1.15:saturation=0.82:brightness=-0.02,"
        "colorbalance=bs=0.07:rs=-0.05"
    ),
    "warm": (
        "eq=contrast=1.05:saturation=1.22:brightness=0.03,"
        "colorbalance=rs=0.06:gs=0.01:bs=-0.05"
    ),
}

_VIGNETTE = "vignette=angle=PI/5"


def _get_visual_filter_chain(mood: str) -> str:
    grade = _MOOD_COLOR_GRADE.get(mood, _MOOD_COLOR_GRADE["neutral"])
    return f"{grade},{_VIGNETTE}"


def get_style_config(caption_style: str = None):
    settings = config_manager.get_settings()
    if caption_style:
        presets = settings.get("caption_style_presets", {})
        preset  = presets.get(caption_style)
        if preset:
            style = dict(preset)
            style["PrimaryColour"] = "&H00FFFFFF"
            style.setdefault("FontName",     "Anton")
            style.setdefault("FontSize",     "90")
            style.setdefault("Alignment",    "2")
            style.setdefault("MarginV",      "500")
            style.setdefault("GlowSize",     "28")
            style.setdefault("BlurStrength", "15")
            return style
    base_style = settings.get("subtitle_style", {
        "FontName":      "Anton",
        "FontSize":      "90",
        "PrimaryColour": "&H00FFFFFF",
        "OutlineColour": "&H00000000",
        "Outline":       "5",
        "Shadow":        "0",
        "BorderStyle":   "1",
        "Alignment":     "2",
        "MarginV":       "500",
    })
    base_style["PrimaryColour"] = "&H00FFFFFF"
    base_style.setdefault("GlowSize",     "28")
    base_style.setdefault("BlurStrength", "15")
    return base_style


def time_to_seconds(time_str):
    h, m, s_ms = time_str.split(":")
    s, ms      = s_ms.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


# ── Caption cleaning ──────────────────────────────────────────────────────────
# Filler words to strip from the start of caption lines
_FILLER_WORDS = {
    "so", "um", "uh", "like", "okay", "ok", "well", "actually",
    "basically", "literally", "honestly", "right", "now",
}

# Words that should NOT be preceded by a comma in captions
# (remove commas before "and", "but", "so", "or", "yet", "nor", "for")
_NO_COMMA_BEFORE = {"and", "but", "so", "or", "yet", "nor", "for"}


def _clean_caption_text(text: str) -> str:
    """
    Clean caption text for cleaner, more readable display.
    - Strip filler words at the start of lines
    - Remove mid-sentence commas before 'and', 'but', 'so', etc.
    - Collapse multiple spaces
    - Trim leading/trailing whitespace
    - Keep sentence-ending punctuation (. ! ?)
    """
    t = text.strip()
    if not t:
        return t

    # Preserve case for proper nouns but lowercase for consistency
    # (don't UPPERCASE everything — keep original casing)
    # Ghost Engine currently does .upper() which is bad for readability

    # Strip leading filler words (check first word)
    parts = t.split()
    while parts and parts[0].lower().rstrip(",") in _FILLER_WORDS:
        parts = parts[1:]
    if not parts:
        return t

    # Remove commas before conjunction words
    cleaned = []
    for i, word in enumerate(parts):
        if word.lower() in _NO_COMMA_BEFORE and i > 0:
            prev = cleaned[-1] if cleaned else ""
            if prev.endswith(","):
                cleaned[-1] = prev[:-1]
        cleaned.append(word)

    # Collapse multiple spaces
    result = " ".join(cleaned)
    # Remove double commas
    result = re.sub(r",\s*,", ",", result)
    # Remove trailing commas
    result = re.sub(r",\s*$", "", result)
    # Remove comma before sentence-ending punctuation
    result = re.sub(r",\s*([.!?])", r"\1", result)
    # Remove leading comma
    result = re.sub(r"^,\s*", "", result)

    # Viral Shorts look much better in ALL CAPS (Anton font looks best uppercase)
    return result.strip().upper()


# ── ASS caption generation with word-by-word highlighting + two-layer glow ────
# This is a MAJOR upgrade: combines Ghost Engine's two-layer neon glow with
# ClipBot's word-by-word active-word highlighting for a premium CapCut-style
# karaoke caption experience.

def _sec_to_ass(sec: float) -> str:
    """Convert float seconds to ASS time format H:MM:SS.cc"""
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _srt_time_to_sec(srt_time: str) -> float:
    """Convert SRT time format (HH:MM:SS,mmm) to seconds."""
    h, m, rest = srt_time.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def _build_ass_style_section(style: dict) -> str:
    """
    Build the ASS [V4+ Styles] section for a clean, modern, single-layer look.
    Bold white text, thick black outline, and soft drop shadow.
    """
    font          = style.get("FontName",      "Anton")
    size          = style.get("FontSize",      "95")
    alignment     = style.get("Alignment",     "2")
    margin_v      = style.get("MarginV",       "450")

    return (
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font},{size},"
        f"&H00FFFFFF,&H000000FF,"       # Primary: White
        f"&H00000000,&H99000000,"       # Outline: Black, Back: Semi-transparent Black shadow
        f"1,0,0,0,100,100,0,0,1,6,4,{alignment},30,30,{margin_v},1\n\n"
    )


def srt_to_ass(srt_path, ass_path, style, glow_color=None):
    """
    Convert SRT → ASS with:
    1. Clean, single-layer modern Hormozi-style text.
    2. Word-by-word highlighting (active word turns bright yellow).
    3. Caption cleaning (filler words stripped, commas cleaned).
    4. Smooth, no scaling popups or neon glows.
    """
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1080\n"
        "PlayResY: 1920\n\n"
    )

    ass_header = header + _build_ass_style_section(style)

    ass_header += (
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    try:
        with open(srt_path, "r", encoding="utf-8") as f:
            content = f.read()

        srt_blocks = []
        for block in content.strip().split("\n\n"):
            lines = block.split("\n")
            if len(lines) >= 3 and "-->" in lines[1]:
                times = re.findall(r"(\d+:\d+:\d+,\d+)", lines[1])
                if len(times) == 2:
                    text = re.sub(r"<[^>]+>", "", " ".join(lines[2:]))
                    text = _clean_caption_text(text)
                    if not text:
                        continue
                    t0 = _srt_time_to_sec(times[0])
                    t1 = _srt_time_to_sec(times[1])
                    if t1 <= t0:
                        t1 = t0 + 0.5
                    srt_blocks.append({
                        "start": t0,
                        "end": t1,
                        "text": text,
                        "words": text.split(),
                    })

        if not srt_blocks:
            return False

        events = []

        for block in srt_blocks:
            words = block["words"]
            if not words:
                continue

            duration = block["end"] - block["start"]
            per_word_time = duration / len(words)

            for i, word in enumerate(words):
                w_start = block["start"] + i * per_word_time
                w_end = w_start + per_word_time

                start_ass = _sec_to_ass(w_start)
                end_ass = _sec_to_ass(w_end)

                default_parts = []
                
                for j, w in enumerate(words):
                    if j == i:
                        # Active word: Clean bright Yellow
                        default_parts.append(f"{{\\c&H0000D7FF&}}{w}{{\\c&H00FFFFFF&}}")
                    elif j < i:
                        # Spoken word: Dimmed slightly or kept white
                        default_parts.append(f"{w}")
                    else:
                        # Upcoming word: White
                        default_parts.append(w)

                default_text = " ".join(default_parts)
                events.append(f"Dialogue: 0,{start_ass},{end_ass},Default,,0,0,0,,{default_text}")

        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(ass_header + "\n".join(events))

        print(
            f"🎨 [RENDERER] ASS subtitles built — "
            f"word-by-word + glow: {safe_glow} | font: {style.get('FontName','Anton')} {style.get('FontSize','90')}pt | "
            f"align: {style.get('Alignment','2')} | margin: {style.get('MarginV','500')} | "
            f"glow_size: {style.get('GlowSize','28')}px | blur: {blur_strength}"
        )
        return True

    except Exception as e:
        trace = traceback.format_exc()
        print(f"⚠️ [RENDERER] SRT to ASS conversion failed:\n{trace}")
        return False


def _select_watermark_preset(mood: str = "neutral") -> dict:
    settings    = config_manager.get_settings()
    wm_cfg      = settings.get("watermark_presets", {})
    mood_map    = wm_cfg.get("mood_map", {})
    presets     = wm_cfg.get("presets", {})

    primary_preset_name = mood_map.get(mood, "standard")

    if random.random() < 0.30:
        all_preset_names = list(presets.keys())
        other_presets    = [p for p in all_preset_names if p != primary_preset_name]
        if other_presets:
            primary_preset_name = random.choice(other_presets)

    preset = presets.get(primary_preset_name, {})

    return {
        "x":           preset.get("x",        "(w-text_w)/2"),
        "y":           preset.get("y",        "h*0.28"),
        "opacity":     preset.get("opacity",  "0.35"),
        "fontsize":    preset.get("fontsize", "55"),
        "preset_name": primary_preset_name,
    }


def _mix_background_music(output_path: str, mood: str = "neutral") -> bool:
    settings  = config_manager.get_settings()
    music_cfg = settings.get("music", {})

    volume       = float(music_cfg.get("volume",           0.08))
    fade_in      = float(music_cfg.get("fade_in_seconds",  1.0))
    fade_out     = float(music_cfg.get("fade_out_seconds", 1.5))
    mood_folders = music_cfg.get("mood_to_folder", {})
    folder_name  = mood_folders.get(mood, "cinematic_sad")

    root_dir    = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    folder_path = os.path.join(root_dir, "assets", "music", folder_name)

    if not os.path.isdir(folder_path):
        print(f"🎵 [MUSIC] Folder not found: {folder_path}. Skipping music mix.")
        return False

    mp3_files = glob.glob(os.path.join(folder_path, "*.mp3"))
    if not mp3_files:
        print(f"🎵 [MUSIC] No tracks in '{folder_name}/'. Skipping music mix.")
        return False

    track_path = random.choice(mp3_files)
    print(f"🎵 [MUSIC] Mixing track: {os.path.basename(track_path)} (mood={mood})")

    temp_path = output_path + ".music_mix.tmp.mp4"

    try:
        probe_result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", output_path],
            capture_output=True, timeout=30,
        )
        video_duration = 59.0
        if probe_result.returncode == 0:
            probe_data = json.loads(probe_result.stdout)
            video_duration = float(probe_data.get("format", {}).get("duration", 59.0))

        fade_out_start = max(0, video_duration - fade_out)

        music_filter = (
            f"[1:a]"
            f"volume={volume},"
            f"afade=t=in:st=0:d={fade_in},"
            f"afade=t=out:st={fade_out_start:.2f}:d={fade_out}"
            f"[music];"
            f"[0:a][music]amix=inputs=2:duration=first:dropout_transition=3[aout]"
        )

        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i",           output_path,
                "-stream_loop", "-1",
                "-i",           track_path,
                "-filter_complex", music_filter,
                "-map",         "0:v",
                "-map",         "[aout]",
                "-c:v",         "copy",
                "-c:a",         "aac",
                "-b:a",         "192k",
                "-shortest",
                temp_path,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=300,
        )

        if result.returncode != 0:
            err = result.stderr.decode("utf-8", errors="replace")[:400]
            print(f"⚠️ [MUSIC] FFmpeg mix failed:\n{err}")
            if os.path.exists(temp_path):
                os.remove(temp_path)
            return False

        if not os.path.exists(temp_path) or os.path.getsize(temp_path) < 10000:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            return False

        os.replace(temp_path, output_path)
        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        print(f"✅ [MUSIC] Background music mixed in ({size_mb:.1f} MB final).")
        return True

    except subprocess.TimeoutExpired:
        print(f"⚠️ [MUSIC] FFmpeg music mix timed out. Skipping.")
        if os.path.exists(temp_path):
            try: os.remove(temp_path)
            except: pass
        return False
    except Exception:
        trace = traceback.format_exc()
        print(f"⚠️ [MUSIC] Music mix exception:\n{trace}")
        if os.path.exists(temp_path):
            try: os.remove(temp_path)
            except: pass
        return False


def _smoothstep(t: float) -> float:
    """
    Hermite smoothstep interpolation: t²(3 - 2t)
    Provides smooth ease-in/ease-out compared to linear motion.
    t is clamped to [0, 1].
    """
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def create_ken_burns_clip(image_path, duration, output_path, index=0, fps=60):
    """
    Create a smooth Ken Burns animation clip from a still image.

    IMPROVEMENTS:
    - Reduced pan travel (5% instead of 12%) for more subtle, professional drift
    - Smoothstep easing (ease-in/ease-out) instead of linear motion
    - Reduced sharpen (0.15 instead of 0.3) to avoid halos
    - Subtle zoom (1.0 → 1.03) combined with pan for cinematic feel
    - Crossfade-friendly (no hard cuts)
    """
    frames = int(duration * fps)

    # Source dimensions: 2x output for smooth pan headroom
    SRC_W, SRC_H = 2160, 3840
    OUT_W, OUT_H = 1080, 1920

    # Center positions for non-moving axis
    cx = (SRC_W - OUT_W) // 2   # 540px
    cy = (SRC_H - OUT_H) // 2   # 960px

    # REDUCED pan travel: reads pan_percent from settings.yaml (default 5%)
    settings_render = config_manager.get_settings().get("render", {})
    PAN_PCT = float(settings_render.get("pan_percent", 0.05))
    DIAG_PCT = float(settings_render.get("diagonal_percent", 0.04))
    SHARP_LUMA = float(settings_render.get("sharpen_luma", 0.15))
    BASE_CT = float(settings_render.get("base_contrast", 1.03))
    BASE_SAT = float(settings_render.get("base_saturation", 1.10))

    pan_x = int((SRC_W - OUT_W) * PAN_PCT)   # ~54px horizontal
    pan_y = int((SRC_H - OUT_H) * PAN_PCT)   # ~96px vertical

    # Diagonal travel: reads diagonal_percent (default 4%)
    pan_dx = int((SRC_W - OUT_W) * DIAG_PCT)     # ~43px diagonal x
    pan_dy = int((SRC_H - OUT_H) * DIAG_PCT)     # ~77px diagonal y

    # Subtle zoom: 1.0 → 1.03 (very subtle, Ken Burns signature)
    zoom_start = 1.0
    zoom_end = 1.03

    # Base prep: scale to SRC, crop exact, fix SAR
    prep = (
        f"scale={SRC_W}:{SRC_H}:force_original_aspect_ratio=increase,"
        f"crop={SRC_W}:{SRC_H},"
        f"setsar=1"
    )

    # REDUCED sharpen: reads sharpen_luma from settings.yaml (default 0.15)
    sharpen = f"unsharp=lx=3:ly=3:la={SHARP_LUMA}:cx=3:cy=3:ca=0"

    # eq per-clip: reads base_contrast/saturation from settings.yaml
    base_eq = f"eq=contrast={BASE_CT}:saturation={BASE_SAT}"

    # Eased expressions using smoothstep
    # `t = n/{frames}` = normalized progress
    # `s = smoothstep(t)` = eased progress
    # We embed the smoothstep directly in the FFmpeg expression
    # In FFmpeg expression syntax: smoothstep = t*t*(3 - 2*t)
    # We'll use a helper: let s = smoothstep(t)
    # Then position = pan * s (for start→end) or pan * (1 - s) (for end→start)

    # FFmpeg expression for smoothstep: (t)*(t)*(3-2*(t)) where t = n/frames
    # But we need to inject this inline. We'll use the expression:
    # pos = PAN * ( (n/frames)*(n/frames)*(3 - 2*(n/frames)) )
    # Which simplifies to: pos = PAN * (n*n)*(3*frames - 2*n) / (frames*frames*frames)

    # 8 smooth motion patterns with ease-in/ease-out using smoothstep
    # The expression: s = (n/frames)*(n/frames)*(3 - 2*(n/frames))
    # Expressed as: s = (n*n)*(3*frames - 2*n) / (frames*frames*frames)
    # For reverse: 1 - s

    # Pre-compute the expression parts for readability
    # s(t) = t²(3-2t) where t = n/frames
    # In FFmpeg: ((n)*(n)/(frames)/(frames))*(3-2*(n)/(frames))
    # = (n*n)*(3*frames - 2*n) / (frames*frames*frames)

    # Zoom: z = zoom_start + (zoom_end - zoom_start) * s
    # zoom_center = (iw/zoom) / 2 for the crop center

    # Simplified: we use smoothstep for pan, linear for zoom (subtle enough)

    # Build the smoothstep expression: (n/frames)*(n/frames)*(3-2*(n/frames))
    # In FFmpeg: let t=n/frames, then t*t*(3-2*t)
    # We'll use the literal: (n/frames)*(n/frames)*(3-2*(n/frames))

    # For the crop filter, position = start + pan_amount * s(t)
    # where s(t) = smoothstep
    # For reverse: position = start + pan_amount * (1 - s(t))

    # s(t) inline = (n/fr)*(n/fr)*(3-2*(n/fr)) where fr = frames
    # To avoid repeating, we'll use the expanded form:
    # s = (n*n)*(3*frames - 2*n) / (frames*frames*frames)

    fr = frames  # alias for readability

    # NOTE: `n` in the expressions below is the FFmpeg frame counter variable
    # (starts at 0). It must remain literal — NOT a Python f-string interpolation.
    # The smoothstep expression: s = (n/fr)*(n/fr)*(3-2*(n/fr))
    # Expanded: s = (n*n)*(3*fr - 2*n) / (fr*fr*fr)
    # We use {{n}} in f-strings to emit a literal `n` for FFmpeg.

    effects = [
        # 0: Pan left → right, eased, center vertically
        (
            f"{prep},"
            f"zoompan=z='1.05':d={fr}:s={OUT_W}x{OUT_H}:fps=60:"
            f"x='{pan_x}*((on*on)*({3*fr}-2*on)/({fr}*{fr}*{fr}))':y='{cy}',"
            f"{sharpen},{base_eq},format=yuv420p"
        ),
        # 1: Pan right → left, eased, center vertically
        (
            f"{prep},"
            f"zoompan=z='1.05':d={fr}:s={OUT_W}x{OUT_H}:fps=60:"
            f"x='{pan_x}*(1-((on*on)*({3*fr}-2*on)/({fr}*{fr}*{fr})))':y='{cy}',"
            f"{sharpen},{base_eq},format=yuv420p"
        ),
        # 2: Pan top → bottom, eased, center horizontally
        (
            f"{prep},"
            f"zoompan=z='1.05':d={fr}:s={OUT_W}x{OUT_H}:fps=60:"
            f"x='{cx}':y='{pan_y}*((on*on)*({3*fr}-2*on)/({fr}*{fr}*{fr}))',"
            f"{sharpen},{base_eq},format=yuv420p"
        ),
        # 3: Pan bottom → top, eased, center horizontally
        (
            f"{prep},"
            f"zoompan=z='1.05':d={fr}:s={OUT_W}x{OUT_H}:fps=60:"
            f"x='{cx}':y='{pan_y}*(1-((on*on)*({3*fr}-2*on)/({fr}*{fr}*{fr})))',"
            f"{sharpen},{base_eq},format=yuv420p"
        ),
        # 4: Diagonal TL → BR, eased
        (
            f"{prep},"
            f"zoompan=z='1.05':d={fr}:s={OUT_W}x{OUT_H}:fps=60:"
            f"x='{pan_dx}*((on*on)*({3*fr}-2*on)/({fr}*{fr}*{fr}))':"
            f"y='{pan_dy}*((on*on)*({3*fr}-2*on)/({fr}*{fr}*{fr}))',"
            f"{sharpen},{base_eq},format=yuv420p"
        ),
        # 5: Diagonal TR → BL, eased
        (
            f"{prep},"
            f"zoompan=z='1.05':d={fr}:s={OUT_W}x{OUT_H}:fps=60:"
            f"x='{pan_dx}*(1-((on*on)*({3*fr}-2*on)/({fr}*{fr}*{fr})))':"
            f"y='{pan_dy}*((on*on)*({3*fr}-2*on)/({fr}*{fr}*{fr}))',"
            f"{sharpen},{base_eq},format=yuv420p"
        ),
        # 6: Diagonal BL → TR, eased
        (
            f"{prep},"
            f"zoompan=z='1.05':d={fr}:s={OUT_W}x{OUT_H}:fps=60:"
            f"x='{pan_dx}*((on*on)*({3*fr}-2*on)/({fr}*{fr}*{fr}))':"
            f"y='{pan_dy}*(1-((on*on)*({3*fr}-2*on)/({fr}*{fr}*{fr})))',"
            f"{sharpen},{base_eq},format=yuv420p"
        ),
        # 7: Diagonal BR → TL, eased
        (
            f"{prep},"
            f"zoompan=z='1.05':d={fr}:s={OUT_W}x{OUT_H}:fps=60:"
            f"x='{pan_dx}*(1-((on*on)*({3*fr}-2*on)/({fr}*{fr}*{fr})))':"
            f"y='{pan_dy}*(1-((on*on)*({3*fr}-2*on)/({fr}*{fr}*{fr})))',"
            f"{sharpen},{base_eq},format=yuv420p"
        ),
    ]

    chosen = effects[index % len(effects)]

    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-loop",    "1",
                "-i",       image_path,
                "-vf",      chosen,
                "-c:v",     "libx264",
                "-t",       str(duration),
                "-pix_fmt", "yuv420p",
                "-preset",  "fast",
                "-crf",     "18",
                "-r",       "60",
                output_path,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=True,
            timeout=600,
        )
        return True
    except Exception:
        trace = traceback.format_exc()
        print(f"⚠️ [RENDERER] Ken Burns generation failed:\n{trace}")
        return False


def render_video(image_paths, audio_path, output_path,
                 scene_weights=None, watermark_text="Topato", glow_color=None,
                 mood="neutral", caption_style=None,
                 subtitle_color=None):
    """
    Master render function.

    IMPROVEMENTS:
    - Crossfade transitions between scenes (0.5s xfade)
    - Eased Ken Burns motion (smoothstep instead of linear)
    - Reduced pan travel (5% instead of 12%)
    - Reduced sharpen (0.15 instead of 0.3)
    - Word-by-word caption highlighting + two-layer glow
    - Caption cleaning (filler words, commas, smart breaks)
    """
    print("⚙️ [RENDERER] Executing Master Render Engine...")
    print(f"   Mood: {mood} | Caption Style: {caption_style or 'default'}")

    if glow_color is None and subtitle_color is not None:
        glow_color = subtitle_color

    if not _check_disk_space():
        return False, 0.0, 0

    srt_path    = audio_path.replace(".wav", ".srt")
    ass_path    = audio_path.replace(".wav", ".ass")
    temp_concat = "concat_list.txt"
    temp_merged = "temp_merged_no_subs.mp4"

    resolved_glow = _resolve_glow_color(glow_color)
    style         = get_style_config(caption_style)

    if not srt_to_ass(srt_path, ass_path, style, glow_color=resolved_glow):
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

    # ── Compute per-scene durations ───────────────────────────────────────────
    clip_durs = (
        [w * total_dur for w in scene_weights]
        if scene_weights
        else [total_dur / len(image_paths)] * len(image_paths)
    )
    if clip_durs:
        clip_durs[-1] += 0.6   # tail buffer for last scene

    # ── Generate Ken Burns clips ──────────────────────────────────────────────
    clip_files   = []
    effect_index = 0

    for i, img in enumerate(image_paths):
        clip_out = f"temp_anim_{i}.mp4"
        success  = create_ken_burns_clip(img, clip_durs[i], clip_out, index=effect_index)
        if success:
            clip_files.append(clip_out)
        else:
            print(f"⚠️ [RENDERER] Clip {i} failed — skipping scene.")
        effect_index += 1

    print(f"   📽️  Clips generated: {len(clip_files)} (from {len(image_paths)} unique scenes)")

    if not clip_files:
        return False, total_dur, 0

    # ── Concat with crossfade transitions ─────────────────────────────────────
    # NEW: Use xfade filter between clips instead of hard cuts
    # xfade=transition=fade:duration=0.5:offset=...
    # This creates smooth 0.5s fade transitions between each scene
    if len(clip_files) == 1:
        # Single clip — no crossfade needed
        subprocess.run(
            ["ffmpeg", "-y", "-i", clip_files[0], "-i", audio_path,
             "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
             "-shortest", temp_merged],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, timeout=600,
        )
    else:
        # Multiple clips — use xfade for smooth transitions
        # Build complex xfade filter chain
        # xfade requires input streams to be the same resolution/fps
        # We'll use the concat demuxer for simplicity, then add crossfade
        # Actually, let's use xfade directly:
        # ffmpeg -i clip0 -i clip1 -i clip2 -filter_complex "
        #   [0:v]settb=AVTB[0v]; [1:v]settb=AVTB[1v]; [2:v]settb=AVTB[2v];
        #   [0v][1v]xfade=transition=fade:duration=0.5:offset={d0}[v01];
        #   [v01][2v]xfade=transition=fade:duration=0.5:offset={d1}[vout]"
        #  -map "[vout]" -map {audio} -c:v libx264 -preset fast -crf 18 ...

        # We need to know the duration of each clip for offset calculation
        # Use ffprobe to get durations
        clip_durations = []
        for cf in clip_files:
            try:
                probe = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "json", cf],
                    capture_output=True, text=True, timeout=30,
                )
                data = json.loads(probe.stdout)
                clip_durations.append(float(data["format"]["duration"]))
            except Exception:
                clip_durations.append(clip_durs[len(clip_durations)] if len(clip_durations) < len(clip_durs) else 4.0)

        # Build xfade filter — duration reads from settings.yaml render.xfade_duration
        # (0 disables transitions and uses plain concat)
        xfade_duration = float(
            config_manager.get_settings().get("render", {}).get("xfade_duration", 0.3)
        )

        if xfade_duration <= 0:
            # Transitions disabled — plain concat
            with open(temp_concat, "w") as f:
                for c in clip_files:
                    f.write(f"file '{c}'\n")
            subprocess.run(
                ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", temp_concat,
                 "-i", audio_path, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                 "-shortest", temp_merged],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, timeout=600,
            )
        else:
            filter_parts = []
            input_maps = []
            for i in range(len(clip_files)):
                filter_parts.append(f"[{i}:v]settb=AVTB[{i}v]")
                input_maps.append(f"-i {clip_files[i]}")

            # Chain xfade filters
            current_input = "0v"
            for i in range(1, len(clip_files)):
                offset = sum(clip_durations[:i]) - xfade_duration
                next_input = f"v{i}"
                filter_parts.append(
                    f"[{current_input}][{i}v]xfade=transition=fade:"
                    f"duration={xfade_duration}:offset={offset}[{next_input}]"
                )
                current_input = next_input

            final_output = current_input
            filter_complex = ";".join(filter_parts)

            audio_input_idx = len(clip_files)
            xfade_cmd = (
                f"ffmpeg -y "
                + " ".join(input_maps)
                + f" -i {audio_path}"
                + f" -filter_complex \"{filter_complex}\""
                + f" -map \"[{final_output}]\""
                + f" -map {audio_input_idx}:a"
                + f" -c:v libx264 -preset fast -crf 18 -r 60"
                + f" -c:a aac -b:a 192k -shortest {temp_merged}"
            )

            try:
                subprocess.run(
                    xfade_cmd, shell=True, check=True,
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=600,
                )
            except subprocess.CalledProcessError as e:
                stderr = e.stderr.decode(errors="replace")[:500] if e.stderr else ""
                print(f"⚠️ [RENDERER] xfade concat failed. Falling back to simple concat.\n   Error: {stderr}")
                # Fallback: simple concat without transitions
                with open(temp_concat, "w") as f:
                    for c in clip_files:
                        f.write(f"file '{c}'\n")
                subprocess.run(
                    ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", temp_concat,
                     "-i", audio_path, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                     "-shortest", temp_merged],
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, timeout=600,
                )

    font_path = download_cinematic_font()
    safe_font = font_path.replace("\\", "/").replace(":", r"\:")
    safe_ass  = ass_path.replace("\\", "/").replace(":", r"\:")

    # ── Watermark (mood-driven dynamic position) ──────────────────────────────
    safe_watermark   = re.sub(r"[^a-zA-Z0-9\s]", "", watermark_text).strip().upper() or "TOPATO"
    wm               = _select_watermark_preset(mood)
    watermark_filter = (
        f",drawtext=fontfile='{safe_font}':text='{safe_watermark}':"
        f"fontcolor=0xC8C8C8@{wm['opacity']}:"
        f"fontsize={wm['fontsize']}:x={wm['x']}:y={wm['y']}"
    )
    print(f"   Watermark preset: {wm['preset_name']} | opacity: {wm['opacity']}")

    # ── Visual filter chain ───────────────────────────────────────────────────
    visual_chain = _get_visual_filter_chain(mood)
    print(f"   Visual grade: {mood}")

    # The ASS file now contains word-by-word events with two-layer glow
    final_vf = f"{visual_chain},ass='{safe_ass}'{watermark_filter}"

    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-i",     temp_merged,
                "-vf",    final_vf,
                "-c:v",   "libx264",
                "-pix_fmt","yuv420p",
                "-preset","fast",
                "-crf",   "18",
                "-r",     "60",
                "-c:a",   "copy",
                output_path,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=True,
            timeout=600,
        )
    except Exception as e:
        trace = traceback.format_exc()
        print(f"⚠️ [RENDERER] Final composite pass failed:\n{trace}")
        return False, total_dur, 0

    if not os.path.exists(output_path):
        return False, total_dur, 0

    file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
    if file_size_mb < 0.5:
        return False, total_dur, file_size_mb

    # ── Background music mix ──────────────────────────────────────────────────
    _mix_background_music(output_path, mood)

    final_size_mb = os.path.getsize(output_path) / (1024 * 1024)
    return True, total_dur, final_size_mb