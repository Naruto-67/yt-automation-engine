import os
import subprocess
import json
from moviepy import VideoFileClip, AudioFileClip, concatenate_videoclips

def load_style_config(style_name="default"):
    """
    Loads the styling configuration for the captions.
    """
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    style_path = os.path.join(root_dir, "style_configs", f"{style_name}.json")
    
    default_style = "Alignment=5,FontName=Arial,FontSize=22,PrimaryColour=&H0000FFFF,OutlineColour=&H00000000,Outline=2,Bold=1,MarginV=25"
    
    if os.path.exists(style_path):
        try:
            with open(style_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "ffmpeg_style" in data:
                    print(f"🎨 Loaded custom style config: {style_name}.json")
                    return data["ffmpeg_style"]
        except Exception as e:
            print(f"⚠️ Warning: Could not read style config {style_name}.json: {e}")
            
    return default_style

def render_video(video_path, audio_path, output_path="FINAL_YOUTUBE_SHORT.mp4", style_name="default"):
    """
    Assembles the final 60fps video by looping the background, syncing the audio, 
    and burning the SRT via FFmpeg.
    """
    if not os.path.exists(video_path) or not os.path.exists(audio_path):
        print(f"❌ Error: Missing input files. Video: {video_path}, Audio: {audio_path}")
        return False

    temp_no_subs = "temp_no_subs.mp4"
    srt_path = audio_path.replace(".wav", ".srt").replace(".mp3", ".srt")

    try:
        print(f"🎬 Loading media assets into memory...")
        v_clip = VideoFileClip(video_path)
        a_clip = AudioFileClip(audio_path)

        if v_clip.duration < a_clip.duration:
            loops = int(a_clip.duration // v_clip.duration) + 1
            v_clip = concatenate_videoclips([v_clip] * loops)

        final_v = v_clip.subclipped(0, a_clip.duration)
        final_v = final_v.with_audio(a_clip)

        print("⚙️ Rendering base video at buttery smooth 60 FPS...")
        final_v.write_videofile(
            temp_no_subs,
            fps=60,  # UPGRADED TO 60 FPS
            codec="libx264",
            audio_codec="aac",
            preset="ultrafast",  
            logger=None
        )
        
        v_clip.close()
        a_clip.close()
        final_v.close()

        if os.path.exists(srt_path):
            print("🔥 Burning dynamic SRT captions into the video...")
            
            ass_style = load_style_config(style_name)
            abs_srt = os.path.abspath(srt_path)
            safe_srt = abs_srt.replace('\\', '/').replace(':', r'\:')
            safe_style = ass_style.replace(',', r'\,')
            
            ffmpeg_cmd = [
                "ffmpeg", "-y",
                "-i", temp_no_subs,
                "-vf", f"subtitles={safe_srt}:force_style='{safe_style}'",
                "-c:a", "copy",
                output_path
            ]
            
            subprocess.run(ffmpeg_cmd, check=True)
            
            if os.path.exists(temp_no_subs):
                os.remove(temp_no_subs)
                
            print(f"✅ Success! Masterpiece rendered to {output_path}")
            return True
        else:
            print(f"⚠️ Warning: SRT file {srt_path} not found. Outputting video without subs.")
            os.rename(temp_no_subs, output_path)
            return True

    except subprocess.CalledProcessError as e:
        print(f"❌ FFmpeg styling failed with error code: {e.returncode}")
        return False
    except Exception as e:
        print(f"❌ Assembly failed: {e}")
        return False
