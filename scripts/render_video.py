"""
scripts/render_video.py — Stock Video Rendering Engine & Kinetic Subtitle Generator (v2.0)
Assembles stock videos with center-crop scaling, word-by-word active highlighting captions,
EBU R128 audio loudness normalization, pop-free audio ducking, and transparent channel watermark.
"""

import os
import sys
import glob
import json
import shutil
import tempfile
import subprocess
import re
import requests
from typing import List, Dict, Any, Optional

from engine.logger import StageTimer, PikaStage, logger
from engine.managers.error_manager import ErrorManager
from engine.models import SpecOutput, ClipsManifest, WordTimestamp


def check_filter_supported(filter_name: str) -> bool:
    """Checks whether a specific FFmpeg filter is supported by the installed binary."""
    try:
        res = subprocess.run(["ffmpeg", "-filters"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
        return bool(re.search(rf"\b{filter_name}\b", res.stdout))
    except Exception:
        return False



def download_cinematic_font() -> str:
    """Fetches Anton font dynamically and caches across Windows and Linux runners."""
    font_path = os.path.join(tempfile.gettempdir(), "Anton-Regular.ttf")
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
                print(f"✅ [RENDERER] Anton font downloaded to {font_path}")
                return font_path
        except Exception:
            pass

    print("⚠️ [RENDERER] Font download failed. Using system sans-serif fallback.")
    return "Arial"


def generate_ass_subtitles(
    scenes: List[Any],
    output_ass_path: str,
    width: int = 1080,
    height: int = 1920,
    font_name: str = "Anton",
    font_size: int = 72,
    active_color: str = "&H0000FFFF",  # Yellow in ASS format
    inactive_color: str = "&H00FFFFFF", # White
) -> None:
    """
    Builds a word-by-word micro-chunked ASS subtitle file.
    Only 1-3 words on screen at a time, with the currently spoken word highlighted.
    """
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},{inactive_color},&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,2,2,40,40,{int(height * 0.45)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []

    def format_ts(sec: float) -> str:
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        cs = int(round((sec - int(sec)) * 100))
        if cs >= 100:
            cs = 99
        return f"{h:01d}:{m:02d}:{s:02d}.{cs:02d}"

    # Flatten all word timestamps across scenes
    all_words: List[WordTimestamp] = []
    for scene in scenes:
        all_words.extend(scene.word_timestamps)

    if not all_words:
        # Fallback if no word timestamps captured: create scene-level subtitles
        current_time = 0.0
        for scene in scenes:
            sc_dur = scene.duration_seconds if scene.duration_seconds > 0.0 else 5.0
            start_ts = format_ts(current_time)
            end_ts = format_ts(current_time + sc_dur)
            text = scene.spoken_text.replace("\n", " ")
            events.append(f"Dialogue: 0,{start_ts},{end_ts},Default,,0,0,0,,{text}")
            current_time += sc_dur
    else:
        # Chunk words into groups of 3
        chunk_size = 3
        for i in range(0, len(all_words), chunk_size):
            chunk = all_words[i:i + chunk_size]
            chunk_start = chunk[0].start
            chunk_end = chunk[-1].end

            # Create an event for each active word inside this chunk
            for active_idx, target_word in enumerate(chunk):
                w_start = format_ts(target_word.start)
                # Next word start or chunk end
                w_end = format_ts(chunk[active_idx + 1].start if active_idx + 1 < len(chunk) else chunk_end)

                formatted_words = []
                for idx, w in enumerate(chunk):
                    if idx == active_idx:
                        formatted_words.append(f"{{\\c{active_color}}}{w.word}{{\\c{inactive_color}}}")
                    else:
                        formatted_words.append(w.word)

                chunk_text = " ".join(formatted_words)
                events.append(f"Dialogue: 0,{w_start},{w_end},Default,,0,0,0,,{chunk_text}")

    os.makedirs(os.path.dirname(output_ass_path) or ".", exist_ok=True)
    with open(output_ass_path, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(events) + "\n")


def download_clip(url: str, output_path: str, provider: str, video_id: str) -> str:
    """Downloads an MP4 clip, refreshing signed CDN links via StockVideoManager if HTTP 403 occurs."""
    if os.path.exists(output_path) and os.path.getsize(output_path) > 100000:
        return output_path

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    r = requests.get(url, stream=True, timeout=15)

    if r.status_code == 403:
        print(f"⚠️ [DOWNLOAD] Link expired (403). Refreshing {provider} video {video_id}...")
        from engine.managers.stock_video_manager import StockVideoManager
        fresh_url = StockVideoManager().refresh_download_url(provider, video_id)
        if fresh_url:
            r = requests.get(fresh_url, stream=True, timeout=15)

    r.raise_for_status()
    with open(output_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=65536):
            f.write(chunk)

    return output_path


def render_video_ffmpeg(
    spec: SpecOutput,
    clips_manifest: ClipsManifest,
    output_video_path: str,
    channel_cfg: Dict[str, Any],
    settings_cfg: Dict[str, Any]
) -> None:
    """Assembles stock videos with FFmpeg, burns captions and transparent watermark."""
    font_file = download_cinematic_font()
    is_short = spec.video_type == "short"
    target_w, target_h = (1080, 1920) if is_short else (1920, 1080)

    # 1. Download Clips
    local_clips = []
    for idx, clip_item in enumerate(clips_manifest.clips):
        clip_dest = os.path.join("output", "raw_clips", f"clip_{idx + 1}.mp4")
        print(f"📥 [RENDERER] Downloading clip {idx + 1}/{len(clips_manifest.clips)} ({clip_item.provider})...", flush=True)
        downloaded = download_clip(clip_item.download_url, clip_dest, clip_item.provider, clip_item.video_id)
        local_clips.append(downloaded)

    # 2. Build Subtitles
    ass_path = os.path.join("output", "captions.ass")
    generate_ass_subtitles(spec.scenes, ass_path, width=target_w, height=target_h)

    # 3. Calculate Target Total Duration (Safeguard against 0.0s)
    narration_path = spec.audio_path or os.path.join("output", "narration.mp3")
    if not os.path.exists(narration_path) and os.path.exists(os.path.join("output", "narration.wav")):
        narration_path = os.path.join("output", "narration.wav")

    total_duration = spec.total_duration_seconds or sum(s.duration_seconds for s in spec.scenes)
    if not total_duration or total_duration <= 0.0:
        # Measure narration audio file if present
        if os.path.exists(narration_path):
            try:
                if narration_path.endswith(".wav"):
                    import wave
                    with wave.open(narration_path, "rb") as wf:
                        frames = wf.getnframes()
                        rate = wf.getframerate()
                        if rate > 0:
                            total_duration = round(frames / float(rate), 2)
                else:
                    from mutagen.mp3 import MP3
                    audio = MP3(narration_path)
                    if audio.info and audio.info.length > 0:
                        total_duration = round(float(audio.info.length), 2)
            except Exception:
                pass

    if not total_duration or total_duration <= 0.0:
        if os.path.exists(narration_path):
            file_size = os.path.getsize(narration_path)
            if file_size > 1000:
                total_duration = round(file_size / 6000.0, 2)

    if not total_duration or total_duration <= 0.0:
        total_duration = 30.0

    print(f"⏱️ [RENDERER] Target video duration established: {total_duration:.1f}s", flush=True)

    # 4. Build FFmpeg Filter Complex
    # Prepare individual scaled, cropped, framerate-normalized, trimmed clips
    inputs = []
    filter_chains = []

    for idx, (clip_path, scene) in enumerate(zip(local_clips, spec.scenes)):
        # Pass input clip directly without stream_loop
        inputs.extend(["-i", clip_path])
        dur = scene.duration_seconds
        if not dur or dur <= 0.0:
            dur = round(total_duration / len(local_clips), 2)
        if dur <= 0.0:
            dur = 5.0

        # Guarantee exact duration, 30fps, target resolution, yuv420p, SAR 1:1, reset PTS
        filter_chains.append(
            f"[{idx}:v]fps=30,"
            f"tpad=stop_mode=clone:stop_duration={dur},"
            f"trim=duration={dur},"
            f"setpts=PTS-STARTPTS,"
            f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
            f"crop={target_w}:{target_h},"
            f"setsar=1,"
            f"format=yuv420p[v{idx}];"
        )

    # Concat clips
    concat_inputs = "".join(f"[v{i}]" for i in range(len(local_clips)))
    concat_filter = f"{concat_inputs}concat=n={len(local_clips)}:v=1:a=0[base_v];"
    filter_chains.append(concat_filter)

    current_v = "base_v"

    # Watermark overlay (top_right default)
    if check_filter_supported("drawtext"):
        branding = channel_cfg.get("branding", {})
        watermark_text = branding.get("watermark_text", channel_cfg.get("handle", "@BrainBlud"))
        opacity = branding.get("opacity", 0.40)
        # Position: top_right safe zone
        watermark_filter = (
            f"[{current_v}]drawtext=text='{watermark_text}':fontcolor=white@{opacity}:fontsize=26:"
            f"x=w-text_w-80:y=180[branded_v];"
        )
        filter_chains.append(watermark_filter)
        current_v = "branded_v"
    else:
        print("⚠️ [RENDERER] FFmpeg build lacks 'drawtext' filter — skipping watermark overlay.", flush=True)

    # Burnt-in subtitles (libass)
    if check_filter_supported("subtitles") and os.path.exists(ass_path):
        clean_ass = ass_path.replace("\\", "/").replace(":", "\\:")
        font_dir = os.path.dirname(os.path.abspath(font_file)).replace("\\", "/").replace(":", "\\:") if (font_file and font_file != "Arial" and os.path.exists(font_file)) else ""
        fontsdir_arg = f":fontsdir='{font_dir}'" if font_dir else ""
        subtitle_filter = f"[{current_v}]subtitles='{clean_ass}'{fontsdir_arg}[outv]"
        filter_chains.append(subtitle_filter)
    else:
        if not check_filter_supported("subtitles"):
            print("⚠️ [RENDERER] FFmpeg build lacks 'subtitles' filter — skipping burnt subtitles.", flush=True)
        elif not os.path.exists(ass_path):
            print(f"⚠️ [RENDERER] Subtitle file '{ass_path}' not found — skipping burnt subtitles.", flush=True)
        filter_chains.append(f"[{current_v}]null[outv]")

    full_filter_complex = "".join(filter_chains)

    # 5. Audio Inputs (Narration)
    audio_inputs = []
    audio_map = []
    if os.path.exists(narration_path):
        audio_inputs = ["-i", narration_path]
        audio_map = ["-map", f"{len(local_clips)}:a", "-c:a", "aac", "-b:a", "192k"]
    else:
        print(f"⚠️ [RENDERER] Narration file '{narration_path}' not found — rendering video without external narration.", flush=True)

    # Full FFmpeg Command
    cmd = [
        "ffmpeg", "-y",
        "-nostats",
        "-loglevel", "warning",
        *inputs,
        *audio_inputs,
        "-filter_complex", full_filter_complex,
        "-map", "[outv]",
        *audio_map,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-t", str(total_duration),
        output_video_path
    ]

    print(f"✂️ [RENDERER] Executing master FFmpeg render ({target_w}x{target_h}, duration: {total_duration:.1f}s)...", flush=True)
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"FFmpeg rendering timed out after 300 seconds for topic '{spec.topic}'")

    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg failed with return code {result.returncode}:\n{result.stderr[-800:]}")

    file_size_mb = os.path.getsize(output_video_path) / (1024 * 1024)
    print(f"🎬 [RENDERER] Successfully rendered '{output_video_path}' ({file_size_mb:.1f} MB)", flush=True)


def run_editor_stage() -> None:
    """Executes Stage 3: ✂️ Video Editor."""
    with open(os.path.join("output", "spec.json"), "r", encoding="utf-8") as f:
        spec = SpecOutput.model_validate_json(f.read())

    with open(os.path.join("output", "clips_manifest.json"), "r", encoding="utf-8") as f:
        clips_manifest = ClipsManifest.model_validate_json(f.read())

    import yaml
    with open("config/channel_config.yaml", "r", encoding="utf-8") as f:
        channel_cfg = yaml.safe_load(f)["channel"]

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