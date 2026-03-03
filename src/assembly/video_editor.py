import os
import subprocess
from moviepy import VideoFileClip, AudioFileClip, concatenate_videoclips

def assemble_video(video_path, audio_path, output_path="master_final_video.mp4"):
    temp_no_subs = "temp_no_subs.mp4"
    srt_path = audio_path.replace(".mp3", ".srt")

    # 1. Sync Video/Audio
    v_clip = VideoFileClip(video_path)
    a_clip = AudioFileClip(audio_path)
    if v_clip.duration < a_clip.duration:
        loops = int(a_clip.duration // v_clip.duration) + 1
        v_clip = concatenate_videoclips([v_clip] * loops)
    
    final_v = v_clip.subclipped(0, a_clip.duration).with_audio(a_clip)
    final_v.write_videofile(temp_no_subs, fps=30, codec="libx264", audio_codec="aac", logger=None)
    v_clip.close()
    a_clip.close()

    # 2. Basic FFmpeg Burn
    # No complex styles, just centered white text with a black outline
    cmd = [
        "ffmpeg", "-y", "-i", temp_no_subs,
        "-vf", f"subtitles={srt_path}:force_style='Alignment=6,FontSize=18,Outline=1'",
        "-c:a", "copy",
        output_path
    ]
    
    subprocess.run(cmd, check=True)
    if os.path.exists(temp_no_subs): os.remove(temp_no_subs)
    return True

if __name__ == "__main__":
    assemble_video("test_video.mp4", "test_audio.mp3")
