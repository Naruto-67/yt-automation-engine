"""
scripts/render_video.py — Stock Video Rendering Engine & Kinetic Subtitle Generator (v2.0)
Implements a robust 3-stage segmented pipeline:
  Stage 1: Pre-process and normalize each clip segment individually to standard specs.
  Stage 2: Lossless stream-copy concat via FFmpeg concat demuxer (-f concat -c copy).
  Stage 3: Composite pass burning word-by-word highlighted captions, watermark, and audio mux.
Eliminates FFmpeg filter complex buffer deadlocks and accelerates renders to ~20-30 seconds.
"""

import os
import sys
import glob
import json
import shutil
import tempfile
import subprocess
import re
import time
try:
    import requests
except ImportError:
    import urllib.request
    import urllib.parse
    import urllib.error

    class _RequestsShim:
        class Response:
            def __init__(self, data: bytes, status_code: int):
                self._data = data
                self.status_code = status_code
            def json(self):
                return json.loads(self._data.decode("utf-8"))
            def raise_for_status(self):
                if 400 <= self.status_code < 600:
                    raise urllib.error.HTTPError("", self.status_code, "HTTP Error", None, None)
            @property
            def content(self):
                return self._data
            def iter_content(self, chunk_size=65536):
                for i in range(0, len(self._data), chunk_size):
                    yield self._data[i:i + chunk_size]

        def get(self, url, headers=None, params=None, timeout=10, stream=False):
            if params:
                qs = urllib.parse.urlencode(params)
                url = f"{url}?{qs}" if "?" not in url else f"{url}&{qs}"
            req = urllib.request.Request(url, headers=headers or {"User-Agent": "Mozilla/5.0"})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return self.Response(resp.read(), resp.status)
            except urllib.error.HTTPError as e:
                return self.Response(b"", e.code)

    requests = _RequestsShim()

from typing import List, Dict, Any, Optional

from engine.logger import StageTimer, PikaStage, logger
from engine.managers.error_manager import ErrorManager
from engine.models import SpecOutput, ClipsManifest, WordTimestamp
from engine.managers.music_manager import MusicManager


def find_ffmpeg_bin() -> str:
    """Finds available FFmpeg binary (favoring environment or PATH)."""
    env_bin = os.environ.get("FFMPEG_BINARY")
    if env_bin and os.path.exists(env_bin):
        return env_bin
    try:
        import shutil
        sys_bin = shutil.which("ffmpeg")
        if sys_bin:
            return sys_bin
    except Exception:
        pass
    return "ffmpeg"


