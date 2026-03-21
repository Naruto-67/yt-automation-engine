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
    """
    Download Anton-Regular.ttf — the heavy condensed Impact-class font used
    in viral YouTube Shorts captions (CapCut Neon/Hornet presets).
    Falls back to Liberation Sans Bold if all mirrors fail.
    """
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
# ASS colour format: &HAABBGGRR  (alpha 00 = fully opaque)
# Map any legacy subtitle_color values to proper glow colors so old jobs
# that still have "target_color" in their script JSON don't produce red text.
_LEGACY_COLOR_REMAP = {
    "&H00FFFFFF": "&H0000D700",  # old "white text" → green glow
    "&H0000FFFF": "&H00FFD700",  # old "yellow text" → cyan glow
    "&H000000FF": "&H000015FF",  # old "red text"    → red glow
    "&H00FF0000": "&H00FF8040",  # old "blue text"   → blue glow
}

# Valid glow presets the LLM is instructed to choose from
_VALID_GLOW_COLORS = {
    "&H0000D700",  # Green  — nature, animals, science facts
    "&H00FFD700",  # Cyan   — technology, space, futurism
    "&H000015FF",  # Red    — horror, danger, dark revelations
    "&H00FF8040",  # Blue   — mystery, ocean, sci-fi
}


def _resolve_glow_color(raw_color: str) -> str:
    """
    Normalise whatever value arrived from the LLM / script JSON into a
    valid glow color code. Falls back to green if value is unrecognised.
    """
    if not raw_color or not isinstance(raw_color, str):
        return "&H0000D700"
    remapped = _LEGACY_COLOR_REMAP.get(raw_color, raw_color)
    return remapped if remapped in _VALID_GLOW_COLORS else "&H0000D700"


# ── Mood-specific visual color grades ─────────────────────────────────────────
# Applied in the final FFmpeg composite pass (after concat, before subtitle burn-in).
# Each grade is a self-contained FFmpeg -vf filter string fragment.
#
# neutral    → Clean contrast/saturation boost. No tint.
# wonder     → Slightly cooler/teal shadows (cosmic, sci-fi feel)
# excitement → High contrast, punchy saturation (energetic, viral)
# horror     → Desaturated, cold blue tint, crushed blacks (unsettling)
# warm       → Warm orange-gold tint, soft contrast (emotional, story)
#
# colorbalance: rs/gs/bs = red/green/blue in shadows
#               rm/gm/bm = red/green/blue in midtones
#               rh/gh/bh = red/green/blue in highlights
# All values: -1.0 (remove channel) to +1.0 (add channel)
_MOOD_COLOR_GRADE = {
    "neutral": (
        "eq=contrast=1.06:saturation=1.18:brightness=0.01"
    ),
    "wonder": (
        "eq=contrast=1.08:saturation=1.15:brightness=0.02,"
        "colorbalance=bs=-0.06:gs=-0.02:rs=0.02"   # slight teal-cool shadows
    ),
    "excitement": (
        "eq=contrast=1.12:saturation=1.38:brightness=0.02"  # punchy, high-energy
    ),
    "horror": (
        "eq=contrast=1.15:saturation=0.82:brightness=-0.02,"
        "colorbalance=bs=0.07:rs=-0.05"            # cold blue, crushed blacks
    ),
    "warm": (
        "eq=contrast=1.05:saturation=1.22:brightness=0.03,"
        "colorbalance=rs=0.06:gs=0.01:bs=-0.05"   # warm orange-gold
    ),
}

# ── Post-grade overlays (applied same pass, after color grade) ─────────────────
# vignette: subtle edge darkening — focuses viewer attention on center
#   angle=PI/5 is the default (moderate, not heavy)
# noise: film grain — makes AI renders look shot, not generated
#   alls=5 = very subtle (0-100 scale), allf=t = temporal (organic, changes per frame)
_VIGNETTE = "vignette=angle=PI/5"
_FILM_GRAIN = "noise=alls=5:allf=t"


def _get_visual_filter_chain(mood: str) -> str:
    """
    Build the complete visual filter chain for the final FFmpeg pass.
    Order: color grade → vignette → film grain → [then ass+watermark appended by caller]
    Color grade and vignette run BEFORE subtitle burn-in so captions stay pure white.
    """
    grade = _MOOD_COLOR_GRADE.get(mood, _MOOD_COLOR_GRADE["neutral"])
    return f"{grade},{_VIGNETTE},{_FILM_GRAIN}"


def get_style_config(caption_style: str = None):
    """
    Return the ASS style dict for the given caption_style preset name.

    If caption_style is None or not found in settings.yaml, falls back to
    the base subtitle_style block (backward compatible with all old jobs).
    PrimaryColour is ALWAYS forced to white — the LLM controls the glow
    halo color separately via glow_color, not the text color.
    """
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


