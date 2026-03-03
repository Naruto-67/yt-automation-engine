import os
import subprocess
from moviepy import VideoFileClip, AudioFileClip, concatenate_videoclips

def assemble_video(video_path, audio_path, output_path="master_final_video.mp4"):
    temp_video = "temp_raw.mp4"
    ass_path = audio_path.replace(".mp3", ".ass")

    print("Step 1: Aligning video and audio...")
    v_clip = VideoFileClip(video_path)
    a_clip = AudioFileClip(audio_path)
    
    if v_clip.duration < a_clip.duration:
        loops = int(a_clip.duration // v_clip.duration) + 1
        v_clip = concatenate_videoclips([v_clip] * loops)
    
    final_v = v_clip.subclipped(0, a_clip.duration).with_audio(a_clip)
    final_v.write_videofile(temp_video, fps=30, codec="libx264", audio_codec="aac", logger=None)
    
    v_clip.close()
    a_clip.close()

    print("Step 2: Hard-burning subtitles with FFmpeg...")
    # This command uses the libass library to burn the .ass file perfectly
    cmd = [
        "ffmpeg", "-y", "-i", temp_video, 
        "-vf", f"ass={ass_path}", 
        "-c:a", "copy", 
        output_path
    ]
    
    subprocess.run(cmd, check=True)
    
    if os.path.exists(temp_video):
        os.remove(temp_video)
    print("Success! Video rendered.")
    return True

if __name__ == "__main__":
    assemble_video("test_video.mp4", "test_audio.mp3")