def check_filter_supported(filter_name: str) -> bool:
    """Checks whether a specific FFmpeg filter is supported by the installed binary."""
    try:
        res = subprocess.run(["ffmpeg", "-filters"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
        return bool(re.search(rf"\b{filter_name}\b", res.stdout))
    except Exception:
        return False



def download_cinematic_font(preferred_path: Optional[str] = "assets/fonts/ZY-Resolve.ttf") -> str:
    """
    Locates the primary cinematic font (ZY Resolve) or downloads Anton fallback.
    Checks:
      1. Local repository assets (preferred_path, e.g. assets/fonts/ZY-Resolve.ttf)
      2. Local CapCut effect cache for ZY Resolve
      3. output/fonts/ directory
      4. Dynamic download of Anton-Regular.ttf from Google Fonts mirror
      5. System font fallback ("Arial")
    """
    if preferred_path and os.path.exists(preferred_path) and os.path.getsize(preferred_path) > 1000:
        return preferred_path

    # Check CapCut local effect cache
    try:
        user_home = os.path.expanduser("~")
        capcut_cache = os.path.join(user_home, "AppData", "Local", "CapCut", "User Data", "Cache")
        if os.path.exists(capcut_cache):
            for root, _, files in os.walk(capcut_cache):
                for file in files:
                    if file.lower() in ("zy resolve.ttf", "zy-resolve.ttf"):
                        candidate = os.path.join(root, file)
                        if os.path.getsize(candidate) > 1000:
                            return candidate
    except Exception:
        pass

    font_dir = os.path.join("output", "fonts")
    os.makedirs(font_dir, exist_ok=True)
    font_path = os.path.join(font_dir, "Anton-Regular.ttf")
    if os.path.exists(font_path) and os.path.getsize(font_path) > 20000:
        return font_path

    mirrors = [
        "https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf",
        "https://fonts.gstatic.com/s/anton/v25/1Ptgg87LROyAm3K.ttf",
        "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/anton/Anton-Regular.ttf",
    ]
    for url in mirrors:
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200 and len(r.content) > 20000:
                with open(font_path, "wb") as f:
                    f.write(r.content)
                print(f"✅ [RENDERER] Anton font downloaded to {font_path}", flush=True)
                return font_path
        except Exception:
            pass

    print("⚠️ [RENDERER] Font download failed. Using system sans-serif fallback.", flush=True)
    return "Arial"


def generate_ass_subtitles(
    scenes: List[Any],
    output_ass_path: str,
    width: int = 1080,
    height: int = 1920,
    font_name: str = "ZY Resolve",
    font_size: int = 88,
    active_color: str = "&H0000E6FF",   # Lemon Yellow highlight (#FFE600 in BGR)
    inactive_color: str = "&H00FFFFFF", # Crisp white
    outline_color: str = "&H00000000",  # Solid Black
    outline_width: int = 7,
    shadow_depth: int = 5,
    shadow_blur: int = 3,
    shadow_color: str = "&H33000000",   # 80% opacity black
    chunk_size: int = 2,
    uppercase: bool = False,
    margin_v: Optional[int] = None,
    master_word_timestamps: Optional[List[WordTimestamp]] = None,
) -> None:
    """
    Builds a word-by-word micro-chunked ASS subtitle file.
    Only 1-2 words on screen at a time for shorts (with orphan absorption), or conversational phrasing for long-form.
    Uses continuous master timeline when available to eliminate boundary slicing jitter.
    """
    if margin_v is None:
        margin_v = int(height * 0.44) if height > width else int(height * 0.12)

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},{inactive_color},&H000000FF,{outline_color},{shadow_color},-1,0,0,0,100,100,0,0,1,{outline_width},{shadow_depth},2,40,40,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []

    def format_ts(sec: float) -> str:
        sec = max(0.0, float(sec))
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        cs = int(round((sec - int(sec)) * 100))
        if cs >= 100:
            cs = 99
        return f"{h:01d}:{m:02d}:{s:02d}.{cs:02d}"

    # 1. Determine words per scene (guaranteeing no cross-scene word bleeding)
    has_scene_words = any(bool(getattr(s, "word_timestamps", None)) for s in scenes)
    if has_scene_words:
        scene_word_groups = [list(getattr(s, "word_timestamps", []) or []) for s in scenes]
    elif master_word_timestamps and len(scenes) > 0:
        from engine.managers.caption_aligner import CaptionAligner
        raw_scene_dicts = [{"spoken_text": s.spoken_text} for s in scenes]
        scene_word_groups = CaptionAligner.slice_words_by_scenes(master_word_timestamps, raw_scene_dicts)
    else:
        scene_word_groups = []

    total_words_found = sum(len(grp) for grp in scene_word_groups)

    if total_words_found == 0:
        # Fallback if no word timestamps captured: create scene-level subtitles
        current_time = 0.0
        for scene in scenes:
            sc_dur = scene.duration_seconds if (scene.duration_seconds and scene.duration_seconds > 0.0) else 5.0
            start_ts = format_ts(current_time)
            end_ts = format_ts(current_time + sc_dur)
            raw_text = scene.spoken_text.upper() if uppercase else scene.spoken_text
            text = raw_text.replace("\n", " ")
            if shadow_blur > 0:
                text = f"{{\\blur{shadow_blur}}}{text}"
            events.append(f"Dialogue: 0,{start_ts},{end_ts},Default,,0,0,0,,{text}")
            current_time += sc_dur
    else:
        step_size = max(1, int(chunk_size))

        # Chunk strictly per scene / per thought — eliminating cross-scene merging
        for s_idx, scene in enumerate(scenes):
            s_words = scene_word_groups[s_idx] if s_idx < len(scene_word_groups) else []
            if not s_words:
                continue

            scene_chunks = [s_words[j:j + step_size] for j in range(0, len(s_words), step_size)]

            # Orphan absorption: if trailing chunk is a lone word, merge into preceding chunk
            if step_size >= 2 and len(scene_chunks) > 1 and len(scene_chunks[-1]) == 1:
                scene_chunks[-2].extend(scene_chunks.pop())

            for c_idx, chunk in enumerate(scene_chunks):
                is_last_chunk_in_scene = (c_idx == len(scene_chunks) - 1)

                for active_idx, target_word in enumerate(chunk):
                    start_sec = target_word.start
                    # Guard against identical start timestamps within the same chunk
                    if active_idx > 0 and start_sec <= chunk[active_idx - 1].start:
                        start_sec = round(chunk[active_idx - 1].start + 0.12, 3)

                    if active_idx + 1 < len(chunk):
                        # Advance to next word inside the same displayed chunk
                        next_word_start = chunk[active_idx + 1].start
                        if next_word_start > start_sec:
                            end_sec = next_word_start
                        else:
                            end_sec = round(start_sec + max(0.12, (chunk[active_idx + 1].end - start_sec) / 2.0), 3)
                    elif not is_last_chunk_in_scene:
                        # Advance to next chunk inside the SAME sentence/thought.
                        # Bridge the full gap regardless of pause length so the
                        # caption stays on-screen through natural speech pauses
                        # (e.g. a 0.7 s breath between "poisonous?" and "Or").
                        next_chunk_start = scene_chunks[c_idx + 1][0].start
                        if next_chunk_start > start_sec:
                            end_sec = next_chunk_start
                        else:
                            end_sec = target_word.end + 0.06
                    else:
                        # FINAL CHUNK OF THIS THOUGHT: Cut off immediately when speech ends!
                        # Zero captions hang on screen during the inter-thought silence gap!
                        end_sec = target_word.end + 0.05

                    if end_sec <= start_sec:
                        end_sec = start_sec + 0.20

                    w_start = format_ts(start_sec)
                    w_end = format_ts(end_sec)

                    formatted_words = []
                    for idx, w in enumerate(chunk):
                        raw_w = w.word.strip()
                        # Strip leading and trailing punctuation while preserving internal apostrophes
                        clean_w = re.sub(r"^[^\w]+|[^\w]+$", "", raw_w)
                        word_str = (clean_w or raw_w).upper() if uppercase else (clean_w or raw_w)
                        if idx == active_idx:
                            formatted_words.append(f"{{\\c{active_color}}}{word_str}{{\\c{inactive_color}}}")
                        else:
                            formatted_words.append(word_str)

                    chunk_text = " ".join(formatted_words)
                    if shadow_blur > 0:
                        chunk_text = f"{{\\blur{shadow_blur}}}{chunk_text}"
                    events.append(f"Dialogue: 0,{w_start},{w_end},Default,,0,0,0,,{chunk_text}")

    os.makedirs(os.path.dirname(output_ass_path) or ".", exist_ok=True)
    with open(output_ass_path, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(events) + "\n")


def download_clip(url: str, output_path: str, provider: str, video_id: str) -> str:
    """Downloads an MP4 clip, copying local vault clips directly or refreshing CDN links if HTTP 403 occurs."""
    if os.path.exists(output_path) and os.path.getsize(output_path) > 100000:
        return output_path

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    # Local fallback clip handling: direct file copy without HTTP network call
    if provider == "local" or os.path.isfile(url):
        import shutil
        if os.path.abspath(url) != os.path.abspath(output_path):
            shutil.copy2(url, output_path)
        return output_path

    r = requests.get(url, stream=True, timeout=15)


    if r.status_code == 403:
        print(f"⚠️ [DOWNLOAD] Link expired (403). Refreshing {provider} video {video_id}...", flush=True)
        from engine.managers.stock_video_manager import StockVideoManager
        fresh_url = StockVideoManager().refresh_download_url(provider, video_id)
        if fresh_url:
            r = requests.get(fresh_url, stream=True, timeout=15)

    r.raise_for_status()
    with open(output_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=65536):
            f.write(chunk)

    if os.path.getsize(output_path) < 1000:
        raise ValueError(f"Downloaded clip {output_path} is unexpectedly small ({os.path.getsize(output_path)} bytes).")

    return output_path


def render_video_ffmpeg(
    spec: SpecOutput,
    clips_manifest: ClipsManifest,
    output_video_path: str,
    channel_cfg: Dict[str, Any],
    settings_cfg: Dict[str, Any]
) -> None:
    """
    Assembles stock videos using a robust 3-stage segmented pipeline:
      1. Pre-render individual normalized segments (1080x1920 / 1920x1080 @ 30fps).
      2. Instant lossless merge via FFmpeg concat demuxer (-c copy).
      3. Composite pass adding audio track, dynamic captions, and watermark.
    """
    channel_caption_cfg = channel_cfg.get("caption_settings", {})
    caption_cfg = {**settings_cfg.get("captions", {}), **channel_caption_cfg}
    cfg_font_name = caption_cfg.get("font_name", "ZY Resolve")
    preferred_font_path = caption_cfg.get("font_file", "assets/fonts/ZY-Resolve.ttf")
    try:
        font_file = download_cinematic_font(preferred_path=preferred_font_path)
    except TypeError:
        font_file = download_cinematic_font()
    if font_file and "zy" in os.path.basename(font_file).lower():
        font_name = cfg_font_name
    elif font_file and "anton" in os.path.basename(font_file).lower():
        font_name = "Anton"
    elif font_file and os.path.exists(font_file):
        font_name = cfg_font_name
    elif font_file == "Arial":
        font_name = "Arial"
    else:
        font_name = cfg_font_name if os.path.exists("assets/fonts/ZY-Resolve.ttf") else "sans-serif"

    print(f"🎬 [RENDERER] Caption typography: '{font_name}' active (source: {font_file})", flush=True)

    is_short = spec.video_type == "short"
    target_w, target_h = (1080, 1920) if is_short else (1920, 1080)
    fps = 30  # Standard 30fps for stable, fast cloud rendering

    # Preset selection (default 'fast' for high quality without excessive encode time)
    preset = settings_cfg.get("video_profiles", {}).get(spec.video_type, {}).get("preset", "fast")

    # 1. Download Clips
    local_clips = []
    for idx, clip_item in enumerate(clips_manifest.clips):
        clip_dest = os.path.join("output", "raw_clips", f"clip_{idx + 1}.mp4")
        print(f"📥 [RENDERER] Downloading clip {idx + 1}/{len(clips_manifest.clips)} ({clip_item.provider})...", flush=True)
        downloaded = download_clip(clip_item.download_url, clip_dest, clip_item.provider, clip_item.video_id)
        local_clips.append(downloaded)

    if not local_clips:
        raise ValueError("No video clips available in clips manifest to render.")

    # 2. Audio & Target Duration Resolution
    narration_path = spec.audio_path or os.path.join("output", "narration.mp3")
    if not os.path.exists(narration_path) and os.path.exists(os.path.join("output", "narration.wav")):
        narration_path = os.path.join("output", "narration.wav")

    total_duration = spec.total_duration_seconds or sum(s.duration_seconds for s in spec.scenes)
    audio_duration = 0.0
    if os.path.exists(narration_path):
        try:
            if narration_path.endswith(".wav"):
                import wave
                with wave.open(narration_path, "rb") as wf:
                    frames = wf.getnframes()
                    rate = wf.getframerate()
                    if rate > 0:
                        audio_duration = round(frames / float(rate), 2)
            else:
                from mutagen.mp3 import MP3
                audio = MP3(narration_path)
                if audio.info and audio.info.length > 0:
                    audio_duration = round(float(audio.info.length), 2)
        except Exception:
            pass

    if audio_duration > 0.0:
        total_duration = audio_duration
    elif not total_duration or total_duration <= 0.0:
        total_duration = 30.0

    print(f"⏱️ [RENDERER] Target video duration established: {total_duration:.1f}s", flush=True)

    # 3. Build Subtitles (ASS)
    ass_path = os.path.join("output", "captions.ass")
    if is_short:
        sub_font_size = caption_cfg.get("font_size", 88)
        sub_chunk_size = caption_cfg.get("max_words_per_chunk", 2)
        sub_outline_width = caption_cfg.get("outline_width", 7)
        sub_uppercase = caption_cfg.get("uppercase", True)
        sub_margin_v = int(target_h * 0.44)
    else:
        # Long-form 16:9 documentary styling: lower-third, elegant sizing, conversational flow
        sub_font_size = caption_cfg.get("font_size_long", 44)
        sub_chunk_size = caption_cfg.get("max_words_per_chunk_long", 6)
        sub_outline_width = caption_cfg.get("outline_width_long", 3)
        sub_uppercase = caption_cfg.get("uppercase_long", False)
        sub_margin_v = int(target_h * 0.12)

    generate_ass_subtitles(
        scenes=spec.scenes,
        output_ass_path=ass_path,
        width=target_w,
        height=target_h,
        font_name=font_name,
        font_size=sub_font_size,
        active_color=caption_cfg.get("active_color", "&H0000E6FF"),
        inactive_color=caption_cfg.get("inactive_color", "&H00FFFFFF"),
        outline_color=caption_cfg.get("outline_color", "&H00000000"),
        outline_width=sub_outline_width,
        shadow_depth=caption_cfg.get("shadow_depth", 5),
        shadow_blur=caption_cfg.get("shadow_blur", 3),
        shadow_color=caption_cfg.get("shadow_color", "&H33000000"),
        chunk_size=sub_chunk_size,
        uppercase=sub_uppercase,
        margin_v=sub_margin_v,
        master_word_timestamps=getattr(spec, "word_timestamps", None) or None,
    )

    # 4. Prepare Segment Timeline & Workspace
    temp_dir = os.path.join("output", ".compose_tmp")
    shutil.rmtree(temp_dir, ignore_errors=True)
    os.makedirs(temp_dir, exist_ok=True)

    num_scenes = len(spec.scenes) if spec.scenes else 1
    scene_durations = []
    for s in spec.scenes:
        d = s.duration_seconds if (s.duration_seconds and s.duration_seconds > 0) else (total_duration / num_scenes)
        scene_durations.append(max(1.0, float(d)))

    if not scene_durations:
        scene_durations = [total_duration]

    current_sum = sum(scene_durations)
    if total_duration > current_sum:
        # Give remaining audio duration to the final scene to avoid audio cut-off
        scene_durations[-1] = round(scene_durations[-1] + (total_duration - current_sum), 2)
    elif current_sum > total_duration:
        total_duration = round(current_sum, 2)

    # ─── STAGE 1: NORMALIZE INDIVIDUAL SEGMENTS ────────────────────────────────
    print(f"🎞️ [RENDERER - STEP 1/3] Normalizing {len(scene_durations)} segment(s) ({target_w}x{target_h} @ {fps}fps, preset: {preset})...", flush=True)
    segment_files = []

    for idx, seg_dur in enumerate(scene_durations):
        clip_path = local_clips[idx % len(local_clips)]
        seg_output = os.path.join(temp_dir, f"segment_{idx:03d}.mp4")
        segment_files.append(seg_output)

        seg_start = time.time()
        vf_filter = (
            f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
            f"crop={target_w}:{target_h},"
            f"setsar=1,"
            f"fps={fps},"
            f"setpts=N/(FRAME_RATE*TB),"
            f"format=yuv420p"
        )

        seg_cmd = [
            "ffmpeg", "-y",
            "-stream_loop", "-1",
            "-fflags", "+genpts",
            "-i", clip_path,
            "-t", str(seg_dur),
            "-vf", vf_filter,
            "-c:v", "libx264",
            "-preset", preset,
            "-crf", "22",
            "-pix_fmt", "yuv420p",
            "-an",
            seg_output
        ]

        res = subprocess.run(seg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=120)
        if res.returncode != 0:
            err_tail = "\n".join(res.stderr.strip().splitlines()[-15:])
            raise RuntimeError(f"FFmpeg failed to normalize segment {idx + 1} from '{clip_path}':\n{err_tail}")

        seg_elapsed = round(time.time() - seg_start, 2)
        print(f"  ✅ Segment {idx + 1}/{len(scene_durations)} rendered ({seg_dur:.1f}s) in {seg_elapsed}s", flush=True)

    # ─── STAGE 2: STREAM-COPY CONCAT DEMUXER ──────────────────────────────────
    concat_list_file = os.path.join(temp_dir, "concat_list.txt")
    with open(concat_list_file, "w", encoding="utf-8") as f:
        for seg_f in segment_files:
            clean_path = os.path.abspath(seg_f).replace("\\", "/").replace("'", "'\\''")
            f.write(f"file '{clean_path}'\n")

    concat_base = os.path.join(temp_dir, "concat_base.mp4")
    print(f"🔗 [RENDERER - STEP 2/3] Merging segments via stream-copy demuxer...", flush=True)
    concat_start = time.time()

    concat_cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_list_file,
        "-c", "copy",
        concat_base
    ]

    res = subprocess.run(concat_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=60)
    if res.returncode != 0:
        err_tail = "\n".join(res.stderr.strip().splitlines()[-15:])
        raise RuntimeError(f"FFmpeg concat demuxer failed:\n{err_tail}")

    concat_elapsed = round(time.time() - concat_start, 2)
    print(f"  ✅ Concat completed in {concat_elapsed}s", flush=True)

    # ─── STAGE 3: COMPOSITE AUDIO, SUBTITLES & WATERMARK ──────────────────────
    print(f"🎨 [RENDERER - STEP 3/3] Compositing audio, subtitles & watermark (target: {total_duration:.1f}s)...", flush=True)
    comp_start = time.time()

    vf_filters = []
    # Watermark overlay
    if check_filter_supported("drawtext"):
        branding = channel_cfg.get("branding", {})
        watermark_text = branding.get("watermark_text", channel_cfg.get("handle", "@metopato"))
        opacity = branding.get("opacity", 0.35)
        font_size = branding.get("font_size", 26)
        position = branding.get("position", "lower_center")
        clean_wm = watermark_text.replace(":", "\\:").replace("'", "\\'")

        if position == "lower_center":
            if is_short:
                pos_x = "(w-text_w)/2"
                pos_y = "h*0.62"
            else:
                pos_x = "w-text_w-80"
                pos_y = "h-text_h-80"
        elif position == "top_right":
            pos_x = "w-text_w-80"
            pos_y = "80" if not is_short else "180"
        elif position == "top_left":
            pos_x = "80"
            pos_y = "80" if not is_short else "180"
        elif position == "bottom_right":
            pos_x = "w-text_w-80"
            pos_y = "h-text_h-80" if not is_short else "h-text_h-120"
        else:
            pos_x = "(w-text_w)/2" if is_short else "w-text_w-80"
            pos_y = "h*0.62" if is_short else "h-text_h-80"

        vf_filters.append(
            f"drawtext=text='{clean_wm}':fontcolor=white@{opacity}:fontsize={font_size}:x={pos_x}:y={pos_y}"
        )
    else:
        print("⚠️ [RENDERER] FFmpeg build lacks 'drawtext' filter — skipping watermark overlay.", flush=True)

    # Burnt subtitles
    if check_filter_supported("subtitles") and os.path.exists(ass_path):
        clean_ass = ass_path.replace("\\", "/")
        font_dir = ""
        if font_file and font_file != "Arial" and os.path.exists(font_file):
            font_dir = os.path.dirname(os.path.abspath(font_file)).replace("\\", "/")
        elif os.path.isdir("assets/fonts"):
            font_dir = os.path.abspath("assets/fonts").replace("\\", "/")
        fontsdir_arg = f":fontsdir='{font_dir}'" if font_dir else ""
        vf_filters.append(f"subtitles='{clean_ass}'{fontsdir_arg}")
    else:
        if not check_filter_supported("subtitles"):
            print("⚠️ [RENDERER] FFmpeg build lacks 'subtitles' filter — skipping burnt subtitles.", flush=True)
        elif not os.path.exists(ass_path):
            print(f"⚠️ [RENDERER] Subtitle file '{ass_path}' not found — skipping burnt subtitles.", flush=True)

    vf_arg = ["-vf", ",".join(vf_filters)] if vf_filters else []

    # Audio mastering and background Lo-Fi music mixing
    audio_cfg = settings_cfg.get("audio_mastering", {})
    target_lufs = audio_cfg.get("target_lufs", -14.0)
    target_lra = audio_cfg.get("loudness_range", 7.0)
    target_tp = audio_cfg.get("true_peak", -1.5)
    voice_gain = audio_cfg.get("voice_gain", 1.5)

    music_cfg = settings_cfg.get("music", {})
    bg_vol = music_cfg.get("volume", 0.08)

    bg_music_path = MusicManager.get_or_create_lofi_track(duration=total_duration, mood="lofi_chill")

    audio_inputs = []
    audio_mapping = []

    if os.path.exists(narration_path) and os.path.getsize(narration_path) > 1000:
        audio_inputs = ["-i", narration_path]
        if bg_music_path and os.path.exists(bg_music_path) and os.path.getsize(bg_music_path) > 4096:
            audio_inputs.extend(["-stream_loop", "-1", "-i", bg_music_path])
            filter_complex = (
                f"[1:a]loudnorm=I={target_lufs}:LRA={target_lra}:TP={target_tp}:linear=true,volume={voice_gain}[voice];"
                f"[2:a]volume={bg_vol}[bg];"
                f"[voice][bg]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[aout]"
            )
            audio_mapping = [
                "-filter_complex", filter_complex,
                "-map", "0:v",
                "-map", "[aout]",
                "-c:a", "aac",
                "-b:a", "192k",
                "-ar", "44100",
                "-shortest"
            ]
            print(f"🎵 [RENDERER] Mixing mastered narration (target {target_lufs} LUFS) with Lo-Fi background music ({os.path.basename(bg_music_path)} @ vol={bg_vol})...", flush=True)
        else:
            filter_complex = f"[1:a]loudnorm=I={target_lufs}:LRA={target_lra}:TP={target_tp}:linear=true,volume={voice_gain}[aout]"
            audio_mapping = [
                "-filter_complex", filter_complex,
                "-map", "0:v",
                "-map", "[aout]",
                "-c:a", "aac",
                "-b:a", "192k",
                "-ar", "44100",
                "-shortest"
            ]
            print(f"🎙️ [RENDERER] Mastering narration to broadcast loudness ({target_lufs} LUFS)...", flush=True)
    else:
        print(f"⚠️ [RENDERER] Narration file '{narration_path}' not found — rendering without audio.", flush=True)
        audio_mapping = ["-map", "0:v"]

    os.makedirs(os.path.dirname(output_video_path) or ".", exist_ok=True)

    comp_cmd = [
        "ffmpeg", "-y",
        "-i", concat_base,
        *audio_inputs,
        *vf_arg,
        *audio_mapping,
        "-c:v", "libx264",
        "-preset", preset,
        "-crf", "22",
        "-pix_fmt", "yuv420p",
        "-t", str(total_duration),
        output_video_path
    ]

    res = subprocess.run(
        comp_cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        timeout=300
    )

    if res.returncode != 0:
        err_tail = "\n".join(res.stderr.strip().splitlines()[-30:])
        raise RuntimeError(f"FFmpeg composite pass failed with return code {res.returncode}:\n{err_tail}")

    comp_elapsed = round(time.time() - comp_start, 2)
    file_size_mb = os.path.getsize(output_video_path) / (1024 * 1024) if os.path.exists(output_video_path) else 0.0
    print(f"🎬 [RENDERER] Successfully rendered '{output_video_path}' ({file_size_mb:.1f} MB in {comp_elapsed}s)", flush=True)

    # Clean up temporary segments directory
    shutil.rmtree(temp_dir, ignore_errors=True)


