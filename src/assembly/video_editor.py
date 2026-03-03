import os
import json
import subprocess
from PIL import Image, ImageDraw, ImageFont

FONT_SIZE_NORMAL      = 72
FONT_SIZE_ACTIVE      = 90
COLOR_NORMAL          = "white"
COLOR_ACTIVE          = "yellow"
BORDER_W_NORMAL       = 4
BORDER_W_ACTIVE       = 6
SPACE_PX              = 20
CAPTION_Y_FROM_BOTTOM = 240

FONT_PATH = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
FONT_PATH_FALLBACK = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"


def get_font_path():
    if os.path.exists(FONT_PATH):
        return FONT_PATH
    if os.path.exists(FONT_PATH_FALLBACK):
        return FONT_PATH_FALLBACK
    raise RuntimeError(f"No font found at {FONT_PATH} — run: sudo apt-get install -y fonts-liberation")


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
    font = ImageFont.truetype(font_path, font_size)
    img  = Image.new("RGB", (4000, 400))
    draw = ImageDraw.Draw(img)
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def esc(text):
    """Escape text for FFmpeg drawtext filter value."""
    text = str(text)
    text = text.replace("\\", "\\\\")
    text = text.replace("'", "\u2019")   # replace smart apostrophe — safest
    text = text.replace(":", "\\:")
    text = text.replace("%", "\\%")
    return text


def build_drawtext_filters(chunks, font_path, video_w, video_h):
    """
    Returns a list of drawtext filter strings.
    Layer 1: all words white (full chunk duration)
    Layer 2: active word yellow + bigger (word duration only) — draws on top
    """
    filters = []
    # FFmpeg needs forward slashes and escaped colons in fontfile path
    escaped_font = font_path.replace("\\", "/").replace(":", "\\:")

    print(f"  Building filters for {len(chunks)} chunks...")

    for ci, chunk in enumerate(chunks):
        words      = chunk.get("words", [])
        if not words:
            print(f"  WARNING: chunk {ci} has no words, skipping")
            continue

        chunk_s    = f"{float(chunk['start']):.3f}"
        chunk_e    = f"{float(chunk['end']):.3f}"
        word_texts = [w["text"].upper() for w in words]

        # Measure at normal size for layout
        widths  = [measure_word_width(wt, font_path, FONT_SIZE_NORMAL) for wt in word_texts]
        total_w = sum(widths) + SPACE_PX * (len(widths) - 1)
        x_start = (video_w - total_w) // 2
        y_pos   = video_h - CAPTION_Y_FROM_BOTTOM - FONT_SIZE_NORMAL

        x = x_start
        for wt, ww in zip(word_texts, widths):
            filters.append(
                f"drawtext=fontfile='{escaped_font}'"
                f":text='{esc(wt)}'"
                f":fontsize={FONT_SIZE_NORMAL}"
                f":fontcolor={COLOR_NORMAL}"
                f":x={x}:y={y_pos}"
                f":bordercolor=black:borderw={BORDER_W_NORMAL}"
                f":enable='between(t,{chunk_s},{chunk_e})'"
            )
            x += ww + SPACE_PX

        # Layer 2: active word yellow + pop scale
        x = x_start
        for word, wt, ww in zip(words, word_texts, widths):
            word_s   = f"{float(word['start']):.3f}"
            word_e   = f"{float(word['end']):.3f}"
            active_w = measure_word_width(wt, font_path, FONT_SIZE_ACTIVE)
            x_active = x + (ww - active_w) // 2
            y_active = y_pos - (FONT_SIZE_ACTIVE - FONT_SIZE_NORMAL) // 2

            filters.append(
                f"drawtext=fontfile='{escaped_font}'"
                f":text='{esc(wt)}'"
                f":fontsize={FONT_SIZE_ACTIVE}"
                f":fontcolor={COLOR_ACTIVE}"
                f":x={x_active}:y={y_active}"
                f":bordercolor=black:borderw={BORDER_W_ACTIVE}"
                f":enable='between(t,{word_s},{word_e})'"
            )
            x += ww + SPACE_PX

    print(f"  Total filters generated: {len(filters)}")
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

    print(f"  Timings JSON raw length: {len(raw)} bytes")
    print(f"  First 300 chars: {raw[:300]}")

    chunks = json.loads(raw)
    print(f"✅ Loaded {len(chunks)} caption chunks")

    if len(chunks) == 0:
        print("❌ FATAL: Timings JSON is empty — audio_generator.py produced no WordBoundary events")
        return False

    # ── Video info ───────────────────────────────────────────────────────────
    audio_dur          = get_audio_duration(audio_path)
    video_w, video_h, fps = get_video_info(video_path)
    print(f"✅ Audio: {audio_dur:.2f}s | Video: {video_w}x{video_h} @ {fps:.1f}fps")

    # ── Step 1: Loop background ──────────────────────────────────────────────
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

    # ── Step 2: Build filters ────────────────────────────────────────────────
    filters = build_drawtext_filters(chunks, font_path, video_w, video_h)

    if not filters:
        print("❌ FATAL: No drawtext filters were generated.")
        print("   Check that chunks have a 'words' key with content.")
        print("   First chunk sample:", chunks[0] if chunks else "N/A")
        return False

    # Join with comma ONLY — no newlines inside filter string
    filter_str = ",".join(filters)
    print(f"✅ Filter string length: {len(filter_str)} chars")
    print(f"   First 200 chars: {filter_str[:200]}")

    # ── Step 3: Write filter script file ─────────────────────────────────────
    # Using -filter_script instead of -vf avoids any command-line length limits
    filter_script_path = os.path.join(root_dir, "caption_filters.txt")
    with open(filter_script_path, "w") as f:
        f.write(filter_str)
    print(f"✅ Filter script written: {filter_script_path}")

    # ── Step 4: Burn captions ────────────────────────────────────────────────
    print("🎬 Burning captions with FFmpeg...")
    burn_result = subprocess.run([
        "ffmpeg", "-y",
        "-i", looped_path,
        "-i", audio_path,
        "-filter_script:v", filter_script_path,   # ← avoids CLI length limits
        "-map", "0:v",
        "-map", "1:a",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac",
        "-pix_fmt", "yuv420p",
        "-shortest",
        output_path
    ], capture_output=True, text=True)

    if burn_result.returncode != 0:
        print("❌ Caption burn failed. FFmpeg stderr (last 3000 chars):")
        print(burn_result.stderr[-3000:])
        return False

    # Cleanup
    for f in [looped_path, filter_script_path]:
        if os.path.exists(f):
            os.remove(f)

    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"\n✅ SUCCESS → {output_path} ({size_mb:.1f} MB)")
    return True


if __name__ == "__main__":
    assemble_video("test_video.mp4", "test_audio.mp3")
