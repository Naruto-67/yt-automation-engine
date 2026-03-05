import os
import subprocess
import json
import traceback

def load_style_config(style_name="default"):
    """
    Loads the styling configuration for the captions.
    """
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    style_path = os.path.join(root_dir, "style_configs", f"{style_name}.json")
    
    # High-retention, high-contrast default caption style
    default_style = "Alignment=5,FontName=Arial,FontSize=22,PrimaryColour=&H0000FFFF,OutlineColour=&H00000000,Outline=2,Bold=1,MarginV=25"
    
    if os.path.exists(style_path):
        try:
            with open(style_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "ffmpeg_style" in data:
                    print(f"🎨 [RENDERER] Loaded custom style config: {style_name}.json")
                    return data["ffmpeg_style"]
        except Exception as e:
            print(f"⚠️ [RENDERER] Could not read style config {style_name}.json: {e}")
            
    return default_style

def render_video(video_path, audio_path, output_path="FINAL_YOUTUBE_SHORT.mp4", style_name="default"):
    """
    The Pure FFmpeg Assembly Engine.
    Uses 0% MoviePy to guarantee the GitHub Actions Runner never runs out of RAM.
    Loops the background, syncs the audio, and burns the SRT in a single fast pass.
    """
    if not os.path.exists(video_path) or not os.path.exists(audio_path):
        print(f"❌ [RENDERER] Missing input files. Video: {video_path}, Audio: {audio_path}")
        return False

    srt_path = audio_path.replace(".wav", ".srt").replace(".mp3", ".srt")

    try:
        print(f"🎬 [RENDERER] Booting FFmpeg Assembly Engine (RAM-Safe Mode)...")
        
        # Prepare the Subtitles formatting
        if os.path.exists(srt_path):
            ass_style = load_style_config(style_name)
            abs_srt = os.path.abspath(srt_path)
            # FFmpeg is extremely strict about path escaping in Windows/Linux environments
            safe_srt = abs_srt.replace('\\', '/').replace(':', r'\:')
            safe_style = ass_style.replace(',', r'\,')
            
            subtitles_filter = f"subtitles={safe_srt}:force_style='{safe_style}'"
            print("🔥 [RENDERER] Dynamic SRT Captions detected. Burning into video...")
        else:
            subtitles_filter = "null" # Fallback if no subs exist
            print("⚠️ [RENDERER] No SRT file found. Outputting video without subs.")

        # THE PURE FFMPEG COMMAND
        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-stream_loop", "-1",       # Infinitely loop the background video
            "-i", video_path,           # Input 1: Background Video
            "-i", audio_path,           # Input 2: Voiceover Audio
            "-vf", subtitles_filter,    # Video Filter: Burn Subtitles
            "-c:v", "libx264",          # Standard YouTube Video Codec
            "-preset", "veryfast",      # Optimized for cloud rendering speed
            "-crf", "23",               # High visual quality
            "-c:a", "aac",              # Standard YouTube Audio Codec
            "-b:a", "192k",             # Crisp audio bitrate
            "-shortest",                # CRITICAL: Stop rendering the exact millisecond the audio ends
            output_path
        ]
        
        # Execute the command and capture errors if it fails
        process = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
        
        if process.returncode == 0:
            print(f"✅ [RENDERER] Success! Masterpiece locked and rendered to {output_path}")
            return True
        else:
            print(f"❌ [RENDERER] FFmpeg failed with error code {process.returncode}")
            print(f"FFmpeg Error Log:\n{process.stderr}")
            return False

    except Exception as e:
        print(f"❌ [RENDERER] Assembly crashed catastrophically:")
        traceback.print_exc()
        return False

if __name__ == "__main__":
    # Local Testing Trigger
    render_video("test_background.mp4", "test_output.wav", "TEST_FINAL.mp4")