def run_editor_stage() -> None:
    """Executes Stage 3: ✂️ Video Editor."""
    with open(os.path.join("output", "spec.json"), "r", encoding="utf-8") as f:
        spec = SpecOutput.model_validate_json(f.read())

    with open(os.path.join("output", "clips_manifest.json"), "r", encoding="utf-8") as f:
        clips_manifest = ClipsManifest.model_validate_json(f.read())

    import yaml
    with open("config/channel_config.yaml", "r", encoding="utf-8") as f:
        full_cfg = yaml.safe_load(f) or {}
        channel_cfg = full_cfg.get("channel", {})
        if "caption_settings" in full_cfg:
            channel_cfg["caption_settings"] = full_cfg["caption_settings"]
        if "branding" in full_cfg:
            channel_cfg["branding"] = full_cfg["branding"]

    with open("config/settings.yaml", "r", encoding="utf-8") as f:
        settings_cfg = yaml.safe_load(f)

    output_render = os.path.join("output", "final_render.mp4")

    with StageTimer(PikaStage.EDITOR, topic=spec.topic):
        render_video_ffmpeg(
            spec=spec,
            clips_manifest=clips_manifest,
            output_video_path=output_render,
            channel_cfg=channel_cfg,
            settings_cfg=settings_cfg
        )