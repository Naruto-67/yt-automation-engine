import os
from moviepy import VideoFileClip, AudioFileClip, TextClip, CompositeVideoClip, concatenate_videoclips

def parse_vtt(vtt_file):
    """Reads the subtitle file and extracts the exact start/end time for each word."""
    subs = []
    if not os.path.exists(vtt_file):
        print(f"Warning: Subtitle file {vtt_file} not found.")
        return subs

    with open(vtt_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    start_time, end_time, text = None, None, []
    
    for line in lines:
        line = line.strip()
        if "-->" in line:
            parts = line.split(" --> ")
            start_time, end_time = parts[0], parts[1]
        elif line == "" and start_time:
            # Convert HH:MM:SS.mmm to exact seconds
            def time_to_sec(t_str):
                h, m, s = t_str.split(':')
                sec, ms = s.split('.')
                return int(h)*3600 + int(m)*60 + int(sec) + int(ms)/1000.0
            
            subs.append({
                "start": time_to_sec(start_time),
                "end": time_to_sec(end_time),
                "text": " ".join(text)
            })
            start_time, end_time, text = None, None, []
        elif start_time and line and line != "WEBVTT":
            text.append(line)
            
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
        vtt_path = audio_path.replace(".mp3", ".vtt")
        subtitles = parse_vtt(vtt_path)
        
        # Start our layers with the background video
        clips = [video_clip]
        
        print("Generating heavy subtitle text graphics...")
        for sub in subtitles:
            # Create a big, yellow text graphic with a black stroke
            txt_clip = TextClip(
                font="Ubuntu-Bold", # Standard Linux font built into GitHub
                text=sub['text'], 
                font_size=90, 
                color='yellow', 
                stroke_color='black', 
                stroke_width=4,
                method='caption',
                size=(video_clip.w * 0.8, None)
            )
            
            # Place it dead center and time it perfectly
            txt_clip = txt_clip.with_position(('center', 'center'))
            txt_clip = txt_clip.with_start(sub['start']).with_end(sub['end'])
            
            clips.append(txt_clip)

        print("Overlaying all layers...")
        final_video = CompositeVideoClip(clips)
        final_video = final_video.with_audio(audio_clip)

        print("Rendering final masterpiece. This takes serious compute power...")
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
        final_video.
