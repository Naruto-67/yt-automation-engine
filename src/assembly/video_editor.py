import os
import re
from moviepy import VideoFileClip, AudioFileClip, TextClip, CompositeVideoClip, concatenate_videoclips

def parse_srt(srt_file):
    """Bulletproof SRT parser using regular expressions."""
    if not os.path.exists(srt_file):
        print(f"Warning: Subtitle file {srt_file} not found.")
        return []

    with open(srt_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # Regex to mathematically extract exact start, end, and text chunks
    pattern = re.compile(r'(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\s*\n(.*?)(?=\n\n|\Z)', re.DOTALL)
    
    subs = []
    for match in pattern.finditer(content):
        start_str = match.group(1)
        end_str = match.group(2)
        text = match.group(3).replace('\n', ' ').strip()
        
        def time_to_sec(t_str):
            h, m, s_ms = t_str.split(':')
            sec, ms = s_ms.split(',')
            return int(h)*3600 + int(m)*60 + int(sec) + int(ms)/1000.0
            
        subs.append({
            "start": time_to_sec(start_str),
            "end": time_to_sec(end_str),
            "text": text
        })
        
    print(f"DEBUG: Successfully parsed {len(subs)} subtitle blocks from SRT.")
    return subs

def assemble_video(video_path, audio_path, output_path="final_video.mp4"):
    """Stitches video, audio, and subtitles together into a viral Short."""
    if not os.path.exists(video_path) or not os.path.exists(audio_path):
        print("Error: Missing media files.")
        return False

    try:
        print("Loading media...")
        video_clip = VideoFileClip(video_path)
        audio_clip = AudioFileClip(audio_path)

        # Loop if necessary to cover the audio
        if video_clip.duration < audio_clip.duration:
            loops_needed = int(audio_clip.duration // video_clip.duration) + 1
            video_clip = concatenate_videoclips([video_clip] * loops_needed)

        # Cut to exact length
        video_clip = video_clip.subclipped(0, audio_clip.duration)
        
        # Build the Subtitle Clips
        srt_path = audio_path.replace(".mp3", ".srt")
        subtitles = parse_srt(srt_path)
        
        # Start our layers with the background video
        clips = [video_clip]
        
        print("Generating heavy subtitle text graphics...")
        for sub in subtitles:
            # Removed the specific font to allow Ubuntu to use its safe default
            txt_clip = TextClip(
                text=sub['text'], 
                font_size=90, 
                color='yellow', 
                stroke_color='black', 
                stroke_width=3,
                method='caption',
                size=(video_clip.w * 0.8, None)
            )
            
            # Place it dead center and time it perfectly
            txt_clip = txt_clip.with_position(('center', 'center'))
            txt_clip = txt_clip.with_start(sub['start']).with_end(sub['end'])
            
            clips.append(txt_clip)

        print(f"Overlaying {len(clips)} total layers (1 Video + {len(subtitles)} Text Clips)...")
        final_video = CompositeVideoClip(clips)
        final_video = final_video.with_audio(audio_clip)

        print("Rendering final masterpiece...")
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
        final_video.close()
        
        print(f"Success! Subtitled video rendered to {output_path}")
        return True

    except Exception as e:
        print(f"Failed to assemble video: {e}")
        return False

if __name__ == "__main__":
    assemble_video("test_video.mp4", "test_audio.mp3", "master_final_video.mp4")
