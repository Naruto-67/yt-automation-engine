import os
import json
import subprocess
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# ── CapCut-style caption config ─────────────────────────────────────────────
FONT_PATH        = os.path.join(os.path.dirname(__file__), "../../assets/Montserrat-Bold.ttf")
FONT_SIZE_NORMAL = 72
FONT_SIZE_ACTIVE = 90        # 1.25x pop-up scale for active word
THICKNESS_NORMAL = 4
THICKNESS_ACTIVE = 6
COLOR_NORMAL     = (255, 255, 255)     # RGB white
COLOR_ACTIVE     = (255, 220,   0)     # RGB warm yellow
COLOR_OUTLINE    = (0,     0,   0)     # RGB black
CAPTION_BOTTOM_MARGIN = 200            # px from bottom of frame
SPACE_EXTRA      = 18                  # extra px between words


def get_audio_duration(audio_path):
    result = subprocess.run([
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams", audio_path
    ], capture_output=True, text=True, check=True)
    info = json.loads(result.stdout)
    for stream in info.get("streams", []):
        if "duration" in stream:
            return float(stream["duration"])
    raise RuntimeError("ffprobe could not determine audio duration.")


def draw_outline_text(draw, x, y, text, font, fill, outline=COLOR_OUTLINE, outline_w=4):
    """Draw text with a solid pixel outline — works on any background."""
    for dx in range(-outline_w, outline_w + 1):
        for dy in range(-outline_w, outline_w + 1):
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, font=font, fill=outline)
    draw.text((x, y), text, font=font, fill=fill)


def draw_caption_on_frame(pil_img, t, chunks, font_normal, font_active):
    """
    Draws CapCut-combo captions onto a PIL Image:
      - Active word: YELLOW + larger font (pop scale) + thicker outline
      - Other words: WHITE + normal font
    Returns modified PIL Image.
    """
    # Find the active chunk
    active = None
    for chunk in chunks:
        if chunk["start"] <= t <= chunk["end"]:
            active = chunk
            break
    if active is None:
        return pil_img

    words = active["words"]

    # Which word is active right now
    active_idx = 0
    for i, w in enumerate(words):
        if w["start"] <= t:
            active_idx = i

    word_texts = [w["text"].upper() for w in words]

    # Measure each word at its own font size so we can center the line
    draw = ImageDraw.Draw(pil_img)
    word_data = []
    for i, wt in enumerate(word_texts):
        font = font_active if i == active_idx else font_normal
        bbox = draw.textbbox((0, 0), wt, font=font)
        w_w  = bbox[2] - bbox[0]
        w_h  = bbox[3] - bbox[1]
        word_data.append({"text": wt, "font": font, "w": w_w, "h": w_h})

    total_w = sum(d["w"] for d in word_data) + SPACE_EXTRA * (len(word_data) - 1)
    img_w, img_h = pil_img.size
    x = (img_w - total_w) // 2

    # Baseline y: anchor to bottom margin, align all words to same baseline
    max_h   = max(d["h"] for d in word_data)
    y_base  = img_h - CAPTION_BOTTOM_MARGIN

    cur_x = x
    for i, d in enumerate(word_data):
        color   = COLOR_ACTIVE if i == active_idx else COLOR_NORMAL
        outline = THICKNESS_ACTIVE if i == active_idx else THICKNESS_NORMAL

        # Vertically align smaller words to the same baseline as the tallest
        y_offset = y_base + (max_h - d["h"])

        draw_outline_text(draw, cur_x, y_offset, d["text"], d["font"],
                          fill=color, outline_w=outline)
        cur_x += d["w"] + SPACE_EXTRA

    return pil_img