def srt_to_ass(srt_path, ass_path, style, glow_color="&H0000D700"):
    """
    Convert SRT → ASS with a two-layer caption system that replicates the
    CapCut 'Neon/Hornet' preset:

      Layer 0  'Glow'    — transparent text, thick colored outline (GlowSize px),
                           Gaussian blur → outer neon halo effect
      Layer 1  'Default' — white text, thin black outline (5px), sharp
    """
    font          = style.get("FontName",      "Anton")
    size          = style.get("FontSize",      "90")
    alignment     = style.get("Alignment",     "2")
    margin_v      = style.get("MarginV",       "500")
    glow_size     = style.get("GlowSize",      "28")
    blur_strength = style.get("BlurStrength",  "15")
    safe_glow     = _resolve_glow_color(glow_color)

    blur_tag = f"{{\\blur{blur_strength}}}"

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1080\n"
        "PlayResY: 1920\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Glow,{font},{size},"
        f"&H00000000,&H000000FF,"
        f"{safe_glow},&H00000000,"
        f"1,0,0,0,100,100,0,0,1,{glow_size},0,{alignment},10,10,{margin_v},1\n"
        f"Style: Default,{font},{size},"
        f"&H00FFFFFF,&H000000FF,"
        f"&H00000000,&H00000000,"
        f"1,0,0,0,100,100,0,0,1,5,0,{alignment},10,10,{margin_v},1\n\n"
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
                    t0 = convert_time(times[0])
                    t1 = convert_time(times[1])
                    events.append(f"Dialogue: 0,{t0},{t1},Glow,,0,0,0,,{blur_tag}{text}")
                    events.append(f"Dialogue: 1,{t0},{t1},Default,,0,0,0,,{text}")

        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(header + "\n".join(events))

        print(
            f"🎨 [RENDERER] ASS subtitles built — "
            f"glow: {safe_glow} | font: {font} {size}pt | "
            f"align: {alignment} | margin: {margin_v} | "
            f"glow_size: {glow_size}px | blur: {blur_strength}"
        )
        return True

    except Exception as e:
        trace = traceback.format_exc()
        print(f"⚠️ [RENDERER] SRT to ASS conversion failed:\n{trace}")
        return False


def _select_watermark_preset(mood: str = "neutral") -> dict:
    """
    Select the watermark position/opacity preset based on content mood.
    Applies a 30% random override to break visual fingerprint across uploads.
    """
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
    """
    Find a background music track for the given mood and mix it into the
    output video at a low volume level. Skips silently on any failure.
    """
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


