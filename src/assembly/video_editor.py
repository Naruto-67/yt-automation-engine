import os
import json
import subprocess

FONT_PATH          = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
FONT_PATH_FALLBACK = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
FONT_SIZE          = 72
CAPTION_Y_FROM_BOTTOM = 200


def get_font_path():
    if os.path.exists(FONT_PATH):
        return FONT_PATH
    if os.path.exists(FONT_PATH_FALLBACK):
        return FONT_PATH_FALLBACK
    raise RuntimeError("No font found. Run: sudo apt-get install -y fonts-liberation")


def get_video_info(video_path):
    result = subprocess.run([
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams", video_path
    ], capture_output=True, text=True, check=True)
    info = json.loads(result.stdout)
    for s in info["streams"]:
        if s.get("codec_type") == "video":
            w = int(s["width"])
            h = int(s["height"])
            fps_parts = s.get("r_frame_rate", "30/1").split("/")
            fps = float(fps_parts[0]) / float(fps_parts[1])
            return w, h, fps
    raise RuntimeError("No video stream found.")


def get_audio_duration(audio_path):
    result = subprocess.run([
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams", audio_path
    ], capture_output=True, text=True, check=True)
    info = json.loads(result.stdout)
    for s in info.get("streams", []):
        if "duration" in s:
            return float(s["duration"])
    raise RuntimeError("Cannot determine audio duration.")


def esc(text):
    """Escape text for FFmpeg drawtext filter."""
    text = str(text)
    text = text.replace("\\", "\\\\")
    text = text.replace("'",  "\u2019")  # smart apostrophe — safest replacement
    text = text.replace(":",  "\\:")
    text = text.replace("%",  "\\%")
    return text


def build_drawtext_filters(chunks, font_path, video_h):
    """
    One drawtext per chunk.
    Full line, yellow, centered horizontally, fixed y position.
    No per-word logic, no measurement, nothing to break.
    """
    filters = []
    escaped_font = font_path.replace("\\", "/").replace(":", "\\:")
    y_pos = video_h - CAPTION_Y_FROM_BOTTOM - FONT_SIZE

    print(f"  Building filters for {len(chunks)} chunks...")

    for chunk in chunks:
        words = chunk.get("words", [])
        if not words:
            continue

        chunk_s   = f"{float(chunk['start']):.3f}"
        chunk_e   = f"{float(chunk['end']):.3f}"

        # Join all words in chunk into one line
        line = " ".join(w["text"].upper() for w in words)

        filters.append(
            f"drawtext=fontfile='{escaped_font}'"
            f":text='{esc(line)}'"
            f":fontsize={FONT_SIZE}"
            f":fontcolor=yellow"
            f":x=(w-text_w)/2"        # FFmpeg centers it — no manual measurement
            f":y={y_pos}"
            f":bordercolor=black:borderw=4"
            f":enable='between(t,{chunk_s},{chunk_e})'"
        )

    print(f"  Total filters: {len(filters)}")
    return filters


def assemble_video(video_filename, audio_filename, output_filename="master_final_video.mp4"):
    root_dir     = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
    video_path   = os.path.join(root_dir, video_filename)
    audio_path   = os.path.join(root_dir, audio_filename)
    timings_path = audio_path.replace(".mp3", "_timings.json")
    output_path  = os.path.join(root_dir, output_filename)
    looped_path  = os.path.join(root_dir, "temp_looped.mp4")

    # ── Sanity checks ────────────────────────────────────────────────────────
    for path, label in [
        (video_path,   "Background video"),
        (audio_path,   "Audio MP3"),
        (timings_path, "Timings JSON"),
    ]:
        if not os.path.exists(path):
            print(f"❌ MISSING: {label} → {path}")
            print("Root contents:", os.listdir(root_dir))
            return False

    font_path = get_font_path()
    print(f"✅ Font: {font_path}")

    with open(timings_path) as f:
        chunks = json.load(f)
    print(f"✅ Loaded {len(chunks)} caption chunks")

    if not chunks:
        print("❌ FATAL: Timings JSON is empty")
        return False

    audio_dur            = get_audio_duration(audio_path)
    video_w, video_h, fps = get_video_info(video_path)
    print(f"✅ Audio: {audio_dur:.2f}s | Video: {video_w}x{video_h} @ {fps:.1f}fps")

    # ── Step 1: Loop background ──────────────────────────────────────────────
    print("🔄 Looping background...")
    loop = subprocess.run([
        "ffmpeg", "-y",
        "-stream_loop", "-1",
        "-i", video_path,
        "-t", str(audio_dur + 0.5),
        "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", "-an",
        looped_path
    ], capture_output=True, text=True)

    if loop.returncode != 0:
        print("❌ Loop failed:")
        print(loop.stderr[-1500:])
        return False
    print("✅ Background looped")

    # ── Step 2: Build filters ────────────────────────────────────────────────
    filters = build_drawtext_filters(chunks, font_path, video_h)

    if not filters:
        print("❌ FATAL: No filters generated")
        return False

    filter_str         = ",".join(filters)
    filter_script_path = os.path.join(root_dir, "caption_filters.txt")
    with open(filter_script_path, "w") as f:
        f.write(filter_str)
    print(f"✅ Filter script written ({len(filter_str)} chars)")

    # ── Step 3: Burn captions + mux audio ───────────────────────────────────
    print("🎬 Burning captions...")
    burn = subprocess.run([
        "ffmpeg", "-y",
        "-i", looped_path,
        "-i", audio_path,
        "-filter_script:v", filter_script_path,
        "-map", "0:v",
        "-map", "1:a",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac",
        "-pix_fmt", "yuv420p",
        "-shortest",
        output_path
    ], capture_output=True, text=True)

    if burn.returncode != 0:
        print("❌ Caption burn failed:")
        print(burn.stderr[-3000:])
        return False

    for f in [looped_path, filter_script_path]:
        if os.path.exists(f):
            os.remove(f)

    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"\n✅ SUCCESS → {output_path} ({size_mb:.1f} MB)")
    return True


if __name__ == "__main__":
    assemble_video("test_video.mp4", "test_audio.mp3")
