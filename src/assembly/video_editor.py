import os
import json
import subprocess
from PIL import Image, ImageDraw, ImageFont

# ── Caption style ────────────────────────────────────────────────────────────
FONT_SIZE_NORMAL  = 72
FONT_SIZE_ACTIVE  = 92    # pop scale for active word
COLOR_NORMAL      = "white"
COLOR_ACTIVE      = "yellow"
BORDER_W_NORMAL   = 4
BORDER_W_ACTIVE   = 6
SPACE_PX          = 20    # pixels between words
CAPTION_Y_FROM_BOTTOM = 240  # px from bottom of frame

# Font pre-installed on Ubuntu via fonts-liberation (apt)
FONT_PATH = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
# Fallback if running locally on macOS
FONT_PATH_FALLBACK = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"


def get_font_path():
    if os.path.exists(FONT_PATH):
        return FONT_PATH
    if os.path.exists(FONT_PATH_FALLBACK):
        return FONT_PATH_FALLBACK
    raise RuntimeError(
        f"No font found. Install fonts-liberation:\n"
        f"  sudo apt-get install -y fonts-liberation"
    )


def get_video_info(video_path):
    """Use ffprobe to get video width, height, fps, duration."""
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
            # fps can be "30/1" or "30000/1001"
            fps_parts = s.get("r_frame_rate", "30/1").split("/")
            fps = float(fps_parts[0]) / float(fps_parts[1])
            return w, h, fps
    raise RuntimeError("No video stream found in file.")


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


def esc(text):
    """
    Escape text for FFmpeg drawtext filter.
    When passed via subprocess list (no shell), only FFmpeg's own
    filter parser rules apply — not shell escaping.
    """
    text = text.replace("\\", "\\\\")
    text = text.replace(":", "\\:")
    text = text.replace("'", "\\'")
    text = text.replace("%", "%%")
    return text


def build_drawtext_filters(chunks, font_path, video_w, video_h):
    """
    Build list of drawtext filter strings for the full video.

    Strategy (CapCut combo):
      Layer 1 — all words in WHITE at normal size, enabled for chunk duration
      Layer 2 — active word in YELLOW at larger size, enabled for word duration
                (yellow draws on top of white → creates highlight + pop effect)
    """
    filters = []
    escaped_font = font_path.replace(":", "\\:")

    for chunk in chunks:
        words      = chunk["words"]
        chunk_s    = f"{chunk['start']:.3f}"
        chunk_e    = f"{chunk['end']:.3f}"
        word_texts = [w["text"].upper() for w in words]

        # Measure each word at NORMAL size to calculate line layout
        widths = [measure_word_width(wt, font_path, FONT_SIZE_NORMAL) for wt in word_texts]
        total_w = sum(widths) + SPACE_PX * (len(widths) - 1)
        x_start = (video_w - total_w) // 2
        y_pos   = video_h - CAPTION_Y_FROM_BOTTOM - FONT_SIZE_NORMAL

        # ── Layer 1: all words white, normal size, full chunk duration ──────
        x = x_start
        for wt, ww in zip(word_texts, widths):
            filters.append(
                f"drawtext="
                f"fontfile='{escaped_font}':"
                f"text='{esc(wt)}':"
                f"fontsize={FONT_SIZE_NORMAL}:"
                f"fontcolor={COLOR_NORMAL}:"
                f"x={x}:y={y_pos}:"
                f"bordercolor=black:borderw={BORDER_W_NORMAL}:"
                f"enable='between(t,{chunk_s},{chunk_e})'"
            )
            x += ww + SPACE_PX

        # ── Layer 2: active word yellow+bigger, only during its spoken time ─
        x = x_start
        for i, (word, wt, ww) in enumerate(zip(words, word_texts, widths)):
            word_s = f"{word['start']:.3f}"
            word_e = f"{word['end']:.3f}"

            # Measure at ACTIVE size and center it over the normal-size slot
            active_w = measure_word_width(wt, font_path, FONT_SIZE_ACTIVE)
            x_active = x + (ww - active_w) // 2
            # Raise y slightly so it grows upward (looks like a pop)
            y_active = y_pos - (FONT_SIZE_ACTIVE - FONT_SIZE_NORMAL) // 2

            filters.append(
                f"drawtext="
                f"fontfile='{escaped_font}':"
                f"text='{esc(wt)}':"
                f"fontsize={FONT_SIZE_ACTIVE}:"
                f"fontcolor={COLOR_ACTIVE}:"
                f"x={x_active}:y={y_active}:"
                f"bordercolor=black:borderw={BORDER_W_ACTIVE}:"
                f"enable='between(t,{word_s},{word_e})'"
            )
            x += ww + SPACE_PX

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

    audio_dur  = get_audio_duration(audio_path)
    video_w, video_h, fps = get_video_info(video_path)
    print(f"✅ Audio: {audio_dur:.2f}s | Video: {video_w}x{video_h} @ {fps:.1f}fps")

    # ── Step 1: Loop background video to match audio length ──────────────────
    print("🔄 Looping background to match audio duration...")
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
    print("🖊️  Building caption filters...")
    filters = build_drawtext_filters(chunks, font_path, video_w, video_h)
    filter_str = ",\n".join(filters)
    print(f"   {len(filters)} drawtext filters generated")

    # ── Step 3: Burn captions + mux audio in one FFmpeg pass ─────────────────
    # We pass filter_str as a single list element — no shell, no shell escaping
    print("🎬 Burning captions...")
    burn_result = subprocess.run([
        "ffmpeg", "-y",
        "-i", looped_path,
        "-i", audio_path,
        "-vf", filter_str,          # passed directly, no shell interpretation
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

    # Cleanup
    if os.path.exists(looped_path):
        os.remove(looped_path)

    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"\n✅ SUCCESS → {output_path} ({size_mb:.1f} MB)")
    return True


if __name__ == "__main__":
    assemble_video("test_video.mp4", "test_audio.mp3")
