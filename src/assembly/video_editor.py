import os
import subprocess
from moviepy import VideoFileClip, AudioFileClip, concatenate_videoclips

def assemble_video(video_path, audio_path, output_path="master_final_video.mp4"):
    temp_video = "temp_raw.mp4"
    # Force absolute path for FFmpeg
    ass_path = os.path.abspath(audio_path.replace(".mp3", ".ass"))
    
    if not os.path.exists(ass_path):
        print(f"CRITICAL ERROR: Subtitle file {ass_path} missing!")
        return False

    print("Step 1: Creating synced base video...")
    v_clip = VideoFileClip(video_path)
    a_clip = AudioFileClip(audio_path)
    
    if v_clip.duration < a_clip.duration:
        loops = int(a_clip.duration // v_clip.duration) + 1
        v_clip = concatenate_videoclips([v_clip] * loops)
    
    final_v = v_clip.subclipped(0, a_clip.duration).with_audio(a_clip)
    final_v.write_videofile(temp_video, fps=30, codec="libx264", audio_codec="aac", logger=None)
    v_clip.close()
    a_clip.close()

    print(f"Step 2: Hard-burning {ass_path} via FFmpeg...")
    
    # FFmpeg 'ass' filter requires backslashes for colons on some Linux builds
    escaped_ass_path = ass_path.replace(":", "\\:").replace("\\", "/")
    
    cmd = [
        "ffmpeg", "-y", "-i", temp_video,
        "-vf", f"ass='{escaped_ass_path}'",
        "-c:a", "copy",
        output_path
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"FFmpeg Error: {result.stderr}")
        return False

    if os.path.exists(temp_video):
        os.remove(temp_video)
    print("Success! Download master_final_video.mp4 now.")
    return True

if __name__ == "__main__":
    assemble_video("test_video.mp4", "test_audio.mp3")
