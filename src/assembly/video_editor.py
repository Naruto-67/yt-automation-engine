import os
import subprocess
from moviepy import VideoFileClip, AudioFileClip, concatenate_videoclips

def assemble_video(video_path, audio_path, output_path="master_final_video.mp4"):
    temp_no_subs = "temp_no_subs.mp4"
    
    # Absolute path for the SRT
    raw_srt = os.path.abspath(audio_path.replace(".mp3", ".srt"))
    
    # Escape colons for FFmpeg's filtergraph syntax
    escaped_srt = raw_srt.replace("\\", "/").replace(":", "\\:")

    if not os.path.exists(raw_srt):
        print(f"Error: Subtitle file {raw_srt} not found!")
        return False

    print("Step 1: Syncing audio and video...")
    v_clip = VideoFileClip(video_path)
    a_clip = AudioFileClip(audio_path)
    
    if v_clip.duration < a_clip.duration:
        loops = int(a_clip.duration // v_clip.duration) + 1
        v_clip = concatenate_videoclips([v_clip] * loops)
    
    final_v = v_clip.subclipped(0, a_clip.duration).with_audio(a_clip)
    final_v.write_videofile(temp_no_subs, fps=30, codec="libx264", audio_codec="aac", logger=None)
    v_clip.close()
    a_clip.close()

    print("Step 2: Burning stable SRT captions...")
    
    # THE FIX: Removed the single quotes around {escaped_srt}
    cmd = [
        "ffmpeg", "-y", "-i", temp_no_subs,
        "-vf", f"subtitles={escaped_srt}:force_style='Alignment=6,FontSize=18,Outline=1'",
        "-c:a", "copy",
        output_path
    ]
    
    # Print the exact command to the GitHub logs for easy debugging
    print(f"Running FFmpeg command: {' '.join(cmd)}")
    
    subprocess.run(cmd, check=True)
    
    if os.path.exists(temp_no_subs): 
        os.remove(temp_no_subs)
    
    print("Success! Stable video rendered.")
    return True

if __name__ == "__main__":
    assemble_video("test_video.mp4", "test_audio.mp3")
