import os
import json
import subprocess
import numpy as np
from moviepy import VideoFileClip, AudioFileClip, concatenate_videoclips, VideoClip
from PIL import Image, ImageDraw, ImageFont

# ── Font setup ──────────────────────────────────────────────────────────────
# Try to find a bold TTF on the system. On GitHub Actions Ubuntu,
# fonts-dejavu-core is pre-installed and always at this path.
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",        # macOS fallback
]

def find_font():
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return path
    # Last resort: PIL default (always exists, not pretty but works)
    return None

def draw_outline_text(draw, x, y, text, font, fill_color, outline_color=(0, 0, 0), outline_width=4):
    """Draw text with a solid outline for readability."""
    for dx in range(-outline_width, outline_width + 1):
        for dy in range(-outline_width, outline_width + 1):
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
    draw.text((x, y), text, font=font, fill=fill_color)

def make_caption_frame(frame_array, t, caption_chunks, font, video_w, video_h):
    """
    Given a raw video frame (numpy array) and a timestamp t,
    finds the active caption chunk, determines the active word,
    and burns the caption onto the frame using Pillow.
    Returns a numpy array.
    """
    img = Image.fromarray(frame_array)
    draw = ImageDraw.Draw(img)

    # Find the active chunk for this timestamp
    active_chunk = None
    for chunk in caption_chunks:
        if chunk["start"] <= t <= chunk["end"]:
            active_chunk = chunk
            break

    if active_chunk is None:
        return frame_array  # No caption for this frame

    # Find the active word within the chunk
    active_word_idx = 0
    for i, word in enumerate(active_chunk["words"]):
        if word["start"] <= t:
            active_word_idx = i

    words = active_chunk["words"]

    # ── Calculate positions ─────────────────────────────────────────────
    # Measure each word's pixel width so we can center the whole line
    word_texts = [w["text"].upper() for w in words]
    word_widths = []
    space_width = font.getbbox(" ")[2]

    for wt in word_texts:
        bbox = font.getbbox(wt)
        word_widths.append(bbox[2] - bbox[0])

    # Total line width including spaces between words
    total_width = sum(word_widths) + space_width * (len(word_texts) - 1)
    x_start = (video_w - total_width) // 2

    # Position captions in the lower third — safe for 9:16
    font_height = font.getbbox("A")[3]
    y = video_h - font_height - 180

    # ── Draw each word ──────────────────────────────────────────────────
    x = x_start
    for i, (word_text, word_width) in enumerate(zip(word_texts, word_widths)):
        # Active word = yellow, rest = white
        color = (255, 230, 0) if i == active_word_idx else (255, 255, 255)
        draw_outline_text(draw, x, y, word_text, font, fill_color=color, outline_width=5)
        x += word_width + space_width

    return np.array(img)

def assemble_video(video_filename, audio_filename, output_filename="master_final_video.mp4"):
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))

    video_path   = os.path.join(root_dir, video_filename)
    audio_path   = os.path.join(root_dir, audio_filename)
    timings_path = audio_path.replace(".mp3", "_timings.json")
    output_path  = os.path.join(root_dir, output_filename)

    # ── Sanity checks ───────────────────────────────────────────────────
    for path, label in [(video_path, "Video"), (audio_path, "Audio"), (timings_path, "Timings JSON")]:
        if not os.path.exists(path):
            print(f"CRITICAL ERROR: {label} file missing: {path}")
            print("Files in root:", os.listdir(root_dir))
            return False

    # ── Load caption data ───────────────────────────────────────────────
    with open(timings_path, "r") as f:
        caption_chunks = json.load(f)
    print(f"Loaded {len(caption_chunks)} caption chunks from timings JSON.")

    # ── Load font ───────────────────────────────────────────────────────
    font_path = find_font()
    if font_path:
        print(f"Using font: {font_path}")
        font = ImageFont.truetype(font_path, 85)
    else:
        print("WARNING: No TTF font found. Using PIL default font (captions will be small).")
        font = ImageFont.load_default()

    # ── Load and loop video to match audio length ───────────────────────
    v_clip = VideoFileClip(video_path)
    a_clip = AudioFileClip(audio_path)

    if v_clip.duration < a_clip.duration:
        loops = int(a_clip.duration // v_clip.duration) + 1
        v_clip = concatenate_videoclips([v_clip] * loops)

    v_clip = v_clip.subclipped(0, a_clip.duration).with_audio(a_clip)

    video_w = v_clip.w
    video_h = v_clip.h

    # ── Apply Pillow caption overlay frame by frame ─────────────────────
    print("Burning captions onto frames (this takes a moment)...")

    def process_frame(get_frame, t):
        frame = get_frame(t)
        return make_caption_frame(frame, t, caption_chunks, font, video_w, video_h)

    captioned = v_clip.transform(process_frame)

    # ── Write final video ───────────────────────────────────────────────
    captioned.write_videofile(
        output_path,
        fps=30,
        codec="libx264",
        audio_codec="aac",
        threads=4,
        logger=None
    )

    v_clip.close()
    a_clip.close()
    captioned.close()

    print(f"\n✅ Success! Final video at: {output_path}")
    return True

if __name__ == "__main__":
    assemble_video("test_video.mp4", "test_audio.mp3")
