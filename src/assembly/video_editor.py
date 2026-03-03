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
        cur
