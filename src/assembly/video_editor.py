import os
import json
from moviepy import VideoFileClip, AudioFileClip, TextClip, CompositeVideoClip, concatenate_videoclips

def assemble_video(video_path, audio_path, output_path="master_final_video.mp4"):
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    
    if not os.path.exists(video_path) or not os.path.exists(audio_path):
        return False

    json_path = audio_path.replace(".mp3", ".json")
    with open(json_path, 'r') as f:
        word_timings = json.load(f)
    
    video_clip = VideoFileClip(video_path)
    audio_clip = AudioFileClip(audio_path)
    
    # Standard Short looping logic
    if video_clip.duration < audio_clip.duration:
        loops = int(audio_clip.duration // video_clip.duration) + 1
        video_clip = concatenate_videoclips([video_clip] * loops)
    video_clip = video_clip.subclipped(0, audio_clip.duration)

    all_clips = [video_clip]
    
    # THE FIX: Smaller font and explicit width constraints
    # We use a 3-word chunk to keep the lines short and readable
    words_per_line = 3 
    for i in range(0, len(word_timings), words_per_line):
        line_chunk = word_timings[i:i + words_per_line]
        line_start = line_chunk[0]['start']
        line_end = line_chunk[-1]['start'] + line_chunk[-1]['duration']
        
        full_line_text = " ".join([w['text'] for w in line_chunk]).upper()
        
        # 1. BASE TEXT (White with shadow)
        # Using 'label' prevents the 'stretching' seen in your screenshot
        base_txt = TextClip(
            text=full_line_text, 
            font_size=55, 
            color='white',
            font=font_path,
            stroke_color='black', 
            stroke_width=2,
            method='label' 
        ).with_start(line_start).with_end(line_end).with_position(('center', 0.6), relative=True)
        
        all_clips.append(base_txt)

        # 2. ACTIVE WORD OVERLAY (Yellow)
        # This flashes the yellow word exactly over the white text
        for word in line_chunk:
            highlight = TextClip(
                text=word['text'].upper(), 
                font_size=55, 
                color='yellow',
                font=font_path,
                stroke_color='black', 
                stroke_width=2,
                method='label'
            ).with_start(word['start']).with_end(word['start'] + word['duration']).with_position(('center', 0.6), relative=True)
            
            all_clips.append(highlight)

    print(f"Assembling {len(all_clips)} layers...")
    final_video = CompositeVideoClip(all_clips, size=video_clip.size).with_audio(audio_clip)
    final_video.write_videofile(output_path, fps=30, codec="libx264", preset="ultrafast", logger=None)
    
    video_clip.close()
    audio_clip.close()
    return True

if __name__ == "__main__":
    assemble_video("test_video.mp4", "test_audio.mp3")