def assemble_video(video_filename, audio_filename, output_filename="master_final_video.mp4"):
    root_dir     = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
    video_path   = os.path.join(root_dir, video_filename)
    audio_path   = os.path.join(root_dir, audio_filename)
    timings_path = audio_path.replace(".mp3", "_timings.json")
    output_path  = os.path.join(root_dir, output_filename)
    temp_path    = os.path.join(root_dir, "temp_captioned_silent.mp4")
    font_path    = os.path.join(root_dir, "assets", "Montserrat-Bold.ttf")

    # ── Sanity checks ────────────────────────────────────────────────────────
    for path, label in [
        (video_path,   "Background video"),
        (audio_path,   "Audio MP3"),
        (timings_path, "Timings JSON"),
        (font_path,    "Montserrat-Bold.ttf font"),
    ]:
        if not os.path.exists(path):
            print(f"❌ MISSING: {label} → {path}")
            print("Root contents:", os.listdir(root_dir))
            return False

    # ── Load assets ──────────────────────────────────────────────────────────
    with open(timings_path, "r") as f:
        chunks = json.load(f)
    print(f"✅ Loaded {len(chunks)} caption chunks.")

    font_normal = ImageFont.truetype(font_path, FONT_SIZE_NORMAL)
    font_active = ImageFont.truetype(font_path, FONT_SIZE_ACTIVE)
    print(f"✅ Font loaded: {font_path}")

    # ── Open source video with OpenCV ────────────────────────────────────────
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"❌ Cannot open video: {video_path}")
        return False

    fps           = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_w       = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_h       = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_src_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    audio_dur     = get_audio_duration(audio_path)
    frames_needed = int(audio_dur * fps) + 2

    print(f"📹 Video: {frame_w}x{frame_h} @ {fps:.1f}fps | need {frames_needed} frames for {audio_dur:.1f}s audio")

    # ── Start FFmpeg encoder reading raw BGR frames from stdin ───────────────
    ffmpeg_encode = [
        "ffmpeg", "-y",
        "-f", "rawvideo",
        "-vcodec", "rawvideo",
        "-s", f"{frame_w}x{frame_h}",
        "-pix_fmt", "bgr24",
        "-r", str(fps),
        "-i", "pipe:0",
        "-vcodec", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        temp_path
    ]
    encoder = subprocess.Popen(ffmpeg_encode, stdin=subprocess.PIPE)
    print("🎬 FFmpeg encoder started. Processing frames...")

    frame_num = 0
    while frame_num < frames_needed:
        # Loop background if shorter than audio
        if frame_num > 0 and (frame_num % total_src_frames) == 0:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

        ret, bgr_frame = cap.read()
        if not ret:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, bgr_frame = cap.read()
            if not ret:
                print("❌ Could not read frame. Stopping.")
                break

        t = frame_num / fps

        # Convert BGR → RGB PIL Image → draw captions → back to BGR numpy
        rgb_frame = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        pil_img   = Image.fromarray(rgb_frame)
        pil_img   = draw_caption_on_frame(pil_img, t, chunks, font_normal, font_active)
        bgr_out   = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

        encoder.stdin.write(bgr_out.tobytes())
        frame_num += 1

        if frame_num % 90 == 0:
            print(f"   {frame_num}/{frames_needed} frames ({frame_num/frames_needed*100:.0f}%)")

    cap.release()
    encoder.stdin.close()
    if encoder.wait() != 0:
        print("❌ FFmpeg encoding failed.")
        return False
    print("✅ Frames encoded. Muxing audio...")

    # ── Mux audio into encoded video ─────────────────────────────────────────
    mux = subprocess.run([
        "ffmpeg", "-y",
        "-i", temp_path,
        "-i", audio_path,
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        output_path
    ], capture_output=True, text=True)

    if mux.returncode != 0:
        print("❌ Audio mux failed:")
        print(mux.stderr[-2000:])
        return False

    if os.path.exists(temp_path):
        os.remove(temp_path)

    print(f"\n✅ SUCCESS → {output_path}")
    return True


if __name__ == "__main__":
    assemble_video("test_video.mp4", "test_audio.mp3")