def create_ken_burns_clip(image_path, duration, output_path, index=0, fps=30):
    """
    Create a smooth Ken Burns animation clip from a still image.

    WHY CROP-BASED (not zoompan):
    ─────────────────────────────
    The `zoompan` filter produces visible wobble because it computes position
    as a float (iw/2 - (iw/zoom)/2) and truncates to integer pixels in an
    irregular pattern: 0→0→1→1→1→0→1 steps per frame.

    The crop approach uses floor(PAN*n/FRAMES) which produces perfectly
    uniform steps — mathematically smooth, no jitter.

    8 MOTION EFFECTS:
    ─────────────────
    4 cardinal directions + 4 diagonals. Using 6 sub-clips per video
    (2 per image), each video cycles through 6 unique effects with zero
    repetition. The 8-effect pool ensures variety across consecutive videos.

    SHARPEN:
    ────────
    AI-generated images are slightly soft. unsharp luma=0.3 (subtle) makes
    them look crisper without introducing halos or noise artifacts.
    """
    frames = int(duration * fps)

    # Source dimensions: 2x output for smooth pan headroom (no upscaling artifacts)
    SRC_W, SRC_H = 2160, 3840
    OUT_W, OUT_H = 1080, 1920

    # Center positions for non-moving axis
    cx = (SRC_W - OUT_W) // 2   # 540px
    cy = (SRC_H - OUT_H) // 2   # 960px

    # Pan travel: 40% of available headroom → cinematic, not distracting
    pan_x = int((SRC_W - OUT_W) * 0.40)   # 432px horizontal travel
    pan_y = int((SRC_H - OUT_H) * 0.40)   # 768px vertical travel

    # Diagonal travel: 30% on both axes simultaneously
    pan_dx = int((SRC_W - OUT_W) * 0.30)  # 324px diagonal x
    pan_dy = int((SRC_H - OUT_H) * 0.30)  # 576px diagonal y

    # Base prep: scale to SRC, crop exact, fix SAR
    prep = (
        f"scale={SRC_W}:{SRC_H}:force_original_aspect_ratio=increase,"
        f"crop={SRC_W}:{SRC_H},"
        f"setsar=1"
    )

    # Subtle per-clip sharpen — makes AI images look crisper
    # unsharp: lx=ly=3 (kernel), la=0.3 (luma strength), ca=0 (no chroma fringe)
    sharpen = "unsharp=lx=3:ly=3:la=0.3:cx=3:cy=3:ca=0"

    # eq per-clip: base contrast/saturation before mood-grade in final pass
    base_eq = "eq=contrast=1.05:saturation=1.15"

    # 8 smooth motion patterns using crop with perfectly linear floor() expressions
    # `n` = input frame number starting at 0
    effects = [
        # 0: Pan left → right, center vertically
        (
            f"{prep},"
            f"crop={OUT_W}:{OUT_H}:'floor({pan_x}*n/{frames})':{cy},"
            f"scale={OUT_W}:{OUT_H},"
            f"{sharpen},{base_eq}"
        ),
        # 1: Pan right → left, center vertically
        (
            f"{prep},"
            f"crop={OUT_W}:{OUT_H}:'floor({pan_x}*(1-n/{frames}))':{cy},"
            f"scale={OUT_W}:{OUT_H},"
            f"{sharpen},{base_eq}"
        ),
        # 2: Pan top → bottom, center horizontally
        (
            f"{prep},"
            f"crop={OUT_W}:{OUT_H}:{cx}:'floor({pan_y}*n/{frames})',"
            f"scale={OUT_W}:{OUT_H},"
            f"{sharpen},{base_eq}"
        ),
        # 3: Pan bottom → top, center horizontally
        (
            f"{prep},"
            f"crop={OUT_W}:{OUT_H}:{cx}:'floor({pan_y}*(1-n/{frames}))',"
            f"scale={OUT_W}:{OUT_H},"
            f"{sharpen},{base_eq}"
        ),
        # 4: Diagonal TL → BR
        (
            f"{prep},"
            f"crop={OUT_W}:{OUT_H}:'floor({pan_dx}*n/{frames})':"
            f"'floor({pan_dy}*n/{frames})',"
            f"scale={OUT_W}:{OUT_H},"
            f"{sharpen},{base_eq}"
        ),
        # 5: Diagonal TR → BL
        (
            f"{prep},"
            f"crop={OUT_W}:{OUT_H}:'floor({pan_dx}*(1-n/{frames}))':"
            f"'floor({pan_dy}*n/{frames})',"
            f"scale={OUT_W}:{OUT_H},"
            f"{sharpen},{base_eq}"
        ),
        # 6: Diagonal BL → TR
        (
            f"{prep},"
            f"crop={OUT_W}:{OUT_H}:'floor({pan_dx}*n/{frames})':"
            f"'floor({pan_dy}*(1-n/{frames}))',"
            f"scale={OUT_W}:{OUT_H},"
            f"{sharpen},{base_eq}"
        ),
        # 7: Diagonal BR → TL
        (
            f"{prep},"
            f"crop={OUT_W}:{OUT_H}:'floor({pan_dx}*(1-n/{frames}))':"
            f"'floor({pan_dy}*(1-n/{frames}))',"
            f"scale={OUT_W}:{OUT_H},"
            f"{sharpen},{base_eq}"
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
                 # ── backward-compat shim — old callers may pass subtitle_color ──
                 subtitle_color=None):
    """
    Master render function.

    Parameters
    ----------
    image_paths    : list of image file paths (one per scene)
    audio_path     : path to .wav file (must have matching .srt alongside it)
    output_path    : destination .mp4 path
    scene_weights  : optional list of floats summing to 1.0 for scene durations
    watermark_text : channel name (will be uppercased)
    glow_color     : ASS &HAABBGGRR color for the caption neon glow halo
    mood           : emotional register — controls color grade, watermark, music
    caption_style  : preset key from caption_style_presets in settings.yaml
    subtitle_color : deprecated alias for glow_color — accepted for back-compat

    IMAGE REUSE FOR PACING:
    ────────────────────────
    Each source image is rendered as 2 sub-clips with different Ken Burns
    motion effects. This doubles the visual cut frequency without any extra
    API calls:
        3 images × 2 effects = 6 clips
        25s ÷ 6 clips ≈ 4s per cut   ← fast-paced Shorts rhythm
    vs:
        3 images × 1 effect = 3 clips
        25s ÷ 3 clips ≈ 8s per cut   ← slow and static

    VISUAL FILTER PIPELINE (final pass):
    ──────────────────────────────────────
    mood color grade → vignette → film grain → subtitles → watermark
    Color grade and vignette run BEFORE subtitle burn-in so captions
    stay pure white regardless of the mood tint.
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

    # ── One unique Ken Burns clip per scene ────────────────────────────────────
    # Each image gets exactly one motion effect. Effect index cycles through the
    # 8-effect pool so consecutive scenes always have different motion directions.
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
    # Order: color grade → vignette → film grain → subtitle burn-in → watermark
    # Color grade + vignette + grain run BEFORE ass so captions stay pure white.
    visual_chain = _get_visual_filter_chain(mood)
    print(f"   Visual grade: {mood}")

    final_vf = f"{visual_chain},ass='{safe_ass}'{watermark_filter}"

    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-i",     temp_merged,
                "-vf",    final_vf,
                "-c:v",   "libx264",
                "-pix_fmt","yuv420p",   # REQUIRED: force universal pixel format
                "-preset","fast",
                "-crf",   "18",
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

    # ── Background music mix (post-render, in-place, silent skip if empty) ────
    _mix_background_music(output_path, mood)

    final_size_mb = os.path.getsize(output_path) / (1024 * 1024)
    return True, total_dur, final_size_mb
