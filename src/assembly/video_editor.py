import os
import subprocess
from moviepy import VideoFileClip, AudioFileClip, concatenate_videoclips

def assemble_video(video_path, audio_path, output_path="final_video.mp4"):
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
        final_video = video_clip.with_audio(audio_clip)

        temp_video = "temp_no_subs.mp4"
        print("Rendering base video without subtitles...")
        final_video.write_videofile(
            temp_video, 
            fps=30, 
            codec="libx264", 
            audio_codec="aac",
            preset="ultrafast",
            logger=None
        )
        
        video_clip.close()
        audio_clip.close()
        final_video.close()

        srt_path = audio_path.replace(".mp3", ".srt")
        if not os.path.exists(srt_path):
            print(f"Error: Subtitle file {srt_path} not found. Skipping text burn-in.")
            os.rename(temp_video, output_path)
            return True
            
        print("Burning big yellow subtitles into the video using FFmpeg...")
        
        # THE FIX: We use a raw string (r"") and backslashes (\,) to hide the commas from FFmpeg
        style = r"Alignment=5\,FontName=Ubuntu\,FontSize=22\,PrimaryColour=&H0000FFFF\,OutlineColour=&H00000000\,Outline=2\,Bold=1"
        
        # We pass the command as a secure list so it cannot be scrambled
        ffmpeg_cmd = [
            "ffmpeg", "-y", 
            "-i", temp_video, 
            "-vf", f"subtitles={srt_path}:force_style='{style}'", 
            "-c:a", "copy", 
            output_path
        ]
        
        subprocess.run(ffmpeg_cmd, check=True)
        
        # Clean up temp file
        if os.path.exists(temp_video):
            os.remove(temp_video)
            
        print(f"Success! Subtitled video rendered to {output_path}")
        return True

    except subprocess.CalledProcessError as e:
        print(f"FFmpeg failed with error code: {e.returncode}")
        return False
    except Exception as e:
        print(f"Failed to assemble video: {e}")
        return False

if __name__ == "__main__":
    assemble_video("test_video.mp4", "test_audio.mp3", "master_final_video.mp4")
