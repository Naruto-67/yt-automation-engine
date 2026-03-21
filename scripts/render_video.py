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
    "&H000000FF": "&H000015FF",  # old "red text"    → red glow  (now applied as halo)
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
    valid glow color code.  Falls back to green if value is unrecognised.
    """
    if not raw_color or not isinstance(raw_color, str):
        return "&H0000D700"
    remapped = _LEGACY_COLOR_REMAP.get(raw_color, raw_color)
    return remapped if remapped in _VALID_GLOW_COLORS else "&H0000D700"


def get_style_config(caption_style: str = None):
    """
    Return the ASS style dict for the given caption_style preset name.

    If caption_style is None or not found in settings.yaml, falls back to
    the base subtitle_style block (backward compatible with all old jobs).
    PrimaryColour is ALWAYS forced to white — the LLM controls the glow
    halo color separately via glow_color, not the text color.

    Parameters
    ----------
    caption_style : preset key from caption_style_presets in settings.yaml
                    e.g. "viral_impact", "cinematic", "horror_tight", etc.
                    Pass None to get the base legacy style.

    Returns
    -------
    dict with ASS style keys: FontName, FontSize, Alignment, MarginV,
                              GlowSize, BlurStrength, PrimaryColour
    """
    settings = config_manager.get_settings()

    # Try to load from caption_style_presets if a named style was requested
    if caption_style:
        presets = settings.get("caption_style_presets", {})
        preset  = presets.get(caption_style)
        if preset:
            style = dict(preset)
            style["PrimaryColour"] = "&H00FFFFFF"   # Always white text
            # Ensure all keys exist with safe defaults
            style.setdefault("FontName",     "Anton")
            style.setdefault("FontSize",     "90")
            style.setdefault("Alignment",    "2")
            style.setdefault("MarginV",      "500")
            style.setdefault("GlowSize",     "28")
            style.setdefault("BlurStrength", "15")
            return style

    # Fallback: load base subtitle_style block (backward compat for old jobs)
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
    CapCut 'Neon/Hornet' preset used in the manually-created Topato videos:

      Layer 0  'Glow'    — transparent text, thick colored outline (GlowSize px),
                           Gaussian blur (BlurStrength) → outer neon halo effect
      Layer 1  'Default' — white text, thin black outline (5px), sharp
                           → clean readable foreground

    Both layers share identical timing so they composite perfectly.
    The glow_color argument controls the halo color (ASS &HAABBGGRR format).
    The GlowSize and BlurStrength come from the caption_style preset, so
    different moods get different halo intensities.
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
        # ── Glow layer ────────────────────────────────────────────────────────
        # PrimaryColour &H00000000 = fully transparent text body
        # OutlineColour = the chosen neon glow color
        # Outline = GlowSize px thick → spreads into a wide halo
        # \blurN tag applied per-event for soft Gaussian falloff
        f"Style: Glow,{font},{size},"
        f"&H00000000,&H000000FF,"
        f"{safe_glow},&H00000000,"
        f"1,0,0,0,100,100,0,0,1,{glow_size},0,{alignment},10,10,{margin_v},1\n"
        # ── Text layer ────────────────────────────────────────────────────────
        # PrimaryColour &H00FFFFFF = pure white
        # OutlineColour &H00000000 = pure black outline
        # Outline = 5px → crisp, readable stroke
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
            # SRT  00:00:01,234  →  ASS  00:00:01.23
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
                    # Layer 0: blurred glow halo (rendered first / behind)
                    events.append(
                        f"Dialogue: 0,{t0},{t1},Glow,,0,0,0,,{blur_tag}{text}"
                    )
                    # Layer 1: sharp white text on top
                    events.append(
                        f"Dialogue: 1,{t0},{t1},Default,,0,0,0,,{text}"
                    )

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
    Applies a 30% random override so even same-mood videos vary in watermark
    position, breaking the visual fingerprint across uploads.

    Returns a dict with keys: x, y, opacity, fontsize
    """
    settings    = config_manager.get_settings()
    wm_cfg      = settings.get("watermark_presets", {})
    mood_map    = wm_cfg.get("mood_map", {})
    presets     = wm_cfg.get("presets", {})

    # Determine the mood-driven preset name
    primary_preset_name = mood_map.get(mood, "standard")

    # 30% random override — pick any other preset
    if random.random() < 0.30:
        all_preset_names = list(presets.keys())
        other_presets    = [p for p in all_preset_names if p != primary_preset_name]
        if other_presets:
            primary_preset_name = random.choice(other_presets)

    preset = presets.get(primary_preset_name, {})

    # Return with safe defaults if preset is missing or misconfigured
    return {
        "x":        preset.get("x",        "(w-text_w)/2"),
        "y":        preset.get("y",        "h*0.28"),
        "opacity":  preset.get("opacity",  "0.35"),
        "fontsize": preset.get("fontsize", "55"),
        "preset_name": primary_preset_name,
    }


