import os
import json
import subprocess
from PIL import Image, ImageDraw, ImageFont

# ── Caption style constants ──────────────────────────────────────────────────
SAFE_WIDTH_RATIO      = 0.88
FONT_SIZE_MAX         = 85
FONT_SIZE_MIN         = 36
SPACE_PX              = 20
CAPTION_Y_FROM_BOTTOM = 240

FONT_PATH          = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
FONT_PATH_FALLBACK = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"


def get_font_path():
    if os.path.exists(FONT_PATH):
        return FONT_PATH
    if os.path.exists(FONT_PATH_FALLBACK):
        return FONT_PATH_FALLBACK
    raise RuntimeError(
        f"No font found. Run: sudo apt-get install -y fonts-liberation"
    )


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


def measure_word_width(text, font_path, font_size):
    """Use Pillow purely for pixel-accurate text measurement."""
    font = ImageFont.truetype(font_path, font_size)
    img  = Image.new("RGB", (4000, 400))
    draw = ImageDraw.Draw(img)
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def fit_font_size(word_texts, font_path, video_w):
    """
    Find the largest font size where the full line fits within safe width.
    Returns (font_size, widths_list, space_width)
    """
    max_px = int(video_w * SAFE_WIDTH_RATIO)
    font_size = FONT_SIZE_MAX

    while font_size >= FONT_SIZE_MIN:
        widths  = [measure_word_width(wt, font_path, font_size) for wt in word_texts]
        space_w = max(int(font_size * 0.28), 8)
        total_w = sum(widths) + space_w * (len(widths) - 1)
        if total_w <= max_px:
            return font_size, widths, space_w
        font_size -= 4

    # Absolute fallback — use minimum size regardless
    widths  = [measure_word_width(wt, font_path, FONT_SIZE_MIN) for wt in word_texts]
    space_w = max(int(FONT_SIZE_MIN * 0.28), 8)
    return FONT_SIZE_MIN, widths, space_w


def esc(text):
    """Escape text for FFmpeg drawtext filter."""
    text = str(text)
    text = text.replace("\\", "\\\\")
    text = text.replace("'", "\u2019")
    text = text.replace(":", "\\:")
    text = text.replace("%", "\\%")
    return text


def build_drawtext_filters(chunks, font_path, video_w, video_h):
    filters = []
    escaped_font = font_path.replace("\\", "/").replace(":", "\\:")

    print(f"  Building filters for {len(chunks)} chunks...")

    for chunk in chunks:
        words = chunk.get("words", [])
        if not words:
            continue

        chunk_s    = f"{float(chunk['start']):.3f}"
        chunk_e    = f"{float(chunk['end']):.3f}"
        word_texts = [w["text"].upper() for w in words]

        # Fit font size dynamically to frame width
        base_size, widths, space_w = fit_font_size(word_texts, font_path, video_w)

        total_w = sum(widths) + space_w * (len(widths) - 1)
        x_start = (video_w - total_w) // 2
        y_pos   = video_h - CAPTION_Y_FROM_BOTTOM - base_size

        # Single layer — white text, shown for full chunk duration
        x = x_start
        for wt, ww in zip(word_texts, widths):
            filters.append(
                f"drawtext=fontfile='{escaped_font}'"
                f":text='{esc(wt)}'"
                f":fontsize={base_size}"
                f":fontcolor=white"
                f":x={x}:y={y_pos}"
                f":bordercolor=black:borderw={max(3, base_size // 20)}"
                f":enable='between(t,{chunk_s},{chunk_e})'"
            )
            x += ww + space_w

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

    # ── Load + validate timings ──────────────────────────────────────────────
    with open(timings_path) as f:
        raw = f.read()

    print(f"  Timings JSON: {len(raw)} bytes")
    chunks = json.loads(raw)
    print(f"✅ Loaded {len(chunks)} caption chunks")

    if len(chunks) == 0:
        print("❌ FATAL: Timings JSON is empty")
        return False

    # ── Video info ───────────────────────────────────────────────────────────
    audio_dur          = get_audio_duration(audio_path)
    video_w, video_h, fps = get_video_info(video_path)
    print(f"✅ Audio: {audio_dur:.2f}s | Video: {video_w}x{video_h} @ {fps:.1f}fps")

    # ── Step 1: Loop background to match audio length ────────────────────────
    print("🔄 Looping background...")
    loop_result = subprocess.run([
        "ffmpeg", "-y",
        "-stream_loop", "-1",
        "-i", video_path,
        "-t", str(audio_dur + 0.5),
        "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", "-an",
        looped_path
    ], capture_output=True, text=True)

    if loop_result.returncode != 0:
        print("❌ Loop failed:")
        print(loop_result.stderr[-1500:])
        return False
    print("✅ Background looped")

    # ── Step 2: Build drawtext filtergraph ───────────────────────────────────
    filters = build_drawtext_filters(chunks, font_path, video_w, video_h)

    if not filters:
        print("❌ FATAL: No drawtext filters generated")
        print("  First chunk sample:", chunks[0] if chunks else "N/A")
        return False

    # Join with comma only — no newlines
    filter_str = ",".join(filters)
    print(f"✅ Filter string: {len(filter_str)} chars")

    # Write filter to file to avoid CLI length limits
    filter_script_path = os.path.join(root_dir, "caption_filters.txt")
    with open(filter_script_path, "w") as f:
        f.write(filter_str)
    print(f"✅ Filter script written")

    # ── Step 3: Burn captions + mux audio ───────────────────────────────────
    print("🎬 Burning captions...")
    burn_result = subprocess.run([
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

    if burn_result.returncode != 0:
        print("❌ Caption burn failed. FFmpeg stderr:")
        print(burn_result.stderr[-3000:])
        return False

    # Cleanup temp files
    for f in [looped_path, filter_script_path]:
        if os.path.exists(f):
            os.remove(f)

    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"\n✅ SUCCESS → {output_path} ({size_mb:.1f} MB)")
    return True


if __name__ == "__main__":
    assemble_video("test_video.mp4", "test_audio.mp3")
