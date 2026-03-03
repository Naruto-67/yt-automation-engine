import os
import json
from moviepy import VideoFileClip, AudioFileClip, TextClip, CompositeVideoClip, concatenate_videoclips

def assemble_video(video_path, audio_path, output_path="master_final_video.mp4"):
    # 1. ROBUST FONT SELECTOR
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    if not os.path.exists(font_path):
        font_path = "Arial" # Fallback for local testing

    # 2. DATA VALIDATION
    json_path = audio_path.replace(".mp3", ".json")
    if not os.path.exists(json_path):
        print("Missing JSON metadata!")
        return False

    with open(json_path, 'r') as f:
        word_timings = json.load(f)

    video_clip = VideoFileClip(video_path)
    audio_clip = AudioFileClip(audio_path)
    
    # Standard Short looping & sizing
    if video_clip.duration < audio_clip.duration:
        loops = int(audio_clip.duration // video_clip.duration) + 1
        video_clip = concatenate_videoclips([video_clip] * loops)
    video_clip = video_clip.subclipped(0, audio_clip.duration)

    all_clips = [video_clip]
    
    # 3. DYNAMIC CAPTION SETTINGS
    V_WIDTH, V_HEIGHT = video_clip.w, video_clip.h
    SAFE_WIDTH = int(V_WIDTH * 0.85) # 85% of screen width max
    
    # We group words into small segments (max 3 words)
    words_per_line = 3 
    
    for i in range(0, len(word_timings), words_per_line):
        line_chunk = word_timings[i:i + words_per_line]
        line_start = line_chunk[0]['start']
        line_end = line_chunk[-1]['start'] + line_chunk[-1]['duration']
        
        full_text = " ".join([w['text'] for w in line_chunk]).upper()
        
        # --- THE FIX: DYNAMIC FONT SCALING ---
        # If the line is very long, we shrink the font automatically
        current_font_size = 70
        if len(full_text) > 15: current_font_size = 55
        if len(full_text) > 25: current_font_size = 40

        # Create the Base Line (White)
        # Using method='label' + size ensures it never stretches
        base_line = TextClip(
            text=full_text,
            font_size=current_font_size,
            color='white',
            font=font_path,
            stroke_color='black',
            stroke_width=2,
            method='label'
        ).with_start(line_start).with_end(line_end).with_position(('center', 0.7), relative=True)

        all_clips.append(base_line)

        # 4. THE HIGHLIGHT ENGINE (Yellow Pop)
        # We overlay the active word directly on top of its position in the line
        for word in line_chunk:
            # Note: We use a larger font size + yellow color for the "Pop" effect
            highlight = TextClip(
                text=word['text'].upper(),
                font_size=current_font_size + 5, 
                color='yellow',
                font=font_path,
                stroke_color='black',
                stroke_width=2,
                method='label'
            ).with_start(word['start']).with_end(word['start'] + word['duration']).with_position(('center', 0.7), relative=True)
            
            all_clips.append(highlight)

    print(f"Baking {len(all_clips)} layers into 9:16 format...")
    final_video = CompositeVideoClip(all_clips, size=(V_WIDTH, V_HEIGHT)).with_audio(audio_clip)
    
    final_video.write_videofile(
        output_path, 
        fps=30, 
        codec="libx264", 
        audio_codec="aac",
        preset="ultrafast",
        logger=None
    )
    
    video_clip.close()
    audio_clip.close()
    return True

if __name__ == "__main__":
    assemble_video("test_video.mp4", "test_audio.mp3")
