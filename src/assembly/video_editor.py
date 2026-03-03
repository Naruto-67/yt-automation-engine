import os
import json
from moviepy import VideoFileClip, AudioFileClip, TextClip, CompositeVideoClip, concatenate_videoclips

def assemble_video(video_path, audio_path, output_path="master_final_video.mp4"):
    # 1. Path Setup
    # On Ubuntu/GitHub Actions, this is the most reliable font path
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    
    if not os.path.exists(font_path):
        print(f"Warning: {font_path} not found. Falling back to system default.")
        font_path = "DejaVu-Sans-Bold" # Last ditch effort

    if not os.path.exists(video_path) or not os.path.exists(audio_path):
        print("Error: Video or Audio file missing.")
        return False

    json_path = audio_path.replace(".mp3", ".json")
    with open(json_path, 'r') as f:
        word_timings = json.load(f)
    
    if not word_timings:
        print("Error: JSON word timings are empty!")
        return False

    print(f"Loading media and processing {len(word_timings)} words...")
    video_clip = VideoFileClip(video_path)
    audio_clip = AudioFileClip(audio_path)
    
    if video_clip.duration < audio_clip.duration:
        loops = int(audio_clip.duration // video_clip.duration) + 1
        video_clip = concatenate_videoclips([video_clip] * loops)
    video_clip = video_clip.subclipped(0, audio_clip.duration)

    all_clips = [video_clip]
    
    # 2. Line-by-Line Logic
    words_per_line = 4 
    for i in range(0, len(word_timings), words_per_line):
        line_chunk = word_timings[i:i + words_per_line]
        line_start = line_chunk[0]['start']
        line_end = line_chunk[-1]['start'] + line_chunk[-1]['duration']
        
        full_line_text = " ".join([w['text'] for w in line_chunk]).upper()
        
        # Background White Line
        base_txt = TextClip(
            text=full_line_text, 
            font_size=70, 
            color='white',
            font=font_path, # Using absolute path
            stroke_color='black', 
            stroke_width=2, 
            method='caption',
            size=(video_clip.w * 0.8, None)
        ).with_start(line_start).with_end(line_end).with_position(('center', 1400))
        
        all_clips.append(base_txt)

        # Yellow Highlight for active word
        for word in line_chunk:
            highlight = TextClip(
                text=word['text'].upper(), 
                font_size=75, 
                color='yellow',
                font=font_path, # Using absolute path
                stroke_color='black', 
                stroke_width=3, 
                method='caption'
            ).with_start(word['start']).with_end(word['start'] + word['duration']).with_position(('center', 1400))
            
            all_clips.append(highlight)

    print("Rendering final video...")
    final_video = CompositeVideoClip(all_clips).with_audio(audio_clip)
    final_video.write_videofile(output_path, fps=30, codec="libx264", preset="ultrafast", logger=None)
    
    video_clip.close()
    audio_clip.close()
    print("Success!")
    return True

if __name__ == "__main__":
    assemble_video("test_video.mp4", "test_audio.mp3")