def _mix_background_music(output_path: str, mood: str = "neutral") -> bool:
    """
    Find a background music track from assets/music/{folder}/ matching the
    given mood, and mix it into the output video at a low volume level.

    Uses FFmpeg amix filter: voice track at full volume, music at ~-22dB.
    Applies fade-in and fade-out as configured in settings.yaml.

    This function overwrites output_path in-place using a temp file.
    Returns True if music was mixed in, False if skipped (empty folder, no
    PIXABAY_API_KEY, or any error).

    Skipping is always silent — no exception is raised, no crash occurs.
    """
    settings  = config_manager.get_settings()
    music_cfg = settings.get("music", {})

    volume       = float(music_cfg.get("volume",           0.08))
    fade_in      = float(music_cfg.get("fade_in_seconds",  1.0))
    fade_out     = float(music_cfg.get("fade_out_seconds", 1.5))
    mood_folders = music_cfg.get("mood_to_folder", {})
    folder_name  = mood_folders.get(mood, "cinematic_sad")

    root_dir     = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    folder_path  = os.path.join(root_dir, "assets", "music", folder_name)

    if not os.path.isdir(folder_path):
        print(f"🎵 [MUSIC] Folder not found: {folder_path}. Skipping music mix.")
        return False

    mp3_files = glob.glob(os.path.join(folder_path, "*.mp3"))
    if not mp3_files:
        print(f"🎵 [MUSIC] No tracks in '{folder_name}/'. Skipping music mix.")
        return False

    track_path = random.choice(mp3_files)
    print(f"🎵 [MUSIC] Mixing track: {os.path.basename(track_path)} (mood={mood}, folder={folder_name})")

    temp_path = output_path + ".music_mix.tmp.mp4"

    try:
        # Get video duration so we can calculate fade_out timing
        probe_result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                output_path,
            ],
            capture_output=True, timeout=30,
        )
        video_duration = 59.0   # safe default
        if probe_result.returncode == 0:
            probe_data = json.loads(probe_result.stdout)
            video_duration = float(probe_data.get("format", {}).get("duration", 59.0))

        fade_out_start = max(0, video_duration - fade_out)

        # Build FFmpeg audio filter:
        # - Loop the music track to ensure it covers the full video duration
        # - Apply volume scaling
        # - Apply fade in and fade out
        # - amix with voice track: voice (input 0) full volume, music (input 1) as background
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
                "-i",        output_path,         # input 0: video with voice
                "-stream_loop", "-1",             # loop music if shorter than video
                "-i",        track_path,           # input 1: background music
                "-filter_complex", music_filter,
                "-map",      "0:v",               # keep original video stream
                "-map",      "[aout]",            # use mixed audio output
                "-c:v",      "copy",              # no re-encode of video
                "-c:a",      "aac",
                "-b:a",      "192k",
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
            print(f"⚠️ [MUSIC] Mixed file too small or missing. Skipping.")
            if os.path.exists(temp_path):
                os.remove(temp_path)
            return False

        # Replace original output with mixed version
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
    mood           : emotional register — controls watermark preset + music folder
                     ("neutral"|"wonder"|"excitement"|"horror"|"warm")
    caption_style  : preset key from caption_style_presets in settings.yaml
                     If None or unrecognised, falls back to base subtitle_style
    subtitle_color : deprecated alias for glow_color — accepted for back-compat
    """
    print("⚙️ [RENDERER] Executing Master Render Engine...")
    print(f"   Mood: {mood} | Caption Style: {caption_style or 'default'}")

    # Back-compat: if caller passed the old subtitle_color kwarg, honour it
    if glow_color is None and subtitle_color is not None:
        glow_color = subtitle_color

    if not _check_disk_space():
        return False, 0.0, 0

    srt_path    = audio_path.replace(".wav", ".srt")
    ass_path    = audio_path.replace(".wav", ".ass")
    temp_concat = "concat_list.txt"
    temp_merged = "temp_merged_no_subs.mp4"

    resolved_glow = _resolve_glow_color(glow_color)

    # Load caption style — dynamic per mood/LLM selection
    style = get_style_config(caption_style)

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

    # ── Watermark: mood-driven dynamic positioning ────────────────────────────
    # Selects position/opacity preset based on content mood.
    # A 30% random override is applied to break visual fingerprint.
    safe_watermark  = re.sub(r"[^a-zA-Z0-9\s]", "", watermark_text).strip().upper() or "TOPATO"
    wm              = _select_watermark_preset(mood)
    watermark_filter = (
        f",drawtext=fontfile='{safe_font}':text='{safe_watermark}':"
        f"fontcolor=0xC8C8C8@{wm['opacity']}:"
        f"fontsize={wm['fontsize']}:x={wm['x']}:y={wm['y']}"
    )
    print(f"   Watermark preset: {wm['preset_name']} | opacity: {wm['opacity']}")

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

    # ── Background music mix (post-render, in-place) ──────────────────────────
    # Skipped silently if: no music tracks cached, no PIXABAY_API_KEY, any error.
    # This runs AFTER the video is confirmed valid so a music failure never
    # prevents a successful video from being produced.
    _mix_background_music(output_path, mood)

    # Re-check final size after potential music mix
    final_size_mb = os.path.getsize(output_path) / (1024 * 1024)
    return True, total_dur, final_size_mb
