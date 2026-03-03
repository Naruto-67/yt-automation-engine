import os
from moviepy import VideoFileClip, AudioFileClip

def assemble_video(video_path, audio_path, output_path="final_video.mp4"):
    """
    Combines the background video and the TTS audio.
    Trims the video to match the audio length perfectly.
    """
    if not os.path.exists(video_path):
        print(f"Error: Video file not found at {video_path}")
        return False
        
    if not os.path.exists(audio_path):
        print(f"Error: Audio file not found at {audio_path}")
        return False

    try:
        print("Loading media into the editor...")
        video_clip = VideoFileClip(video_path)
        audio_clip = AudioFileClip(audio_path)

        # Ensure the video is at least as long as the audio
        if video_clip.duration < audio_clip.duration:
            print("Warning: Background video is shorter than the audio. It will freeze at the end.")
            # In a later advanced version, we will loop the video here!

        print(f"Trimming video to exactly {audio_clip.duration} seconds...")
        # Cut the video to match the audio length perfectly
        final_video = video_clip.subclipped(0, audio_clip.duration)
        
        # Attach our generated voiceover to the video
        final_video = final_video.with_audio(audio_clip)

        print("Rendering final video. This might take a minute...")
        # Render the final file
        final_video.write_videofile(
            output_path, 
            fps=30, 
            codec="libx264", 
            audio_codec="aac",
            preset="ultrafast",
            logger=None # Turns off the messy progress bar in the logs
        )
        
        # Clean up memory
        video_clip.close()
        audio_clip.close()
        final_video.close()
        
        print(f"Success! Final video rendered to {output_path}")
        return True

    except Exception as e:
        print(f"Failed to assemble video: {e}")
        return False

if __name__ == "__main__":
    # Test the assembly using the files we generated in Phase 2
    assemble_video("test_video.mp4", "test_audio.mp3", "master_final_video.mp4")
