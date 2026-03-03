import os
import subprocess
from moviepy import VideoFileClip, AudioFileClip, concatenate_videoclips

def assemble_video(video_filename, audio_filename, output_filename="master_final_video.mp4"):
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))

    video_path = os.path.join(root_dir, video_filename)
    audio_path = os.path.join(root_dir, audio_filename)
    ass_path = audio_path.replace(".mp3", ".ass")
    output_path = os.path.join(root_dir, output_filename)
    temp_video = os.path.join(root_dir, "temp_raw.mp4")

    if not os.path.exists(ass_path):
        print(f"CRITICAL ERROR: Subtitle file {ass_path} missing!")
        print("Files in root:", os.listdir(root_dir))
        return False

    v_clip = VideoFileClip(video_path)
    a_clip = AudioFileClip(audio_path)

    if v_clip.duration < a_clip.duration:
        loops = int(a_clip.duration // v_clip.duration) + 1
        v_clip = concatenate_videoclips([v_clip] * loops)

    final_v = v_clip.subclipped(0, a_clip.duration).with_audio(a_clip)
    final_v.write_videofile(temp_video, fps=30, codec="libx264", audio_codec="aac", logger=None)
    v_clip.close()
    a_clip.close()

    # FIX 1 & 2: On Linux, only forward slashes needed — no colon escaping
    escaped_ass = ass_path.replace("\\", "/")

    cmd = [
        "ffmpeg", "-y", "-i", temp_video,
        "-vf", f"ass={escaped_ass}",   # FIX: no single quotes around path
        "-c:a", "copy",
        output_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    
    # Print FFmpeg output so you can see exactly what happened
    if result.returncode != 0:
        print("FFmpeg FAILED:")
        print(result.stderr)
        return False

    if os.path.exists(temp_video):
        os.remove(temp_video)

    print(f"Success! Final video at {output_path}")
    return True

if __name__ == "__main__":
    assemble_video("test_video.mp4", "test_audio.mp3")
